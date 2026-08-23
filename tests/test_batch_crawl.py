"""Test route crawl hàng loạt chương đã chọn (POST /api/ebooks/{slug}/batch/crawl).

Phục vụ nút "Crawl" / "Crawl lại (force)" trên thanh hành động hàng loạt của
trang Tổng quan: `force=False` chỉ tải chương thiếu raw, `force=True` tải lại
cả chương đã có raw.
"""
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


class _FakeJob:
    """Stub app.state.job: ghi lại start_custom, KHÔNG chạy target (crawl thật
    cần mạng — test chỉ cần biết job được xếp đúng category và cờ force)."""

    def __init__(self):
        self.started: list[dict] = []

    def status(self):
        return {
            "crawl": {"running": False, "step": "", "error": "", "log": []},
            "translate": {"running": False, "step": "", "error": "", "log": []},
        }

    def start_custom(self, name, target, *, category, **_kwargs):
        self.started.append({"name": name, "category": category})
        return True


def _client(cfg, monkeypatch) -> TestClient:
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    from app.main import app

    app.state.job = _FakeJob()
    return TestClient(app)


def _seed(tmp_path) -> Storage:
    storage = Storage(str(tmp_path), "t")
    storage.save_manifest(Manifest(slug="t", chapters=[
        Chapter(index=1, url="http://x/1"),
        Chapter(index=2, url="http://x/2"),
    ]))
    return storage


def test_batch_crawl_enqueues_crawl_job(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path)
    client = _client(cfg, monkeypatch)

    res = client.post("/api/ebooks/t/batch/crawl", data={"indexes": "1,2"})
    assert res.status_code == 200
    data = res.json()
    assert data == {"started": True, "total": 2, "force": False}
    assert client.app.state.job.started[0]["category"] == "crawl"


def test_batch_crawl_force_flag_reaches_job_label_kind(tmp_path, monkeypatch):
    """force=True phải thấy khác force=False ở tên job (nhãn 'Cào lại')."""
    cfg = _cfg(tmp_path)
    _seed(tmp_path)
    client = _client(cfg, monkeypatch)

    res = client.post(
        "/api/ebooks/t/batch/crawl", data={"indexes": "1", "force": "true"}
    )
    assert res.status_code == 200
    assert res.json()["force"] is True
    assert "crawl-force" in client.app.state.job.started[0]["name"]


def test_batch_crawl_empty_indexes_returns_400(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path)
    client = _client(cfg, monkeypatch)

    res = client.post("/api/ebooks/t/batch/crawl", data={"indexes": ""})
    # Form(...) bắt buộc → FastAPI trả 422 khi thiếu hẳn; chuỗi rỗng → handler 400.
    assert res.status_code in (400, 422)
