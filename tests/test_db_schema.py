import sqlite3

import pytest

from novel2epub.db import SCHEMA_VERSION, get_connection, init_schema, schema_version

_EXPECTED_TABLES = {
    "_meta",
    "settings",
    "sources",
    "ebooks",
    "chapters",
    "glossary_entries",
    "notes",
    "ebook_covers",
    "ebook_extra_json",
    "job_queue_history",
    "job_queue_pending",
    "automations",
}


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return {r["name"] for r in rows}


def test_init_schema_creates_expected_tables():
    conn = get_connection(":memory:")
    init_schema(conn)
    assert _EXPECTED_TABLES <= _table_names(conn)


def test_init_schema_is_idempotent():
    conn = get_connection(":memory:")
    init_schema(conn)
    init_schema(conn)  # gọi lần 2 không lỗi, không tạo trùng bảng
    assert _table_names(conn) & _EXPECTED_TABLES == _EXPECTED_TABLES


def test_schema_version_recorded():
    conn = get_connection(":memory:")
    init_schema(conn)
    assert schema_version(conn) == SCHEMA_VERSION


def test_settings_is_single_row_table():
    conn = get_connection(":memory:")
    init_schema(conn)
    with conn:
        conn.execute("INSERT INTO settings (id) VALUES (1)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO settings (id) VALUES (2)")


def test_foreign_key_violation_rejected():
    conn = get_connection(":memory:")
    init_schema(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO chapters (ebook_slug, idx) VALUES ('ghost', 1)")


def test_cascade_delete_removes_dependent_rows():
    conn = get_connection(":memory:")
    init_schema(conn)
    with conn:
        conn.execute("INSERT INTO ebooks (slug) VALUES ('demo')")
        conn.execute("INSERT INTO chapters (ebook_slug, idx) VALUES ('demo', 1)")
        conn.execute(
            "INSERT INTO glossary_entries (ebook_slug, list_name, source, target) "
            "VALUES ('demo', 'names.txt', '庄国', 'Trang Quốc')"
        )
    with conn:
        conn.execute("DELETE FROM ebooks WHERE slug = 'demo'")
    assert conn.execute("SELECT COUNT(*) AS c FROM chapters").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM glossary_entries").fetchone()["c"] == 0


def test_glossary_entries_upsert_dedup_last_wins():
    conn = get_connection(":memory:")
    init_schema(conn)
    with conn:
        conn.execute("INSERT INTO ebooks (slug) VALUES ('demo')")
    upsert = """
        INSERT INTO glossary_entries (ebook_slug, list_name, source, target, note)
        VALUES ('demo', 'names.txt', '庄国', ?, ?)
        ON CONFLICT(ebook_slug, list_name, source) DO UPDATE SET
            target = excluded.target, note = excluded.note
    """
    with conn:
        conn.execute(upsert, ("Trang Quốc", ""))
    with conn:
        conn.execute(upsert, ("Trang Quốc Mới", "cập nhật"))
    row = conn.execute(
        "SELECT target, note FROM glossary_entries WHERE ebook_slug='demo' AND source='庄国'"
    ).fetchone()
    assert row["target"] == "Trang Quốc Mới"
    assert row["note"] == "cập nhật"


def test_chapters_without_rowid_composite_key():
    conn = get_connection(":memory:")
    init_schema(conn)
    with conn:
        conn.execute("INSERT INTO ebooks (slug) VALUES ('demo')")
        conn.execute("INSERT INTO chapters (ebook_slug, idx) VALUES ('demo', 1)")
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            conn.execute("INSERT INTO chapters (ebook_slug, idx) VALUES ('demo', 1)")
