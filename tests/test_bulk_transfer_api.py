"""Test route export/import biên tập hàng loạt (POST /api/ebooks/{slug}/batch/...)."""
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


def _client(cfg, monkeypatch):
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    from app.main import app
    return TestClient(app)


def _seed(tmp_path):
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=1, url="http://x/1"), Chapter(index=2, url="http://x/2")]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    storage.write_translated(chapters[0], "Bản dịch chương 1")
    storage.write_translated(chapters[1], "Bản dịch chương 2")
    storage.write_translated_mt(chapters[0], "MT 1")
    storage.write_translated_mt(chapters[1], "MT 2")
    return storage, chapters


def test_export_returns_text_with_prompt_and_chapters(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage, _ = _seed(tmp_path)
    storage.write_glossary_file("names.txt", "萧炎 = Tiêu Viêm\n")
    client = _client(cfg, monkeypatch)

    res = client.post("/api/ebooks/t/batch/export", data={"indexes": "1,2"})
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2
    assert data["skipped"] == []
    assert "## Chương 1" in data["text"]
    assert "Bản dịch chương 1" in data["text"]
    assert "萧炎 = Tiêu Viêm" in data["text"]


def test_export_skips_untranslated(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=1, url="http://x/1"), Chapter(index=2, url="http://x/2")]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    storage.write_translated(chapters[0], "Chỉ chương 1")
    client = _client(cfg, monkeypatch)

    res = client.post("/api/ebooks/t/batch/export", data={"indexes": "1,2"})
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["skipped"] == [2]


def test_export_raw_returns_translate_prompt_and_raw_text(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=1, url="http://x/1", title_zh="第一章")]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    storage.write_raw(chapters[0], "原文内容")
    client = _client(cfg, monkeypatch)

    res = client.post("/api/ebooks/t/batch/export", data={"indexes": "1", "source": "raw"})
    assert res.status_code == 200
    data = res.json()
    assert data["source"] == "raw"
    assert data["total"] == 1
    assert "Yêu cầu dịch truyện" in data["text"]
    assert "BIÊN TẬP LẠI" not in data["text"]
    assert "原文内容" in data["text"]
    assert "## Chương 1: 第一章" in data["text"]


def test_export_raw_skips_chapters_without_raw(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=1, url="http://x/1"), Chapter(index=2, url="http://x/2")]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    storage.write_raw(chapters[0], "只有章节一")
    client = _client(cfg, monkeypatch)

    res = client.post("/api/ebooks/t/batch/export", data={"indexes": "1,2", "source": "raw"})
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["skipped"] == [2]


def test_export_invalid_source_400(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path)
    client = _client(cfg, monkeypatch)
    res = client.post("/api/ebooks/t/batch/export", data={"indexes": "1", "source": "bogus"})
    assert res.status_code == 400


def test_export_no_indexes_400(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path)
    client = _client(cfg, monkeypatch)
    res = client.post("/api/ebooks/t/batch/export", data={"indexes": ""})
    assert res.status_code == 400


def test_import_preview_does_not_write(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage, chapters = _seed(tmp_path)
    client = _client(cfg, monkeypatch)

    text = (
        "========== CHƯƠNG 1 ==========\nĐã sửa chương 1\n"
        "========== CHƯƠNG 2 ==========\nBản dịch chương 2\n"
        "========== GLOSSARY ==========\n[NAMES]\n林动 = Lâm Động\n"
    )
    res = client.post(
        "/api/ebooks/t/batch/import",
        data={"text": text, "indexes": "1,2", "mode": "preview"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "preview"
    # Chương 1 đổi, chương 2 không đổi.
    by_idx = {c["index"]: c for c in data["chapters"]}
    assert by_idx[1]["changed"] is True
    assert by_idx[2]["changed"] is False
    assert data["glossary_names"] == {"林动": "Lâm Động"}
    # Preview KHÔNG ghi.
    assert storage.read_translated(chapters[0]) == "Bản dịch chương 1"
    assert storage.read_glossary_file("names.txt") == {}


def test_import_confirm_writes_and_merges_glossary(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage, chapters = _seed(tmp_path)
    client = _client(cfg, monkeypatch)

    text = (
        "========== CHƯƠNG 1 ==========\nĐã sửa chương 1\n"
        "========== GLOSSARY ==========\n[NAMES]\n林动 = Lâm Động\n[VIETPHRASE]\n斗气 = Đấu khí\n"
    )
    res = client.post(
        "/api/ebooks/t/batch/import",
        data={"text": text, "indexes": "1", "mode": "confirm"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["written"] == [1]
    assert data["glossary_added"] == 2
    # Ghi đè translated/ đúng chương.
    assert storage.read_translated(chapters[0]) == "Đã sửa chương 1"
    # KHÔNG đụng translated_mt/.
    assert storage.read_translated_mt(chapters[0]) == "MT 1"
    # Glossary đã merge.
    assert storage.read_glossary_file("names.txt") == {"林动": "Lâm Động"}
    assert storage.read_glossary_file("vietphrase.txt") == {"斗气": "Đấu khí"}


def test_import_confirm_backfills_translated_mt_when_missing(tmp_path, monkeypatch):
    """Chương chưa từng có translated_mt (vd vừa dịch lần đầu qua luồng 'xuất
    raw để dịch') — confirm phải ghi cả translated_mt lẫn translated."""
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=1, url="http://x/1")]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    storage.write_raw(chapters[0], "原文")
    client = _client(cfg, monkeypatch)

    text = "## Chương 1\nBản dịch đầu tiên\n"
    res = client.post(
        "/api/ebooks/t/batch/import",
        data={"text": text, "indexes": "1", "mode": "confirm"},
    )
    assert res.status_code == 200
    assert storage.read_translated(chapters[0]) == "Bản dịch đầu tiên"
    assert storage.has_translated_mt(chapters[0])
    assert storage.read_translated_mt(chapters[0]) == "Bản dịch đầu tiên"


def test_import_no_marker_400(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path)
    client = _client(cfg, monkeypatch)
    res = client.post(
        "/api/ebooks/t/batch/import",
        data={"text": "không có marker", "indexes": "1", "mode": "preview"},
    )
    assert res.status_code == 400


def test_import_unknown_index_not_written(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage, chapters = _seed(tmp_path)
    client = _client(cfg, monkeypatch)

    text = "========== CHƯƠNG 99 ==========\nChương không thuộc truyện\n"
    res = client.post(
        "/api/ebooks/t/batch/import",
        data={"text": text, "indexes": "1", "mode": "confirm"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["written"] == []
    assert data["unknown"] == [99]
