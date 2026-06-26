"""Automation model (persist) + scheduler (due-check, chạy chuỗi step, enqueue
qua JobQueue) — xem spec automation-scheduling."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.queue import JobQueue
from app.scheduler import AutomationScheduler, _is_due, run_automation_steps
from novel2epub.automation import Automation, add_automation, load_automations, remove_automation, update_automation


def test_add_and_load_automation_roundtrip(tmp_path):
    path = tmp_path / "automations.yaml"
    a = add_automation(path, "myebook", ["fetch-toc", "build"], schedule="daily@03:00")
    loaded = load_automations(path)
    assert a.id in loaded
    assert loaded[a.id].ebook == "myebook"
    assert loaded[a.id].steps == ["fetch-toc", "build"]
    assert loaded[a.id].schedule == "daily@03:00"
    assert loaded[a.id].enabled is True


def test_update_automation_persists_changes(tmp_path):
    path = tmp_path / "automations.yaml"
    a = add_automation(path, "myebook", ["build"])
    update_automation(path, a.id, {"last_run_at": "2024-01-01T00:00:00", "last_run_outcome": "success"})
    loaded = load_automations(path)
    assert loaded[a.id].last_run_at == "2024-01-01T00:00:00"
    assert loaded[a.id].last_run_outcome == "success"


def test_remove_automation(tmp_path):
    path = tmp_path / "automations.yaml"
    a = add_automation(path, "myebook", ["build"])
    remove_automation(path, a.id)
    assert load_automations(path) == {}


# ---------- _is_due ----------


def test_manual_schedule_never_due():
    a = Automation(id="x", ebook="e", schedule="manual")
    assert _is_due(a, datetime.now()) is False


def test_disabled_automation_never_due():
    a = Automation(id="x", ebook="e", schedule="daily@00:00", enabled=False)
    assert _is_due(a, datetime.now()) is False


def test_daily_schedule_due_after_scheduled_time_today():
    now = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
    a = Automation(id="x", ebook="e", schedule="daily@09:00")
    assert _is_due(a, now) is True


def test_daily_schedule_not_due_before_scheduled_time():
    now = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
    a = Automation(id="x", ebook="e", schedule="daily@09:00")
    assert _is_due(a, now) is False


def test_daily_schedule_not_due_twice_same_day():
    now = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
    a = Automation(id="x", ebook="e", schedule="daily@09:00", last_run_at=now.isoformat())
    assert _is_due(a, now) is False


def test_daily_schedule_due_again_next_day():
    yesterday = datetime.now() - timedelta(days=1)
    now = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
    a = Automation(id="x", ebook="e", schedule="daily@09:00", last_run_at=yesterday.isoformat())
    assert _is_due(a, now) is True


# ---------- run_automation_steps ----------


def test_run_automation_steps_all_succeed(tmp_path, monkeypatch):
    from app import scheduler as scheduler_mod

    calls = []
    monkeypatch.setattr(scheduler_mod, "load_config", lambda path, slug: object())
    monkeypatch.setitem(scheduler_mod._STEP_FN, "fetch-toc", lambda cfg, log: calls.append("fetch-toc"))
    monkeypatch.setitem(scheduler_mod._STEP_FN, "build", lambda cfg, log: calls.append("build"))

    a = Automation(id="x", ebook="e", steps=["fetch-toc", "build"])
    outcome = run_automation_steps(tmp_path, a, lambda m: None)
    assert outcome == "success"
    assert calls == ["fetch-toc", "build"]


def test_run_automation_steps_partial_on_failure(monkeypatch, tmp_path):
    from app import scheduler as scheduler_mod

    monkeypatch.setattr(scheduler_mod, "load_config", lambda path, slug: object())

    def _boom(cfg, log):
        raise RuntimeError("lỗi crawl")

    monkeypatch.setitem(scheduler_mod._STEP_FN, "fetch-toc", lambda cfg, log: None)
    monkeypatch.setitem(scheduler_mod._STEP_FN, "crawl-new", _boom)
    monkeypatch.setitem(scheduler_mod._STEP_FN, "build", lambda cfg, log: None)

    a = Automation(id="x", ebook="e", steps=["fetch-toc", "crawl-new", "build"])
    outcome = run_automation_steps(tmp_path, a, lambda m: None)
    assert outcome == "partial"


def test_run_automation_steps_failure_when_first_step_fails(monkeypatch, tmp_path):
    from app import scheduler as scheduler_mod

    monkeypatch.setattr(scheduler_mod, "load_config", lambda path, slug: object())

    def _boom(cfg, log):
        raise RuntimeError("lỗi")

    monkeypatch.setitem(scheduler_mod._STEP_FN, "build", _boom)
    a = Automation(id="x", ebook="e", steps=["build"])
    outcome = run_automation_steps(tmp_path, a, lambda m: None)
    assert outcome == "failure"


# ---------- AutomationScheduler.run_now / _tick enqueue qua JobQueue ----------


def test_run_now_enqueues_job_in_both_category(tmp_path, monkeypatch):
    from app import scheduler as scheduler_mod

    path = tmp_path / "automations.yaml"
    a = add_automation(path, "e", ["build"])
    monkeypatch.setattr(scheduler_mod, "load_config", lambda p, slug: object())
    monkeypatch.setitem(scheduler_mod._STEP_FN, "build", lambda cfg, log: None)

    queue = JobQueue(workers={"crawl": 1, "translate": 1})
    sched = AutomationScheduler(path, tmp_path, queue, poll_seconds=1000)
    job_id = sched.run_now(a.id)
    assert job_id is not None

    import time

    deadline = time.time() + 3
    while time.time() < deadline:
        history = queue.snapshot()["history"]
        if any(j["id"] == job_id and j["state"] == "done" for j in history):
            break
        time.sleep(0.05)
    history = queue.snapshot()["history"]
    job = next(j for j in history if j["id"] == job_id)
    assert job["category"] == "both"
    assert job["state"] == "done"

    loaded = load_automations(path)
    assert loaded[a.id].last_run_outcome == "success"


def test_run_now_returns_none_for_unknown_id(tmp_path):
    queue = JobQueue(workers={"crawl": 1, "translate": 1})
    sched = AutomationScheduler(tmp_path / "automations.yaml", tmp_path, queue, poll_seconds=1000)
    assert sched.run_now("does-not-exist") is None
