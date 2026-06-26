"""Bulk action + archive/unarchive trên trang chủ (xem spec ebook-management)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from novel2epub.config import Config, CrawlConfig, LibraryConfig, LibraryEntry, NovelConfig, OutputConfig, TranslateConfig


class _FakeJob:
    def __init__(self):
        self.queue = _FakeQueue()

    def status(self):
        return {
            "crawl": {"running": False, "step": "", "error": "", "log": []},
            "translate": {"running": False, "step": "", "error": "", "log": []},
        }


class _FakeQueue:
    def __init__(self):
        self.enqueued = []

    def enqueue(self, category, step, target, *, label="", ebook=""):
        self.enqueued.append({"category": category, "step": step, "label": label, "ebook": ebook})

        class _Job:
            id = "fake-id"
        return _Job()


def _cfg(tmp_path, slug):
    return Config(
        novel=NovelConfig(slug=slug, title=f"Truyện {slug}"),
        crawl=CrawlConfig(toc_url="http://x/book/1/"),
        translate=TranslateConfig(type="none"),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


def _client(monkeypatch, tmp_path, slugs=("a", "b")):
    from app import deps
    from app.main import app

    library = LibraryConfig(ebooks={slug: LibraryEntry(slug=slug, name=f"Truyện {slug}") for slug in slugs})
    monkeypatch.setattr(deps, "library", lambda: library)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: _cfg(tmp_path, slug))
    monkeypatch.setattr(deps, "LIBRARY_STATE_PATH", tmp_path / "library_state.json")
    fake_job = _FakeJob()
    app.state.job = fake_job
    return app, TestClient(app), fake_job


def test_index_hides_archived_by_default(monkeypatch, tmp_path):
    from app.library_state import set_archived

    app, client, _job = _client(monkeypatch, tmp_path)
    set_archived(tmp_path / "library_state.json", "a", True)

    res = client.get("/")
    assert res.status_code == 200
    assert "Truyện a" not in res.text
    assert "Truyện b" in res.text


def test_index_shows_archived_with_query_param(monkeypatch, tmp_path):
    from app.library_state import set_archived

    app, client, _job = _client(monkeypatch, tmp_path)
    set_archived(tmp_path / "library_state.json", "a", True)

    res = client.get("/?show_archived=1")
    assert res.status_code == 200
    assert "Truyện a" in res.text
    assert "Truyện b" in res.text


def test_archive_then_unarchive_roundtrip(monkeypatch, tmp_path):
    from app.library_state import archived_slugs

    app, client, _job = _client(monkeypatch, tmp_path)
    client.post("/library/ebooks/a/archive", follow_redirects=False)
    assert archived_slugs(tmp_path / "library_state.json") == {"a"}

    client.post("/library/ebooks/a/unarchive", follow_redirects=False)
    assert archived_slugs(tmp_path / "library_state.json") == set()


def test_bulk_action_enqueues_one_job_per_selected_slug(monkeypatch, tmp_path):
    app, client, fake_job = _client(monkeypatch, tmp_path)
    res = client.post(
        "/library/ebooks/bulk-action",
        data={"action": "crawl", "slugs": ["a", "b"]},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert len(fake_job.queue.enqueued) == 2
    assert {j["ebook"] for j in fake_job.queue.enqueued} == {"a", "b"}
    assert all(j["category"] == "crawl" for j in fake_job.queue.enqueued)


def test_bulk_action_rejects_invalid_action(monkeypatch, tmp_path):
    app, client, fake_job = _client(monkeypatch, tmp_path)
    res = client.post("/library/ebooks/bulk-action", data={"action": "delete", "slugs": ["a"]})
    assert res.status_code == 400


def test_export_config_returns_yaml(monkeypatch, tmp_path):
    app, client, fake_job = _client(monkeypatch, tmp_path)
    res = client.get("/ebooks/a/config/export")
    assert res.status_code == 200
    assert "novel" in res.text
    assert "Truyện a" in res.text
    assert res.headers["content-disposition"].startswith("attachment;")
