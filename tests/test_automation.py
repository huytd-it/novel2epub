"""Automation model (persist) + scheduler (due-check, chạy chuỗi step, enqueue
qua JobQueue) — xem spec automation-scheduling."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.queue import JobQueue
from app.scheduler import AutomationScheduler, _is_due, run_automation_steps
from novel2epub.automation import Automation, add_automation, load_automations, remove_automation, update_automation


def test_add_and_load_automation_roundtrip(tmp_path):
    path = tmp_path / "automations.yaml"
    a = add_automation(path, "myebook", ["fetch-toc", "build"], schedule="0 3 * * *")
    loaded = load_automations(path)
    assert a.id in loaded
    assert loaded[a.id].ebook == "myebook"
    assert loaded[a.id].steps == ["fetch-toc", "build"]
    assert loaded[a.id].schedule == "0 3 * * *"
    assert loaded[a.id].enabled is True
    assert loaded[a.id].crawl_workers == 4
    assert loaded[a.id].translate_workers == 4


def test_update_automation_persists_changes(tmp_path):
    path = tmp_path / "automations.yaml"
    a = add_automation(path, "myebook", ["build"])
    update_automation(path, a.id, {"last_run_at": "2024-01-01T00:00:00", "last_run_outcome": "success"})
    loaded = load_automations(path)
    assert loaded[a.id].last_run_at == "2024-01-01T00:00:00"
    assert loaded[a.id].last_run_outcome == "success"


def test_automation_roundtrip_includes_error_and_stats_fields(tmp_path):
    path = tmp_path / "automations.yaml"
    a = add_automation(path, "myebook", ["build"])
    assert a.last_run_error == ""
    assert a.last_run_stats == {}

    stats = {"chapters_total": 10, "crawled": 3, "translated": 2, "han_fixed": 1}
    update_automation(path, a.id, {"last_run_error": "build: boom", "last_run_stats": stats})
    loaded = load_automations(path)
    assert loaded[a.id].last_run_error == "build: boom"
    assert loaded[a.id].last_run_stats == stats


def test_add_automation_sets_created_at(tmp_path):
    path = tmp_path / "automations.yaml"
    a = add_automation(path, "myebook", ["build"])
    assert a.created_at != ""
    loaded = load_automations(path)
    assert loaded[a.id].created_at == a.created_at


def test_remove_automation(tmp_path):
    path = tmp_path / "automations.yaml"
    a = add_automation(path, "myebook", ["build"])
    remove_automation(path, a.id)
    assert load_automations(path) == {}


# ---------- _is_due (cron) ----------

T0 = datetime(2026, 7, 16, 12, 0, 0)


def test_manual_schedule_never_due():
    a = Automation(id="x", ebook="e", schedule="manual", created_at=T0.isoformat())
    assert _is_due(a, T0 + timedelta(days=1)) is False


def test_disabled_automation_never_due():
    a = Automation(id="x", ebook="e", schedule="*/30 * * * *", enabled=False,
                   created_at=T0.isoformat())
    assert _is_due(a, T0 + timedelta(days=1)) is False


def test_cron_due_after_next_mark_since_last_run():
    a = Automation(id="x", ebook="e", schedule="*/30 * * * *", last_run_at=T0.isoformat())
    assert _is_due(a, T0 + timedelta(minutes=29)) is False
    assert _is_due(a, T0 + timedelta(minutes=30)) is True


def test_cron_daily_equivalent():
    a = Automation(id="x", ebook="e", schedule="0 9 * * *",
                   last_run_at=datetime(2026, 7, 16, 9, 0, 5).isoformat())
    assert _is_due(a, datetime(2026, 7, 16, 23, 0)) is False   # mốc kế = 9h mai
    assert _is_due(a, datetime(2026, 7, 17, 9, 0)) is True


def test_cron_missed_marks_catch_up_once():
    # lỡ nhiều mốc (máy tắt 3 ngày) → đến hạn ngay; sau khi chạy (last_run_at
    # = giờ xong) thì mốc kế mới lại là tương lai → chỉ bù 1 lần
    a = Automation(id="x", ebook="e", schedule="*/30 * * * *",
                   last_run_at=(T0 - timedelta(days=3)).isoformat())
    assert _is_due(a, T0) is True
    a.last_run_at = T0.isoformat()
    assert _is_due(a, T0 + timedelta(minutes=5)) is False


def test_never_run_uses_created_at_as_base():
    a = Automation(id="x", ebook="e", schedule="*/30 * * * *", created_at=T0.isoformat())
    assert _is_due(a, T0 + timedelta(minutes=5)) is False
    assert _is_due(a, T0 + timedelta(minutes=30)) is True


def test_never_run_without_created_at_is_due():
    # hàng tiền-migration (không created_at, chưa chạy lần nào) → coi như đến hạn
    a = Automation(id="x", ebook="e", schedule="*/30 * * * *")
    assert _is_due(a, T0) is True


def test_is_due_raises_on_garbage_cron():
    import pytest

    a = Automation(id="x", ebook="e", schedule="not a cron", created_at=T0.isoformat())
    with pytest.raises(Exception):
        _is_due(a, T0)


def test_tick_survives_one_garbage_automation(tmp_path, monkeypatch):
    # 1 automation dữ liệu rác không được chặn các automation sau trong cùng
    # vòng poll. Lưu ý: schedule rác đã bị load_automations migrate → "manual"
    # nên phải dùng last_run_at rác (migration không đụng) để ép exception
    # trong _is_due (datetime.fromisoformat nổ ValueError).
    import json

    from novel2epub.db import get_thread_connection

    path = tmp_path / "automations.yaml"
    conn = get_thread_connection(path)
    with conn:
        for aid, last_run in [("bad", "không-phải-ISO"), ("good", (T0 - timedelta(hours=2)).isoformat())]:
            conn.execute(
                "INSERT INTO automations (id, ebook, steps_json, schedule, enabled,"
                " last_run_at, last_run_outcome, last_run_error, last_run_stats_json, created_at)"
                " VALUES (?, ?, ?, '*/30 * * * *', 1, ?, '', '', '{}', ?)",
                (aid, f"ebook-{aid}", json.dumps(["build"]), last_run, T0.isoformat()),
            )
    queue = JobQueue(workers={"crawl": 1, "translate": 1})
    sched = AutomationScheduler(path, tmp_path, queue, poll_seconds=1000)
    ran = []
    monkeypatch.setattr(sched, "run_now", lambda aid: ran.append(aid))
    sched._tick()
    assert ran == ["good"]


# ---------- run_automation_steps ----------


def _stub_progress(**overrides):
    base = {"chapters_total": 0, "raw": 0, "translated": 0, "han_fixed": 0}
    base.update(overrides)
    return base


def test_cleanup_han_is_a_valid_step_mapped_in_step_fn():
    from app import scheduler as scheduler_mod

    assert "cleanup-han" in scheduler_mod._STEP_FN


def test_run_automation_steps_invokes_cleanup_han_step(tmp_path, monkeypatch):
    from app import scheduler as scheduler_mod

    calls = []
    monkeypatch.setattr(scheduler_mod, "load_config", lambda path, slug: object())
    monkeypatch.setattr(scheduler_mod, "_count_progress", lambda cfg: _stub_progress())
    monkeypatch.setitem(scheduler_mod._STEP_FN, "cleanup-han", lambda cfg, log: calls.append("cleanup-han"))
    monkeypatch.setitem(scheduler_mod._STEP_FN, "build", lambda cfg, log: calls.append("build"))

    a = Automation(id="x", ebook="e", steps=["cleanup-han", "build"])
    result = run_automation_steps(tmp_path, a, lambda m: None)
    assert result["outcome"] == "success"
    assert calls == ["cleanup-han", "build"]


def test_run_automation_steps_all_succeed(tmp_path, monkeypatch):
    from app import scheduler as scheduler_mod

    calls = []
    monkeypatch.setattr(scheduler_mod, "load_config", lambda path, slug: object())
    monkeypatch.setattr(scheduler_mod, "_count_progress", lambda cfg: _stub_progress())
    monkeypatch.setitem(scheduler_mod._STEP_FN, "fetch-toc", lambda cfg, log: calls.append("fetch-toc"))
    monkeypatch.setitem(scheduler_mod._STEP_FN, "build", lambda cfg, log: calls.append("build"))

    a = Automation(id="x", ebook="e", steps=["fetch-toc", "build"])
    result = run_automation_steps(tmp_path, a, lambda m: None)
    assert result["outcome"] == "success"
    assert result["error"] == ""
    assert calls == ["fetch-toc", "build"]


def test_run_automation_steps_applies_worker_options(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app import scheduler as scheduler_mod

    cfg = SimpleNamespace(
        crawl=SimpleNamespace(max_workers=1),
        translate=SimpleNamespace(max_workers=1),
    )
    seen = []
    monkeypatch.setattr(scheduler_mod, "load_config", lambda path, slug: cfg)
    monkeypatch.setattr(scheduler_mod, "_count_progress", lambda value: _stub_progress())
    monkeypatch.setitem(
        scheduler_mod._STEP_FN, "crawl-new",
        lambda value, log: seen.append(("crawl", value.crawl.max_workers)),
    )
    monkeypatch.setitem(
        scheduler_mod._STEP_FN, "translate-pending",
        lambda value, log: seen.append(("translate", value.translate.max_workers)),
    )

    automation = Automation(
        id="x", ebook="e", steps=["crawl-new", "translate-pending"],
        crawl_workers=6, translate_workers=8,
    )
    result = run_automation_steps(tmp_path, automation, lambda message: None)

    assert result["outcome"] == "success"
    assert seen == [("crawl", 6), ("translate", 8)]


def test_run_automation_steps_partial_on_failure(monkeypatch, tmp_path):
    from app import scheduler as scheduler_mod

    monkeypatch.setattr(scheduler_mod, "load_config", lambda path, slug: object())
    monkeypatch.setattr(scheduler_mod, "_count_progress", lambda cfg: _stub_progress())

    def _boom(cfg, log):
        raise RuntimeError("lỗi crawl")

    monkeypatch.setitem(scheduler_mod._STEP_FN, "fetch-toc", lambda cfg, log: None)
    monkeypatch.setitem(scheduler_mod._STEP_FN, "crawl-new", _boom)
    monkeypatch.setitem(scheduler_mod._STEP_FN, "build", lambda cfg, log: None)

    a = Automation(id="x", ebook="e", steps=["fetch-toc", "crawl-new", "build"])
    result = run_automation_steps(tmp_path, a, lambda m: None)
    assert result["outcome"] == "partial"
    assert result["error"] == "crawl-new: lỗi crawl"


def test_run_automation_steps_failure_when_first_step_fails(monkeypatch, tmp_path):
    from app import scheduler as scheduler_mod

    monkeypatch.setattr(scheduler_mod, "load_config", lambda path, slug: object())
    monkeypatch.setattr(scheduler_mod, "_count_progress", lambda cfg: _stub_progress())

    def _boom(cfg, log):
        raise RuntimeError("lỗi")

    monkeypatch.setitem(scheduler_mod._STEP_FN, "build", _boom)
    a = Automation(id="x", ebook="e", steps=["build"])
    result = run_automation_steps(tmp_path, a, lambda m: None)
    assert result["outcome"] == "failure"
    assert result["error"] == "build: lỗi"


def test_run_automation_steps_computes_stats_delta(monkeypatch, tmp_path):
    from app import scheduler as scheduler_mod

    monkeypatch.setattr(scheduler_mod, "load_config", lambda path, slug: object())
    progress_calls = [
        _stub_progress(chapters_total=10, raw=2, translated=1, han_fixed=0),
        _stub_progress(chapters_total=10, raw=5, translated=4, han_fixed=3),
    ]
    monkeypatch.setattr(scheduler_mod, "_count_progress", lambda cfg: progress_calls.pop(0))
    monkeypatch.setitem(scheduler_mod._STEP_FN, "build", lambda cfg, log: None)

    a = Automation(id="x", ebook="e", steps=["build"])
    result = run_automation_steps(tmp_path, a, lambda m: None)
    assert result["outcome"] == "success"
    assert result["stats"] == {"chapters_total": 10, "crawled": 3, "translated": 3, "han_fixed": 3}


# ---------- AutomationScheduler.run_now / _tick enqueue qua JobQueue ----------


def test_run_now_enqueues_job_in_both_category(tmp_path, monkeypatch):
    from app import scheduler as scheduler_mod

    path = tmp_path / "automations.yaml"
    a = add_automation(path, "e", ["build"])
    monkeypatch.setattr(scheduler_mod, "load_config", lambda p, slug: object())
    monkeypatch.setattr(scheduler_mod, "_count_progress", lambda cfg: _stub_progress())
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


# ---------- migrate_schedule ----------


def test_migrate_schedule_mapping():
    from novel2epub.automation import migrate_schedule

    assert migrate_schedule("daily@03:00") == "0 3 * * *"
    assert migrate_schedule("daily@23:59") == "59 23 * * *"
    assert migrate_schedule("continuous") == "*/30 * * * *"
    assert migrate_schedule("continuous@15") == "*/15 * * * *"
    assert migrate_schedule("continuous@59") == "*/59 * * * *"
    assert migrate_schedule("continuous@60") == "0 */1 * * *"
    assert migrate_schedule("continuous@120") == "0 */2 * * *"
    assert migrate_schedule("continuous@5000") == "0 */23 * * *"  # kẹp 23h


def test_migrate_schedule_garbage_falls_back_to_manual():
    from novel2epub.automation import migrate_schedule

    assert migrate_schedule("daily@25:00") == "manual"
    assert migrate_schedule("daily@10:99") == "manual"
    assert migrate_schedule("continuous@0") == "manual"
    assert migrate_schedule("continuous@-5") == "manual"
    assert migrate_schedule("contineous@30") == "manual"
    assert migrate_schedule("Daily@03:00") == "manual"
    assert migrate_schedule("") == "manual"


def test_migrate_schedule_keeps_valid_values():
    from novel2epub.automation import migrate_schedule

    assert migrate_schedule("manual") == "manual"
    assert migrate_schedule("*/30 * * * *") == "*/30 * * * *"


def test_load_automations_migrates_legacy_schedule_and_backfills_created_at(tmp_path):
    import json

    from novel2epub.db import get_thread_connection

    path = tmp_path / "automations.yaml"
    conn = get_thread_connection(path)
    with conn:
        conn.execute(
            "INSERT INTO automations (id, ebook, steps_json, schedule, enabled,"
            " last_run_at, last_run_outcome, last_run_error, last_run_stats_json, created_at)"
            " VALUES (?, ?, ?, ?, 1, '', '', '', '{}', '')",
            ("legacy-id", "e", json.dumps(["build"]), "continuous@30"),
        )
    loaded = load_automations(path)
    assert loaded["legacy-id"].schedule == "*/30 * * * *"
    assert loaded["legacy-id"].created_at != ""
    # đã ghi lại DB — load lần 2 không đổi gì thêm (idempotent)
    row = conn.execute("SELECT schedule, created_at FROM automations WHERE id='legacy-id'").fetchone()
    assert row["schedule"] == "*/30 * * * *"
    persisted_created = row["created_at"]
    loaded2 = load_automations(path)
    assert loaded2["legacy-id"].schedule == "*/30 * * * *"
    assert loaded2["legacy-id"].created_at == persisted_created


# ---------- validate_schedule ----------


def test_validate_schedule_accepts_manual_and_cron():
    from novel2epub.automation import validate_schedule

    assert validate_schedule("manual") is True
    assert validate_schedule("*/30 * * * *") is True
    assert validate_schedule("0 3 * * *") is True
    assert validate_schedule("0 3 * * 0") is True
    assert validate_schedule("0 0 3 * * *") is False
    assert validate_schedule("@daily") is False


def test_validate_schedule_rejects_legacy_and_garbage():
    from novel2epub.automation import validate_schedule

    assert validate_schedule("daily@03:00") is False
    assert validate_schedule("continuous@30") is False
    assert validate_schedule("61 * * * *") is False
    assert validate_schedule("abc") is False
    assert validate_schedule("") is False
    assert validate_schedule("Manual") is False
