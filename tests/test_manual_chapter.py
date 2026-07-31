from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from novel2epub.config import Config, CrawlConfig, NovelConfig, OutputConfig, TranslateConfig
from novel2epub.storage import Chapter, Manifest, Storage


def _storage(tmp_path: Path) -> Storage:
    storage = Storage(tmp_path, "t")
    storage.save_manifest(Manifest(slug="t"))
    return storage


def _chapter_row(storage: Storage, index: int):
    return storage.conn.execute(
        "SELECT * FROM chapters WHERE ebook_slug=? AND idx=?",
        ("t", index),
    ).fetchone()


def _cfg(tmp_path):
    return Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/book/", delay_seconds=0),
        translate=TranslateConfig(type="none"),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


def _client(tmp_path, monkeypatch):
    from app import deps
    from app.main import app

    cfg = _cfg(tmp_path)
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)

    class _FakeJob:
        def status(self):
            return {
                "crawl": {"running": False, "step": "", "error": "", "running_ebooks": []},
                "translate": {"running": False, "step": "", "error": "", "running_ebooks": []},
            }
    app.state.job = _FakeJob()
    return TestClient(app, follow_redirects=False)


# --- Storage.insert_chapter tests (from Task 1) ---


def test_insert_chapter_into_empty_manifest(tmp_path):
    storage = _storage(tmp_path)

    storage.insert_chapter(Chapter(index=1, url="https://x/1", title="第一章", title_zh="第一章"))

    manifest = storage.load_manifest()
    assert [(ch.index, ch.url, ch.title, ch.title_zh) for ch in manifest.chapters] == [
        (1, "https://x/1", "第一章", "第一章")
    ]


def test_insert_chapter_appends_at_n_plus_one(tmp_path):
    storage = _storage(tmp_path)
    storage.save_manifest(Manifest(slug="t", chapters=[Chapter(1, "https://x/1", "One")]))

    storage.insert_chapter(Chapter(2, "https://x/2", "Two", "Two"))

    assert [ch.index for ch in storage.load_manifest().chapters] == [1, 2]


def test_insert_chapter_shifts_complete_rows_without_data_loss(tmp_path):
    storage = _storage(tmp_path)
    first = Chapter(1, "https://x/1", "One", "一", "note", ["author"], None, "done", True)
    second = Chapter(2, "https://x/2", "Two", "二")
    storage.save_manifest(Manifest(slug="t", chapters=[first, second]))
    storage.write_raw(second, "RAW TWO")
    storage.write_translated(second, "TRANSLATED TWO")
    storage.write_translated_mt(second, "MT TWO")
    storage.write_meta(second, {"complete": True, "warnings": ["kept"]})
    before = dict(_chapter_row(storage, 2))

    storage.insert_chapter(Chapter(2, "https://x/new", "New", "New"))

    shifted = dict(_chapter_row(storage, 3))
    assert {k: v for k, v in shifted.items() if k != "idx"} == {
        k: v for k, v in before.items() if k != "idx"
    }
    assert storage.read_raw(storage.load_manifest().chapters[2]) == "RAW TWO"
    assert storage.read_translated(storage.load_manifest().chapters[2]) == "TRANSLATED TWO"
    assert storage.read_translated_mt(storage.load_manifest().chapters[2]) == "MT TWO"
    assert storage.read_meta(storage.load_manifest().chapters[2]) == {
        "complete": True,
        "warnings": ["kept"],
    }


@pytest.mark.parametrize("index", [0, 3])
def test_insert_chapter_rejects_out_of_range_without_changes(tmp_path, index):
    storage = _storage(tmp_path)
    storage.save_manifest(Manifest(slug="t", chapters=[Chapter(1, "https://x/1", "One")]))
    before = storage.load_manifest().to_json()

    with pytest.raises(ValueError, match="Vị trí"):
        storage.insert_chapter(Chapter(index, "https://x/new", "New"))

    assert storage.load_manifest().to_json() == before


def test_insert_chapter_rejects_duplicate_url_without_changes(tmp_path):
    storage = _storage(tmp_path)
    storage.save_manifest(Manifest(slug="t", chapters=[Chapter(1, "https://x/1", "One")]))
    before = storage.load_manifest().to_json()

    with pytest.raises(ValueError, match="URL"):
        storage.insert_chapter(Chapter(1, "https://x/1", "Duplicate"))

    assert storage.load_manifest().to_json() == before


# --- Route tests for POST /ebooks/{slug}/chapters/manual ---


def test_manual_chapter_success_trims_and_redirects(tmp_path, monkeypatch):
    """Successful request with whitespace stores trimmed title and URL,
    sets title_zh equal to title, shifts old chapter, returns 303 to /ebooks/t."""
    client = _client(tmp_path, monkeypatch)
    storage = Storage(tmp_path, "t")
    storage.save_manifest(Manifest(slug="t", chapters=[Chapter(1, "https://x/1", "Old")]))

    res = client.post(
        "/ebooks/t/chapters/manual",
        data={"index": 1, "title": "  New Title  ", "url": "  https://x/new  "},
    )

    assert res.status_code == 303
    assert res.headers["location"] == "/ebooks/t"
    manifest = storage.load_manifest()
    assert [(c.index, c.url, c.title, c.title_zh) for c in manifest.chapters] == [
        (1, "https://x/new", "New Title", "New Title"),
        (2, "https://x/1", "Old", ""),
    ]


def test_manual_chapter_empty_manifest_invalid_index(tmp_path, monkeypatch):
    """Empty-manifest invalid index 2 returns 400 containing Vị trí."""
    client = _client(tmp_path, monkeypatch)
    Storage(tmp_path, "t").save_manifest(Manifest(slug="t"))

    res = client.post(
        "/ebooks/t/chapters/manual",
        data={"index": 2, "title": "New", "url": "https://x/new"},
    )

    assert res.status_code == 400
    assert "Vị trí" in res.text


def test_manual_chapter_blank_title_returns_400(tmp_path, monkeypatch):
    """Blank title returns 400 containing Tiêu đề."""
    client = _client(tmp_path, monkeypatch)
    Storage(tmp_path, "t").save_manifest(Manifest(slug="t"))

    res = client.post(
        "/ebooks/t/chapters/manual",
        data={"index": 1, "title": "  ", "url": "https://x/new"},
    )

    assert res.status_code == 400
    assert "Tiêu đề" in res.text


def test_manual_chapter_blank_url_returns_400(tmp_path, monkeypatch):
    """Blank URL returns 400 containing URL."""
    client = _client(tmp_path, monkeypatch)
    Storage(tmp_path, "t").save_manifest(Manifest(slug="t"))

    res = client.post(
        "/ebooks/t/chapters/manual",
        data={"index": 1, "title": "New", "url": "  "},
    )

    assert res.status_code == 400
    assert "URL" in res.text


def test_manual_chapter_duplicate_url_returns_400_without_mutation(tmp_path, monkeypatch):
    """Duplicate URL returns 400 containing URL and leaves the original row unchanged."""
    client = _client(tmp_path, monkeypatch)
    storage = Storage(tmp_path, "t")
    storage.save_manifest(Manifest(slug="t", chapters=[Chapter(1, "https://x/1", "Original")]))
    before = storage.load_manifest().to_json()

    res = client.post(
        "/ebooks/t/chapters/manual",
        data={"index": 2, "title": "Dup", "url": "https://x/1"},
    )

    assert res.status_code == 400
    assert "URL" in res.text
    assert storage.load_manifest().to_json() == before


def test_manual_chapter_template_assertions(tmp_path, monkeypatch):
    """Template contains IDs add-manual-chapter-btn and manual-chapter-modal,
    form action, and named fields index, title, url."""
    client = _client(tmp_path, monkeypatch)
    Storage(tmp_path, "t").save_manifest(Manifest(slug="t"))

    res = client.get("/ebooks/t")

    assert res.status_code == 200
    html = res.text
    assert 'id="add-manual-chapter-btn"' in html
    assert 'id="manual-chapter-modal"' in html
    assert 'action="/ebooks/t/chapters/manual"' in html
    assert 'name="index"' in html
    assert 'name="title"' in html
    assert 'name="url"' in html
