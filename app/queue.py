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
DEFAULT_HISTORY_LIMIT = 5000


@dataclass
class Job:
    id: str
    category: str  # "crawl" | "translate" | "both"
    step: str
    label: str = ""
    ebook: str = ""
    lock_ebook: bool = True  # False = cho phép nhiều job song song cùng ebook
    chapter_indexes: list = field(default_factory=list)  # Chapters job này xử lý
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
            "lock_ebook": self.lock_ebook,
            "chapter_indexes": self.chapter_indexes,
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
        # Allow 0 workers (paused state)
        self._workers = {c: max(0, int((workers or {}).get(c, 1))) for c in CATEGORIES}
        self._extra_workers: dict[str, int] = {c: 0 for c in CATEGORIES}
        # Số thread thực tế đã spawn cho mỗi category (tránh spawn thừa khi toggle pause)
        self._spawned: dict[str, int] = {c: 0 for c in CATEGORIES}
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
            initial = max(1, self._workers[cat])
            for _ in range(initial):
                self._spawn_worker(cat)
            self._spawned[cat] = initial
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
        lock_ebook: bool = True,
        chapter_indexes: list | None = None,
    ) -> Job:
        if category not in (*CATEGORIES, "both"):
            raise ValueError(f"category không hợp lệ: {category!r}")
        job = Job(
            id=str(uuid.uuid4()),
            category=category,
            step=step,
            label=label,
            target=target,
            ebook=ebook,
            lock_ebook=lock_ebook,
            chapter_indexes=chapter_indexes or [],
        )
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
                try:
                    q.remove(job)
                except ValueError:
                    pass
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
        return self.enqueue(
            job.category, job.step, job.target,
            label=job.label, ebook=job.ebook,
            lock_ebook=job.lock_ebook, chapter_indexes=list(job.chapter_indexes),
        )

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

    def prioritize(self, job_id: str) -> bool:
        """Đưa job pending lên đầu hàng đợi."""
        with self._cv:
            job = self._jobs.get(job_id)
            if job is None or job.state != "pending":
                return False
            q = self._pending[job.category]
            items = list(q)
            if job not in items:
                return False
            items.remove(job)
            items.insert(0, job)
            q.clear()
            q.extend(items)
            self._cv.notify_all()
        return True

    def delete(self, job_id: str) -> bool:
        """Xóa job khỏi lịch sử (hoặc hàng đợi pending). Không xóa job đang chạy."""
        with self._cv:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if job.state == "running":
                return False  # Phải cancel trước
            if job.state == "pending":
                q = self._pending[job.category]
                try:
                    q.remove(job)
                except ValueError:
                    pass
                job.state = "cancelled"
                job.ended_at = time.time()
            # Xóa khỏi history
            try:
                self._history.remove(job)
            except ValueError:
                pass
            self._jobs.pop(job_id, None)
            self._save_history()
            self._cv.notify_all()
        return True

    def update_workers(self, category: str, count: int) -> int:
        """Cập nhật số worker của category tại chỗ. 0 = tạm dừng."""
        if category not in CATEGORIES:
            raise ValueError(f"category không hợp lệ: {category!r}")
        count = max(0, int(count))
        with self._cv:
            self._workers[category] = count
            # Chỉ spawn thread mới nếu count vượt quá số thread đã spawn
            # (tránh tích lũy thread khi toggle pause nhiều lần)
            if count > self._spawned[category]:
                delta = count - self._spawned[category]
                for _ in range(delta):
                    self._spawn_worker(category)
                self._spawned[category] = count
            self._cv.notify_all()
        return count

    def start_now(self, job_id: str) -> bool:
        """Đưa job lên đầu hàng đợi + đảm bảo có worker chạy ngay."""
        with self._cv:
            job = self._jobs.get(job_id)
            if job is None or job.state != "pending":
                return False
            category = job.category
            q = self._pending[category]
            items = list(q)
            if job not in items:
                return False
            # Đưa lên đầu
            items.remove(job)
            items.insert(0, job)
            q.clear()
            q.extend(items)
            # Nếu category thông thường, đảm bảo có ít nhất 1 slot worker trống.
            # So sánh với base_workers (không tính extra) để tránh thiếu worker
            # khi start_now được gọi nhiều lần trong lúc queue đang paused.
            if category != "both":
                extra = self._extra_workers.get(category, 0)
                base = self._workers[category] - extra
                need_extra = base <= 0 or self._active[category] >= self._workers[category]
                if need_extra:
                    new_extra = extra + 1
                    self._extra_workers[category] = new_extra
                    # Bump workers to allow all extra workers to run in parallel
                    self._workers[category] = self._active[category] + new_extra
                    self._spawn_worker(category)
                    # Không cập nhật _spawned vì đây là thread tạm thời
            self._cv.notify_all()
        return True

    def bulk_cancel(self, job_ids: list[str]) -> int:
        return sum(1 for jid in job_ids if self.cancel(jid))

    def bulk_delete(self, job_ids: list[str]) -> int:
        return sum(1 for jid in job_ids if self.delete(jid))

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
        # Scan queue for first runnable job (skip ebook-locked jobs)
        ebook_locks = self._ebook_locks.get(category, set())
        for candidate in self._pending[category]:
            if not candidate.lock_ebook or not candidate.ebook or candidate.ebook not in ebook_locks:
                return candidate
        return None

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
                # Dequeue (may not be at front if ebook-locking skipped jobs)
                if category == "both":
                    self._pending[category].popleft()
                else:
                    try:
                        self._pending[category].remove(job)
                    except ValueError:
                        pass
                if category == "both":
                    self._both_active = True
                    self._both_waiting = False
                else:
                    self._active[category] += 1
                if job.ebook and job.lock_ebook:
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
                if job.ebook and job.lock_ebook:
                    self._ebook_locks[category].discard(job.ebook)
                self._push_history(job)
                # Worker tạm thời (start_now): thoát sau 1 job để restore worker count
                if category != "both" and self._extra_workers.get(category, 0) > 0:
                    self._extra_workers[category] -= 1
                    self._workers[category] = max(0, self._workers[category] - 1)
                    self._cv.notify_all()
                    return
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
                lock_ebook=item.get("lock_ebook", True),
                chapter_indexes=item.get("chapter_indexes", []),
            )
            job.state = item.get("state", "done")
            job.enqueued_at = item.get("enqueued_at") or time.time()
            job.started_at = item.get("started_at")
            job.ended_at = item.get("ended_at")
            job.error = item.get("error", "")
            self._history.appendleft(job)
            self._jobs[job.id] = job
