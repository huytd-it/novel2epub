"""Test route crawl hàng loạt chương đã chọn (POST /api/ebooks/{slug}/batch/crawl).

Phục vụ nút "Crawl" / "Crawl lại (force)" trên thanh hành động hàng loạt của
trang Tổng quan: `force=False` chỉ tải chương thiếu raw, `force=True` tải lại
cả chương đã có raw.
"""
from __future__ import annotations

from novel2epub.storage import Chapter, Manifest, Storage
from tests.helpers.routes import make_client as _client, make_config as _cfg


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
