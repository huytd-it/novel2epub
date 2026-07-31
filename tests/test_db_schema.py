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


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_cot_reader_co_mat_tren_db_tao_moi():
    conn = get_connection(":memory:")
    init_schema(conn)
    assert "reader_json" in _column_names(conn, "settings")
    assert "reader_overrides_json" in _column_names(conn, "ebooks")


def test_db_cu_thieu_cot_reader_duoc_va_bang_alter_table():
    """`init_schema` chỉ chạy CREATE TABLE IF NOT EXISTS nên cột thêm ở schema
    v2 không tự xuất hiện trên DB cũ — `_ensure_columns` phải ALTER TABLE vá."""
    conn = get_connection(":memory:")
    # Dựng lại bảng kiểu schema v1 (chưa có cột reader).
    with conn:
        conn.execute("""
            CREATE TABLE settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                novel_json TEXT NOT NULL DEFAULT '{}',
                crawl_json TEXT NOT NULL DEFAULT '{}',
                translate_json TEXT NOT NULL DEFAULT '{}',
                ai_json TEXT NOT NULL DEFAULT '{}',
                output_json TEXT NOT NULL DEFAULT '{}',
                queue_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE ebooks (
                slug TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                archived INTEGER NOT NULL DEFAULT 0,
                crawl_overrides_json TEXT NOT NULL DEFAULT '{}',
                output_overrides_json TEXT NOT NULL DEFAULT '{}'
            )
        """)
        conn.execute("INSERT INTO settings (id, novel_json) VALUES (1, '{\"title\": \"cũ\"}')")
        conn.execute("INSERT INTO ebooks (slug) VALUES ('demo')")

    init_schema(conn)

    assert "reader_json" in _column_names(conn, "settings")
    assert "reader_overrides_json" in _column_names(conn, "ebooks")
    # Dữ liệu cũ còn nguyên, cột mới có default dùng được ngay.
    row = conn.execute("SELECT novel_json, reader_json FROM settings WHERE id = 1").fetchone()
    assert row["novel_json"] == '{"title": "cũ"}'
    assert row["reader_json"] == "{}"
    assert conn.execute("SELECT reader_overrides_json FROM ebooks").fetchone()[0] == "{}"


def test_ensure_columns_idempotent_khong_alter_hai_lan():
    conn = get_connection(":memory:")
    init_schema(conn)
    init_schema(conn)
    init_schema(conn)
    assert "reader_json" in _column_names(conn, "settings")


def test_characters_tables_exist():
    conn = get_connection(":memory:")
    init_schema(conn)
    names = _table_names(conn)
    assert "characters" in names
    assert "character_relations" in names
    assert SCHEMA_VERSION == 6


def test_schema_v6_columns_present():
    conn = get_connection(":memory:")
    init_schema(conn)
    rel_cols = {r[1] for r in conn.execute("PRAGMA table_info(character_relations)")}
    for col in ("to_chapter", "a_calls_b_raw", "a_self_raw", "evidence",
                "inferred", "confidence"):
        assert col in rel_cols
    char_cols = {r[1] for r in conn.execute("PRAGMA table_info(characters)")}
    assert "aliases_vi" in char_cols


def test_v5_database_gets_new_columns_without_data_loss():
    """DB đã tồn tại ở v5 (bảng có sẵn, thiếu cột mới) phải được ALTER TABLE vá.

    Đây là ca THẬT của người dùng: sub-project A đã merge nên DB của họ có hai
    bảng này rồi, và CREATE TABLE IF NOT EXISTS sẽ không thêm cột. Mô phỏng bằng
    cách chạy `init_schema` thật (dựng đủ schema, gồm `ebooks`) rồi hạ cấp riêng
    `character_relations` về hình dạng 7-cột cũ (sub-project A) trước khi chạy
    lại `init_schema`.
    """
    conn = get_connection(":memory:")
    init_schema(conn)
    conn.execute("INSERT INTO ebooks (slug) VALUES ('t')")
    conn.execute("DROP TABLE character_relations")
    conn.execute(
        "CREATE TABLE character_relations (ebook_slug TEXT NOT NULL, "
        "a_source TEXT NOT NULL, b_source TEXT NOT NULL, "
        "from_chapter INTEGER NOT NULL DEFAULT 0, a_calls_b TEXT NOT NULL DEFAULT '', "
        "a_self TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '', "
        "PRIMARY KEY (ebook_slug, a_source, b_source, from_chapter))"
    )
    conn.execute(
        "INSERT INTO character_relations (ebook_slug, a_source, b_source, "
        "from_chapter, a_calls_b, a_self) VALUES ('t','A','B',5,'sư phụ','đồ nhi')"
    )
    conn.commit()

    init_schema(conn)

    cols = {r[1] for r in conn.execute("PRAGMA table_info(character_relations)")}
    assert "to_chapter" in cols and "confidence" in cols
    row = conn.execute(
        "SELECT a_calls_b, a_self, to_chapter FROM character_relations"
    ).fetchone()
    assert row[0] == "sư phụ" and row[1] == "đồ nhi" and row[2] is None
