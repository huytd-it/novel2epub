"""Kho nhật ký ứng dụng trên SQLite (bảng ``app_logs``) — nguồn sự thật duy
nhất cho log runtime, thay cho ``logs/app.log`` xoay vòng theo dung lượng.

Toàn bộ thao tác quản lý (truy vấn có lọc, thống kê, xoá, retention) nằm ở đây
để route chỉ mỏng và test được không cần FastAPI. Handler ghi log dùng hàm
:func:`insert_log`; UI/API dùng các hàm còn lại.

Retention: bảng bị chặn tăng trưởng vô hạn bằng :func:`prune_logs` — giữ N hàng
mới nhất (gọi định kỳ từ handler ghi). Xoá chủ động qua :func:`clear_logs`.
"""
from __future__ import annotations

import sqlite3
import time

LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

# Mức hiển thị mặc định khi caller không chỉ định (DEBUG thường là noise).
DEFAULT_LEVELS = ("INFO", "WARNING", "ERROR", "CRITICAL")

# Retention mặc định: giữ tối đa số hàng này (≈ vài chục MB text). Prune chạy
# mỗi _PRUNE_EVERY lần insert để chi phí amortised gần bằng 0.
MAX_ROWS = 100_000
_PRUNE_EVERY = 500


def normalize_levels(levels) -> tuple[str, ...]:
    """Chuẩn hoá danh sách mức: trim + uppercase, bỏ giá trị lạ và trùng.

    Giá trị không hợp lệ bị BỎ QUÊ thay vì raise — đầu vào đến từ query param
    của client, lọc im lặng an toàn hơn 500."""
    out: list[str] = []
    for raw in levels or ():
        level = str(raw).strip().upper()
        if level in LEVELS and level not in out:
            out.append(level)
    return tuple(out)


def insert_log(
    conn: sqlite3.Connection,
    *,
    ts: float | None = None,
    level: str,
    logger: str = "",
    message: str,
    job_id: str = "",
) -> None:
    """Ghi 1 dòng log. Caller tự quản transaction (handler dùng autocommit qua
    ``with conn`` riêng nếu cần atomic — ở đây 1 INSERT tự đủ nguyên tử)."""
    with conn:
        conn.execute(
            "INSERT INTO app_logs (ts, level, logger, message, job_id) VALUES (?, ?, ?, ?, ?)",
            (ts if ts is not None else time.time(), str(level), str(logger), str(message), str(job_id)),
        )


def prune_logs(conn: sqlite3.Connection, max_rows: int = MAX_ROWS) -> int:
    """Xoá log cũ nhất, chỉ giữ ``max_rows`` hàng mới nhất. Trả số hàng xoá."""
    with conn:
        cur = conn.execute(
            "DELETE FROM app_logs WHERE id NOT IN "
            "(SELECT id FROM app_logs ORDER BY id DESC LIMIT ?)",
            (max(1, int(max_rows)),),
        )
        return cur.rowcount if cur.rowcount > 0 else 0


class LogFilter:
    """Bộ lọc dùng chung cho query/stats/clear/export — một nơi định nghĩa,
    nhiều nơi tiêu thụ nên semantics lọc luôn khớp nhau."""

    __slots__ = ("q", "levels", "loggers", "job_id", "since", "until")

    def __init__(
        self,
        *,
        q: str = "",
        levels=(),
        loggers=(),
        job_id: str = "",
        since: float | None = None,
        until: float | None = None,
    ):
        self.q = str(q or "").strip()
        self.levels = normalize_levels(levels)
        self.loggers = tuple(str(x) for x in loggers or () if str(x))
        self.job_id = str(job_id or "")
        self.since = since
        self.until = until

    def where(self) -> tuple[str, list[object]]:
        clauses: list[str] = []
        params: list[object] = []
        if self.q:
            clauses.append("message LIKE ?")
            params.append(f"%{self.q}%")
        if self.levels:
            clauses.append(f"level IN ({','.join('?' * len(self.levels))})")
            params.extend(self.levels)
        if self.loggers:
            # Prefix match theo chấm để 'novel2epub.crawler' khớp mà không nuốt
            # 'novel2epub.crawler_extra'; logger đúng nguyên chuỗi vẫn khớp.
            parts = []
            for name in self.loggers:
                parts.append("logger = ?")
                params.append(name)
                parts.append("logger LIKE ?")
                params.append(f"{name}.%")
            clauses.append("(" + " OR ".join(parts) + ")")
        if self.job_id:
            clauses.append("job_id = ?")
            params.append(self.job_id)
        if self.since is not None:
            clauses.append("ts >= ?")
            params.append(float(self.since))
        if self.until is not None:
            clauses.append("ts <= ?")
            params.append(float(self.until))
        sql = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        return sql, params


def query_logs(
    conn: sqlite3.Connection,
    flt: LogFilter,
    *,
    limit: int = 300,
    before_id: int | None = None,
    after_id: int | None = None,
    order: str = "desc",
) -> dict:
    """Trang log mới nhất (order='desc') hoặc cũ nhất ('asc') khớp bộ lọc.

    ``before_id``/``after_id`` là con trỏ phân trang theo id (ổn định giữa hai
    lần tải dù log mới cứ ghi thêm): 'desc' trả các hàng cũ hơn ``before_id``,
    'asc' trả các hàng mới hơn ``after_id``.

    Response: ``{"entries": [...], "total": <tổng số hàng khớp lọc>}``. Total
    tính không giới hạn để UI hiển thị "x/y" và biết còn trang sau hay không.
    """
    limit = max(1, min(int(limit), 5000))
    where_sql, params = flt.where()
    total = conn.execute(f"SELECT COUNT(*) FROM app_logs{where_sql}", params).fetchone()[0]
    if before_id is not None:
        where_sql = f"{where_sql} AND " if where_sql else " WHERE "
        where_sql += "id < ?"
        params = [*params, int(before_id)]
    elif after_id is not None:
        where_sql = f"{where_sql} AND " if where_sql else " WHERE "
        where_sql += "id > ?"
        params = [*params, int(after_id)]
    direction = "ASC" if order == "asc" else "DESC"
    rows = conn.execute(
        f"SELECT id, ts, level, logger, message, job_id FROM app_logs"
        f"{where_sql} ORDER BY id {direction} LIMIT ?",
        [*params, limit],
    ).fetchall()
    entries = [
        {
            "id": r["id"],
            "ts": r["ts"],
            "level": r["level"],
            "logger": r["logger"],
            "message": r["message"],
            "job_id": r["job_id"],
        }
        for r in rows
    ]
    return {"entries": entries, "total": total}


def format_entry(entry: dict) -> str:
    """Dựng 1 dòng text đúng định dạng file log cũ
    '2026-08-25 10:00:00 [LEVEL] logger: message' — dùng cho export và endpoint
    legacy trả `lines`."""
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(entry["ts"]))
    return f"{stamp} [{entry['level']}] {entry['logger']}: {entry['message']}"


def log_stats(conn: sqlite3.Connection) -> dict:
    """Tổng quan cho UI: tổng số hàng, đếm theo mức và biên thời gian."""
    by_level = {level: 0 for level in LEVELS}
    for row in conn.execute("SELECT level, COUNT(*) AS n FROM app_logs GROUP BY level"):
        by_level[str(row["level"])] = row["n"]
    bounds = conn.execute(
        "SELECT MIN(ts) AS oldest, MAX(ts) AS newest FROM app_logs"
    ).fetchone()
    return {
        "total": sum(by_level.values()),
        "by_level": by_level,
        "oldest_ts": bounds["oldest"],
        "newest_ts": bounds["newest"],
    }


def log_sources(conn: sqlite3.Connection, limit: int = 200) -> list[dict]:
    """Danh sách logger đã ghi log kèm số dòng — dropdown 'nguồn' của UI."""
    rows = conn.execute(
        "SELECT logger, COUNT(*) AS n FROM app_logs GROUP BY logger "
        "ORDER BY n DESC, logger ASC LIMIT ?",
        (max(1, int(limit)),),
    ).fetchall()
    return [{"logger": r["logger"], "count": r["n"]} for r in rows]


def clear_logs(conn: sqlite3.Connection, flt: LogFilter) -> int:
    """Xoá log khớp bộ lọc (toàn bộ nếu filter rỗng). Trả số hàng xoá."""
    where_sql, params = flt.where()
    with conn:
        cur = conn.execute(f"DELETE FROM app_logs{where_sql}", params)
        return cur.rowcount if cur.rowcount > 0 else 0


def delete_log_by_id(conn: sqlite3.Connection, entry_id: int) -> bool:
    """Xoá đúng 1 dòng log theo id (nút Xoá trên từng dòng của UI)."""
    with conn:
        cur = conn.execute("DELETE FROM app_logs WHERE id = ?", (int(entry_id),))
        return cur.rowcount > 0


def get_log_by_id(conn: sqlite3.Connection, entry_id: int) -> dict | None:
    """Đọc 1 dòng log đầy đủ — cho xem chi tiết khi UI rút gọn dòng lỗi."""
    row = conn.execute(
        "SELECT id, ts, level, logger, message, job_id FROM app_logs WHERE id = ?",
        (int(entry_id),),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "ts": row["ts"],
        "level": row["level"],
        "logger": row["logger"],
        "message": row["message"],
        "job_id": row["job_id"],
    }
