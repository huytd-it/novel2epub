"""Trang /storage render được và hiện đúng số liệu.

Trang này từng KHÔNG BAO GIỜ render nổi: template dùng ternary kiểu JS
(`a ? b : c`) — lỗi cú pháp Jinja nên chết ngay lúc compile — và tham chiếu
loạt trường (`epub_size`, `raw_files`, ...) mà `ebook_storage_report` chưa bao
giờ trả về. Không có test nào chạm tới route nên bug lọt qua. Test này giữ cửa.
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
    storage.write_raw(ch1, "你好世界" * 10)
    storage.write_raw(ch2, "再见世界" * 10)
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
    _seed(tmp_path)
    client = _client(monkeypatch, _cfg(tmp_path))

    res = client.get("/storage")

    assert res.status_code == 200, res.text[:400]
    assert "Truyện T" in res.text


def test_storage_page_shows_counts(tmp_path, monkeypatch):
    _seed(tmp_path)
    client = _client(monkeypatch, _cfg(tmp_path))

    text = client.get("/storage").text

    assert "2 chương" in text, "phải hiện 2 chương có raw"
    assert "1 chương" in text, "phải hiện 1 chương đã dịch"


def test_storage_page_marks_epub_missing(tmp_path, monkeypatch):
    _seed(tmp_path)
    client = _client(monkeypatch, _cfg(tmp_path, epub_path=tmp_path / "missing.epub"))

    text = client.get("/storage").text

    assert "Chưa có" in text


def test_storage_page_shows_epub_size_when_built(tmp_path, monkeypatch):
    _seed(tmp_path)
    epub = tmp_path / "out.epub"
    epub.write_bytes(b"x" * (2 * 1024 * 1024))
    client = _client(monkeypatch, _cfg(tmp_path, epub_path=epub))

    text = client.get("/storage").text

    assert "2.0 MB" in text
    assert "Chưa có" not in text
