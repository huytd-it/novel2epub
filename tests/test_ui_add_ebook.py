"""JSON API cho SPA thêm ebook đơn và hàng loạt."""
from __future__ import annotations

from fastapi import HTTPException
from fastapi.testclient import TestClient

from novel2epub.config import LibraryConfig


class _Queue:
    def __init__(self):
        self.restored = []

    def restore_ebook(self, slug):
        self.restored.append(slug)


class _Job:
    def __init__(self):
        self.queue = _Queue()
        self.enqueued = []

    def enqueue_step(self, step, cfg, *, label="", ebook=""):
        self.enqueued.append((step, ebook))
        return {"job_id": f"job-{ebook}", "category": "crawl"}

    def status(self):
        return {}


def _client(monkeypatch):
    from app import deps
    from app.main import app

    monkeypatch.setattr(deps, "library", lambda: LibraryConfig())
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: object())
    app.state.job = _Job()
    return app, TestClient(app)


def _meta(url, source=""):
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    return {
        "name": slug.title(), "author": "Tác giả", "description": "Mô tả",
        "slug": slug, "cover_url": "https://img/cover.jpg", "chapter_count": 12,
        "source": source,
    }


def test_preview_auto_and_explicit_source(monkeypatch):
    from app.routes import library, webui

    app, client = _client(monkeypatch)
    calls = []
    monkeypatch.setattr(library, "_fetch_meta", lambda url, mode="", source="": _meta(url, source or "auto"))
    monkeypatch.setattr(
        library, "_build_meta_crawl_cfg",
        lambda url, mode="", source="": (type("Cfg", (), {"scrapling": type("S", (), {"mode": mode or "stealthy"})()})(), source or "auto"),
    )
    monkeypatch.setattr(library, "_crawl_preview", lambda cfg: {"scrapling_mode": cfg.scrapling.mode})

    auto = client.post("/api/ui/library/ebooks/preview", json={"toc_url": "https://x/book"})
    explicit = client.post("/api/ui/library/ebooks/preview", json={
        "toc_url": "https://other.example/book", "source": "forced", "scrapling_mode": "dynamic",
    })
    assert auto.status_code == 200 and auto.json()["source"] == "auto"
    assert explicit.status_code == 200
    assert explicit.json()["source"] == "forced"
    assert explicit.json()["crawl_preview"]["scrapling_mode"] == "dynamic"


def test_preview_unknown_source_is_400(monkeypatch):
    from app.routes import library

    app, client = _client(monkeypatch)
    monkeypatch.setattr(
        library, "_fetch_meta",
        lambda *args: (_ for _ in ()).throw(HTTPException(400, "Nguồn 'missing' không tồn tại.")),
    )
    response = client.post("/api/ui/library/ebooks/preview", json={
        "toc_url": "https://x/book", "source": "missing",
    })
    assert response.status_code == 400
    assert "không tồn tại" in response.json()["detail"]


def test_create_quick_fetches_metadata_and_saves_extras(monkeypatch):
    from app.routes import library

    app, client = _client(monkeypatch)
    captured = {}
    monkeypatch.setattr(library, "_fetch_meta", lambda url, mode="", source="": _meta(url, source))
    monkeypatch.setattr(
        library, "_write_new_ebook",
        lambda url, slug, name, author, **kwargs: {"slug": slug, "name": name, "source": kwargs["source_name"]},
    )
    monkeypatch.setattr(
        library, "_save_ebook_metadata",
        lambda slug, description="", cover_url="": captured.update(slug=slug, description=description, cover_url=cover_url),
    )

    response = client.post("/api/ui/library/ebooks", json={"toc_url": "https://x/quick", "source": "forced"})
    assert response.status_code == 200
    assert response.json()["slug"] == "quick"
    assert response.json()["source"] == "forced"
    assert captured == {"slug": "quick", "description": "Mô tả", "cover_url": "https://img/cover.jpg"}
    assert app.state.job.queue.restored == ["quick"]
    assert app.state.job.enqueued == []


def test_create_preview_payload_and_fetch_toc(monkeypatch):
    from app.routes import library

    app, client = _client(monkeypatch)
    captured = {}
    monkeypatch.setattr(
        library, "_write_new_ebook",
        lambda url, slug, name, author, **kwargs: captured.update(slug=slug, name=name, author=author) or {"slug": slug, "name": name, "source": ""},
    )
    monkeypatch.setattr(library, "_save_ebook_metadata", lambda *args: None)

    response = client.post("/api/ui/library/ebooks", json={
        "toc_url": "https://x/book", "slug": "edited", "name": "Tên sửa",
        "author": "TG sửa", "description": "MT sửa", "fetch_toc": True,
    })
    assert response.status_code == 200
    assert captured == {"slug": "edited", "name": "Tên sửa", "author": "TG sửa"}
    assert app.state.job.queue.restored == ["edited"]
    assert app.state.job.enqueued == [("fetch-toc", "edited")]
    assert response.json()["toc_job"]["job_id"] == "job-edited"


def test_create_duplicate_returns_409(monkeypatch):
    from app.routes import library

    app, client = _client(monkeypatch)
    monkeypatch.setattr(
        library, "_write_new_ebook",
        lambda *args, **kwargs: (_ for _ in ()).throw(HTTPException(409, "đã tồn tại")),
    )
    response = client.post("/api/ui/library/ebooks", json={
        "toc_url": "https://x/book", "name": "Book",
    })
    assert response.status_code == 409


def test_bulk_partial_failure_duplicate_auto_source_and_toc(monkeypatch):
    from app.routes import library

    app, client = _client(monkeypatch)
    fetched_calls = []

    def fetch(url):
        fetched_calls.append(url)
        if "bad" in url:
            raise RuntimeError("Lỗi mạng")
        return _meta(url, "detected")

    def write(url, slug, name, author):
        if "duplicate" in url:
            raise HTTPException(409, "đã tồn tại")
        return {"slug": slug, "name": name, "source": "detected"}

    monkeypatch.setattr(library, "_fetch_meta", fetch)
    monkeypatch.setattr(library, "_write_new_ebook", write)
    monkeypatch.setattr(library, "_save_ebook_metadata", lambda *args: None)
    response = client.post("/api/ui/library/ebooks/bulk", json={
        "toc_urls": ["https://x/good", "https://x/duplicate", "https://x/bad"],
        "fetch_toc": True,
    })
    assert response.status_code == 200
    assert [item["status"] for item in response.json()["results"]] == [
        "created", "skipped-duplicate", "failed",
    ]
    assert fetched_calls == ["https://x/good", "https://x/duplicate", "https://x/bad"]
    assert app.state.job.queue.restored == ["good"]
    assert app.state.job.enqueued == [("fetch-toc", "good")]


def test_bulk_accepts_twenty_and_rejects_twenty_one(monkeypatch):
    from app.routes import library

    app, client = _client(monkeypatch)
    monkeypatch.setattr(library, "_fetch_meta", lambda url: _meta(url))
    monkeypatch.setattr(
        library, "_write_new_ebook",
        lambda url, slug, name, author: {"slug": slug, "name": name, "source": ""},
    )
    monkeypatch.setattr(library, "_save_ebook_metadata", lambda *args: None)
    twenty = [f"https://x/book-{i}" for i in range(20)]
    assert client.post("/api/ui/library/ebooks/bulk", json={"toc_urls": twenty}).status_code == 200
    response = client.post("/api/ui/library/ebooks/bulk", json={"toc_urls": twenty + ["https://x/extra"]})
    assert response.status_code == 400
    assert "20" in response.json()["detail"]
