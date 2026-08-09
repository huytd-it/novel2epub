"""Test cho M1-M3: schema ledger v13, backfill baseline idempotent, canonical hash.

Phủ: fresh schema, v12→v13 giữ dữ liệu, canonical đầy đủ SHA-256 + zlib,
baseline chính xác (decompress/hash), cô lập nhánh, idempotency, không đổi
dữ liệu hiện hành/revision/active_branch, parent NULL, cascade FK.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

import novel2epub.db as db_module
import novel2epub.ops_baseline as ops
from novel2epub.db import (
    SCHEMA_VERSION,
    get_connection,
    get_thread_connection,
    init_schema,
    schema_version,
)
from novel2epub.ops_baseline import (
    baseline_client_operation_id,
    canonical_chapter_payload,
    compress_content,
    decompress_content,
    full_content_hash,
    initialize_branch_revisions,
)
from novel2epub.revisions import BRANCH_AI, BRANCH_LOCAL_MT
from novel2epub.storage import Storage

_SEP = ops._CANONICAL_SEP
_SEP_BYTES = _SEP.encode("ascii")


def _parse_canonical(payload: bytes) -> tuple[str, str]:
    """Giải mã canonical `{tlen}:{title}{xlen}:{text}` — đọc tuần tự theo byte,
    KHÔNG dựa vào `:` trong title/text."""
    pos = 0
    colon = payload.index(_SEP_BYTES, pos)
    t_len = int(payload[pos:colon])
    pos = colon + 1
    title = payload[pos : pos + t_len].decode("utf-8")
    pos += t_len
    colon = payload.index(_SEP_BYTES, pos)
    x_len = int(payload[pos:colon])
    pos = colon + 1
    text = payload[pos : pos + x_len].decode("utf-8")
    return title, text


class _MemStorage(Storage):
    """Storage dựa trên :memory: để test không đụng đĩa — đăng ký kết nối
    vào thread-local của `db` để `ops_baseline` dùng đúng connection."""

    def __init__(self, conn: sqlite3.Connection, slug: str = "demo"):
        object.__setattr__(self, "data_dir", ".:memory:")
        object.__setattr__(self, "slug", slug)
        object.__setattr__(self, "_db_path", ":memory:")
        object.__setattr__(self, "_conn", conn)
        db_module._thread_local.conns = {":memory:": conn}

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn


def _seed_book(conn: sqlite3.Connection, slug: str = "demo") -> None:
    with conn:
        conn.execute("INSERT INTO ebooks (slug) VALUES (?)", (slug,))
        conn.execute(
            "INSERT INTO chapters (ebook_slug, idx, title, translated_text, "
            "local_mt_text, active_branch, revision, local_mt_revision) "
            "VALUES (?, 1, 'Chương 1', 'Bản dịch', 'Bản MT', 'ai', 3, 2)",
            (slug,),
        )
        conn.execute(
            "INSERT INTO chapters (ebook_slug, idx, title, translated_text, "
            "local_mt_text, local_mt_title, revision, local_mt_revision) "
            "VALUES (?, 2, 'Chương 2', 'Dịch 2', 'MT 2', 'Tiêu đề MT 2', 5, 7)",
            (slug,),
        )
        # Chỉ khởi tạo nhánh ai (text = NULL cho local_mt) — không nên baseline.
        conn.execute(
            "INSERT INTO chapters (ebook_slug, idx, title, translated_text) "
            "VALUES (?, 3, 'Chương 3', 'Dịch 3')",
            (slug,),
        )
        # Text rỗng nhưng cột KHÔNG NULL — vẫn tính là đã khởi tạo.
        conn.execute(
            "INSERT INTO chapters (ebook_slug, idx, title, translated_text) "
            "VALUES (?, 4, 'Chương rỗng', '')",
            (slug,),
        )


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def _fetch_baselines(conn: sqlite3.Connection, slug: str = "demo") -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT r.* FROM chapter_revisions r "
        "JOIN chapter_operations o ON o.id = r.operation_id "
        "WHERE o.kind = ? AND r.ebook_slug = ? ORDER BY r.id",
        (ops.KIND_MIGRATION_BASELINE, slug),
    ).fetchall()


def _content(
    conn: sqlite3.Connection, idx: int, branch: str, slug: str = "demo"
) -> sqlite3.Row:
    return conn.execute(
        "SELECT * FROM chapter_revisions WHERE ebook_slug=? "
        "AND chapter_index=? AND branch=? ORDER BY revision_number DESC LIMIT 1",
        (slug, idx, branch),
    ).fetchone()


# ────────────────────────────── M1: schema ──────────────────────────────


def test_v13_fresh_schema_tables_and_columns():
    conn = get_connection(":memory:")
    init_schema(conn)
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"chapter_operations", "chapter_revisions"} <= tables
    op_cols = _column_names(conn, "chapter_operations")
    assert {
        "id", "ebook_slug", "kind", "message", "actor_issuer", "actor_subject",
        "client_operation_id", "request_hash", "metadata_json", "created_at",
    } <= op_cols
    rev_cols = _column_names(conn, "chapter_revisions")
    assert {
        "id", "operation_id", "ebook_slug", "chapter_index", "branch",
        "revision_number", "parent_revision_id", "title", "content_blob",
        "content_encoding", "content_hash", "base_content_hash", "created_at",
    } <= rev_cols
    chapter_cols = _column_names(conn, "chapters")
    assert {"ai_content_hash", "local_mt_content_hash"} <= chapter_cols
    assert schema_version(conn) == SCHEMA_VERSION


def test_v13_operation_client_id_unique_and_kind_required():
    conn = get_connection(":memory:")
    init_schema(conn)
    with conn:
        conn.execute("INSERT INTO ebooks (slug) VALUES ('demo')")
        conn.execute(
            "INSERT INTO chapter_operations (ebook_slug, kind, client_operation_id) "
            "VALUES ('demo', 'migration_baseline', 'x1')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO chapter_operations (ebook_slug, kind, client_operation_id) "
                "VALUES ('demo', 'migration_baseline', 'x1')"
            )
        # kind là bắt buộc (NOT NULL).
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO chapter_operations (ebook_slug, client_operation_id) "
                "VALUES ('demo', 'c1')"
            )
        # client_operation_id là NULL-free (NOT NULL) — không được NULL.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO chapter_operations (ebook_slug, kind, client_operation_id) "
                "VALUES ('demo', 'translate', NULL)"
            )


def test_v13_branch_check_and_content_hash_length():
    conn = get_connection(":memory:")
    init_schema(conn)
    with conn:
        conn.execute("INSERT INTO ebooks (slug) VALUES ('demo')")
        conn.execute(
            "INSERT INTO chapter_operations (ebook_slug, kind, client_operation_id) "
            "VALUES ('demo', 'x', 'a')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            conn.execute(
                "INSERT INTO chapter_revisions (operation_id, ebook_slug, chapter_index, "
                "branch, revision_number, content_hash) VALUES (1, 'demo', 1, 'weird', 1, '')"
            )
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            conn.execute(
                "INSERT INTO chapter_revisions (operation_id, ebook_slug, chapter_index, "
                "branch, revision_number, content_hash) VALUES (1, 'demo', 1, 'ai', 1, 'abc')"
            )
    conn.execute(
        "INSERT INTO chapter_revisions (operation_id, ebook_slug, chapter_index, "
        "branch, revision_number, content_hash) VALUES (1, 'demo', 1, 'ai', 1, '')"
    )


def test_v13_unique_chapter_branch_revision():
    conn = get_connection(":memory:")
    init_schema(conn)
    with conn:
        conn.execute("INSERT INTO ebooks (slug) VALUES ('demo')")
        conn.execute(
            "INSERT INTO chapter_operations (ebook_slug, kind, client_operation_id) "
            "VALUES ('demo', 'x', 'a')"
        )
        conn.execute(
            "INSERT INTO chapter_revisions (operation_id, ebook_slug, chapter_index, "
            "branch, revision_number, content_hash) VALUES (1, 'demo', 1, 'ai', 1, '')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO chapter_revisions (operation_id, ebook_slug, chapter_index, "
                "branch, revision_number, content_hash) VALUES (1, 'demo', 1, 'ai', 1, '')"
            )
        # Cùng chương/nhánh khác revision_number thì cho phép.
        conn.execute(
            "INSERT INTO chapter_revisions (operation_id, ebook_slug, chapter_index, "
            "branch, revision_number, content_hash) VALUES (1, 'demo', 1, 'ai', 2, '')"
        )


def test_v13_revision_indexes_exist():
    conn = get_connection(":memory:")
    init_schema(conn)
    idx = {
        r["name"]: r["sql"] for r in conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='index'"
        )
    }
    assert "idx_chapter_revisions_unique" in idx
    assert "idx_chapter_revisions_branch" in idx
    assert "idx_chapter_revisions_operation" in idx
    assert "idx_chapter_operations_client_id" in idx
    assert "idx_chapters_ai_content_hash" in idx
    assert "idx_chapters_local_mt_content_hash" in idx


def test_v12_database_migrates_to_v13_keeping_data():
    conn = get_connection(":memory:")
    init_schema(conn)
    with conn:
        conn.execute("INSERT INTO ebooks (slug, title) VALUES ('old', 'Dữ liệu cũ')")
        conn.execute(
            "INSERT INTO chapters (ebook_slug, idx, title, translated_text, "
            "local_mt_text, local_mt_revision, revision, active_branch) "
            "VALUES ('old', 1, 'Tiêu đề', 'Dịch AI', 'Dịch MT', 5, 3, 'local_mt')"
        )
        conn.execute(
            "INSERT INTO chapter_operations (ebook_slug, kind, client_operation_id) "
            "VALUES ('old', 'x', 'keep-op')"
        )
        conn.execute(
            "INSERT INTO chapter_revisions (operation_id, ebook_slug, chapter_index, "
            "branch, revision_number, content_hash) VALUES (1, 'old', 1, 'ai', 1, '')"
        )
        conn.execute("UPDATE _meta SET value = '12' WHERE key = 'schema_version'")

    init_schema(conn)
    init_schema(conn)

    assert schema_version(conn) == SCHEMA_VERSION
    chapter = conn.execute(
        "SELECT title, translated_text, local_mt_text, local_mt_revision, "
        "revision, active_branch, ai_content_hash, local_mt_content_hash "
        "FROM chapters WHERE ebook_slug='old' AND idx=1"
    ).fetchone()
    assert chapter["translated_text"] == "Dịch AI"
    assert chapter["local_mt_text"] == "Dịch MT"
    assert chapter["local_mt_revision"] == 5
    assert chapter["revision"] == 3
    assert chapter["active_branch"] == "local_mt"
    assert chapter["ai_content_hash"] == ""
    assert chapter["local_mt_content_hash"] == ""
    assert conn.execute("SELECT * FROM chapter_operations").fetchone()["client_operation_id"] == "keep-op"
    row = conn.execute(
        "SELECT content_hash, base_content_hash, revision_number FROM chapter_revisions"
    ).fetchone()
    assert (row["content_hash"], row["base_content_hash"], row["revision_number"]) == ("", "", 1)


def test_v13_revisions_cascade_on_operation_delete():
    conn = get_connection(":memory:")
    init_schema(conn)
    with conn:
        conn.execute("INSERT INTO ebooks (slug) VALUES ('demo')")
        conn.execute(
            "INSERT INTO chapter_operations (ebook_slug, kind, client_operation_id) "
            "VALUES ('demo', 'x', 'a')"
        )
        conn.execute(
            "INSERT INTO chapter_revisions (operation_id, ebook_slug, chapter_index, "
            "branch, revision_number, content_hash) VALUES (1, 'demo', 1, 'ai', 1, '')"
        )
    with conn:
        conn.execute("DELETE FROM chapter_operations WHERE id = 1")
    assert conn.execute("SELECT COUNT(*) AS c FROM chapter_revisions").fetchone()["c"] == 0


def test_v13_parent_revision_does_not_cascade_delete():
    """Immutable history: xoá revision cha KHÔNG được kéo theo con (parent FK
    là NO ACTION mặc định, không CASCADE). Chỉ operation cascade khi xoá ebook."""
    conn = get_connection(":memory:")
    init_schema(conn)
    with conn:
        conn.execute("INSERT INTO ebooks (slug) VALUES ('demo')")
        conn.execute(
            "INSERT INTO chapter_operations (ebook_slug, kind, client_operation_id) "
            "VALUES ('demo', 'x', 'a')"
        )
        conn.execute(
            "INSERT INTO chapter_revisions (operation_id, ebook_slug, chapter_index, "
            "branch, revision_number, content_hash) VALUES (1, 'demo', 1, 'ai', 1, '')"
        )
        conn.execute(
            "INSERT INTO chapter_revisions (operation_id, ebook_slug, chapter_index, "
            "branch, revision_number, parent_revision_id, content_hash) "
            "VALUES (1, 'demo', 1, 'ai', 2, 1, '')"
        )
    # Cố xoá cha (id=1) có con — phải bị chặn.
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            conn.execute("DELETE FROM chapter_revisions WHERE id = 1")
    assert conn.execute("SELECT COUNT(*) AS c FROM chapter_revisions").fetchone()["c"] == 2
    # Con (id=2) không có con — xoá được.
    with conn:
        conn.execute("DELETE FROM chapter_revisions WHERE id = 2")
    assert conn.execute("SELECT COUNT(*) AS c FROM chapter_revisions").fetchone()["c"] == 1


def test_v13_cascade_delete_with_ebook():
    conn = get_connection(":memory:")
    init_schema(conn)
    with conn:
        conn.execute("INSERT INTO ebooks (slug) VALUES ('demo')")
        conn.execute(
            "INSERT INTO chapter_operations (ebook_slug, kind, client_operation_id) "
            "VALUES ('demo', 'migration_baseline', 'b')"
        )
        conn.execute(
            "INSERT INTO chapter_revisions (operation_id, ebook_slug, chapter_index, "
            "branch, revision_number, content_hash) VALUES (1, 'demo', 1, 'ai', 1, '')"
        )
    with conn:
        conn.execute("DELETE FROM ebooks WHERE slug = 'demo'")
    assert conn.execute("SELECT COUNT(*) AS c FROM chapter_operations").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM chapter_revisions").fetchone()["c"] == 0


# ──────────────────────── M3: canonical + hash + zlib ────────────────────

def test_canonical_is_bytes_preserving_exact_title_and_text():
    title = "  Tiêu đề  \n"
    text = "\n\n  Dòng có khoảng trắng  \n\n"
    payload = canonical_chapter_payload(title, text)
    assert isinstance(payload, bytes)
    assert title.encode("utf-8") in payload
    assert text.encode("utf-8") in payload
    # Giải mã canonical: độ dài theo BYTE phải khớp từng byte.
    round_title, round_text = _parse_canonical(payload)
    assert round_title == title
    assert round_text == text
    assert decompress_content(compress_content(text)) == text


def test_canonical_uses_byte_lengths_not_code_points():
    # 中文 = 6 bytes, 2 code point. Độ dài trong canonical phải là SỐ BYTE.
    title = "T"
    text = "中文"
    payload = canonical_chapter_payload(title, text)
    # Khối prefix `{tlen}:{title}{xlen}:` — đọc tuần tự, title và xlen chạy liền.
    colon = payload.index(_SEP_BYTES)
    assert int(payload[:colon]) == 1
    rest = payload[colon + 1:]
    assert rest.startswith(b"T")
    # Sau title (1 byte) là xlen, rồi `:`.
    assert int(rest[1 : rest.index(_SEP_BYTES)]) == 6
    # Giải mã trả về đúng text gốc.
    assert _parse_canonical(payload) == ("T", "中文")


def test_canonical_distinguishes_trailing_newline():
    # `a\n` và `a` phải ra canonical khác nhau — không bị trim.
    assert canonical_chapter_payload("T", "a\n") != canonical_chapter_payload("T", "a")
    assert full_content_hash("T", "a\n") != full_content_hash("T", "a")


def test_full_content_hash_is_sha256_64_hex():
    digest = full_content_hash("Tiêu đề", "Nội dung")
    assert len(digest) == 64
    import hashlib
    assert digest == hashlib.sha256(
        canonical_chapter_payload("Tiêu đề", "Nội dung")
    ).hexdigest()


def test_hash_changes_with_title_or_text_only():
    h1 = full_content_hash("A", "B")
    assert h1 != full_content_hash("A2", "B")
    assert h1 != full_content_hash("A", "B2")
    assert full_content_hash("A", "B") == h1


def test_compress_decompress_roundtrip_unicode():
    text = "Chương 1\n\nDòng đầu.\n\nDòng thứ hai 中文 " * 50
    blob = compress_content(text)
    assert isinstance(blob, bytes)
    assert decompress_content(blob) == text
    # Nén thật sự nhỏ hơn cho văn bản lặp (bằng chứng zlib được dùng).
    assert len(blob) < len(text.encode("utf-8"))


# ─────────────────────────── M2: baseline backfill ───────────────────────


def test_baseline_snapshots_initialized_branches():
    conn = get_connection(":memory:")
    init_schema(conn)
    _seed_book(conn)
    result = initialize_branch_revisions(_MemStorage(conn))

    # ai: chương 1,2,3,4 — local_mt: chương 1,2 (chương 4 NULL → không baseline).
    assert result["revisions"] == 6
    assert result["branches"] == ["ai", "local_mt"]
    assert result["operations"] == 1
    assert result["chapters"] == 4  # distinct chapter indexes bị ảnh hưởng

    rows = _fetch_baselines(conn)
    assert len(rows) == 6
    for row in rows:
        assert row["parent_revision_id"] is None
        assert row["base_content_hash"] == ""
        assert row["content_encoding"] == "zlib"

    ai1 = _content(conn, 1, BRANCH_AI)
    assert ai1["title"] == "Chương 1"
    assert ai1["revision_number"] == 3  # chapters.revision của nhánh ai
    assert decompress_content(ai1["content_blob"]) == "Bản dịch"
    assert ai1["content_hash"] == full_content_hash("Chương 1", "Bản dịch")

    ai2 = _content(conn, 2, BRANCH_AI)
    assert ai2["revision_number"] == 5
    assert ai2["content_hash"] == full_content_hash("Chương 2", "Dịch 2")

    mt1 = _content(conn, 1, BRANCH_LOCAL_MT)
    assert mt1["title"] == ""
    assert mt1["revision_number"] == 2  # chapters.local_mt_revision
    assert decompress_content(mt1["content_blob"]) == "Bản MT"
    assert mt1["content_hash"] == full_content_hash("", "Bản MT")

    mt2 = _content(conn, 2, BRANCH_LOCAL_MT)
    assert mt2["title"] == "Tiêu đề MT 2"
    assert mt2["revision_number"] == 7
    assert mt2["content_hash"] == full_content_hash("Tiêu đề MT 2", "MT 2")


def test_baseline_handles_empty_but_non_null_text():
    conn = get_connection(":memory:")
    init_schema(conn)
    _seed_book(conn)
    initialize_branch_revisions(_MemStorage(conn))
    ai4 = _content(conn, 4, BRANCH_AI)
    assert ai4 is not None
    assert decompress_content(ai4["content_blob"]) == ""
    assert ai4["content_hash"] == full_content_hash("Chương rỗng", "")
    # local_mt của chương 4 NULL → không có baseline.
    assert _content(conn, 4, BRANCH_LOCAL_MT) is None


def test_baseline_writes_branch_hash_columns():
    conn = get_connection(":memory:")
    init_schema(conn)
    _seed_book(conn)
    initialize_branch_revisions(_MemStorage(conn))
    ch = conn.execute(
        "SELECT ai_content_hash, local_mt_content_hash FROM chapters WHERE idx=1"
    ).fetchone()
    assert ch["ai_content_hash"] == full_content_hash("Chương 1", "Bản dịch")
    assert ch["local_mt_content_hash"] == full_content_hash("", "Bản MT")


def test_baseline_branch_isolation():
    conn = get_connection(":memory:")
    init_schema(conn)
    _seed_book(conn)
    initialize_branch_revisions(_MemStorage(conn), branches=["local_mt"])
    assert _content(conn, 1, BRANCH_LOCAL_MT) is not None
    assert _content(conn, 1, BRANCH_AI) is None
    ch = conn.execute(
        "SELECT ai_content_hash, local_mt_content_hash FROM chapters WHERE idx=1"
    ).fetchone()
    assert ch["ai_content_hash"] == ""
    assert ch["local_mt_content_hash"] == full_content_hash("", "Bản MT")


def test_baseline_does_not_alter_current_data_revision_or_active_branch():
    conn = get_connection(":memory:")
    init_schema(conn)
    _seed_book(conn)
    before = conn.execute(
        "SELECT idx, title, translated_text, local_mt_text, revision, "
        "local_mt_revision, active_branch FROM chapters ORDER BY idx"
    ).fetchall()
    initialize_branch_revisions(_MemStorage(conn))
    initialize_branch_revisions(_MemStorage(conn))
    after = conn.execute(
        "SELECT idx, title, translated_text, local_mt_text, revision, "
        "local_mt_revision, active_branch FROM chapters ORDER BY idx"
    ).fetchall()
    assert [tuple(r) for r in before] == [tuple(r) for r in after]


def test_baseline_is_idempotent_no_duplicates():
    conn = get_connection(":memory:")
    init_schema(conn)
    _seed_book(conn)
    r1 = initialize_branch_revisions(_MemStorage(conn))
    r2 = initialize_branch_revisions(_MemStorage(conn))
    r3 = initialize_branch_revisions(_MemStorage(conn))
    assert r1["revisions"] == 6
    assert r2["revisions"] == 0
    assert r3["revisions"] == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM chapter_revisions").fetchone()["c"] == 6
    assert conn.execute("SELECT COUNT(*) AS c FROM chapter_operations").fetchone()["c"] == 1


def test_baseline_resumes_after_partial_branch():
    conn = get_connection(":memory:")
    init_schema(conn)
    _seed_book(conn)
    initialize_branch_revisions(_MemStorage(conn), branches=["ai"])
    # Chạy tiếp nhánh còn lại — phải thêm đúng phần thiếu, không trùng.
    result = initialize_branch_revisions(_MemStorage(conn), branches=["local_mt"])
    assert result["revisions"] == 2
    rows = _fetch_baselines(conn)
    assert len(rows) == 6
    assert conn.execute("SELECT COUNT(*) AS c FROM chapter_operations").fetchone()["c"] == 1
    assert conn.execute(
        "SELECT COUNT(DISTINCT content_hash) AS c FROM chapter_revisions"
    ).fetchone()["c"] == 6


def test_baseline_single_transaction_rolls_back_cleanly(monkeypatch):
    conn = get_connection(":memory:")
    init_schema(conn)
    _seed_book(conn)
    storage = _MemStorage(conn)

    calls = {"n": 0}

    def boom(*args, **kwargs):
        calls["n"] += 1
        yield ("idx", "title", "text", "ai", 1)
        yield ("idx2", "title", "text", "ai", 1)
        raise RuntimeError("boom giữa chừng")

    monkeypatch.setattr(ops, "_iter_initialized_branches", boom)
    with pytest.raises(RuntimeError, match="boom"):
        initialize_branch_revisions(storage)

    # Transaction rollback: không có operation, không có revision, hash rỗng.
    assert conn.execute("SELECT COUNT(*) AS c FROM chapter_operations").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM chapter_revisions").fetchone()["c"] == 0
    ch = conn.execute("SELECT ai_content_hash FROM chapters WHERE idx=1").fetchone()
    assert ch["ai_content_hash"] == ""


def test_baseline_source_drift_before_lock_aborts_without_operation(monkeypatch):
    conn = get_connection(":memory:")
    init_schema(conn)
    _seed_book(conn)
    original_begin = ops._begin_immediate

    def drift_then_lock(connection):
        connection.execute(
            "UPDATE chapters SET translated_text='đổi xen giữa' "
            "WHERE ebook_slug='demo' AND idx=1"
        )
        connection.commit()
        original_begin(connection)

    monkeypatch.setattr(ops, "_begin_immediate", drift_then_lock)
    with pytest.raises(RuntimeError, match="baseline source changed"):
        initialize_branch_revisions(_MemStorage(conn))
    assert conn.execute("SELECT COUNT(*) FROM chapter_operations").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM chapter_revisions").fetchone()[0] == 0
    hashes = conn.execute(
        "SELECT ai_content_hash, local_mt_content_hash FROM chapters WHERE idx=1"
    ).fetchone()
    assert tuple(hashes) == ("", "")


def test_baseline_failure_after_operation_rolls_back_everything():
    conn = get_connection(":memory:")
    init_schema(conn)
    _seed_book(conn)
    with conn:
        conn.execute(
            "CREATE TRIGGER fail_second_baseline BEFORE INSERT ON chapter_revisions "
            "WHEN NEW.chapter_index=2 BEGIN SELECT RAISE(ABORT, 'forced insert failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="forced insert failure"):
        initialize_branch_revisions(_MemStorage(conn))
    assert conn.execute("SELECT COUNT(*) FROM chapter_operations").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM chapter_revisions").fetchone()[0] == 0
    rows = conn.execute(
        "SELECT ai_content_hash, local_mt_content_hash FROM chapters ORDER BY idx"
    ).fetchall()
    assert all(tuple(row) == ("", "") for row in rows)


def test_baseline_no_initialized_branches_creates_no_operation():
    conn = get_connection(":memory:")
    init_schema(conn)
    with conn:
        conn.execute("INSERT INTO ebooks (slug) VALUES ('demo')")
        conn.execute(
            "INSERT INTO chapters (ebook_slug, idx, title, translated_text) "
            "VALUES ('demo', 1, 'T', NULL)"
        )
    result = initialize_branch_revisions(_MemStorage(conn))
    assert result == {"branches": [], "revisions": 0, "chapters": 0, "operations": 0}
    assert conn.execute("SELECT COUNT(*) AS c FROM chapter_revisions").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM chapter_operations").fetchone()["c"] == 0


def test_baseline_operation_kind_and_metadata():
    conn = get_connection(":memory:")
    init_schema(conn)
    _seed_book(conn)
    initialize_branch_revisions(_MemStorage(conn), message="msg tùy biến", actor_issuer="iss", actor_subject="sub")
    op = conn.execute(
        "SELECT kind, message, actor_issuer, actor_subject, client_operation_id, request_hash, metadata_json "
        "FROM chapter_operations"
    ).fetchone()
    assert op["kind"] == "migration_baseline"
    assert op["message"] == "msg tùy biến"
    assert op["actor_issuer"] == "iss"
    assert op["actor_subject"] == "sub"
    assert json.loads(op["metadata_json"]) == {}
    assert op["client_operation_id"] == baseline_client_operation_id("demo")
    assert op["request_hash"] == ops.baseline_request_hash("demo")
    assert len(op["request_hash"]) == 64


def test_baseline_client_operation_id_differs_per_ebook():
    """client_operation_id phải KHÁC NHAU giữa các ebook (UNIQUE toàn DB) —
    một hằng số chung sẽ đụng nhau giữa hai ebook."""
    assert baseline_client_operation_id("demo") != baseline_client_operation_id("other")
    assert baseline_client_operation_id("demo").endswith("demo")
    assert baseline_client_operation_id("other").endswith("other")


def test_baseline_two_ebooks_independent_and_no_cross_duplicate():
    """Hai ebook cùng baseline-backfill: mỗi ebook một operation riêng
    (client_operation_id gồm slug), revision độc lập, không trùng UNIQUE."""
    conn = get_connection(":memory:")
    init_schema(conn)
    _seed_book(conn, "demo")
    _seed_book(conn, "other")
    r1 = initialize_branch_revisions(_MemStorage(conn, "demo"))
    r2 = initialize_branch_revisions(_MemStorage(conn, "other"))
    assert r1["revisions"] == 6
    assert r2["revisions"] == 6
    assert conn.execute("SELECT COUNT(*) AS c FROM chapter_operations").fetchone()["c"] == 2
    assert conn.execute("SELECT COUNT(*) AS c FROM chapter_revisions").fetchone()["c"] == 12
    ops_ids = {r["client_operation_id"] for r in conn.execute("SELECT client_operation_id FROM chapter_operations")}
    assert ops_ids == {baseline_client_operation_id("demo"), baseline_client_operation_id("other")}
    # Chạy lại — idempotent cho CẢ HAI, không trùng.
    r3 = initialize_branch_revisions(_MemStorage(conn, "demo"))
    r4 = initialize_branch_revisions(_MemStorage(conn, "other"))
    assert r3["revisions"] == 0
    assert r4["revisions"] == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM chapter_operations").fetchone()["c"] == 2
    assert conn.execute("SELECT COUNT(*) AS c FROM chapter_revisions").fetchone()["c"] == 12


def test_baseline_parent_null_for_chain():
    conn = get_connection(":memory:")
    init_schema(conn)
    _seed_book(conn)
    initialize_branch_revisions(_MemStorage(conn))
    row = conn.execute(
        "SELECT parent_revision_id FROM chapter_revisions WHERE content_hash != '' LIMIT 1"
    ).fetchone()
    assert row["parent_revision_id"] is None


def test_baseline_skips_branches_with_existing_history():
    """Một (chương, nhánh) ĐÃ CÓ revision (history ghi trước v13, không phải
    baseline) thì baseline KHÔNG ghi đè — bỏ qua. Baseline chỉ áp cho nhánh
    chưa từng có revision nào."""
    conn = get_connection(":memory:")
    init_schema(conn)
    _seed_book(conn)
    with conn:
        # "History" ghi trước cho (chương 1, ai): revision_number 3 (khớp
        # chapters.revision hiện tại) — không phải baseline (base không rỗng).
        conn.execute(
            "INSERT INTO chapter_operations (ebook_slug, kind, client_operation_id) "
            "VALUES ('demo', 'translate', 'pre-op-1')"
        )
        conn.execute(
            "INSERT INTO chapter_revisions (operation_id, ebook_slug, chapter_index, "
            "branch, revision_number, parent_revision_id, title, content_hash, "
            "base_content_hash) VALUES (1, 'demo', 1, 'ai', 3, NULL, 'Cũ', "
            "'11223344556677889900aabbccddeeff11223344556677889900aabbccddeeff', 'xyz')"
        )
    result = initialize_branch_revisions(_MemStorage(conn))
    # Bỏ qua (1, ai) vì đã có history → chỉ còn ai(2,3,4) + local_mt(1,2) = 5.
    assert result["revisions"] == 5
    ai1 = _content(conn, 1, BRANCH_AI)
    # Baseline KHÔNG ghi đè revision hiện hành của nhánh đã có history.
    assert ai1["operation_id"] == 1
    assert ai1["content_hash"] == "11223344556677889900aabbccddeeff11223344556677889900aabbccddeeff"
    assert ai1["base_content_hash"] == "xyz"


def test_baseline_idempotent_when_existing_revision_not_baseline():
    """Revision không phải baseline (base_content_hash != '') không bị nhầm là
    baseline nhưng VẪN khiến baseline bỏ qua (đã có history) — và không lỗi."""
    conn = get_connection(":memory:")
    init_schema(conn)
    _seed_book(conn)
    initialize_branch_revisions(_MemStorage(conn))
    with conn:
        conn.execute(
            "UPDATE chapter_revisions SET base_content_hash='some-parent' "
            "WHERE chapter_index=2 AND branch='ai'"
        )
    result = initialize_branch_revisions(_MemStorage(conn))
    assert result["revisions"] == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM chapter_revisions").fetchone()["c"] == 6
