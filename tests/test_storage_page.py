"""Trang /storage giờ là route SPA — server trả bundle, dữ liệu qua API.

Giao diện Jinja2 đã gỡ; `/storage` fallback về index.html của SPA (React
router tự xử lý). Dữ liệu lưu trữ client đọc qua API JSON.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import deps
from novel2epub.config import (
    Config,
    CrawlConfig,
    NovelConfig,
    OutputConfig,
    TranslateConfig,
)
from novel2epub.storage import Chapter, Manifest, Storage


def _cfg(tmp_path, epub_path=""):
    return Config(
        novel=NovelConfig(slug="t", title="Truyện T"),
        crawl=CrawlConfig(toc_url="http://x/book/", delay_seconds=0),
        translate=TranslateConfig(type="cli", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path), epub_path=str(epub_path)),
    )


def _seed(tmp_path):
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    ch1, ch2 = Chapter(index=1, url="http://x/1"), Chapter(index=2, url="http://x/2")
    storage.write_raw(ch1, "第一章 开始" * 10)
    storage.write_raw(ch2, "第二章 剧情" * 10)
    storage.write_translated(ch2, "Xin chào thế giới")
    storage.save_manifest(Manifest(slug="t", chapters=[ch1, ch2]))
    return storage


def _client(monkeypatch, cfg):
    entry = type("E", (), {"title": "Truyện T", "slug": "t"})()
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {"t": entry}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda s: cfg)
    from app.main import app
    return TestClient(app)


def test_storage_page_renders(tmp_path, monkeypatch):
    """Route /storage trả SPA bundle (index.html), không phải Jinja2."""
    _seed(tmp_path)
    client = _client(monkeypatch, _cfg(tmp_path))

    res = client.get("/storage")

    assert res.status_code == 200
    assert '<div id="root"></div>' in res.text
    assert res.headers.get("content-type", "").startswith("text/html")


def test_storage_page_shows_counts(tmp_path, monkeypatch):
    """Số liệu lưu trữ do SPA đọc qua API storage report."""
    from app.storage_report import ebook_storage_report

    _seed(tmp_path)
    _client(monkeypatch, _cfg(tmp_path))

    report = ebook_storage_report(Storage(tmp_path, "t"), _cfg(tmp_path).epub_path)
    assert report["raw"] > 0  # raw chương tồn tại
    assert report["translated"] > 0  # bản dịch chương 2


def test_storage_page_marks_epub_missing(tmp_path, monkeypatch):
    _seed(tmp_path)
    _client(monkeypatch, _cfg(tmp_path, epub_path=tmp_path / "missing.epub"))

    from app.storage_report import ebook_storage_report

    report = ebook_storage_report(Storage(tmp_path, "t"), tmp_path / "missing.epub")
    assert report["epub_exists"] is False


def test_storage_page_shows_epub_size_when_built(tmp_path, monkeypatch):
    _seed(tmp_path)
    epub = tmp_path / "out.epub"
    epub.write_bytes(b"x" * (2 * 1024 * 1024))
    _client(monkeypatch, _cfg(tmp_path, epub_path=epub))

    from app.storage_report import ebook_storage_report

    report = ebook_storage_report(Storage(tmp_path, "t"), epub)
    assert report["epub_exists"] is True
    assert report["epub"] >= 2 * 1024 * 1024
