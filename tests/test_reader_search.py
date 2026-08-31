from __future__ import annotations

from fastapi.testclient import TestClient

from app import deps
from novel2epub.config import Config, CrawlConfig, NovelConfig, OutputConfig, TranslateConfig
from novel2epub.storage import Chapter, Manifest, Storage


def _cfg(tmp_path):
    return Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/book/", delay_seconds=0),
        translate=TranslateConfig(type="none", delay_seconds=0),
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
    chapters = [
        Chapter(index=1, url="http://x/1", title="Chương 1 — Mở đầu"),
        Chapter(index=2, url="http://x/2", title=""),
        Chapter(index=3, url="http://x/3", title="Chương 3"),
    ]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    storage.write_translated(chapters[0], "Trương Tam đi chợ. Trương Tam về nhà.")
    storage.write_translated(chapters[1], "trương tam ngủ.")
    # chương 3 chưa dịch → bỏ qua khi tìm.
    return storage, chapters


def test_search_literal_groups_by_chapter_with_counts(tmp_path, monkeypatch):
    _seed(tmp_path)
    client = _client(_cfg(tmp_path), monkeypatch)

    res = client.get("/api/ebooks/t/search", params={"q": "Trương Tam"})
    assert res.status_code == 200
    data = res.json()
    # Mặc định không phân biệt hoa/thường → chương 1 (2) + chương 2 (1).
    assert [(r["chapter_index"], r["count"]) for r in data] == [(1, 2), (2, 1)]
    assert data[0]["title"] == "Chương 1 — Mở đầu"
    assert data[0]["snippets"]


def test_search_case_sensitive_excludes_lowercase(tmp_path, monkeypatch):
    _seed(tmp_path)
    client = _client(_cfg(tmp_path), monkeypatch)

    res = client.get("/api/ebooks/t/search", params={"q": "Trương Tam", "case": 1})
    assert res.status_code == 200
    data = res.json()
    assert [(r["chapter_index"], r["count"]) for r in data] == [(1, 2)]


def test_search_regex_pattern(tmp_path, monkeypatch):
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=1, url="http://x/1", title="")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    storage.write_translated(ch, "Chương 1 và Chương 22 và Chương 333.")
    client = _client(_cfg(tmp_path), monkeypatch)

    res = client.get("/api/ebooks/t/search", params={"q": r"Chương \d+", "regex": 1})
    assert res.status_code == 200
    data = res.json()
    assert data[0]["count"] == 3
    # Chương không có title → fallback "Chương {index}".
    assert data[0]["title"] == "Chương 1"


def test_search_invalid_regex_returns_400(tmp_path, monkeypatch):
    _seed(tmp_path)
    client = _client(_cfg(tmp_path), monkeypatch)
    res = client.get("/api/ebooks/t/search", params={"q": "[bad", "regex": 1})
    assert res.status_code == 400


def test_search_blank_query_returns_400(tmp_path, monkeypatch):
    _seed(tmp_path)
    client = _client(_cfg(tmp_path), monkeypatch)
    res = client.get("/api/ebooks/t/search", params={"q": "   "})
    assert res.status_code == 400


def test_search_no_matches_returns_empty_list(tmp_path, monkeypatch):
    _seed(tmp_path)
    client = _client(_cfg(tmp_path), monkeypatch)
    res = client.get("/api/ebooks/t/search", params={"q": "không tồn tại xyz"})
    assert res.status_code == 200
    assert res.json() == []


def test_reader_page_renders_toc_and_search_ui(tmp_path, monkeypatch):
    """Trang đọc là SPA fallback (`/ebooks/t/read/1` → index.html); dữ liệu tìm
    kiếm chương đi qua API `/api/ebooks/t/search`."""
    _seed(tmp_path)
    client = _client(_cfg(tmp_path), monkeypatch)
    res = client.get("/ebooks/t/read/1")
    assert res.status_code == 200
    assert '<div id="root"></div>' in res.text
    assert res.headers.get("content-type", "").startswith("text/html")

    # Thanh tìm kiếm mục lục render từ dữ liệu API — chương hiện tại phải có
    # dữ liệu để đánh dấu active.
    search = client.get("/api/ebooks/t/search", params={"q": "Trương Tam"})
    assert search.status_code == 200
    assert search.json()[0]["chapter_index"] == 1
