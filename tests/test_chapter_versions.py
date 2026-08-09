from __future__ import annotations

import sqlite3

import pytest

import novel2epub.db as db_module
import novel2epub.chapter_versions as versions
from novel2epub.chapter_versions import ChapterVersionError, ChapterVersionService
from novel2epub.db import get_connection, init_schema
from novel2epub.ops_baseline import decompress_content, full_content_hash, initialize_branch_revisions
from novel2epub.storage import Storage


class MemStorage(Storage):
    def __init__(self, conn: sqlite3.Connection, slug: str = "demo"):
        object.__setattr__(self, "data_dir", ".:memory:")
        object.__setattr__(self, "slug", slug)
        object.__setattr__(self, "_db_path", ":memory:")
        object.__setattr__(self, "_conn", conn)
        db_module._thread_local.conns = {":memory:": conn}

    @property
    def conn(self):
        return self._conn


@pytest.fixture
def env():
    conn = get_connection(":memory:")
    init_schema(conn)
    with conn:
        conn.execute("INSERT INTO ebooks (slug) VALUES ('demo')")
        conn.execute(
            "INSERT INTO chapters (ebook_slug, idx, title, translated_text, revision, "
            "local_mt_title, local_mt_text, local_mt_revision, active_branch) "
            "VALUES ('demo', 1, ?, ?, 3, ?, ?, 7, 'local_mt')",
            ("  Chương 一  \n", "\nDòng một\r\n中文  \n", "MT title", "MT text"),
        )
    storage = MemStorage(conn)
    initialize_branch_revisions(storage)
    return conn, storage, ChapterVersionService(storage)


def counts(conn):
    return tuple(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("chapter_operations", "chapter_revisions"))


def assert_code(code, fn):
    with pytest.raises(ChapterVersionError) as info:
        fn()
    assert info.value.code == code
    return info.value


def test_read_document_preserves_exact_text_and_requires_baseline(env):
    conn, storage, service = env
    doc = service.read_document(1, "ai")
    assert doc.title == "  Chương 一  \n"
    assert doc.translated == "\nDòng một\r\n中文  \n"
    assert doc.revision == 3
    assert doc.content_hash == full_content_hash(doc.title, doc.translated)
    with conn:
        conn.execute("DELETE FROM chapter_revisions WHERE branch='ai'")
    assert_code("branch_not_initialized", lambda: service.read_document(1, "ai"))


def test_commit_is_atomic_immutable_and_parented(env):
    conn, _, service = env
    base = service.read_document(1, "ai")
    result = service.commit_document(
        chapter_index=1, branch="ai", expected_revision=base.revision,
        expected_content_hash=base.content_hash, title=" Tiêu đề mới\n",
        translated="\nNội dung mới\r\n中文\n", client_operation_id="save-1",
        message="Lưu thủ công", actor_issuer="issuer", actor_subject="subject",
    )
    assert result.status == "committed"
    assert result.document.revision == 4
    assert result.document.title == " Tiêu đề mới\n"
    assert result.document.translated == "\nNội dung mới\r\n中文\n"
    row = conn.execute("SELECT * FROM chapter_revisions WHERE id=?", (result.revision_id,)).fetchone()
    assert row["parent_revision_id"] == base.head_revision_id
    assert row["base_content_hash"] == base.content_hash
    assert row["content_hash"] == result.document.content_hash
    assert decompress_content(row["content_blob"]) == result.document.translated
    op = conn.execute("SELECT * FROM chapter_operations WHERE id=?", (result.operation_id,)).fetchone()
    assert op["request_hash"] and len(op["request_hash"]) == 64
    assert (op["message"], op["actor_issuer"], op["actor_subject"]) == ("Lưu thủ công", "issuer", "subject")
    current = conn.execute("SELECT title, translated_text, revision, ai_content_hash, updated_by_issuer FROM chapters WHERE idx=1").fetchone()
    assert tuple(current) == (result.document.title, result.document.translated, 4, result.document.content_hash, "issuer")
    assert service.validate_integrity(chapter_index=1).valid


def test_second_commit_monotonic_single_parent(env):
    _, _, service = env
    base = service.read_document(1, "ai")
    one = service.commit_document(chapter_index=1, branch="ai", expected_revision=3, expected_content_hash=base.content_hash, title="A", translated="B", client_operation_id="one")
    two = service.commit_document(chapter_index=1, branch="ai", expected_revision=4, expected_content_hash=one.document.content_hash, title="C", translated="D", client_operation_id="two")
    assert two.document.revision == 5
    assert service.conn.execute("SELECT parent_revision_id FROM chapter_revisions WHERE id=?", (two.revision_id,)).fetchone()[0] == one.revision_id


def test_branch_isolation(env):
    _, _, service = env
    ai_before = service.read_document(1, "ai")
    mt = service.read_document(1, "local_mt")
    saved = service.commit_document(chapter_index=1, branch="local_mt", expected_revision=mt.revision, expected_content_hash=mt.content_hash, title="MT2", translated="MT changed", client_operation_id="mt-save")
    assert saved.document.revision == 8
    assert service.read_document(1, "ai") == ai_before


def test_noop_creates_nothing(env):
    conn, _, service = env
    doc = service.read_document(1, "ai")
    before = counts(conn)
    result = service.commit_document(chapter_index=1, branch="ai", expected_revision=doc.revision, expected_content_hash=doc.content_hash, title=doc.title, translated=doc.translated, client_operation_id="noop")
    assert result.status == "unchanged"
    assert counts(conn) == before
    assert conn.execute("SELECT 1 FROM chapter_operations WHERE client_operation_id='noop'").fetchone() is None


@pytest.mark.parametrize("which", ["revision", "hash"])
def test_stale_conflict_rolls_back_without_rows(env, which):
    conn, _, service = env
    doc = service.read_document(1, "ai")
    before = counts(conn)
    kwargs = {"expected_revision": doc.revision, "expected_content_hash": doc.content_hash}
    kwargs["expected_revision" if which == "revision" else "expected_content_hash"] = 99 if which == "revision" else "0" * 64
    error = assert_code("document_conflict", lambda: service.commit_document(chapter_index=1, branch="ai", title="new", translated="new", client_operation_id=f"stale-{which}", **kwargs))
    assert error.details["current_revision"] == doc.revision
    assert counts(conn) == before


def test_two_tab_conflict(env):
    conn, storage, first = env
    second = ChapterVersionService(storage)
    a = first.read_document(1, "ai")
    b = second.read_document(1, "ai")
    first.commit_document(chapter_index=1, branch="ai", expected_revision=a.revision, expected_content_hash=a.content_hash, title="first", translated="first", client_operation_id="tab-1")
    before = counts(conn)
    assert_code("document_conflict", lambda: second.commit_document(chapter_index=1, branch="ai", expected_revision=b.revision, expected_content_hash=b.content_hash, title="second", translated="second", client_operation_id="tab-2"))
    assert counts(conn) == before


def test_idempotency_replay_and_reuse(env):
    conn, _, service = env
    doc = service.read_document(1, "ai")
    kwargs = dict(chapter_index=1, branch="ai", expected_revision=doc.revision, expected_content_hash=doc.content_hash, title="saved", translated="saved", client_operation_id="idem")
    first = service.commit_document(**kwargs)
    before = counts(conn)
    replay = service.commit_document(**kwargs)
    assert replay.idempotent_replay
    assert (replay.operation_id, replay.revision_id) == (first.operation_id, first.revision_id)
    assert counts(conn) == before
    changed = dict(kwargs, translated="different")
    assert_code("idempotency_key_reused", lambda: service.commit_document(**changed))
    assert counts(conn) == before


def test_idempotency_replay_returns_original_result_after_later_commit(env):
    conn, _, service = env
    base = service.read_document(1, "ai")
    original_args = dict(
        chapter_index=1, branch="ai", expected_revision=base.revision,
        expected_content_hash=base.content_hash, title="first", translated="first",
        client_operation_id="original",
    )
    first = service.commit_document(**original_args)
    later = service.commit_document(
        chapter_index=1, branch="ai", expected_revision=first.document.revision,
        expected_content_hash=first.document.content_hash, title="later",
        translated="later", client_operation_id="later",
    )
    before = counts(conn)
    replay = service.commit_document(**original_args)
    assert replay.idempotent_replay
    assert replay.revision_id == first.revision_id
    assert replay.document.title == "first"
    assert replay.document.revision == first.document.revision
    assert service.read_document(1, "ai") == later.document
    assert counts(conn) == before


@pytest.mark.parametrize("branch", ["", "AI", "weird", None])
def test_invalid_branch_rejected(env, branch):
    _, _, service = env
    assert_code("invalid_request", lambda: service.read_document(1, branch))


def test_invalid_hash_and_document_limit(env, monkeypatch):
    _, _, service = env
    doc = service.read_document(1, "ai")
    assert_code("invalid_request", lambda: service.commit_document(chapter_index=1, branch="ai", expected_revision=3, expected_content_hash="abc", title="x", translated="x", client_operation_id="x"))
    monkeypatch.setattr(versions, "MAX_DOCUMENT_BYTES", 2)
    assert_code("document_too_large", lambda: service.commit_document(chapter_index=1, branch="ai", expected_revision=3, expected_content_hash=doc.content_hash, title="xx", translated="x", client_operation_id="large"))


@pytest.mark.parametrize("mutation", ["revision", "hash", "title", "text", "blob", "snapshot_hash"])
def test_current_head_divergence_and_corruption_detected(env, mutation):
    conn, _, service = env
    with conn:
        if mutation == "revision":
            conn.execute("UPDATE chapters SET revision=revision+1 WHERE idx=1")
        elif mutation == "hash":
            conn.execute("UPDATE chapters SET ai_content_hash=? WHERE idx=1", ("0" * 64,))
        elif mutation == "title":
            conn.execute("UPDATE chapters SET title='tampered' WHERE idx=1")
        elif mutation == "text":
            conn.execute("UPDATE chapters SET translated_text='tampered' WHERE idx=1")
        elif mutation == "blob":
            conn.execute("UPDATE chapter_revisions SET content_blob=x'00' WHERE branch='ai'")
        else:
            conn.execute("UPDATE chapter_revisions SET content_hash=? WHERE branch='ai'", ("0" * 64,))
    assert_code("history_state_diverged", lambda: service.read_document(1, "ai"))
    report = service.validate_integrity(chapter_index=1)
    assert not report.valid


def test_failed_postcondition_rolls_back_operation_revision_and_current(env, monkeypatch):
    conn, _, service = env
    doc = service.read_document(1, "ai")
    before_counts = counts(conn)
    before_current = tuple(conn.execute("SELECT title, translated_text, revision, ai_content_hash FROM chapters WHERE idx=1").fetchone())
    original = versions._verify_pair
    calls = {"n": 0}

    def fail_post(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ChapterVersionError("history_state_diverged", "forced")
        return original(*args, **kwargs)

    monkeypatch.setattr(versions, "_verify_pair", fail_post)
    assert_code("history_state_diverged", lambda: service.commit_document(chapter_index=1, branch="ai", expected_revision=doc.revision, expected_content_hash=doc.content_hash, title="new", translated="new", client_operation_id="rollback"))
    assert counts(conn) == before_counts
    assert tuple(conn.execute("SELECT title, translated_text, revision, ai_content_hash FROM chapters WHERE idx=1").fetchone()) == before_current
