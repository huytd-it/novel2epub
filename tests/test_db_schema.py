import json
import sqlite3

import pytest

import novel2epub.db as db_module
from novel2epub.db import (
    SCHEMA_VERSION,
    SchemaVersionError,
    get_connection,
    init_schema,
    schema_version,
)

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
    "wireguard_profiles",
    "identities",
    "audit_events",
    "ai_revisions",
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
    assert SCHEMA_VERSION >= 9


def test_schema_v8_has_wireguard_column_and_profiles_table():
    conn = get_connection(":memory:")
    init_schema(conn)
    assert "wireguard_json" in _column_names(conn, "settings")
    assert "wireguard_profiles" in _table_names(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(wireguard_profiles)")}
    for col in ("id", "filename", "source", "enabled", "position", "status",
                "error", "activated_at", "last_error_at", "created_at", "updated_at"):
        assert col in cols


def test_v8_database_gets_wireguard_column_without_data_loss():
    """DB v8 (settings không có wireguard_json) được ALTER TABLE vá, dữ liệu cũ
    còn nguyên và cột mới dùng được ngay với default '{}'."""
    conn = get_connection(":memory:")
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
                reader_json TEXT NOT NULL DEFAULT '{}',
                api_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("INSERT INTO settings (id, novel_json) VALUES (1, '{\"title\": \"cũ\"}')")

    init_schema(conn)

    assert "wireguard_json" in _column_names(conn, "settings")
    row = conn.execute("SELECT novel_json, wireguard_json FROM settings WHERE id = 1").fetchone()
    assert row["novel_json"] == '{"title": "cũ"}'
    assert row["wireguard_json"] == "{}"
    assert "wireguard_profiles" in _table_names(conn)


def test_schema_v7_migrates_legacy_prompts_idempotently():
    conn = get_connection(":memory:")
    init_schema(conn)
    legacy = (
        "Đầu tùy chỉnh. Ngôi xưng phải theo quan hệ và ngữ cảnh, KHÔNG bê nguyên "
        "ta/ngươi. Chọn phù hợp giữa cha/mẹ/thúc/bá/cô/sư phụ/tiền bối/chàng/"
        "nàng/ông ấy/bà ấy/ngài/người/con/cháu... Cuối tùy chỉnh."
    )
    settings = {"openai": {"prompt_template": legacy}, "type": "openai"}
    ebook = {"openai": {"prompt_template": legacy}, "genre": "urban"}
    with conn:
        conn.execute(
            "INSERT INTO settings (id, translate_json) VALUES (1, ?)",
            (json.dumps(settings, ensure_ascii=False),),
        )
        conn.execute(
            "INSERT INTO ebooks (slug, translate_overrides_json) VALUES ('demo', ?)",
            (json.dumps(ebook, ensure_ascii=False),),
        )

    init_schema(conn)
    first_settings = conn.execute("SELECT translate_json FROM settings").fetchone()[0]
    first_ebook = conn.execute("SELECT translate_overrides_json FROM ebooks").fetchone()[0]
    for raw in (first_settings, first_ebook):
        assert "KHÔNG bê nguyên ta/ngươi" not in raw
        assert 'được dùng \\"hắn\\"' in raw
        assert "Đầu tùy chỉnh" in raw and "Cuối tùy chỉnh" in raw

    init_schema(conn)
    assert conn.execute("SELECT translate_json FROM settings").fetchone()[0] == first_settings
    assert conn.execute("SELECT translate_overrides_json FROM ebooks").fetchone()[0] == first_ebook


def test_schema_v7_preserves_custom_and_invalid_prompt_json():
    conn = get_connection(":memory:")
    init_schema(conn)
    custom = json.dumps(
        {"openai": {"prompt_template": "Luật riêng của tôi: giữ nguyên."}},
        ensure_ascii=False,
    )
    with conn:
        conn.execute("INSERT INTO settings (id, translate_json) VALUES (1, ?)", (custom,))
        conn.execute(
            "INSERT INTO ebooks (slug, translate_overrides_json) VALUES ('bad', '{broken')"
        )
    init_schema(conn)
    assert conn.execute("SELECT translate_json FROM settings").fetchone()[0] == custom
    assert conn.execute("SELECT translate_overrides_json FROM ebooks").fetchone()[0] == "{broken"


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


def test_v9_database_migrates_to_v11_without_data_loss():
    conn = get_connection(":memory:")
    init_schema(conn)
    with conn:
        conn.execute("INSERT INTO settings (id, api_json) VALUES (1, ?)", ('{"token":"legacy"}',))
        conn.execute("INSERT INTO ebooks (slug, title) VALUES ('old', 'Dữ liệu cũ')")
        conn.execute(
            "INSERT INTO chapters (ebook_slug, idx, translated_text) VALUES ('old', 1, 'Nội dung')"
        )
        conn.execute("UPDATE _meta SET value = '9' WHERE key = 'schema_version'")

    init_schema(conn)
    init_schema(conn)

    assert schema_version(conn) == 11
    ebook = conn.execute("SELECT title, revision FROM ebooks WHERE slug='old'").fetchone()
    assert (ebook["title"], ebook["revision"]) == ("Dữ liệu cũ", 1)
    chapter = conn.execute(
        "SELECT translated_text, revision FROM chapters WHERE ebook_slug='old' AND idx=1"
    ).fetchone()
    assert (chapter["translated_text"], chapter["revision"]) == ("Nội dung", 1)
    assert json.loads(conn.execute("SELECT api_json FROM settings").fetchone()[0])["token"] == "legacy"
    assert "oidc_json" in _column_names(conn, "settings")
    assert {"identities", "audit_events", "ai_revisions"} <= _table_names(conn)


def test_v10_database_migrates_to_v11_preserving_data():
    """DB v10 chưa có bảng `ai_revisions`; nâng lên v11 thêm bảng, dữ liệu cũ còn nguyên."""
    conn = get_connection(":memory:")
    init_schema(conn)
    with conn:
        conn.execute("INSERT INTO ebooks (slug, title) VALUES ('old', 'Bản cũ')")
        conn.execute(
            "INSERT INTO chapters (ebook_slug, idx, translated_text, revision) VALUES ('old', 1, 'Dịch', 3)"
        )
        conn.execute("UPDATE _meta SET value = '10' WHERE key = 'schema_version'")

    init_schema(conn)

    assert schema_version(conn) == 11
    chapter = conn.execute(
        "SELECT translated_text, revision FROM chapters WHERE ebook_slug='old' AND idx=1"
    ).fetchone()
    assert (chapter["translated_text"], chapter["revision"]) == ("Dịch", 3)
    assert _column_names(conn, "ai_revisions") >= {
        "engine", "status", "base_rev", "base_translated_text",
        "payload_json", "has_raw", "expires_at",
    }


def test_ai_revisions_cascade_delete_with_ebook():
    conn = get_connection(":memory:")
    init_schema(conn)
    with conn:
        conn.execute("INSERT INTO ebooks (slug) VALUES ('demo')")
        conn.execute(
            "INSERT INTO ai_revisions (ebook_slug, idx, engine, base_rev) VALUES ('demo', 1, 'rewrite', 1)"
        )
    with conn:
        conn.execute("DELETE FROM ebooks WHERE slug = 'demo'")
    assert conn.execute("SELECT COUNT(*) AS c FROM ai_revisions").fetchone()["c"] == 0


def test_future_schema_is_rejected_without_downgrade():
    conn = get_connection(":memory:")
    init_schema(conn)
    with conn:
        conn.execute("UPDATE _meta SET value = ? WHERE key = 'schema_version'", (str(SCHEMA_VERSION + 1),))

    with pytest.raises(SchemaVersionError):
        init_schema(conn)
    assert schema_version(conn) == SCHEMA_VERSION + 1


def test_failed_migration_does_not_advance_version(monkeypatch):
    conn = get_connection(":memory:")
    init_schema(conn)
    with conn:
        conn.execute("UPDATE _meta SET value = '9' WHERE key = 'schema_version'")
        conn.execute("INSERT INTO ebooks (slug, title) VALUES ('kept', 'Không mất')")

    def fail_after_write(connection):
        connection.execute("UPDATE ebooks SET title = 'không được commit' WHERE slug = 'kept'")
        raise RuntimeError("simulated migration failure")

    monkeypatch.setitem(db_module._MIGRATIONS, 10, fail_after_write)
    with pytest.raises(RuntimeError, match="simulated migration failure"):
        init_schema(conn)

    assert schema_version(conn) == 9
    assert conn.execute("SELECT title FROM ebooks WHERE slug='kept'").fetchone()[0] == "Không mất"
