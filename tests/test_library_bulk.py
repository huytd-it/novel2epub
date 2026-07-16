"""Tests cho luồng nhập ebook hàng loạt: nhiều URL mục lục -> tạo ebook +
(tùy chọn) bật automation liên tục cho từng ebook."""
from __future__ import annotations

from fastapi.testclient import TestClient

from novel2epub.automation import load_automations


def _fake_job():
    class Job:
        def status(self):
            return {
                "crawl": {"running": False, "step": "", "error": "", "log": []},
                "translate": {"running": False, "step": "", "error": "", "log": []},
            }

    return Job()


def _client(monkeypatch, tmp_path):
    from app import deps
    from app.main import app

    monkeypatch.setattr(deps, "WORKSPACE_PATH", str(tmp_path / "novel2epub.yaml"))
    monkeypatch.setattr(deps, "SOURCES_PATH", str(tmp_path / "sources.yaml"))
    monkeypatch.setattr(deps, "AUTOMATIONS_PATH", tmp_path / "automations.yaml")
    app.state.job = _fake_job()

    class _FakeScheduler:
        def __init__(self):
            self.ran = []

        def run_now(self, automation_id):
            self.ran.append(automation_id)
            return "job-id"

    app.state.scheduler = _FakeScheduler()
    return app, TestClient(app)


def _meta_for(url: str) -> dict:
    # slug/name giả lập theo URL để mỗi test tự kiểm soát được ebook nào trùng nhau.
    name = url.rstrip("/").rsplit("/", 1)[-1]
    return {"name": name, "author": "Tác giả", "slug": name, "cover_url": "", "chapter_count": 10}


def test_bulk_create_happy_path_three_urls(monkeypatch, tmp_path):
    from app.routes import library

    app, client = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(library, "_fetch_meta", lambda url, preset_name="": _meta_for(url))

    res = client.post("/library/ebooks/bulk", data={
        "toc_urls": "https://a.com/truyen-a\nhttps://a.com/truyen-b\nhttps://a.com/truyen-c",
    })
    assert res.status_code == 200
    results = res.json()["results"]
    assert len(results) == 3
    assert all(r["status"] == "created" for r in results)
    assert all(r["automation"] is True for r in results)

    automations = load_automations(tmp_path / "automations.yaml")
    assert len(automations) == 3
    for a in automations.values():
        assert a.schedule == "*/30 * * * *"
        assert a.steps == ["crawl-new", "translate-pending", "cleanup-han", "build"]
    # tạo xong chạy ngay lần đầu — lịch cron chỉ tự nổ từ mốc kế tiếp
    assert sorted(app.state.scheduler.ran) == sorted(automations.keys())


def test_bulk_create_partial_failure_does_not_block_others(monkeypatch, tmp_path):
    from app.routes import library

    app, client = _client(monkeypatch, tmp_path)

    def fake_fetch(url, preset_name=""):
        if "bad" in url:
            raise RuntimeError("Lỗi mạng")
        return _meta_for(url)

    monkeypatch.setattr(library, "_fetch_meta", fake_fetch)

    res = client.post("/library/ebooks/bulk", data={
        "toc_urls": "https://a.com/truyen-a\nhttps://a.com/bad-url\nhttps://a.com/truyen-c",
    })
    assert res.status_code == 200
    results = res.json()["results"]
    statuses = {r["url"]: r["status"] for r in results}
    assert statuses["https://a.com/truyen-a"] == "created"
    assert statuses["https://a.com/bad-url"] == "failed"
    assert statuses["https://a.com/truyen-c"] == "created"

    automations = load_automations(tmp_path / "automations.yaml")
    assert len(automations) == 2


def test_bulk_create_duplicate_slug_within_batch_is_skipped_not_overwritten(monkeypatch, tmp_path):
    from app.routes import library

    app, client = _client(monkeypatch, tmp_path)
    # 2 URL khác nhau nhưng cùng resolve về 1 tên/slug truyện.
    monkeypatch.setattr(library, "_fetch_meta", lambda url, preset_name="": _meta_for("https://x.com/truyen-trung"))

    res = client.post("/library/ebooks/bulk", data={
        "toc_urls": "https://a.com/truyen-trung\nhttps://b.com/truyen-trung",
    })
    assert res.status_code == 200
    results = res.json()["results"]
    assert results[0]["status"] == "created"
    assert results[1]["status"] == "skipped-duplicate"

    automations = load_automations(tmp_path / "automations.yaml")
    assert len(automations) == 1


def test_bulk_create_rejects_more_than_five_urls(monkeypatch, tmp_path):
    from app.routes import library

    app, client = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(library, "_fetch_meta", lambda url, preset_name="": _meta_for(url))

    urls = "\n".join(f"https://a.com/truyen-{i}" for i in range(6))
    res = client.post("/library/ebooks/bulk", data={"toc_urls": urls})
    assert res.status_code == 400

    automations = load_automations(tmp_path / "automations.yaml")
    assert len(automations) == 0


def test_bulk_create_accepts_custom_cron(monkeypatch, tmp_path):
    from app.routes import library

    app, client = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(library, "_fetch_meta", lambda url, preset_name="": _meta_for(url))

    res = client.post("/library/ebooks/bulk", data={
        "toc_urls": "https://a.com/truyen-a",
        "cron": "0 3 * * *",
    })
    assert res.status_code == 200
    automations = load_automations(tmp_path / "automations.yaml")
    assert next(iter(automations.values())).schedule == "0 3 * * *"


def test_bulk_create_rejects_invalid_cron(monkeypatch, tmp_path):
    from app.routes import library

    app, client = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(library, "_fetch_meta", lambda url, preset_name="": _meta_for(url))

    res = client.post("/library/ebooks/bulk", data={
        "toc_urls": "https://a.com/truyen-a",
        "cron": "continuous@30",
    })
    assert res.status_code == 400
    assert load_automations(tmp_path / "automations.yaml") == {}


def test_bulk_create_without_continuous_creates_no_automation(monkeypatch, tmp_path):
    from app.routes import library

    app, client = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(library, "_fetch_meta", lambda url, preset_name="": _meta_for(url))

    res = client.post("/library/ebooks/bulk", data={
        "toc_urls": "https://a.com/truyen-a",
        "enable_continuous": "false",
    })
    assert res.status_code == 200
    results = res.json()["results"]
    assert results[0]["status"] == "created"
    assert results[0]["automation"] is False

    automations = load_automations(tmp_path / "automations.yaml")
    assert len(automations) == 0
