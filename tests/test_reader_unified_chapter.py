from __future__ import annotations

from fastapi.testclient import TestClient

from app import deps
from app.routes.reader import _pad_paras, _reader_paras
from novel2epub.config import Config, CrawlConfig, NovelConfig, OutputConfig, TranslateConfig
from novel2epub.storage import Chapter, Manifest, Storage


def test_reader_paras_splits_blank_lines_and_joins_wrapped_lines():
    assert _reader_paras("甲。\n续行。\n\n乙。\n   \n丙。") == ["甲。 续行。", "乙。", "丙。"]
    assert _reader_paras("") == []


def test_pad_paras_extends_shorter_side():
    left, right = _pad_paras(["raw 1", "raw 2"], ["vi 1"])
    assert left == ["raw 1", "raw 2"]
    assert right == ["vi 1", ""]


def _cfg(tmp_path):
    return Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/book/", delay_seconds=0),
        translate=TranslateConfig(type="none", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


def _client(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    from app.main import app

    return TestClient(app)


def _seed(tmp_path, *, raw=None, translated=None):
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=7, url="http://x/7", title="Bảy")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    if raw is not None:
        storage.write_raw(ch, raw)
    if translated is not None:
        storage.write_translated(ch, translated)
    return storage, ch


def test_reader_missing_raw_shows_large_crawl_cta(tmp_path, monkeypatch):
    _seed(tmp_path)
    client = _client(tmp_path, monkeypatch)

    res = client.get("/ebooks/t/read/7")

    assert res.status_code == 200
    assert 'class="reader-empty-action-card"' in res.text
    assert 'name="action" value="crawl"' in res.text
    assert ">Crawl<" in res.text


def test_reader_raw_without_translation_shows_large_translate_cta(tmp_path, monkeypatch):
    _seed(tmp_path, raw="原文")
    client = _client(tmp_path, monkeypatch)

    res = client.get("/ebooks/t/read/7")

    assert res.status_code == 200
    assert 'class="reader-empty-action-card"' in res.text
    assert 'name="action" value="translate"' in res.text
    assert ">Dịch<" in res.text


def test_reader_with_translation_contains_edit_mode_toolbar(tmp_path, monkeypatch):
    _seed(tmp_path, raw="原文", translated="Bản dịch")
    client = _client(tmp_path, monkeypatch)

    res = client.get("/ebooks/t/read/7")

    assert res.status_code == 200
    assert 'id="edit-mode-toggle-btn"' in res.text
    assert 'id="reader-edit-toolbar"' in res.text
    assert 'name="action" value="cleanup-han"' in res.text
    assert 'action="/ebooks/t/chapters/7/delete-raw"' in res.text
    assert 'action="/ebooks/t/chapters/7/delete-translation"' in res.text
    assert 'href="/ebooks/t/glossary"' in res.text


def test_reader_hides_legacy_edit_controls_until_edit_mode_is_enabled(tmp_path, monkeypatch):
    _seed(tmp_path, raw="原文", translated="Bản dịch")
    client = _client(tmp_path, monkeypatch)

    default = client.get("/ebooks/t/read/7")
    edit_mode = client.get("/ebooks/t/read/7?edit=1")

    assert 'class="reader-toolbar-btn edit-mode-control" title="Sửa bản dịch" aria-label="Edit chapter" hidden' in default.text
    assert 'class="para-edit-btn edit-mode-control" title="Sửa đoạn" data-para="0" hidden' in default.text
    assert "document.querySelectorAll('.edit-mode-control').forEach(control => {" in default.text
    assert "control.hidden = !on;" in default.text
    assert "setEditMode(initialEditMode);" in edit_mode.text


def test_reader_with_raw_and_translation_contains_raw_compare_view(tmp_path, monkeypatch):
    _seed(tmp_path, raw="甲。\n\n乙。", translated="Một.\n\nHai.")
    client = _client(tmp_path, monkeypatch)

    res = client.get("/ebooks/t/read/7")

    assert res.status_code == 200
    assert 'id="raw-compare-toggle-btn"' in res.text
    assert 'id="raw-compare-view"' in res.text
    assert "ZH raw" in res.text
    assert "VI biên tập" in res.text
    assert "甲。" in res.text
    assert "Một." in res.text
