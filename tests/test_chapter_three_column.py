"""Test editor chương 3 cột (ZH · VI bản dịch máy · Biên tập).

Xem spec `chapter-three-column-editor`.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import deps
from app.routes.chapters import _chapter_context
from novel2epub.config import Config, CrawlConfig, NovelConfig, OutputConfig, TranslateConfig
from novel2epub.storage import Chapter, Manifest, Storage


def _cfg(tmp_path):
    return Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/book/", delay_seconds=0),
        translate=TranslateConfig(type="cli", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


# --- context: cột VI dùng snapshot máy, fallback an toàn ---


def test_context_vi_column_uses_mt_snapshot(tmp_path):
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=1, url="x")
    storage.write_translated_mt(ch, "BẢN MÁY")
    storage.write_translated(ch, "BẢN ĐÃ SỬA")
    ctx = _chapter_context(storage, ch, raw="原文", translated="BẢN ĐÃ SỬA", slug="t")
    assert ctx["translated_mt"] == "BẢN MÁY"   # cột VI = snapshot máy
    assert ctx["translated"] == "BẢN ĐÃ SỬA"   # cột Biên tập = bản đã sửa


def test_context_vi_column_falls_back_when_no_snapshot(tmp_path):
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=1, url="x")
    storage.write_translated(ch, "chỉ có bản dịch")
    ctx = _chapter_context(storage, ch, raw="原文", translated="chỉ có bản dịch", slug="t")
    assert ctx["translated_mt"] == "chỉ có bản dịch"  # degrade an toàn


# --- route: trang chương render 3 cột; lưu cột Biên tập không đụng snapshot ---


def _patch_deps(monkeypatch, cfg):
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)


def test_chapter_page_renders_three_columns(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=7, url="http://x/7")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    storage.write_raw(ch, "原文 ZH")
    storage.write_translated_mt(ch, "VI MÁY")
    storage.write_translated(ch, "VI ĐÃ SỬA")
    _patch_deps(monkeypatch, cfg)
    from app.main import app
    client = TestClient(app)

    res = client.get("/ebooks/t/chapters/7")
    assert res.status_code == 200
    body = res.text
    assert "VI MÁY" in body          # cột VI (snapshot máy)
    assert "VI ĐÃ SỬA" in body       # cột Biên tập
    assert "Crawl" in body                # nút crawl


def test_save_edit_column_keeps_mt_snapshot(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=7, url="http://x/7")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    storage.write_translated_mt(ch, "VI MÁY")
    storage.write_translated(ch, "VI MÁY")
    _patch_deps(monkeypatch, cfg)
    from app.main import app
    client = TestClient(app)

    res = client.post(
        "/ebooks/t/chapters/7",
        data={"translated": "VI ĐÃ BIÊN TẬP"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert storage.read_translated(ch) == "VI ĐÃ BIÊN TẬP"   # cột Biên tập cập nhật
    assert storage.read_translated_mt(ch) == "VI MÁY"        # snapshot máy giữ nguyên
