"""Tests cho luồng thêm ebook mới: paste link → preview → tạo ebook."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from novel2epub.config import LibraryConfig


def _fake_job():
    class Queue:
        def __init__(self):
            self.restored = []

        def restore_ebook(self, slug):
            self.restored.append(slug)

    class Job:
        def __init__(self):
            self.queue = Queue()

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
    monkeypatch.setattr(library, "_fetch_meta", lambda url, scrapling_mode="": {
        "title": "Tên Truyện", "author": "Tác Giả", "slug": "ten-truyen",
        "cover_url": "https://x/cover.jpg", "chapter_count": 798,
    })

    res = client.post("/library/ebooks/preview", data={
        "toc_url": "https://www.shuhaige.net/372421/"})
    assert res.status_code == 200
    data = res.json()
    assert data["title"] == "Tên Truyện"
    assert data["chapter_count"] == 798
    assert data["cover_url"].endswith("cover.jpg")


def test_preview_missing_url(monkeypatch):
    app, client = _client(monkeypatch)
    res = client.post("/library/ebooks/preview", data={"toc_url": ""})
    assert res.status_code == 400


def test_preview_fetch_error_returns_400(monkeypatch):
    from app.routes import library

    app, client = _client(monkeypatch)
    monkeypatch.setattr(library, "_fetch_meta", lambda url, scrapling_mode="": (_ for _ in ()).throw(Exception("Lỗi mạng")))
    res = client.post("/library/ebooks/preview", data={
        "toc_url": "https://example.com/toc"})
    assert res.status_code == 400
    assert "Lỗi mạng" in res.json()["error"]


def test_translate_metadata_endpoint(monkeypatch):
    from app.routes import library

    app, client = _client(monkeypatch)
    monkeypatch.setattr(library, "translate_ebook_metadata", lambda cfg, **kwargs: {
        "title": "Tên Việt", "description": "Mô tả Việt", "engine": kwargs["engine"],
    })

    res = client.post("/library/ebooks/translate-metadata", data={
        "title": "中文书名", "description": "中文简介", "engine": "localmt",
    })

    assert res.status_code == 200
    assert res.json() == {
        "title": "Tên Việt", "description": "Mô tả Việt", "engine": "localmt",
    }


def test_translate_metadata_endpoint_reports_model_error(monkeypatch):
    from app.routes import library

    app, client = _client(monkeypatch)
    monkeypatch.setattr(
        library, "translate_ebook_metadata",
        lambda cfg, **kwargs: (_ for _ in ()).throw(RuntimeError("model missing")),
    )

    res = client.post("/library/ebooks/translate-metadata", data={
        "title": "中文书名", "engine": "localmt",
    })

    assert res.status_code == 503
    assert "Local MT" in res.json()["detail"]


# ---------------- create endpoint ----------------


def test_create_ebook_calls_add_ebook(monkeypatch, tmp_path):
    from app.routes import library

    app, client = _client(monkeypatch)

    captured = {}

    def fake_add_ebook(path, slug, *, title="", author="", toc_url="", source_name=""):
        captured.update(path=str(path), slug=slug, title=title)

    monkeypatch.setattr(library, "add_ebook", fake_add_ebook)
    monkeypatch.setattr(library, "load_presets", lambda path: {})

    res = client.post("/library/ebooks", data={
        "toc_url": "https://www.shuhaige.net/372421/",
        "title": "Tên Truyện", "author": "Tác Giả", "slug": "ten-truyen",
    }, follow_redirects=False)

    assert res.status_code == 303
    assert res.headers["location"] == "/ebooks/ten-truyen/settings"
    assert captured["slug"] == "ten-truyen"
    assert app.state.job.queue.restored == ["ten-truyen"]


def test_new_ebook_page_renders(monkeypatch, tmp_path):
    """Trang riêng Thêm ebook: hiện config global Dịch/AI để duyệt trước khi lưu."""
    from tests.conftest import write_db_config

    db = write_db_config(
        tmp_path / "novel2epub.db",
        defaults={"translate": {"type": "openai",
                                "openai": {"model": "model-xem-truoc"}}},
    )
    from app import deps
    from app.main import app

    monkeypatch.setattr(deps, "DB_PATH", db)
    monkeypatch.setattr(deps, "WORKSPACE_PATH", str(db))
    monkeypatch.setattr(deps, "SOURCES_PATH", str(db))
    app.state.job = _fake_job()
    client = TestClient(app)

    res = client.get("/library/ebooks/new")
    assert res.status_code == 200
    assert "Thêm ebook mới" in res.text
    assert "model-xem-truoc" in res.text  # config global hiển thị trong preview
    assert "Hệ thống dịch và AI dùng chung" in res.text
    assert "Dịch nhanh bằng Local MT" in res.text
    assert 'aria-live="polite"' in res.text
    assert "metadataTranslationPending" in res.text
    assert "Local MT chưa sẵn sàng" in res.text


def test_preview_returns_crawl_preview(monkeypatch, tmp_path):
    """Preview trả kèm config crawl hiệu lực (preset khớp URL) — cho trang Thêm ebook."""
    from tests.conftest import write_db_config
    from app import deps
    from app.routes import library

    db = write_db_config(
        tmp_path / "novel2epub.db",
        sources={"aixdzs": {"content_selector": ".preset", "delay_seconds": 2.0,
                            "scrapling_mode": "stealthy", "domains": "aixdzs.com"}},
    )
    monkeypatch.setattr(deps, "SOURCES_PATH", str(db))
    app, client = _client(monkeypatch)
    monkeypatch.setattr(library, "_fetch_meta", lambda url, scrapling_mode="": {
        "title": "Tên", "author": "TG", "slug": "ten", "chapter_count": 3,
    })

    res = client.post("/library/ebooks/preview", data={
        "toc_url": "https://aixdzs.com/d/1"})
    assert res.status_code == 200
    data = res.json()
    assert data["source"] == "aixdzs"
    cp = data["crawl_preview"]
    assert cp["content_selector"] == ".preset"
    assert cp["delay_seconds"] == 2.0
    assert cp["scrapling_mode"] == "stealthy"


def test_create_ebook_saves_description_and_cover(monkeypatch):
    """Trang Thêm ebook gửi kèm description/cover_url đã duyệt — lưu vào novel."""
    from app.routes import library

    app, client = _client(monkeypatch)
    captured = {}

    monkeypatch.setattr(library, "add_ebook", lambda *a, **k: None)
    monkeypatch.setattr(library, "load_presets", lambda path: {})
    monkeypatch.setattr(
        library, "update_ebook",
        lambda path, slug, updates, **k: captured.update(slug=slug, updates=updates),
    )

    res = client.post("/library/ebooks", data={
        "toc_url": "https://example.com/toc",
        "title": "Tên", "slug": "ten-truyen",
        "description": "Mô tả truyện", "cover_url": "https://x/cover.jpg",
    }, follow_redirects=False)

    assert res.status_code == 303
    assert captured["slug"] == "ten-truyen"
    assert captured["updates"]["novel"]["description"] == "Mô tả truyện"
    assert captured["updates"]["novel"]["cover_url"] == "https://x/cover.jpg"


def test_create_ebook_missing_url_rejected(monkeypatch):
    app, client = _client(monkeypatch)
    res = client.post("/library/ebooks", data={
        "toc_url": "",
        "title": "X",
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
