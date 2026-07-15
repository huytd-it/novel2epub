"""Cấu hình logging chi tiết ra file cho web UI.

Mọi dòng log của job (crawl/dịch/build...) được ghi ra `logs/app.log` (xoay
vòng theo dung lượng) kèm traceback đầy đủ khi có lỗi, độc lập với buffer
log trong bộ nhớ (giới hạn dòng, mất khi job mới bắt đầu) dùng để hiển thị
trên UI.
"""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from collections.abc import Iterator, MutableSequence
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .deps import BASE_DIR

LOG_DIR = BASE_DIR.parent / "logs"
LOG_FILE = LOG_DIR / "app.log"

# Logger cha của mọi module (novel2epub.web, .crawler, .search...). Handler gắn
# ở đây để log của crawler cũng ra file + job log, không chỉ riêng .web.
root_logger = logging.getLogger("novel2epub")
logger = logging.getLogger("novel2epub.web")

_job_local = threading.local()


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

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    job_handler = JobLogHandler()
    job_handler.setFormatter(logging.Formatter("%(message)s"))
    root_logger.addHandler(job_handler)

    root_logger.setLevel(logging.INFO)
    root_logger.propagate = False  # không rò lên root logger của Python

    # .web propagate lên cha để dùng chung handler (tránh 2 RotatingFileHandler
    # cùng ghi/xoay 1 file).
    logger.propagate = True
