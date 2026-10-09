"""Test route AI trích nhân vật (POST /api/ebooks/{slug}/batch/extract-characters).

Job giả chạy target đồng bộ ngay trong request để kiểm tra kết quả mà không
cần chờ thread nền.
"""
from __future__ import annotations

from novel2epub import characters_ai
from novel2epub.storage import Chapter, Manifest, Storage
from tests.helpers.routes import make_client, make_config


def _cfg(tmp_path):
    return make_config(tmp_path, translate_type="openai")


def _client(cfg, monkeypatch):
    return make_client(cfg, monkeypatch, run_jobs=True)


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
