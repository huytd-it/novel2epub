"""Tests cho luồng thêm ebook mới: chọn nguồn → paste link khớp domain →
preview → tạo ebook. (refactor add-new-ebook)"""
from __future__ import annotations

from fastapi.testclient import TestClient

from novel2epub.config import LibraryConfig
from novel2epub.sources import SourcePreset, preset_matches_url


def _fake_job():
    class Job:
        def status(self):
            return {
                "crawl": {"running": False, "step": "", "error": "", "log": []},
                "translate": {"running": False, "step": "", "error": "", "log": []},
            }

    return Job()


def _shuhaige():
    return SourcePreset(
        name="shuhaige",
        engine="http",
        url="https://www.shuhaige.net/",
        domains="shuhaige.net",
        content_selector="#content",
    )


# ---------------- unit: preset_matches_url ----------------

def test_preset_matches_url():
    p = SourcePreset(name="x", domains="shuhaige.net,69shu.com")
    assert preset_matches_url(p, "https://www.shuhaige.net/372421/")
    assert preset_matches_url(p, "http://69shu.com/book/1")
    assert not preset_matches_url(p, "https://www.qidian.com/book/1")
    # domains rỗng / url rỗng
    assert not preset_matches_url(SourcePreset(name="y"), "https://www.shuhaige.net/")
    assert not preset_matches_url(p, "")


# ---------------- preview endpoint ----------------

def _client(monkeypatch, presets):
    from app import deps
    from app.main import app

    monkeypatch.setattr(deps, "presets", lambda: presets)
    monkeypatch.setattr(deps, "library", lambda: LibraryConfig())
    app.state.job = _fake_job()
    return app, TestClient(app)


def test_preview_match_returns_metadata(monkeypatch):
    from app.routes import library

    app, client = _client(monkeypatch, {"shuhaige": _shuhaige()})
    monkeypatch.setattr(library, "_fetch_meta", lambda url, preset="": {
        "name": "Tên Truyện", "author": "Tác Giả", "slug": "ten-truyen",
        "cover_url": "https://x/cover.jpg", "chapter_count": 798,
        "preset": "shuhaige", "suggested_preset": None, "suggest_url": "",
    })

    res = client.post("/library/ebooks/preview", data={
        "toc_url": "https://www.shuhaige.net/372421/", "preset": "shuhaige"})
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "Tên Truyện"
    assert data["chapter_count"] == 798
    assert data["cover_url"].endswith("cover.jpg")
    assert data["engine"] == "http"


def test_preview_domain_mismatch_blocks_with_suggest(monkeypatch):
    app, client = _client(monkeypatch, {"shuhaige": _shuhaige()})
    res = client.post("/library/ebooks/preview", data={
        "toc_url": "https://www.69shuba.com/txt/1/2", "preset": "shuhaige"})
    assert res.status_code == 400
    data = res.json()
    assert "không thuộc nguồn" in data["error"]
    assert data["suggest_url"].startswith("/preset-builder?toc_url=")


def test_preview_missing_preset(monkeypatch):
    app, client = _client(monkeypatch, {"shuhaige": _shuhaige()})
    res = client.post("/library/ebooks/preview", data={
        "toc_url": "https://www.shuhaige.net/372421/", "preset": ""})
    assert res.status_code == 400
    assert "chọn nguồn" in res.json()["error"].lower()


# ---------------- create endpoint ----------------

def test_create_ebook_uses_preset_engine(monkeypatch):
    from app.routes import library

    app, client = _client(monkeypatch, {"shuhaige": _shuhaige()})

    captured = {}

    def fake_add_ebook(path, slug, *, name="", title="", author="", toc_url="",
                       engine="http", preset=None):
        captured.update(path=str(path), slug=slug, name=name, title=title,
                        engine=engine, preset=preset)

    monkeypatch.setattr(library, "add_ebook", fake_add_ebook)

    res = client.post("/library/ebooks", data={
        "preset": "shuhaige",
        "toc_url": "https://www.shuhaige.net/372421/",
        "name": "Tên Truyện", "author": "Tác Giả", "slug": "ten-truyen",
    }, follow_redirects=False)

    assert res.status_code == 303
    assert res.headers["location"] == "/ebooks/ten-truyen/settings"
    assert captured["slug"] == "ten-truyen"
    assert captured["engine"] == "http"
    assert captured["preset"]["content_selector"] == "#content"


def test_create_ebook_domain_mismatch_rejected(monkeypatch):
    app, client = _client(monkeypatch, {"shuhaige": _shuhaige()})
    res = client.post("/library/ebooks", data={
        "preset": "shuhaige",
        "toc_url": "https://www.qidian.com/book/1",
        "name": "X",
    }, follow_redirects=False)
    assert res.status_code == 400
