"""Test route dọn nhanh format bản dịch (POST /api/ebooks/{slug}/batch/normalize-text)."""
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
    chapters = [Chapter(index=i, url=f"http://x/{i}", title=f"Chương {i}") for i in (1, 2, 3)]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    # Ch.1 nhánh AI dính cả Markdown lẫn dấu Hán; ch.2 nhánh MT chỉ dính dấu;
    # ch.3 đã sạch (không đổi).
    storage.write_branch_text(chapters[0], "ai", "**Lâm Phàm** nói：「Đi thôi。」")
    storage.write_branch_titles(chapters[0], "ai", "## Gặp gỡ", "")
    storage.write_branch_text(chapters[1], "local_mt", "Hắn nói，rồi đi。")
    storage.write_branch_text(chapters[2], "ai", "Bản sạch.")
    return storage


def test_normalize_text_mode_all(tmp_path, monkeypatch):
    client = _client(_cfg(tmp_path), monkeypatch)
    _seed(tmp_path)

    res = client.post("/api/ebooks/t/batch/normalize-text", data={"indexes": "1,2,3", "mode": "all"})

    assert res.status_code == 200
    assert res.json() == {"scanned": 3, "updated": 2, "mode": "all"}
    storage = Storage(tmp_path, "t")
    manifest = storage.load_manifest()
    assert storage.read_branch_text(manifest.chapters[0], "ai") == 'Lâm Phàm nói:"Đi thôi."'
    assert storage.read_branch_title(manifest.chapters[0], "ai") == "Gặp gỡ"
    assert storage.read_branch_text(manifest.chapters[1], "local_mt") == "Hắn nói,rồi đi."
    assert storage.read_branch_text(manifest.chapters[2], "ai") == "Bản sạch."


def test_normalize_text_mode_markdown_keeps_punct(tmp_path, monkeypatch):
    client = _client(_cfg(tmp_path), monkeypatch)
    _seed(tmp_path)

    res = client.post("/api/ebooks/t/batch/normalize-text", data={"indexes": "1", "mode": "markdown"})

    assert res.status_code == 200
    assert res.json()["updated"] == 1
    storage = Storage(tmp_path, "t")
    ch = storage.load_manifest().chapters[0]
    assert storage.read_branch_text(ch, "ai") == "Lâm Phàm nói：「Đi thôi。」"


def test_normalize_text_mode_punct_keeps_markdown(tmp_path, monkeypatch):
    client = _client(_cfg(tmp_path), monkeypatch)
    _seed(tmp_path)

    res = client.post("/api/ebooks/t/batch/normalize-text", data={"indexes": "1", "mode": "punct"})

    assert res.status_code == 200
    assert res.json()["updated"] == 1
    storage = Storage(tmp_path, "t")
    ch = storage.load_manifest().chapters[0]
    assert storage.read_branch_text(ch, "ai") == '**Lâm Phàm** nói:"Đi thôi."'


def test_normalize_text_rejects_bad_input(tmp_path, monkeypatch):
    client = _client(_cfg(tmp_path), monkeypatch)
    _seed(tmp_path)

    res = client.post("/api/ebooks/t/batch/normalize-text", data={"indexes": " , "})
    assert res.status_code == 400

    res = client.post("/api/ebooks/t/batch/normalize-text", data={"indexes": "1", "mode": "gemini"})
    assert res.status_code == 400
