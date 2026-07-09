"""Daemon thread chạy automation theo lịch, đẩy qua JobQueue (xem spec
automation-scheduling). Mỗi automation = 1 chuỗi step tuần tự (fetch-toc →
crawl-new → translate-pending → build), enqueue thành 1 job "both" duy nhất
để được JobQueue cấp quyền độc quyền crawl+dịch (an toàn vì step có thể đụng
cả 2 lẫn build).
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta

from novel2epub.automation import Automation, load_automations, update_automation
from novel2epub.config import load_config
from novel2epub.pipeline import (
    step_build,
    step_cleanup_han_selected,
    step_crawl_selected,
    step_fetch_toc,
    step_translate_selected,
)
from novel2epub.storage import Storage

from .logging_config import logger
from .queue import JobQueue

_STEP_FN = {
    "fetch-toc": lambda cfg, log: step_fetch_toc(cfg, log),
    "crawl-new": lambda cfg, log: step_crawl_selected(cfg, log),
    "translate-pending": lambda cfg, log: step_translate_selected(cfg, log),
    "cleanup-han": lambda cfg, log: step_cleanup_han_selected(cfg, log),
    "build": lambda cfg, log: step_build(cfg, log),
}

_DEFAULT_CONTINUOUS_COOLDOWN_MINUTES = 30


def _is_due_daily(automation: Automation, now: datetime) -> bool:
    hhmm = automation.schedule.split("@", 1)[1]
    try:
        hh, mm = (int(x) for x in hhmm.split(":"))
    except ValueError:
        return False
    scheduled_today = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if now < scheduled_today:
        return False
    if automation.last_run_at:
        try:
            last_run = datetime.fromisoformat(automation.last_run_at)
        except ValueError:
            last_run = None
        if last_run is not None and last_run.date() == now.date():
            return False
    return True


def _is_due_continuous(automation: Automation, now: datetime) -> bool:
    cooldown = _DEFAULT_CONTINUOUS_COOLDOWN_MINUTES
    if "@" in automation.schedule:
        raw = automation.schedule.split("@", 1)[1]
        try:
            cooldown = int(raw)
        except ValueError:
            cooldown = _DEFAULT_CONTINUOUS_COOLDOWN_MINUTES
    if not automation.last_run_at:
        return True
    try:
        last_run = datetime.fromisoformat(automation.last_run_at)
    except ValueError:
        return True
    return now - last_run >= timedelta(minutes=cooldown)


def _is_due(automation: Automation, now: datetime) -> bool:
    if not automation.enabled or automation.schedule == "manual":
        return False
    if automation.schedule.startswith("continuous"):
        return _is_due_continuous(automation, now)
    if automation.schedule.startswith("daily@"):
        return _is_due_daily(automation, now)
    return False


def _count_progress(cfg) -> dict:
    """Snapshot số chương đã cào/dịch/sửa Hán hiện có — dùng để tính delta trước/sau khi
    chạy chuỗi step (step_* không trả về số liệu, nên phải tự đo bằng Storage)."""
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        return {"chapters_total": 0, "raw": 0, "translated": 0, "han_fixed": 0}
    raw = sum(1 for ch in manifest.chapters if storage.has_raw(ch))
    translated = sum(1 for ch in manifest.chapters if storage.has_translated(ch))
    han_fixed = sum(
        storage.read_meta(ch).get("han_cleanup", {}).get("fixed_count", 0)
        for ch in manifest.chapters
        if storage.has_meta(ch)
    )
    return {
        "chapters_total": len(manifest.chapters),
        "raw": raw,
        "translated": translated,
        "han_fixed": han_fixed,
    }


def run_automation_steps(workspace_path, automation: Automation, log) -> dict:
    """Chạy tuần tự các step của automation, dừng ở step lỗi đầu tiên.

    Trả dict {"outcome", "error", "stats"}:
      - outcome: "success" (mọi step xong), "failure" (step đầu tiên đã lỗi),
        hoặc "partial" (một số step xong trước khi gặp lỗi).
      - error: "{step}: {lỗi}" của step đầu tiên gặp lỗi, "" nếu không có lỗi.
      - stats: delta số chương cào/dịch/sửa Hán trước-sau (đo bằng Storage vì
        các step_* không tự trả về số liệu)."""
    cfg = load_config(workspace_path, automation.ebook)
    before = _count_progress(cfg)
    succeeded = 0
    error = ""
    for step in automation.steps:
        fn = _STEP_FN.get(step)
        if fn is None:
            log(f"[automation] step không hợp lệ: {step!r}, bỏ qua.")
            continue
        try:
            fn(cfg, log)
            succeeded += 1
        except Exception as e:  # noqa: BLE001 - log lỗi, dừng chuỗi step
            log(f"[automation] ! Lỗi ở step {step!r}: {e}")
            error = f"{step}: {e}"
            break
    after = _count_progress(cfg)
    stats = {
        "chapters_total": after["chapters_total"],
        "crawled": after["raw"] - before["raw"],
        "translated": after["translated"] - before["translated"],
        "han_fixed": after["han_fixed"] - before["han_fixed"],
    }
    if succeeded == 0:
        outcome = "failure"
    elif succeeded == len(automation.steps):
        outcome = "success"
    else:
        outcome = "partial"
    return {"outcome": outcome, "error": error, "stats": stats}


class AutomationScheduler:
    """Poll automation tới hạn mỗi `poll_seconds` giây trong 1 daemon thread."""

    def __init__(self, automations_path, workspace_path, queue: JobQueue, poll_seconds: float = 30.0):
        self.automations_path = automations_path
        self.workspace_path = workspace_path
        self.queue = queue
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:  # noqa: BLE001 - 1 vòng lỗi không được giết hẳn scheduler
                logger.exception("Lỗi vòng poll automation")
            self._stop.wait(self.poll_seconds)

    def _tick(self) -> None:
        now = datetime.now()
        for automation in load_automations(self.automations_path).values():
            if not _is_due(automation, now):
                continue
            if self.queue.has_pending_step("automation", automation.ebook):
                continue
            self.run_now(automation.id)

    def run_now(self, automation_id: str) -> str | None:
        automations = load_automations(self.automations_path)
        automation = automations.get(automation_id)
        if automation is None:
            return None

        def _target(log):
            result = run_automation_steps(self.workspace_path, automation, log)
            update_automation(
                self.automations_path,
                automation_id,
                {
                    "last_run_at": datetime.now().isoformat(),
                    "last_run_outcome": result["outcome"],
                    "last_run_error": result["error"],
                    "last_run_stats": result["stats"],
                },
            )

        job = self.queue.enqueue(
            "both", "automation", _target, label=f"automation:{automation.ebook}", ebook=automation.ebook
        )
        return job.id
