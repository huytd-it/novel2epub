"""Test cache của /api/dashboard: đúng số liệu, hit khi DB không đổi, bỏ cache
khi DB đổi, và KHÔNG dùng chung cache giữa 2 DB khác nhau."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import deps
from app.routes import dashboard
from novel2epub.config import (
    Config,
    CrawlConfig,
    NovelConfig,
    OutputConfig,
    TranslateConfig,
)
from novel2epub.storage import Chapter, Manifest, Storage


@pytest.fixture(autouse=True)
def _clear_cache():
    dashboard._cache = None
    yield
    dashboard._cache = None


def _cfg(tmp_path, slug="t"):
    return Config(
        novel=NovelConfig(slug=slug, title="Truyện T"),
        crawl=CrawlConfig(toc_url="http://x/book/", delay_seconds=0),
        translate=TranslateConfig(type="cli", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


def _fake_library(slug="t"):
    entry = type("E", (), {"name": "Truyện T", "slug": slug})()
    return type("L", (), {"ebooks": {slug: entry}})()


class _FakeQueue:
    def __init__(self):
        self.running: list[dict] = []

    def snapshot(self):
        return {"running": list(self.running), "pending": {}, "history": []}


class _FakeJob:
    """Stub cho app.state.job. Test khác gán thẳng `app.state.job = ...` (không
    qua monkeypatch) nên state rò rỉ ra cả suite và có fake không hề có
    `.queue` — tự lắp stub riêng để test này không phụ thuộc thứ tự chạy."""

    def __init__(self):
        self.queue = _FakeQueue()

    def status(self):
        return {"crawl": {"running": False, "step": "", "error": "", "log": []}}


def _seed(tmp_path, slug="t", n=3, raw_for=(), translated_for=()):
    storage = Storage(tmp_path, slug)
    chapters = [Chapter(index=i, url=f"http://x/{i}") for i in range(1, n + 1)]
    storage.save_manifest(Manifest(slug=slug, chapters=chapters))
    for ch in chapters:
        if ch.index in raw_for:
            storage.write_raw(ch, "你好世界" * 20)
        if ch.index in translated_for:
            storage.write_translated(ch, "Xin chào thế giới")
            storage.mark_translated_complete(ch)
    return storage, chapters


def _client(monkeypatch, cfg, slug="t"):
    monkeypatch.setattr(deps, "library", lambda: _fake_library(slug))
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda s: cfg)
    from app.main import app
    app.state.job = _FakeJob()
    return TestClient(app), app.state.job


def test_dashboard_reports_progress(tmp_path, monkeypatch):
    _seed(tmp_path, n=3, raw_for=(1, 2), translated_for=(1,))
    client, _ = _client(monkeypatch, _cfg(tmp_path))

    data = client.get("/api/dashboard").json()

    assert data["summary"]["ebook_count"] == 1
    assert data["summary"]["total_chapters"] == 3
    assert data["summary"]["raw_count"] == 2
    assert data["summary"]["translated_count"] == 1
    row = data["rows"][0]
    assert row["slug"] == "t"
    assert row["progress"]["raw_count"] == 2
    assert row["progress"]["translated_count"] == 1


def test_cache_hit_when_db_unchanged(tmp_path, monkeypatch):
    _seed(tmp_path, n=3, raw_for=(1,))
    client, _ = _client(monkeypatch, _cfg(tmp_path))

    calls = []
    real = dashboard._build_ebook_rows

    def spy(cfgs):
        calls.append(1)
        return real(cfgs)

    monkeypatch.setattr(dashboard, "_build_ebook_rows", spy)

    first = client.get("/api/dashboard").json()
    for _ in range(4):
        client.get("/api/dashboard")
    again = client.get("/api/dashboard").json()

    assert len(calls) == 1, "DB không đổi thì chỉ được dựng lại đúng 1 lần"
    assert again["rows"] == first["rows"]


def test_cache_invalidated_when_db_changes(tmp_path, monkeypatch):
    storage, chapters = _seed(tmp_path, n=3, raw_for=(1,))
    client, _ = _client(monkeypatch, _cfg(tmp_path))

    before = client.get("/api/dashboard").json()
    assert before["summary"]["raw_count"] == 1

    storage.write_raw(chapters[1], "你好世界" * 20)
    after = client.get("/api/dashboard").json()

    assert after["summary"]["raw_count"] == 2, "ghi vào DB phải làm cache mất hiệu lực"


def test_running_jobs_stays_live_on_cache_hit(tmp_path, monkeypatch):
    _seed(tmp_path, n=2, raw_for=(1,))
    client, job = _client(monkeypatch, _cfg(tmp_path))

    assert client.get("/api/dashboard").json()["summary"]["running_jobs"] == 0

    # Job bắt đầu nhưng CHƯA ghi gì vào DB → chữ ký DB không đổi → rows lấy từ
    # cache, nhưng ô "Job đang chạy" vẫn phải cập nhật ngay.
    job.queue.running = [{"id": "j1", "kind": "crawl"}]

    assert client.get("/api/dashboard").json()["summary"]["running_jobs"] == 1


def test_cache_not_shared_between_different_dbs(tmp_path, monkeypatch):
    """deps.DB_PATH đứng yên khi test đổi DB qua resolved_cfg — chữ ký cache
    phải bám theo cfg, nếu không ebook này sẽ thấy số liệu của ebook kia."""
    db_a = tmp_path / "a"
    db_b = tmp_path / "b"
    db_a.mkdir()
    db_b.mkdir()
    _seed(db_a, n=5, raw_for=(1, 2, 3))
    _seed(db_b, n=2, raw_for=())

    client, _ = _client(monkeypatch, _cfg(db_a))
    a = client.get("/api/dashboard").json()
    assert a["summary"]["total_chapters"] == 5
    assert a["summary"]["raw_count"] == 3

    monkeypatch.setattr(deps, "resolved_cfg", lambda s: _cfg(db_b))
    b = client.get("/api/dashboard").json()

    assert b["summary"]["total_chapters"] == 2
    assert b["summary"]["raw_count"] == 0
