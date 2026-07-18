"""Test API sửa đoạn tại chỗ trên trang đọc (app/routes/chapters.py)."""
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
        translate=TranslateConfig(type="none", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


def _seed(tmp_path, *, translated="A.\n\nB.\n\nC.", raw=None, mt=None):
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=7, url="http://x/7")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    if translated is not None:
        storage.write_translated(ch, translated)
    if raw is not None:
        storage.write_raw(ch, raw)
    if mt is not None:
        storage.write_translated_mt(ch, mt)
    return storage, ch


def _client(tmp_path, monkeypatch, cfg):
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    from app.main import app
    return TestClient(app)


def test_para_save_happy_path_keeps_mt_snapshot(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage, ch = _seed(tmp_path, mt="A.\n\nB.\n\nC.")
    client = _client(tmp_path, monkeypatch, cfg)

    res = client.post(
        "/api/ebooks/t/chapters/7/para/save",
        data={"para_index": 1, "para_text": "B.", "new_text": "B đã sửa."},
    )
    assert res.status_code == 200, res.text
    assert res.json()["saved"] is True
    assert storage.read_translated(ch) == "A.\n\nB đã sửa.\n\nC."
    # Snapshot MT KHÔNG đổi
    assert storage.read_translated_mt(ch) == "A.\n\nB.\n\nC."


def test_para_save_stale_conflict(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _storage, _ch = _seed(tmp_path)
    client = _client(tmp_path, monkeypatch, cfg)

    res = client.post(
        "/api/ebooks/t/chapters/7/para/save",
        data={"para_index": 1, "para_text": "Đoạn cũ khác.", "new_text": "x"},
    )
    assert res.status_code == 409
    assert "thay đổi" in res.json()["detail"]


def test_para_save_empty_rejected(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _storage, _ch = _seed(tmp_path)
    client = _client(tmp_path, monkeypatch, cfg)

    res = client.post(
        "/api/ebooks/t/chapters/7/para/save",
        data={"para_index": 1, "para_text": "B.", "new_text": "   "},
    )
    assert res.status_code == 409
    assert "trống" in res.json()["detail"]


def test_para_save_unknown_chapter_404(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path)
    client = _client(tmp_path, monkeypatch, cfg)

    res = client.post(
        "/api/ebooks/t/chapters/999/para/save",
        data={"para_index": 0, "para_text": "A.", "new_text": "x"},
    )
    assert res.status_code == 404
