"""Cấu hình logging cho web UI — nhật ký lưu SQLITE, không còn file text.

Toàn bộ dòng log của novel2epub.* (crawler/translator/queue/scheduler...) được
ghi vào bảng ``app_logs`` trong `.db` thống nhất (xem ``novel2epub/logstore``),
kèm traceback đầy đủ khi có lỗi. Log sống cùng bản backup DB và quản lý được
từ trang Nhật ký (lọc theo mức/nguồn/nội dung, xoá, export).

Song song với đó, :class:`JobLogHandler` đẩy log của job đang chạy trên thread
hiện tại vào buffer trong bộ nhớ để hiển thị trực tiếp trên UI job — buffer
này vẫn giới hạn số dòng và chỉ là bản xem nhanh, không phải nơi lưu trữ.
"""
from __future__ import annotations

import atexit
import logging
import threading
import time
from contextlib import contextmanager
from collections.abc import Iterator, MutableSequence

from novel2epub import logstore

# Logger cha của mọi module (novel2epub.web, .crawler, .search...). Handler gắn
# ở đây để log của crawler cũng xuống DB + job log, không chỉ riêng .web.
root_logger = logging.getLogger("novel2epub")
logger = logging.getLogger("novel2epub.web")

_job_local = threading.local()

# Ghi log BẤT ĐỒNG BỘ theo lô: emit() chỉ đẩy record vào buffer trong RAM
# (rẻ, không I/O trên hot path của worker) — một flusher thread duy nhất rút
# buffer và executemany vào SQLite mỗi _FLUSH_INTERVAL giây hoặc khi đủ lô.
# Insert+commit từng dòng làm job crawl/dịch chậm đi thấy rõ trên Windows
# (mỗi commit là một fsync), nên đồng bộ là không thể chấp nhận.
#
# Đổi lại, crash cứng có thể mất ≤ 1 giây log cuối — chấp nhận được với nhật
# ký vận hành (job history vẫn ghi transactional riêng trong queue.py).
_FLUSH_INTERVAL = 1.0
_FLUSH_BATCH = 100


class SQLiteLogHandler(logging.Handler):
    """Đệm LogRecord và ghi xuống bảng `app_logs` qua flusher thread.

    emit() KHÔNG BAO GIỜ raise và KHÔNG block: log lỗi/khả dụng thấp không
    được làm hỏng job hay treo web UI — DB hỏng thì mất log chứ không mất
    chức năng.
    """

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        # Lock riêng cho phần ghi DB: flush chạy song song từ flusher thread và
        # atexit (thread chính), không được để hai caller đụng chung Connection.
        self._db_lock = threading.Lock()
        self._buffer: list[tuple[float, str, str, str]] = []
        self._wake = threading.Event()
        self._flusher: threading.Thread | None = None
        self._conn: object | None = None
        self._since_prune = 0

    # ── hot path (mọi thread) ────────────────────────────────────────────
    def emit(self, record: logging.LogRecord) -> None:
        try:
            try:
                message = self.format(record)
            except Exception:  # noqa: BLE001 - format hỏng thì dùng nguyên văn
                message = record.getMessage()
            with self._lock:
                full = len(self._buffer) >= _FLUSH_BATCH
                self._buffer.append((time.time(), record.levelname, record.name, message))
            self._ensure_flusher()
            if full:
                self._wake.set()
        except Exception:  # noqa: BLE001 - xem docstring
            pass

    def _ensure_flusher(self) -> None:
        if self._flusher is not None and self._flusher.is_alive():
            return
        with self._lock:
            if self._flusher is not None and self._flusher.is_alive():
                return
            self._flusher = threading.Thread(
                target=self._loop, name="log-flusher", daemon=True
            )
            self._flusher.start()
            atexit.register(self.flush)

    # ── flusher thread ──────────────────────────────────────────────────
    def _loop(self) -> None:
        while True:
            self._wake.wait(timeout=_FLUSH_INTERVAL)
            self._wake.clear()
            self.flush()

    @staticmethod
    def _open_connection():
        """Connection dùng chung giữa flusher thread và thread chính lúc
        atexit → phải mở với check_same_thread=False (truy cập được serialize
        bởi ``_db_lock``). synchronous=NORMAL + WAL: commit log không fsync
        từng lần — log chịu được mất <1s khi mất điện."""
        import sqlite3

        from .deps import DB_PATH
        from novel2epub.db import init_schema

        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        init_schema(conn)
        return conn

    def flush(self) -> None:  # noqa: D102 - công khai cho logging/atexit
        with self._lock:
            batch = self._buffer
            self._buffer = []
        if not batch:
            return
        try:
            with self._db_lock:
                if self._conn is None:
                    self._conn = self._open_connection()
                conn = self._conn
                with conn:
                    conn.executemany(
                        "INSERT INTO app_logs (ts, level, logger, message) VALUES (?, ?, ?, ?)",
                        batch,
                    )
                self._since_prune += len(batch)
                if self._since_prune >= logstore._PRUNE_EVERY:
                    self._since_prune = 0
                    with conn:
                        logstore.prune_logs(conn)
        except Exception:  # noqa: BLE001 - DB hỏng/thư mục chưa có: bỏ lô này
            pass

    def close(self) -> None:
        self.flush()
        super().close()



class JobLogHandler(logging.Handler):
    """Đẩy log của novel2epub.* vào job.log của job đang chạy trên thread này.

    Queue chạy nhiều worker song song nên buffer phải theo thread, nếu không log
    của job này sẽ lẫn sang job khác.
    """

    def emit(self, record: logging.LogRecord) -> None:
        buf = getattr(_job_local, "buf", None)
        if buf is None:
            return
        # log_fn trong queue.py đã append thẳng vào job.log trước khi gọi
        # logger.info() → bỏ qua .web để không nhân đôi dòng trên UI.
        if record.name.startswith("novel2epub.web"):
            return
        try:
            buf.append(self.format(record))
        except Exception:  # noqa: BLE001 - log lỗi không được làm hỏng job
            pass


@contextmanager
def job_log_capture(buf: MutableSequence[str]) -> Iterator[None]:
    """Trong phạm vi này, log novel2epub.* của thread hiện tại chảy vào ``buf``.

    ``buf`` là ``Job.log`` — một ``deque(maxlen=500)``, không phải list.
    """
    prev = getattr(_job_local, "buf", None)
    _job_local.buf = buf
    try:
        yield
    finally:
        _job_local.buf = prev


def setup_logging() -> None:
    if root_logger.handlers:
        return  # tránh gắn handler trùng khi reload

    db_handler = SQLiteLogHandler()
    db_handler.setFormatter(logging.Formatter("%(message)s"))
    root_logger.addHandler(db_handler)

    job_handler = JobLogHandler()
    job_handler.setFormatter(logging.Formatter("%(message)s"))
    root_logger.addHandler(job_handler)

    root_logger.setLevel(logging.INFO)
    root_logger.propagate = False  # không rò lên root logger của Python

    # .web propagate lên cha để dùng chung handler.
    logger.propagate = True
