"""Test endpoint GET /api/ebooks/{slug}/chapters/{index}/translated (spec translate-chunk-streaming)."""
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


def _cfg(tmp_path):
    return Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/book/", delay_seconds=0),
        translate=TranslateConfig(type="cli", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


def _seed(tmp_path, *, with_file: str | None = None, with_meta: dict | None = None):
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=7, url="http://x/7")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    if with_file is not None:
        storage.write_translated(ch, with_file)
    if with_meta is not None:
        storage.write_meta(ch, with_meta)
    return storage, ch


def test_endpoint_returns_empty_when_no_file(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path)
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    from app.main import app
    client = TestClient(app)

    res = client.get("/api/ebooks/t/chapters/7/translated")
    assert res.status_code == 200
    data = res.json()
    assert data["text"] == ""
    assert data["complete"] is False
    assert data["mtime"] == 0
    assert data["char_count"] == 0


def test_endpoint_returns_partial_state(tmp_path, monkeypatch):
    """File có nhưng meta thiếu complete → complete=False, mtime > 0."""
    cfg = _cfg(tmp_path)
    _seed(tmp_path, with_file="PHẦN 1\nPHẦN 2", with_meta={"complete": False, "warnings": []})
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    from app.main import app
    client = TestClient(app)

    res = client.get("/api/ebooks/t/chapters/7/translated")
    assert res.status_code == 200
    data = res.json()
    assert data["text"] == "PHẦN 1\nPHẦN 2"
    assert data["complete"] is False
    assert data["mtime"] > 0
    assert data["char_count"] == len("PHẦN 1\nPHẦN 2")


def test_endpoint_returns_complete_state(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path, with_file="đầy đủ", with_meta={"complete": True, "warnings": []})
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    from app.main import app
    client = TestClient(app)

    res = client.get("/api/ebooks/t/chapters/7/translated")
    assert res.status_code == 200
    data = res.json()
    assert data["text"] == "đầy đủ"
    assert data["complete"] is True
    assert data["mtime"] > 0


def test_endpoint_returns_404_for_unknown_chapter(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path)
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    from app.main import app
    client = TestClient(app)

    res = client.get("/api/ebooks/t/chapters/999/translated")
    assert res.status_code == 404


def test_endpoint_legacy_meta_treated_as_incomplete(tmp_path, monkeypatch):
    """File có, meta không có key 'complete' → complete=False (vì meta hiện ra chỉ khi pipeline chạm).

    Lưu ý: `has_translated` coi meta-missing là complete (back-compat), nhưng endpoint
    JSON nói thật về flag complete: nếu meta không có key, complete=False — UI sẽ
    thấy nút "đang dịch dở" cho tới khi pipeline ghi lại meta mới có key này.
    """
    cfg = _cfg(tmp_path)
    _seed(tmp_path, with_file="abc", with_meta={"warnings": [], "generated_at": "2024-01-01T00:00:00"})
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    from app.main import app
    client = TestClient(app)

    res = client.get("/api/ebooks/t/chapters/7/translated")
    assert res.status_code == 200
    data = res.json()
    assert data["complete"] is False  # meta không có key
    assert data["text"] == "abc"
