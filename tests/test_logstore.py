"""Tests cho kho nhật ký SQLite (`novel2epub.logstore` + bảng `app_logs`).

Log runtime trước đây nằm trong logs/app.log xoay vòng theo dung lượng — chỉ
đọc được tuần tự, không lọc/xoá có chọn lọc được. Giờ là bảng SQL nên mọi tính
năng quản lý (lọc mức/nguồn/nội dung, thống kê, xoá, retention) phải đúng.
"""
from __future__ import annotations

import time

import pytest

from novel2epub.db import SCHEMA_VERSION, get_connection, init_schema, schema_version
from novel2epub.logstore import (
    LogFilter,
    clear_logs,
    delete_log_by_id,
    format_entry,
    get_log_by_id,
    insert_log,
    log_sources,
    log_stats,
    prune_logs,
    query_logs,
)


@pytest.fixture
def conn():
    conn = get_connection(":memory:")
    init_schema(conn)
    return conn


def _seed(conn, n=5):
    """n dòng INFO cách nhau 1 giây, logger xen kẽ."""
    base = 1_700_000_000.0
    for i in range(n):
        insert_log(
            conn,
            ts=base + i,
            level="INFO",
            logger="novel2epub.crawler" if i % 2 else "novel2epub.web",
            message=f"dòng {i}",
        )
    return base


def test_insert_and_query_newest_first(conn):
    _seed(conn, 3)
    data = query_logs(conn, LogFilter())
    assert data["total"] == 3
    assert [e["message"] for e in data["entries"]] == ["dòng 2", "dòng 1", "dòng 0"]


def test_query_filter_by_level(conn):
    base = _seed(conn, 4)
    insert_log(conn, ts=base + 10, level="ERROR", logger="novel2epub.crawler", message="hỏng")
    data = query_logs(conn, LogFilter(levels=["ERROR"]))
    assert data["total"] == 1
    assert data["entries"][0]["message"] == "hỏng"


def test_normalize_levels_ignores_unknown_and_dedupes():
    from novel2epub.logstore import normalize_levels

    assert normalize_levels(["error", "ERROR", "warning ", "bogus"]) == ("ERROR", "WARNING")


def test_query_filter_logger_is_prefix_scoped(conn):
    """`novel2epub.crawler` khớp con cháu (novel2epub.crawler.sub) nhưng không
    nuốt logger chỉ giống tiền tố chữ (novel2epub.crawlerx)."""
    insert_log(conn, ts=1, level="INFO", logger="novel2epub.crawler", message="a")
    insert_log(conn, ts=2, level="INFO", logger="novel2epub.crawler.sub", message="b")
    insert_log(conn, ts=3, level="INFO", logger="novel2epub.crawlerx", message="c")
    data = query_logs(conn, LogFilter(loggers=["novel2epub.crawler"]))
    assert sorted(e["message"] for e in data["entries"]) == ["a", "b"]


def test_query_search_message_substring(conn):
    _seed(conn, 5)
    insert_log(conn, ts=999, level="WARNING", logger="x", message="Mục lục trống hoàn toàn")
    data = query_logs(conn, LogFilter(q="mục lục"))
    assert data["total"] == 1
    assert data["entries"][0]["level"] == "WARNING"


def test_query_time_range_and_cursor_pagination(conn):
    _seed(conn, 6)
    flt = LogFilter(since=1_700_000_002.0, until=1_700_000_004.0)
    data = query_logs(conn, flt)
    assert [e["ts"] for e in data["entries"]] == [
        1_700_000_004.0, 1_700_000_003.0, 1_700_000_002.0,
    ]

    page1 = query_logs(conn, LogFilter(), limit=2)
    page2 = query_logs(conn, LogFilter(), limit=2, before_id=page1["entries"][-1]["id"])
    ids = [e["id"] for e in page1["entries"]] + [e["id"] for e in page2["entries"]]
    all_rows = conn.execute("SELECT id FROM app_logs ORDER BY id DESC").fetchall()
    assert ids == [r["id"] for r in all_rows[:4]]
    # total luôn là tổng khớp lọc, không phải số dòng trang hiện tại
    assert page1["total"] == page2["total"] == 6


def test_query_job_id_filter(conn):
    insert_log(conn, ts=1, level="INFO", logger="j", message="thuộc job", job_id="abc")
    insert_log(conn, ts=2, level="INFO", logger="j", message="ngoài job")
    data = query_logs(conn, LogFilter(job_id="abc"))
    assert [e["message"] for e in data["entries"]] == ["thuộc job"]


def test_log_stats_counts_by_level_and_bounds(conn):
    base = _seed(conn, 3)
    insert_log(conn, ts=base + 100, level="ERROR", logger="x", message="err")
    stats = log_stats(conn)
    assert stats["total"] == 4
    assert stats["by_level"]["ERROR"] == 1
    assert stats["by_level"]["INFO"] == 3
    assert stats["newest_ts"] == base + 100
    assert stats["oldest_ts"] == base


def test_log_sources_groups_by_logger_with_counts(conn):
    _seed(conn, 4)
    sources = {s["logger"]: s["count"] for s in log_sources(conn)}
    assert sources == {"novel2epub.crawler": 2, "novel2epub.web": 2}


def test_clear_older_than_days_keeps_recent(conn):
    """older_than_days tính theo thời gian THỰC: dòng quá khứ bị xoá, dòng mới
    giữ lại — đúng semantics dọn định kỳ."""
    _seed(conn, 3)  # seed ở quá khứ xa (11/2023)
    recent = time.time() + 60
    insert_log(conn, ts=recent, level="INFO", logger="x", message="vừa ghi")

    # "cũ hơn 1 ngày" = xoá dòng có ts <= mốc (route quy đổi thành `until`).
    assert clear_logs(conn, LogFilter(until=time.time() - 86400)) == 3
    remaining = query_logs(conn, LogFilter())
    assert [e["message"] for e in remaining["entries"]] == ["vừa ghi"]


def test_clear_by_level_keeps_other_levels(conn):
    _seed(conn, 2)
    insert_log(conn, ts=50, level="ERROR", logger="x", message="giữ lại")
    deleted = clear_logs(conn, LogFilter(levels=["INFO"]))
    assert deleted == 2
    remaining = query_logs(conn, LogFilter())
    assert [e["message"] for e in remaining["entries"]] == ["giữ lại"]


def test_clear_all_when_filter_empty(conn):
    _seed(conn, 3)
    assert clear_logs(conn, LogFilter()) == 3
    assert log_stats(conn)["total"] == 0


def test_delete_log_by_id_removes_exactly_one_row(conn):
    _seed(conn, 3)
    target = query_logs(conn, LogFilter(), limit=1)["entries"][0]
    assert delete_log_by_id(conn, target["id"]) is True
    remaining = query_logs(conn, LogFilter())
    assert remaining["total"] == 2
    assert all(e["id"] != target["id"] for e in remaining["entries"])
    # Xoá lại id đã mất → False, không lỗi.
    assert delete_log_by_id(conn, target["id"]) is False


def test_get_log_by_id_returns_full_entry_or_none(conn):
    insert_log(conn, ts=42, level="ERROR", logger="novel2epub.translator", message="hỏng sâu", job_id="j1")
    entry = query_logs(conn, LogFilter(), limit=1)["entries"][0]
    got = get_log_by_id(conn, entry["id"])
    assert got is not None
    assert (got["level"], got["logger"], got["message"], got["job_id"]) == (
        "ERROR", "novel2epub.translator", "hỏng sâu", "j1",
    )
    assert get_log_by_id(conn, 10**9) is None


def test_prune_keeps_only_newest_rows(conn):
    _seed(conn, 10)
    pruned = prune_logs(conn, max_rows=3)
    assert pruned == 7
    rows = conn.execute("SELECT message FROM app_logs ORDER BY id DESC").fetchall()
    assert [r["message"] for r in rows] == ["dòng 9", "dòng 8", "dòng 7"]
    assert prune_logs(conn, max_rows=10) == 0


def test_format_entry_matches_legacy_file_layout():
    entry = {
        "ts": 1_700_000_000.0,
        "level": "WARNING",
        "logger": "novel2epub.crawler",
        "message": "retry lần 2",
        "job_id": "",
    }
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(entry["ts"]))
    assert format_entry(entry) == f"{stamp} [WARNING] novel2epub.crawler: retry lần 2"


def test_v22_creates_app_logs_on_existing_database():
    """DB v21 thật (đã có dữ liệu) nâng lên v22 tạo bảng app_logs, không mất gì."""
    conn = get_connection(":memory:")
    init_schema(conn)
    with conn:
        conn.execute("INSERT INTO ebooks (slug, title) VALUES ('old', 'Dữ liệu cũ')")
        conn.execute("UPDATE _meta SET value = '21' WHERE key = 'schema_version'")

    init_schema(conn)

    assert schema_version(conn) == SCHEMA_VERSION
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert "app_logs" in names
    assert conn.execute("SELECT title FROM ebooks WHERE slug='old'").fetchone()["title"] == "Dữ liệu cũ"
    # Ghi/ đọc được ngay sau migration.
    insert_log(conn, level="INFO", logger="t", message="sau upgrade")
    assert query_logs(conn, LogFilter())["total"] == 1


def test_sqlite_log_handler_buffers_then_flushes_to_db(tmp_path, monkeypatch):
    """Handler ghi bất đồng bộ: emit() chỉ đệm trong RAM, flush() mới xuống DB.
    Đảm bảo dòng log thực sự tới được bảng app_logs qua đường dẫn này."""
    import logging as _logging

    import app.deps as deps
    from app.logging_config import SQLiteLogHandler

    db = tmp_path / "handler.db"
    conn = get_connection(str(db))
    init_schema(conn)
    conn.close()
    monkeypatch.setattr(deps, "DB_PATH", db)

    handler = SQLiteLogHandler()
    handler.setFormatter(_logging.Formatter("%(message)s"))
    try:
        handler.emit(_logging.LogRecord(
            "novel2epub.crawler", _logging.INFO, "p", 1,
            "xin chào %s", ("SQLite",), None,
        ))
        handler.flush()

        conn = get_connection(str(db))
        rows = conn.execute("SELECT level, logger, message FROM app_logs").fetchall()
        assert [(r["level"], r["logger"], r["message"]) for r in rows] == [
            ("INFO", "novel2epub.crawler", "xin chào SQLite"),
        ]
    finally:
        handler.close()
