"""Test route chuyển nhánh hàng loạt (POST /api/ebooks/{slug}/batch/set-branch).

Phục vụ nút "Dùng bản dịch AI" trên thanh hành động hàng loạt trang Ebook: đổi
nhánh đang hoạt động của các chương đã chọn sang 'ai', bỏ qua chương chưa có bản
dịch AI, và tiêu đề hiển thị tự cập nhật theo Tiêu đề bản Dịch AI.
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


def _client(cfg, monkeypatch) -> TestClient:
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    from app.main import app

    return TestClient(app)


def _seed(tmp_path) -> Storage:
    storage = Storage(str(tmp_path), "t")
    storage.save_manifest(Manifest(slug="t", chapters=[
        Chapter(index=1, url="http://x/1", title="Chương 1"),
        Chapter(index=2, url="http://x/2", title="Chương 2"),
        Chapter(index=3, url="http://x/3", title="Chương 3"),
    ]))
    # Chương 1, 2 có bản dịch AI; chương 3 chưa có gì.
    for idx in (1, 2):
        ch = Chapter(index=idx, url=f"http://x/{idx}")
        rev = storage.read_branch_revision(ch, "ai")
        storage.compare_and_swap_branch(ch, "ai", expected_rev=rev, new_text=f"AI {idx}")
        storage.mark_branch_complete(ch, "ai")
    # Chương 2 đang active ở local_mt (để test chuyển sang ai).
    storage.set_active_branch(Chapter(index=2, url="http://x/2"), "local_mt")
    return storage


def test_batch_set_branch_switches_and_reports_skipped(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = _seed(tmp_path)
    client = _client(cfg, monkeypatch)

    res = client.post(
        "/api/ebooks/t/batch/set-branch", data={"indexes": "1,2,3", "branch": "ai"}
    )
    assert res.status_code == 200
    data = res.json()
    # Chương 1 (đã ai) và 3 (không có AI) không đếm vào updated.
    assert data["updated"] == 1
    assert data["skipped"] == 1
    assert data["branch"] == "ai"
    assert storage.active_branch(Chapter(index=1, url="x")) == "ai"
    assert storage.active_branch(Chapter(index=2, url="x")) == "ai"
    assert storage.active_branch(Chapter(index=3, url="x")) == "ai"


def test_batch_set_branch_invalid_branch_returns_400(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path)
    client = _client(cfg, monkeypatch)

    res = client.post(
        "/api/ebooks/t/batch/set-branch", data={"indexes": "1", "branch": "bogus"}
    )
    assert res.status_code == 400


def test_batch_set_branch_empty_indexes_returns_400(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path)
    client = _client(cfg, monkeypatch)

    res = client.post(
        "/api/ebooks/t/batch/set-branch", data={"indexes": "   ", "branch": "ai"}
    )
    assert res.status_code in (400, 422)
