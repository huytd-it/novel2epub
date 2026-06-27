"""Hàng đợi job FIFO theo category (crawl/translate) với N worker thread mỗi
category, chạy song song trong giới hạn cấu hình. Step "build"/"run" là job
"both" — chiếm quyền độc quyền trên cả 2 category (đợi crawl+translate rỗng
rồi mới chạy, chặn job crawl/translate mới bắt đầu trong lúc nó chạy).

`JobRunner` (app/job.py) giữ làm shim mỏng gọi vào đây để các route cũ không
phải đổi ngay (xem design.md D1/D2 của change pro-management-suite).
"""
from __future__ import annotations

import json
import threading
import time
import traceback
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .logging_config import logger

CATEGORIES = ("crawl", "translate")
DEFAULT_HISTORY_LIMIT = 200


@dataclass
class Job:
    id: str
    category: str  # "crawl" | "translate" | "both"
    step: str
    label: str = ""
    ebook: str = ""
    target: Callable[[Callable[[str], None]], object] | None = None
    state: str = "pending"  # pending|running|done|failed|cancelled
    enqueued_at: float = field(default_factory=time.time)
    started_at: float | None = None
    ended_at: float | None = None
    error: str = ""
    log: deque = field(default_factory=lambda: deque(maxlen=500))
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def to_dict(self, with_log: bool = False) -> dict:
        d = {
            "id": self.id,
            "category": self.category,
            "step": self.step,
            "label": self.label or self.step,
            "ebook": self.ebook,
            "state": self.state,
            "enqueued_at": self.enqueued_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "error": self.error,
            "cancelling": self.cancel_event.is_set(),
        }
        if with_log:
            d["log"] = list(self.log)
        return d


def _categories_for(category: str) -> tuple[str, ...]:
    return CATEGORIES if category == "both" else (category,)


class JobQueue:
    """FIFO job queue/category + N worker thread/category + lịch sử bounded."""

    def __init__(
        self,
        workers: dict[str, int] | None = None,
        history_path: str | Path | None = None,
        history_limit: int = DEFAULT_HISTORY_LIMIT,
    ):
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._workers = {c: max(1, int((workers or {}).get(c, 1))) for c in CATEGORIES}
        self._pending: dict[str, deque[Job]] = {c: deque() for c in (*CATEGORIES, "both")}
        self._running: dict[str, Job] = {}
        self._active: dict[str, int] = {c: 0 for c in CATEGORIES}
        self._both_active = False
        self._both_waiting = False
        self._ebook_locks: dict[str, set[str]] = {c: set() for c in (*CATEGORIES, "both")}
        self._history: deque[Job] = deque(maxlen=history_limit)
        self._jobs: dict[str, Job] = {}
        self._history_path = Path(history_path) if history_path else None
        self._load_history()
        self._threads: list[threading.Thread] = []
        for cat in CATEGORIES:
            for _ in range(self._workers[cat]):
                self._spawn_worker(cat)
        self._spawn_worker("both")

    def _spawn_worker(self, category: str) -> None:
        t = threading.Thread(target=self._worker_loop, args=(category,), daemon=True)
        t.start()
        self._threads.append(t)

    # ---------- public API ----------

    def enqueue(
        self,
        category: str,
        step: str,
        target: Callable[[Callable[[str], None]], object],
        *,
        label: str = "",
        ebook: str = "",
        cancel_event: threading.Event | None = None,
    ) -> Job:
        if category not in (*CATEGORIES, "both"):
            raise ValueError(f"category không hợp lệ: {category!r}")
        job = Job(id=str(uuid.uuid4()), category=category, step=step, label=label, target=target, ebook=ebook)
        if cancel_event is not None:
            job.cancel_event = cancel_event
        with self._cv:
            self._pending[category].append(job)
            self._jobs[job.id] = job
            self._cv.notify_all()
        return job

    def cancel(self, job_id: str) -> bool:
        with self._cv:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if job.state == "pending":
                q = self._pending[job.category]
                if job in q:
                    q.remove(job)
                job.state = "cancelled"
                job.ended_at = time.time()
                self._push_history(job)
                self._cv.notify_all()
                return True
            if job.state == "running":
                job.cancel_event.set()
                return True
            return False

    def retry(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None or job.target is None:
            return None
        return self.enqueue(job.category, job.step, job.target, label=job.label, ebook=job.ebook)

    def reorder(self, job_id: str, before_id: str | None) -> bool:
        with self._cv:
            job = self._jobs.get(job_id)
            if job is None or job.state != "pending":
                return False
            q = self._pending[job.category]
            if job not in q:
                return False
            items = list(q)
            items.remove(job)
            if before_id is None:
                items.append(job)
            else:
                idx = next((i for i, j in enumerate(items) if j.id == before_id), len(items))
                items.insert(idx, job)
            q.clear()
            q.extend(items)
            self._cv.notify_all()
            return True

    def snapshot(self) -> dict:
        with self._lock:
            running = [j.to_dict() for j in self._running.values()]
            pending = {cat: [j.to_dict() for j in q] for cat, q in self._pending.items()}
            history = [j.to_dict() for j in list(self._history)]
        return {
            "categories": list(CATEGORIES),
            "running": running,
            "pending": pending,
            "history": history,
            "workers": dict(self._workers),
        }

    def job_log(self, job_id: str) -> list[str] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return None if job is None else list(job.log)

    def logs_snapshot(self, limit: int = 30) -> dict:
        with self._lock:
            running = [j.to_dict(with_log=True) for j in self._running.values()]
            seen: set[str] = set()
            jobs_list: list[Job] = []
            for j in self._history:
                if j.id not in seen:
                    seen.add(j.id)
                    jobs_list.append(j)
            for q in self._pending.values():
                for j in q:
                    if j.id not in seen:
                        seen.add(j.id)
                        jobs_list.append(j)
            recent = [j.to_dict(with_log=True) for j in jobs_list[:limit]]
        return {"running": running, "recent": recent}

    # ----- shim cho JobRunner cũ (status theo "crawl"/"translate") -----

    def request_cancel_category(self, category: str) -> bool:
        with self._lock:
            running = [j for j in self._running.values() if category in _categories_for(j.category)]
            for j in running:
                j.cancel_event.set()
        return bool(running)

    def category_status(self, category: str) -> dict:
        with self._lock:
            running_jobs = [j for j in self._running.values() if category in _categories_for(j.category)]
            current = running_jobs[0] if running_jobs else None
            if current is None:
                current = next((j for j in self._history if category in _categories_for(j.category)), None)
            if current is None:
                return {"running": False, "step": "", "error": "", "log": [], "cancelling": False, "ebook_slug": "", "running_ebooks": []}
            return {
                "running": current.state == "running",
                "step": current.step,
                "error": current.error,
                "log": list(current.log),
                "cancelling": current.cancel_event.is_set(),
                "ebook_slug": current.ebook,
                "running_ebooks": [j.ebook for j in running_jobs if j.ebook],
            }

    # ---------- worker loop ----------

    def is_ebook_busy(self, category: str, ebook: str) -> bool:
        """Kiểm tra có job đang chạy cho ebook cụ thể trong category này không."""
        with self._lock:
            return any(
                j.ebook == ebook and category in _categories_for(j.category)
                for j in self._running.values()
            )

    def _can_start(self, category: str) -> Job | None:
        """Gọi khi đã giữ self._cv. Trả job kế tiếp có thể chạy ngay, hoặc None."""
        if category == "both":
            if not self._pending["both"]:
                return None
            if self._active["crawl"] or self._active["translate"] or self._both_active:
                return None
            return self._pending["both"][0]
        if self._both_active or self._both_waiting:
            return None
        if self._active[category] >= self._workers[category]:
            return None
        if not self._pending[category]:
            return None
        candidate = self._pending[category][0]
        if candidate.ebook and candidate.ebook in self._ebook_locks.get(category, set()):
            return None
        return candidate

    def _worker_loop(self, category: str) -> None:
        while True:
            with self._cv:
                if category == "both":
                    self._both_waiting = bool(self._pending["both"])
                job = self._can_start(category)
                while job is None:
                    self._cv.wait(timeout=1.0)
                    if category == "both":
                        self._both_waiting = bool(self._pending["both"])
                    job = self._can_start(category)
                self._pending[category].popleft()
                if category == "both":
                    self._both_active = True
                    self._both_waiting = False
                else:
                    self._active[category] += 1
                if job.ebook:
                    self._ebook_locks[category].add(job.ebook)
                job.state = "running"
                job.started_at = time.time()
                self._running[job.id] = job

            self._execute(job)

            with self._cv:
                self._running.pop(job.id, None)
                if category == "both":
                    self._both_active = False
                else:
                    self._active[category] -= 1
                if job.ebook:
                    self._ebook_locks[category].discard(job.ebook)
                self._push_history(job)
                self._cv.notify_all()

    def _execute(self, job: Job) -> None:
        def log_fn(msg: str) -> None:
            job.log.append(msg)
            logger.info(msg)

        logger.info("Bắt đầu job %r (%s)", job.step, job.id)
        try:
            assert job.target is not None
            job.target(log_fn)
            job.state = "cancelled" if job.cancel_event.is_set() else "done"
            logger.info("Job %r hoàn tất", job.step)
        except Exception as e:  # noqa: BLE001 - hiển thị lỗi bất kỳ lên UI
            job.state = "failed"
            job.error = str(e)
            log_fn(f"[lỗi] {e}")
            log_fn(traceback.format_exc())
            logger.exception("Job %r thất bại: %s", job.step, e)
        job.ended_at = time.time()

    def _push_history(self, job: Job) -> None:
        self._history.appendleft(job)
        self._save_history()

    # ---------- persistence ----------

    def _save_history(self) -> None:
        if self._history_path is None:
            return
        try:
            self._history_path.parent.mkdir(parents=True, exist_ok=True)
            data = [j.to_dict() for j in self._history]
            self._history_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            logger.exception("Không lưu được lịch sử job vào %s", self._history_path)

    def _load_history(self) -> None:
        if self._history_path is None or not self._history_path.exists():
            return
        try:
            data = json.loads(self._history_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for item in reversed(data):
            job = Job(
                id=item.get("id", str(uuid.uuid4())),
                category=item.get("category", "crawl"),
                step=item.get("step", ""),
                label=item.get("label", item.get("step", "")),
                ebook=item.get("ebook", ""),
            )
            job.state = item.get("state", "done")
            job.enqueued_at = item.get("enqueued_at") or time.time()
            job.started_at = item.get("started_at")
            job.ended_at = item.get("ended_at")
            job.error = item.get("error", "")
            self._history.appendleft(job)
            self._jobs[job.id] = job
