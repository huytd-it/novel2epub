import json

import pytest

from novel2epub.config import load_config
from novel2epub.source_switch import apply_switch, propose
from novel2epub.storage import Chapter, Manifest, Storage
from tests.helpers.db import write_db_config


def _seed(tmp_path):
    path = write_db_config(
        tmp_path / "novel2epub.db",
        sources={"backup": {"content_selector": ".new", "chapter_link_pattern": "/chapter/"}},
        ebooks={"book": {"novel": {"slug": "book"}, "crawl": {
            "toc_url": "https://old.example/toc", "content_selector": ".old"}}},
    )
    storage = Storage(tmp_path, "book")
    old = Manifest(slug="book", source_url="https://old.example/toc", title="Sách đã dịch", chapters=[
        Chapter(1, "https://old.example/1", "Bản dịch tên chương", "第1章"),
        Chapter(2, "https://old.example/2", "Chương 2", "第2章"),
    ])
    storage.save_manifest(old)
    storage.write_raw(old.chapters[0], "bản gốc cũ")
    storage.write_translated(old.chapters[0], "bản dịch giữ nguyên")
    incoming = Manifest(slug="book", source_url="https://new.example/toc", chapters=[
        Chapter(1, "https://new.example/chapter/1", "第1章 新版"),
        Chapter(2, "https://new.example/chapter/2", "第2章 新版"),
        Chapter(3, "https://new.example/chapter/3", "第3章"),
    ])
    return path, storage, incoming


def _choices(preview):
    return [{k: row[k] for k in ("position", "action", "old_index", "new_index")} for row in preview["rows"]]


def _apply(storage, incoming, preview, choices):
    return apply_switch(storage, storage.load_manifest(), incoming, choices,
                        preview["old_fingerprint"], preview["toc_fingerprint"],
                        "backup", "https://new.example/toc")


def test_preview_and_confirm_preserve_translation_and_settings(tmp_path):
    path, storage, incoming = _seed(tmp_path)
    preview = propose(storage.load_manifest(), incoming, storage)
    assert [r["action"] for r in preview["rows"]] == ["match", "match", "add"]
    assert preview["rows"][0]["has_raw"] is True
    result = _apply(storage, incoming, preview, _choices(preview))
    assert result == {"matched": 2, "added": 1, "untouched": 0}
    after = storage.load_manifest()
    assert after.title == "Sách đã dịch"
    assert [ch.url for ch in after.chapters] == [ch.url for ch in incoming.chapters]
    assert after.chapters[0].title == "Bản dịch tên chương"
    assert after.chapters[0].title_zh == "第1章 新版"
    assert after.chapters[1].title_zh == "第2章 新版"
    assert storage.read_raw(after.chapters[0]) == "bản gốc cũ"
    assert storage.read_translated(after.chapters[0]) == "bản dịch giữ nguyên"
    row = storage.conn.execute("SELECT source_preset, crawl_overrides_json FROM ebooks WHERE slug='book'").fetchone()
    assert row["source_preset"] == "backup"
    assert json.loads(row["crawl_overrides_json"]) == {"toc_url": "https://new.example/toc"}
    cfg = load_config(path, "book")
    assert cfg.crawl.toc_url == "https://new.example/toc"
    assert cfg.crawl.content_selector == ".new"


def test_fetch_toc_after_switch_does_not_duplicate_and_keeps_translation(tmp_path):
    from novel2epub import pipeline
    from novel2epub.crawler import TocResult

    path, storage, incoming = _seed(tmp_path)
    preview = propose(storage.load_manifest(), incoming, storage)
    _apply(storage, incoming, preview, _choices(preview))

    class Crawler:
        def fetch_toc(self):
            return TocResult(title="Tên trang", author="", description="", cover_url="",
                             chapters=incoming.chapters, source_url="https://new.example/toc")

    pipeline._refresh_manifest(load_config(path, "book"), storage, Crawler(), lambda _message: None)
    after = storage.load_manifest()
    assert len(after.chapters) == 3
    assert after.chapters[0].title == "Bản dịch tên chương"
    assert after.chapters[0].title_zh == "第1章 新版"
    assert storage.read_translated(after.chapters[0]) == "bản dịch giữ nguyên"


def test_switch_updates_title_if_it_was_not_translated(tmp_path):
    _, storage, incoming = _seed(tmp_path)
    old = storage.load_manifest()
    old.chapters[1].title = old.chapters[1].title_zh
    storage.save_chapter(old.chapters[1])
    preview = propose(storage.load_manifest(), incoming, storage)
    _apply(storage, incoming, preview, _choices(preview))
    assert storage.load_manifest().chapters[1].title == "第2章 新版"


def test_missing_chapter_is_filled_at_free_index_without_moving_translation(tmp_path):
    from novel2epub import pipeline
    from novel2epub.crawler import TocResult

    path, storage, incoming = _seed(tmp_path)
    # Old source skipped chapter 2 entirely; the existing chapter 3 has a
    # translation at index 3 which must not move or be overwritten.
    storage.conn.execute("DELETE FROM chapters WHERE ebook_slug='book' AND idx=2")
    storage.conn.execute("INSERT INTO chapters (ebook_slug, idx, url, title, title_zh, translated_text) "
                         "VALUES (?, ?, ?, ?, ?, ?)",
                         ("book", 3, "https://old.example/3", "Chương ba đã dịch", "第3章", "bản dịch chương ba"))
    storage.conn.commit()
    incoming.chapters[2].title = "第3章 新版"
    preview = propose(storage.load_manifest(), incoming, storage)
    assert [(r["action"], r["new_index"]) for r in preview["rows"]] == [
        ("match", None), ("add", 2), ("match", None)]
    result = _apply(storage, incoming, preview, _choices(preview))
    assert result == {"matched": 2, "added": 1, "untouched": 0}
    after = storage.load_manifest()
    assert [ch.index for ch in after.chapters] == [1, 2, 3]
    assert after.chapters[1].url == incoming.chapters[1].url
    assert storage.read_translated(after.chapters[2]) == "bản dịch chương ba"

    class Crawler:
        def fetch_toc(self):
            return TocResult(title="", author="", description="", cover_url="",
                             chapters=incoming.chapters, source_url="https://new.example/toc")

    pipeline._refresh_manifest(load_config(path, "book"), storage, Crawler(), lambda _message: None)
    assert [ch.index for ch in storage.load_manifest().chapters] == [1, 2, 3]


def test_add_at_occupied_index_rejected_without_partial_write(tmp_path):
    _, storage, incoming = _seed(tmp_path)
    preview = propose(storage.load_manifest(), incoming, storage)
    choices = _choices(preview)
    choices[2]["new_index"] = 1
    with pytest.raises(ValueError, match="đã có chương"):
        _apply(storage, incoming, preview, choices)
    assert storage.load_manifest().chapters[0].url == "https://old.example/1"


def test_missing_chapter_with_no_free_index_is_added_not_skipped(tmp_path):
    _, storage, incoming = _seed(tmp_path)
    old = storage.load_manifest()
    old.chapters[1].title_zh = "第3章"
    storage.save_chapter(old.chapters[1])
    incoming.chapters[2].title = "第3章 新版"
    preview = propose(storage.load_manifest(), incoming, storage)
    assert preview["rows"][1]["action"] == "add"
    assert preview["rows"][1]["new_index"] is None
    _apply(storage, incoming, preview, _choices(preview))
    after = storage.load_manifest()
    assert [ch.index for ch in after.chapters] == [1, 2, 3]
    assert after.chapters[1].title_zh == "第3章 新版"
    assert after.chapters[2].title_zh == "第2章 新版"


def test_ambiguous_ordinals_not_matched_automatically(tmp_path):
    _, storage, incoming = _seed(tmp_path)
    incoming.chapters[1].title = "第1章 phần hai"
    preview = propose(storage.load_manifest(), incoming, storage)
    assert [r["action"] for r in preview["rows"]] == ["skip", "skip", "add"]


def test_stale_preview_and_duplicate_mapping_do_not_write(tmp_path):
    _, storage, incoming = _seed(tmp_path)
    preview = propose(storage.load_manifest(), incoming, storage)
    choices = _choices(preview)
    choices[1]["old_index"] = 1
    with pytest.raises(ValueError, match="ghép nhiều lần"):
        _apply(storage, incoming, preview, choices)
    assert storage.load_manifest().chapters[0].url == "https://old.example/1"
    assert storage.conn.execute("SELECT source_preset FROM ebooks WHERE slug='book'").fetchone()[0] is None
    incoming.chapters[0].url = "https://new.example/changed"
    with pytest.raises(ValueError, match="thay đổi"):
        _apply(storage, incoming, preview, _choices(preview))


def test_old_manifest_change_rejects_confirmation(tmp_path):
    _, storage, incoming = _seed(tmp_path)
    preview = propose(storage.load_manifest(), incoming, storage)
    changed = storage.load_manifest()
    changed.chapters[0].title = "Đã sửa"
    storage.save_chapter(changed.chapters[0])
    with pytest.raises(ValueError, match="thay đổi"):
        _apply(storage, incoming, preview, _choices(preview))


def test_api_preview_confirm_and_active_job_guard(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import deps
    from app.main import app
    from app.routes import source_switch

    path, storage, incoming = _seed(tmp_path)
    monkeypatch.setattr(deps, "DB_PATH", path)
    monkeypatch.setattr(deps, "WORKSPACE_PATH", str(path))
    monkeypatch.setattr(source_switch, "_read_toc", lambda name, url, slug, mode=None, headless=None:
                        (incoming, url, mode or "stealthy", True if headless is None else headless))

    class Queue:
        busy = False
        restored = False

        def retire_ebook(self, slug):
            return not self.busy

        def restore_ebook(self, slug):
            self.restored = True

    queue = Queue()
    app.state.job = type("Job", (), {"queue": queue})()
    client = TestClient(app)
    payload = {"source_name": "backup", "toc_url": "https://new.example/toc",
               "crawl_mode": "fetcher", "headless": False}
    response = client.post("/api/ui/ebooks/book/source-switch/preview", json=payload)
    assert response.status_code == 200, response.text
    preview = response.json()
    queue.busy = True
    confirmation = {**payload, "old_fingerprint": preview["old_fingerprint"],
                    "toc_fingerprint": preview["toc_fingerprint"], "choices": _choices(preview)}
    assert client.post("/api/ui/ebooks/book/source-switch/confirm", json=confirmation).status_code == 409
    queue.busy = False
    response = client.post("/api/ui/ebooks/book/source-switch/confirm", json=confirmation)
    assert response.status_code == 200, response.text
    assert queue.restored
    assert storage.load_manifest().chapters[0].url == "https://new.example/chapter/1"
    cfg = load_config(path, "book")
    assert cfg.crawl.scrapling.mode == "fetcher"
    assert cfg.crawl.headless is False


def test_preview_uses_selected_mode_and_headless(tmp_path, monkeypatch):
    from app import deps
    from app.routes import source_switch
    from novel2epub.crawler import TocResult

    path, _, incoming = _seed(tmp_path)
    monkeypatch.setattr(deps, "DB_PATH", path)
    configs = []

    class FakeCrawler:
        def __init__(self, cfg):
            configs.append(cfg)

        def fetch_toc(self):
            return TocResult(title="", author="", description="", cover_url="",
                             chapters=incoming.chapters)

        def close(self):
            pass

    monkeypatch.setattr(source_switch, "ScraplingCrawler", FakeCrawler)
    _, _, mode, headless = source_switch._read_toc(
        "backup", "https://new.example/toc", "book", "stealthy", False)
    assert mode == configs[0].scrapling.mode == "stealthy"
    assert headless is configs[0].headless is False
