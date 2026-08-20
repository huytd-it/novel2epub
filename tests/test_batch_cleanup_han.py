"""Test route dọn chữ Hán hàng loạt (POST /api/ebooks/{slug}/batch/cleanup-han)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import deps
from app.routes import chapters as chapters_route
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


class _FakeJob:
    """Chạy target đồng bộ để test quan sát được tham số truyền xuống pipeline."""

    def __init__(self):
        self.started = []

    def status(self):
        return {
            "crawl": {"running": False, "step": "", "error": "", "log": []},
            "translate": {"running": False, "step": "", "error": "", "log": []},
        }

    def start_custom(self, name, target, category, **kwargs):
        self.started.append({"name": name, "category": category, **kwargs})
        target(lambda msg: None)
        return True


def _client(cfg, monkeypatch):
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    from app.main import app
    app.state.job = _FakeJob()
    return TestClient(app), app.state.job


def _seed(tmp_path):
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=i, url=f"http://x/{i}") for i in (1, 2, 3)]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    return storage


def _capture(monkeypatch):
    calls = []
    monkeypatch.setattr(
        chapters_route,
        "step_cleanup_han_selected",
        lambda cfg, log, **kwargs: calls.append(kwargs),
    )
    return calls


def test_cleanup_han_enqueues_one_job_for_selection(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path)
    calls = _capture(monkeypatch)
    client, job = _client(cfg, monkeypatch)

    res = client.post("/api/ebooks/t/batch/cleanup-han", data={"indexes": "1,3"})

    assert res.status_code == 200
    assert res.json() == {"started": True, "total": 2}
    assert len(job.started) == 1
    assert job.started[0]["category"] == "translate"
    assert job.started[0]["chapter_indexes"] == [1, 3]
    assert len(calls) == 1
    assert calls[0]["selected_indexes"] == [1, 3]
    assert calls[0]["force"] is False
    assert calls[0]["engine"] is None


def test_cleanup_han_passes_engine_and_force(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path)
    calls = _capture(monkeypatch)
    client, _job = _client(cfg, monkeypatch)

    res = client.post(
        "/api/ebooks/t/batch/cleanup-han",
        data={"indexes": "2", "engine": "openai", "force": "true"},
    )

    assert res.status_code == 200
    assert calls[0]["engine"] == "openai"
    assert calls[0]["force"] is True


def test_cleanup_han_rejects_empty_selection(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path)
    _capture(monkeypatch)
    client, _job = _client(cfg, monkeypatch)

    res = client.post("/api/ebooks/t/batch/cleanup-han", data={"indexes": " , "})
    assert res.status_code == 400


def test_cleanup_han_rejects_unknown_engine(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path)
    _capture(monkeypatch)
    client, _job = _client(cfg, monkeypatch)

    res = client.post(
        "/api/ebooks/t/batch/cleanup-han",
        data={"indexes": "1", "engine": "gemini"},
    )
    assert res.status_code == 400
