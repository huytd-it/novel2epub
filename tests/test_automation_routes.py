"""Tests route /automation: validate lịch cron, hiển thị chạy-kế-tiếp."""
from __future__ import annotations

from fastapi.testclient import TestClient

from novel2epub.automation import add_automation, load_automations


def _client(monkeypatch, tmp_path):
    from app import deps
    from app.main import app

    monkeypatch.setattr(deps, "WORKSPACE_PATH", str(tmp_path / "novel2epub.yaml"))
    monkeypatch.setattr(deps, "SOURCES_PATH", str(tmp_path / "sources.yaml"))
    monkeypatch.setattr(deps, "AUTOMATIONS_PATH", tmp_path / "automations.yaml")
    return app, TestClient(app)


def test_create_rejects_invalid_schedule(monkeypatch, tmp_path):
    app, client = _client(monkeypatch, tmp_path)
    res = client.post("/automation", data={
        "ebook": "e", "steps": ["build"], "schedule": "daily@03:00",
    })
    assert res.status_code == 400
    assert load_automations(tmp_path / "automations.yaml") == {}


def test_create_accepts_cron_schedule(monkeypatch, tmp_path):
    app, client = _client(monkeypatch, tmp_path)
    res = client.post("/automation", data={
        "ebook": "e", "steps": ["build"], "schedule": "*/30 * * * *",
    }, follow_redirects=False)
    assert res.status_code == 303
    automations = load_automations(tmp_path / "automations.yaml")
    assert len(automations) == 1
    assert next(iter(automations.values())).schedule == "*/30 * * * *"


def test_update_rejects_invalid_schedule(monkeypatch, tmp_path):
    app, client = _client(monkeypatch, tmp_path)
    a = add_automation(tmp_path / "automations.yaml", "e", ["build"], "*/30 * * * *")
    res = client.post(f"/automation/{a.id}/update", data={
        "steps": ["build"], "schedule": "not-a-cron", "enabled": "true",
    })
    assert res.status_code == 400
    loaded = load_automations(tmp_path / "automations.yaml")
    assert loaded[a.id].schedule == "*/30 * * * *"


def test_page_shows_next_run(monkeypatch, tmp_path):
    from datetime import datetime

    from croniter import croniter

    app, client = _client(monkeypatch, tmp_path)
    a = add_automation(tmp_path / "automations.yaml", "e", ["build"], "0 3 * * *")
    expected = (
        croniter("0 3 * * *", datetime.fromisoformat(a.created_at))
        .get_next(datetime)
        .strftime("%Y-%m-%d %H:%M")
    )
    res = client.get("/automation")
    assert res.status_code == 200
    assert expected in res.text  # cột "Chạy kế tiếp" hiện mốc 3h sáng kế tiếp
