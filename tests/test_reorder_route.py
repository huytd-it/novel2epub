"""Test route sắp xếp chương chạy trực tiếp (POST /api/ebooks/{slug}/jobs/reorder).

Endpoint phải ghi manifest ngay trong request và trả về danh sách đảo vị trí
cũ → mới, KHÔNG xếp job vào hàng đợi nữa.
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


class _FakeJob:
    """Stub app.state.job — ghi lại mọi lần xếp job để test khẳng định là rỗng."""

    def __init__(self):
        self.started = []

    def status(self):
        return {
            "crawl": {"running": False, "step": "", "error": "", "log": []},
            "translate": {"running": False, "step": "", "error": "", "log": []},
        }

    def start_custom(self, name, target, *, category="automation", ebook=None, label=""):
        self.started.append(name)
        target(lambda msg: None)
        return True


def _client(tmp_path, monkeypatch, chapters):
    cfg = Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/book/", delay_seconds=0),
        translate=TranslateConfig(type="cli", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )
    Storage(tmp_path, "t").save_manifest(Manifest(slug="t", chapters=chapters))
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    from app.main import app

    fake = _FakeJob()
    app.state.job = fake
    return TestClient(app), fake


def _chapter(index: int, title: str = "") -> Chapter:
    return Chapter(index=index, url=f"http://x/{index}", title=title)


def test_reorder_manual_applies_immediately_without_queue(tmp_path, monkeypatch):
    client, fake = _client(
        tmp_path, monkeypatch, [_chapter(1), _chapter(2), _chapter(3)]
    )

    res = client.post("/api/ebooks/t/jobs/reorder", data={"order": "3,1,2"})

    assert res.status_code == 200
    body = res.json()
    assert body["mode"] == "manual"
    assert body["total"] == 3
    assert body["moved"] == 3
    assert body["changes"] == [
        {"index": 1, "from": 1, "to": 2},
        {"index": 2, "from": 2, "to": 3},
        {"index": 3, "from": 3, "to": 1},
    ]
    # Không job nào được xếp — thay đổi áp dụng ngay trong request.
    assert fake.started == []
    # Sau khi sắp xếp, index được đánh lại 1..N; nội dung chương theo dõi vị trí.
    manifest = Storage(tmp_path, "t").load_manifest()
    assert [c.url for c in manifest.chapters] == [
        "http://x/3",
        "http://x/1",
        "http://x/2",
    ]


def test_reorder_auto_detects_title_numbers(tmp_path, monkeypatch):
    client, fake = _client(
        tmp_path,
        monkeypatch,
        [_chapter(1, "(Thông báo)"), _chapter(2, "Chương 2"), _chapter(3, "Chương 1")],
    )

    res = client.post("/api/ebooks/t/jobs/reorder", data={"order": "auto"})

    assert res.status_code == 200
    body = res.json()
    assert body["mode"] == "auto"
    # Thông báo không số đứng đầu, nhóm chương sắp theo số: 1 rồi 2.
    assert [change["index"] for change in body["changes"]] == [2, 3]
    assert fake.started == []
    manifest = Storage(tmp_path, "t").load_manifest()
    assert [c.title for c in manifest.chapters] == ["(Thông báo)", "Chương 1", "Chương 2"]


def test_reorder_no_change_reports_zero_moved(tmp_path, monkeypatch):
    client, fake = _client(
        tmp_path, monkeypatch, [_chapter(1), _chapter(2)]
    )

    res = client.post("/api/ebooks/t/jobs/reorder", data={"order": "1,2"})

    assert res.status_code == 200
    assert res.json()["moved"] == 0
    assert res.json()["changes"] == []
    assert fake.started == []


def test_reorder_invalid_order_rejected_without_touching_data(tmp_path, monkeypatch):
    client, fake = _client(
        tmp_path, monkeypatch, [_chapter(1), _chapter(2), _chapter(3)]
    )

    res = client.post("/api/ebooks/t/jobs/reorder", data={"order": "1,2"})

    assert res.status_code == 400
    assert "Thiếu" in res.json()["detail"]
    assert fake.started == []
    manifest = Storage(tmp_path, "t").load_manifest()
    assert [c.url for c in manifest.chapters] == [
        "http://x/1",
        "http://x/2",
        "http://x/3",
    ]
