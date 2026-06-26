"""Daemon thread chạy automation theo lịch, đẩy qua JobQueue (xem spec
automation-scheduling). Mỗi automation = 1 chuỗi step tuần tự (fetch-toc →
crawl-new → translate-pending → build), enqueue thành 1 job "both" duy nhất
để được JobQueue cấp quyền độc quyền crawl+dịch (an toàn vì step có thể đụng
cả 2 lẫn build).
"""
from __future__ import annotations

import threading
from datetime import datetime

from novel2epub.automation import Automation, load_automations, update_automation
from novel2epub.config import load_config
from novel2epub.pipeline import step_build, step_crawl_selected, step_fetch_toc, step_translate_selected

from .logging_config import logger
from .queue import JobQueue

_STEP_FN = {
    "fetch-toc": lambda cfg, log: step_fetch_toc(cfg, log),
    "crawl-new": lambda cfg, log: step_crawl_selected(cfg, log),
    "translate-pending": lambda cfg, log: step_translate_selected(cfg, log),
    "build": lambda cfg, log: step_build(cfg, log),
}


def _is_due(automation: Automation, now: datetime) -> bool:
    if not automation.enabled or automation.schedule == "manual":
        return False
    if not automation.schedule.startswith("daily@"):
        return False
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


def run_automation_steps(workspace_path, automation: Automation, log) -> str:
    """Chạy tuần tự các step của automation, dừng ở step lỗi đầu tiên.

    Trả "success" (mọi step xong), "failure" (step đầu tiên đã lỗi), hoặc
    "partial" (một số step xong trước khi gặp lỗi)."""
    cfg = load_config(workspace_path, automation.ebook)
    succeeded = 0
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
            break
    if succeeded == 0:
        return "failure"
    if succeeded == len(automation.steps):
        return "success"
    return "partial"


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
            if _is_due(automation, now):
                self.run_now(automation.id)

    def run_now(self, automation_id: str) -> str | None:
        automations = load_automations(self.automations_path)
        automation = automations.get(automation_id)
        if automation is None:
            return None

        def _target(log):
            outcome = run_automation_steps(self.workspace_path, automation, log)
            update_automation(
                self.automations_path,
                automation_id,
                {"last_run_at": datetime.now().isoformat(), "last_run_outcome": outcome},
            )

        job = self.queue.enqueue(
            "both", "automation", _target, label=f"automation:{automation.ebook}", ebook=automation.ebook
        )
        return job.id
