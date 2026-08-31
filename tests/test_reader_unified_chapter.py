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


def _chapter_data(client, index=7):
    res = client.get(f"/api/ebooks/t/read/{index}/data")
    assert res.status_code == 200
    return res.json()


def test_reader_missing_raw_shows_large_crawl_cta(tmp_path, monkeypatch):
    _seed(tmp_path)
    client = _client(tmp_path, monkeypatch)

    data = _chapter_data(client)

    assert data["index"] == 7
    assert data["has_raw"] is False
    assert data["has_translated"] is False
    assert data["edit_paras"] == []  # CTA crawl lớn: chưa có nội dung nào


def test_reader_raw_without_translation_shows_large_translate_cta(tmp_path, monkeypatch):
    _seed(tmp_path, raw="原文")
    client = _client(tmp_path, monkeypatch)

    data = _chapter_data(client)

    assert data["has_raw"] is True
    assert data["raw_paras"] == ["原文"]
    assert data["has_translated"] is False  # CTA dịch lớn


def test_reader_with_translation_contains_edit_mode_toolbar(tmp_path, monkeypatch):
    _seed(tmp_path, raw="原文", translated="Bản dịch")
    client = _client(tmp_path, monkeypatch)

    data = _chapter_data(client)

    assert data["has_translated"] is True
    assert data["translated_paras"] == ["Bản dịch"]
    assert data["edit_paras"] == ["Bản dịch"]
    assert data["word_count"] > 0


def test_reader_hides_legacy_edit_controls_until_edit_mode_is_enabled(tmp_path, monkeypatch):
    _seed(tmp_path, raw="原文", translated="Bản dịch")
    client = _client(tmp_path, monkeypatch)

    default = _chapter_data(client)
    edit_mode = _chapter_data(client)

    assert default["has_translated"] is True
    # Dữ liệu biên tập sẵn sàng cho mọi chế độ — UI quyết định bật toolbar lúc nào.
    assert edit_mode["edit_paras"] == ["Bản dịch"]
    assert edit_mode["raw_paras"] == ["原文"]


def test_reader_does_not_register_global_keyboard_shortcuts(tmp_path, monkeypatch):
    """Shortcut bàn phím là client-side (SPA); server chỉ cung cấp dữ liệu
    chương — không có HTML chứa xử lý phím."""
    _seed(tmp_path, raw="原文", translated="Bản dịch")
    client = _client(tmp_path, monkeypatch)

    res = client.get("/ebooks/t/read/7")
    assert res.status_code == 200
    assert '<div id="root"></div>' in res.text

    data = _chapter_data(client)
    assert "Ctrl+Shift+F" not in str(data)
    assert "Bookmark" not in str(data)


def test_reader_with_raw_and_translation_contains_raw_compare_view(tmp_path, monkeypatch):
    _seed(tmp_path, raw="甲。\n\n乙。", translated="Một.\n\nHai.")
    client = _client(tmp_path, monkeypatch)

    data = _chapter_data(client)

    assert data["raw_paras"] == ["甲。", "乙。"]
    assert data["translated_paras"] == ["Một.", "Hai."]
    # Cột ZH raw và VI biên tập được đối soát qua paras đã pad cùng độ dài.
    assert len(data["raw_paras"]) == len(data["translated_paras"])
