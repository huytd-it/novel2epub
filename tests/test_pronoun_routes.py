from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import pronouns
from novel2epub.chapter_versions import ChapterVersionError, ChapterVersionService
from novel2epub.pronoun_review import apply_pronoun_preview, preview_pronouns
from novel2epub.storage import Chapter, Manifest, Storage


@pytest.fixture
def book(tmp_path, monkeypatch):
    storage = Storage(tmp_path, "demo")
    chapters = [Chapter(index=i, url=f"https://test/{i}", title=f"Chương {i}") for i in range(1, 5)]
    storage.save_manifest(Manifest(slug="demo", chapters=chapters))
    for chapter in chapters:
        storage.write_raw(chapter, "Raw unchanged")
        for branch in ("ai", "local_mt"):
            storage.write_branch_text(chapter, branch, 'Hắn nói. “Tôi đợi mày.”')
            storage.write_branch_titles(chapter, branch, chapter.title, "")
            storage.write_branch_mt_snapshot(chapter, branch, "Snapshot unchanged")
            storage.mark_branch_complete(chapter, branch)
    with storage.conn:
        storage.conn.execute("UPDATE chapters SET skipped=1 WHERE ebook_slug='demo' AND idx=3")
        storage.conn.execute("UPDATE chapters SET meta_json=? WHERE ebook_slug='demo' AND idx=4", ('{"local_mt_complete": false}',))
    cfg = SimpleNamespace(output=SimpleNamespace(data_dir=tmp_path), novel=SimpleNamespace(slug="demo"))

    def resolved(slug):
        if slug != "demo":
            raise KeyError(slug)
        return cfg

    monkeypatch.setattr(pronouns.deps, "resolved_cfg", resolved)
    app = FastAPI()
    app.include_router(pronouns.router)
    with TestClient(app) as client:
        yield client, storage


def counts(storage):
    return tuple(storage.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in (
        "chapter_revisions", "chapter_operations", "ebook_extra_json",
    ))


def test_preview_read_only_full_diff_and_scope(book):
    client, storage = book
    before = counts(storage)
    rows = list(storage.conn.execute("SELECT * FROM chapters ORDER BY idx"))
    response = client.post("/api/ui/ebooks/demo/pronouns/preview", json={"branch": "local_mt", "indexes": [1, 3, 4]})
    assert response.status_code == 200
    report = response.json()
    assert report["scanned"] == 1 and report["replacements"] == 2
    assert [item["index"] for item in report["chapters"]] == [1]
    assert [item["index"] for item in report["skipped"]] == [3, 4]
    assert '-Hắn nói. “Tôi đợi mày.”' in report["chapters"][0]["diff"]
    assert '+Hắn nói. “Ta đợi ngươi.”' in report["chapters"][0]["diff"]
    assert counts(storage) == before
    assert [tuple(row) for row in storage.conn.execute("SELECT * FROM chapters ORDER BY idx")] == [tuple(row) for row in rows]


def test_apply_exact_preview_preserves_other_data_and_history(book):
    client, storage = book
    scope = {"branch": "local_mt", "indexes": [1]}
    preview = client.post("/api/ui/ebooks/demo/pronouns/preview", json=scope).json()
    response = client.post("/api/ui/ebooks/demo/pronouns/apply", json={**scope, "token": preview["token"], "confirmed": True})
    assert response.status_code == 200
    assert response.json() == {"applied": [1], "failed": [], "replacements": 2}
    chapter = storage.get_chapter(1)
    assert storage.read_branch_text(chapter, "local_mt") == 'Hắn nói. “Ta đợi ngươi.”'
    assert storage.read_branch_text(chapter, "ai") == 'Hắn nói. “Tôi đợi mày.”'
    assert storage.read_raw(chapter) == "Raw unchanged"
    assert storage.read_branch_mt_snapshot(chapter, "local_mt") == "Snapshot unchanged"
    assert storage.read_branch_mt_snapshot(chapter, "ai") == "Snapshot unchanged"
    assert storage.read_branch_title(chapter, "local_mt") == "Chương 1"
    # Immutable baseline + new revision, with provenance in the operation.
    assert storage.conn.execute("SELECT COUNT(*) FROM chapter_revisions WHERE branch='local_mt' AND chapter_index=1").fetchone()[0] == 2
    assert storage.conn.execute("SELECT COUNT(*) FROM chapter_operations WHERE kind='normalize_pronouns'").fetchone()[0] == 1
    # An old approval cannot be replayed after success.
    assert client.post("/api/ui/ebooks/demo/pronouns/apply", json={**scope, "token": preview["token"], "confirmed": True}).status_code == 409


@pytest.mark.parametrize("change", ["text", "title", "revision", "skip", "complete", "entities", "scope", "branch"])
def test_stale_preview_rejected_before_writes(book, change):
    client, storage = book
    scope = {"branch": "local_mt", "indexes": [1]}
    report = client.post("/api/ui/ebooks/demo/pronouns/preview", json=scope).json()
    with storage.conn:
        if change == "text":
            storage.conn.execute("UPDATE chapters SET local_mt_text='Edited' WHERE idx=1")
        elif change == "title":
            storage.conn.execute("UPDATE chapters SET local_mt_title='New title' WHERE idx=1")
        elif change == "revision":
            storage.conn.execute("UPDATE chapters SET local_mt_revision=local_mt_revision+1 WHERE idx=1")
        elif change == "skip":
            storage.conn.execute("UPDATE chapters SET skipped=1 WHERE idx=1")
        elif change == "complete":
            storage.conn.execute("UPDATE chapters SET meta_json=? WHERE idx=1", ('{"local_mt_complete": false}',))
        elif change == "entities":
            storage.conn.execute("INSERT INTO entity_dictionary (source, target, protect) VALUES ('Tôi', 'Tên', 1)")
    if change == "scope":
        scope["indexes"] = [2]
    elif change == "branch":
        scope["branch"] = "ai"
    before = counts(storage)
    response = client.post("/api/ui/ebooks/demo/pronouns/apply", json={**scope, "token": report["token"], "confirmed": True})
    assert response.status_code == 409
    assert counts(storage) == before


@pytest.mark.parametrize("payload", [
    {"branch": "other", "indexes": [1]}, {"branch": "ai", "indexes": []},
    {"branch": "ai", "indexes": list(range(51))}, {"branch": "ai", "indexes": [True]},
    {"branch": "ai", "indexes": [1, 1]}, {"branch": "ai", "indexes": [-1]},
    {"branch": "ai", "indexes": [999]},
])
def test_invalid_scopes(book, payload):
    client, storage = book
    before = counts(storage)
    response = client.post("/api/ui/ebooks/demo/pronouns/preview", json=payload)
    assert response.status_code in (400, 422)
    assert counts(storage) == before


def test_confirmation_and_token_required(book):
    client, storage = book
    scope = {"branch": "ai", "indexes": [1]}
    report = client.post("/api/ui/ebooks/demo/pronouns/preview", json=scope).json()
    before = counts(storage)
    for payload in [scope, {**scope, "token": report["token"]}, {**scope, "token": report["token"], "confirmed": False}, {**scope, "token": "é" * 64, "confirmed": True}]:
        assert client.post("/api/ui/ebooks/demo/pronouns/apply", json=payload).status_code == 422
    assert client.post("/api/ui/ebooks/unknown/pronouns/preview", json=scope).status_code == 404
    assert counts(storage) == before


def test_partial_cas_failure_is_reported_not_overwritten(book, monkeypatch):
    _client, storage = book
    scope = {"branch": "ai", "indexes": [1, 2]}
    preview = preview_pronouns(storage, **scope)
    original = ChapterVersionService.commit_document

    def commit(self, **kwargs):
        if kwargs["chapter_index"] == 2:
            raise ChapterVersionError("document_conflict", "Concurrent edit")
        return original(self, **kwargs)

    monkeypatch.setattr(ChapterVersionService, "commit_document", commit)
    result = apply_pronoun_preview(storage, **scope, token=preview["token"])
    assert result["applied"] == [1]
    assert result["failed"] == [{"index": 2, "code": "document_conflict", "error": "Concurrent edit"}]
    assert storage.read_branch_text(storage.get_chapter(2), "ai") == 'Hắn nói. “Tôi đợi mày.”'


def test_noop_and_non_bmp_full_diff(book):
    _client, storage = book
    ch = storage.get_chapter(1)
    storage.write_branch_text(ch, "ai", "😀\n" + "Không đổi\n" * 200 + '“Tôi về.”\nCUỐI CHƯƠNG')
    report = preview_pronouns(storage, branch="ai", indexes=[1])
    assert '-“Tôi về.”' in report["chapters"][0]["diff"]
    assert '+“Ta về.”' in report["chapters"][0]["diff"]
    assert "CUỐI CHƯƠNG" in report["chapters"][0]["diff"]
    storage.write_branch_text(ch, "ai", "Không có thoại")
    report = preview_pronouns(storage, branch="ai", indexes=[1])
    before = counts(storage)
    assert apply_pronoun_preview(storage, branch="ai", indexes=[1], token=report["token"]) == {"applied": [], "failed": [], "replacements": 0}
    assert counts(storage) == before


def test_preview_payload_is_bounded(book):
    client, storage = book
    storage.write_branch_text(storage.get_chapter(1), "ai", "a" * 2_000_001)
    before = counts(storage)
    response = client.post("/api/ui/ebooks/demo/pronouns/preview", json={"branch": "ai", "indexes": [1]})
    assert response.status_code == 400
    assert "2 MB" in response.json()["detail"]
    assert counts(storage) == before


def test_stale_unchanged_chapter_rejects_entire_approval(book):
    client, storage = book
    storage.write_branch_text(storage.get_chapter(2), "ai", "Không có thoại")
    scope = {"branch": "ai", "indexes": [1, 2]}
    report = client.post("/api/ui/ebooks/demo/pronouns/preview", json=scope).json()
    assert report["unchanged"] == 1
    storage.write_branch_text(storage.get_chapter(2), "ai", "Nội dung mới")
    before = counts(storage)
    response = client.post("/api/ui/ebooks/demo/pronouns/apply", json={**scope, "token": report["token"], "confirmed": True})
    assert response.status_code == 409
    assert counts(storage) == before
    assert storage.read_branch_text(storage.get_chapter(1), "ai") == 'Hắn nói. “Tôi đợi mày.”'
