"""Tests cho luồng thêm ebook mới: paste link → preview → tạo ebook."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from novel2epub.config import LibraryConfig


def _fake_job():
    class Job:
        def status(self):
            return {
                "crawl": {"running": False, "step": "", "error": "", "log": []},
                "translate": {"running": False, "step": "", "error": "", "log": []},
            }

    return Job()


# ---------------- preview endpoint ----------------


def _client(monkeypatch):
    from app import deps
    from app.main import app

    monkeypatch.setattr(deps, "library", lambda: LibraryConfig())
    app.state.job = _fake_job()
    return app, TestClient(app)


def test_preview_returns_metadata(monkeypatch):
    from app.routes import library

    app, client = _client(monkeypatch)
    monkeypatch.setattr(library, "_fetch_meta", lambda url, preset_name="": {
        "name": "Tên Truyện", "author": "Tác Giả", "slug": "ten-truyen",
        "cover_url": "https://x/cover.jpg", "chapter_count": 798,
    })

    res = client.post("/library/ebooks/preview", data={
        "toc_url": "https://www.shuhaige.net/372421/"})
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "Tên Truyện"
    assert data["chapter_count"] == 798
    assert data["cover_url"].endswith("cover.jpg")


def test_preview_missing_url(monkeypatch):
    app, client = _client(monkeypatch)
    res = client.post("/library/ebooks/preview", data={"toc_url": ""})
    assert res.status_code == 400


def test_preview_fetch_error_returns_400(monkeypatch):
    from app.routes import library

    app, client = _client(monkeypatch)
    monkeypatch.setattr(library, "_fetch_meta", lambda url, preset_name="": (_ for _ in ()).throw(Exception("Lỗi mạng")))
    res = client.post("/library/ebooks/preview", data={
        "toc_url": "https://example.com/toc"})
    assert res.status_code == 400
    assert "Lỗi mạng" in res.json()["error"]


# ---------------- create endpoint ----------------


def test_create_ebook_uses_scrapling_engine(monkeypatch, tmp_path):
    from app.routes import library

    app, client = _client(monkeypatch)

    captured = {}

    def fake_add_ebook(path, slug, *, name="", title="", author="", toc_url="",
                       engine="scrapling"):
        captured.update(path=str(path), slug=slug, name=name, title=title,
                        engine=engine)

    monkeypatch.setattr(library, "add_ebook", fake_add_ebook)

    res = client.post("/library/ebooks", data={
        "toc_url": "https://www.shuhaige.net/372421/",
        "name": "Tên Truyện", "author": "Tác Giả", "slug": "ten-truyen",
    }, follow_redirects=False)

    assert res.status_code == 303
    assert res.headers["location"] == "/ebooks/ten-truyen/settings"
    assert captured["slug"] == "ten-truyen"
    assert captured["engine"] == "scrapling"


def test_create_ebook_missing_url_rejected(monkeypatch):
    app, client = _client(monkeypatch)
    res = client.post("/library/ebooks", data={
        "toc_url": "",
        "name": "X",
    }, follow_redirects=False)
    assert res.status_code == 400


def test_create_ebook_duplicate_slug_rejected(monkeypatch):
    from app import deps

    app, client = _client(monkeypatch)
    monkeypatch.setattr(deps, "library", lambda: LibraryConfig(ebooks={
        "ten-truyen": type("E", (), {"slug": "ten-truyen"})(),
    }))
    res = client.post("/library/ebooks", data={
        "toc_url": "https://example.com/toc",
        "slug": "ten-truyen",
    }, follow_redirects=False)
    assert res.status_code == 409
