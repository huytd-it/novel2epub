"""Test route AI trích nhân vật (POST /api/ebooks/{slug}/batch/extract-characters).

_FakeJob.start_custom chạy target ĐỒNG BỘ ngay trong request — pattern mượn từ
`tests/test_batch_delete_translation.py` — để assert được kết quả mà không cần
chờ thread nền.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import deps
from novel2epub import characters_ai
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
        translate=TranslateConfig(type="openai", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


class _FakeJob:
    def __init__(self):
        self.started = []

    def status(self):
        return {
            "crawl": {"running": False, "step": "", "error": "", "log": []},
            "translate": {"running": False, "step": "", "error": "", "log": []},
        }

    def start_custom(
        self,
        name,
        target,
        *,
        category,
        ebook="",
        spec=None,
        cancel_event=None,
        chapter_indexes=None,
        lock_ebook=True,
        label="",
    ):
        self.started.append({"name": name, "target": target, "category": category})
        target(lambda msg: None)
        return True


def _client(cfg, monkeypatch):
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    from app.main import app

    app.state.job = _FakeJob()
    return TestClient(app)


def _seed_chapters(tmp_path):
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=1, url="http://x/1"), Chapter(index=2, url="http://x/2")]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    storage.write_raw(chapters[0], "林凡说：\"师父，弟子回来了。\"")
    storage.write_raw(chapters[1], "苏清雪说：\"林公子，请自重。\"")
    return storage, chapters


def test_extract_characters_writes_pending_queue(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage, _chapters = _seed_chapters(tmp_path)
    client = _client(cfg, monkeypatch)

    def fake_extract(ai_cfg, chapters, existing, glossary, *, genre, max_chars, log=None):
        assert len(chapters) == 2
        return {
            "characters": [{"source": "林凡", "target": "Lâm Phàm"}],
            "relations": [],
        }

    monkeypatch.setattr(characters_ai, "extract_characters", fake_extract)

    res = client.post(
        "/api/ebooks/t/batch/extract-characters", data={"indexes": "1,2"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["started"] is True
    assert data["total"] == 2

    pending = storage.read_extra_json("characters_pending")
    assert pending["characters"] == [{"source": "林凡", "target": "Lâm Phàm"}]


def test_extract_characters_skips_chapters_without_raw(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=1, url="http://x/1")]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    # Không ghi raw — chương rỗng phải bị bỏ qua, không gọi AI.
    client = _client(cfg, monkeypatch)

    called = []
    monkeypatch.setattr(
        characters_ai, "extract_characters",
        lambda *a, **kw: called.append(1) or {"characters": [], "relations": []},
    )

    res = client.post("/api/ebooks/t/batch/extract-characters", data={"indexes": "1"})
    assert res.status_code == 200
    assert called == []
    assert storage.read_extra_json("characters_pending") in (None, {})
