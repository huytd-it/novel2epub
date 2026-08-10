"""Hàng đợi job FIFO theo category (crawl/local-mt/ai-translate/ai-edit/build)
với N worker thread mỗi category, chạy song song trong giới hạn cấu hình. Step
"run" là job "both" — chiếm quyền độc quyền trên tất cả category (đợi tất cả
rỗng rồi mới chạy, chặn job mới bắt đầu trong lúc nó chạy).

Category cũ `translate` được giữ làm alias của `ai-translate` để job đã lưu
trong DB và route cũ (start_custom(... category="translate")) vẫn chạy nguyên
vẹn — xem `_CATEGORY_ALIASES`/`_normalize_category`.

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

from novel2epub.codes import ebook_identity
from novel2epub.db import get_thread_connection

from .logging_config import job_log_capture, logger

# Category vật lý. `translate` (category cũ) được ánh xạ về `ai-translate`.
CATEGORIES = ("crawl", "local-mt", "ai-translate", "ai-edit", "build")
# Alias cũ → category mới. Giữ job cũ (persisted trong DB) và route cũ hoạt động.
_CATEGORY_ALIASES = {"translate": "ai-translate"}
# Category "both" chiếm độc quyền mọi category (job `run`/`reindex`/automation).
DEFAULT_HISTORY_LIMIT = 5000

# Artifact mà mỗi category GHI vào. Hai job CÙNG EBOOK chỉ đụng nhau khi tập
# artifact họ ghi giao nhau (write-write). Đọc (raw, bản dịch) KHÔNG chặn nhau
# và KHÔNG chặn writer — ví dụ crawl (ghi raw) chạy song song ai-translate (đọc
# raw), còn hai ai-translate cùng ebook (cùng ghi `ai`) phải nối đuôi.
CATEGORY_WRITES: dict[str, frozenset[str]] = {
    "crawl": frozenset({"raw"}),
    "local-mt": frozenset({"local_mt"}),
    "ai-translate": frozenset({"ai"}),
    "ai-edit": frozenset({"edit"}),
    # Build đọc active workspace của cả hai nhánh; xem như giữ read-lock trên
    # chúng để writer không đổi input giữa snapshot và đóng gói EPUB.
    "build": frozenset({"build", "ai", "local_mt"}),
}


def _normalize_category(category: str) -> str:
    """Chuẩn hoá category; alias cũ (`translate`) → category mới (`ai-translate`)."""
    return _CATEGORY_ALIASES.get(category, category)


@dataclass
class Job:
    id: str
    category: str  # "crawl" | "local-mt" | "ai-translate" | "ai-edit" | "build" | "both"
    step: str
    label: str = ""
    ebook: str = ""
    ebook_code: str = ""
    lock_ebook: bool = True  # False = cho phép nhiều job song song cùng ebook
    chapter_indexes: list = field(default_factory=list)  # Chapters job này xử lý
    chapter_codes: list = field(default_factory=list)
    target: Callable[[Callable[[str], None]], object] | None = None
    state: str = "pending"  # pending|running|done|failed|cancelled
    enqueued_at: float = field(default_factory=time.time)
    started_at: float | None = None
    ended_at: float | None = None
    error: str = ""
    log: deque = field(default_factory=lambda: deque(maxlen=500))
    cancel_event: threading.Event = field(default_factory=threading.Event)
    # spec: {"kind": ..., "params": {...JSON-serializable...}} — cho phép tái
    # tạo lại `target` sau khi restart (xem JobQueue.register_kind/load_pending).
    spec: dict | None = None
    outcome: dict | None = None

    def to_dict(self, with_log: bool = False) -> dict:
        d = {
            "id": self.id,
            "category": self.category,
            "step": self.step,
            "label": self.label or self.step,
            "ebook": self.ebook,
            "ebook_code": self.ebook_code or self.ebook,
            "lock_ebook": self.lock_ebook,
            "chapter_indexes": self.chapter_indexes,
            "chapter_codes": self.chapter_codes,
            "state": self.state,
            "enqueued_at": self.enqueued_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "error": self.error,
            "cancelling": self.cancel_event.is_set(),
        }
        if self.spec and self.spec.get("kind") == "automation":
            d["automation_id"] = self.spec.get("params", {}).get("automation_id", "")
        if self.outcome is not None:
            d["outcome"] = self.outcome
        if with_log:
            d["log"] = list(self.log)
        return d


def _categories_for(category: str) -> tuple[str, ...]:
    category = _normalize_category(category)
    return CATEGORIES if category == "both" else (category,)


class JobQueue:
    """FIFO job queue/category + N worker thread/category + lịch sử bounded."""

    def __init__(
        self,
        workers: dict[str, int] | None = None,
        db_path: str | Path | None = None,
        history_limit: int = DEFAULT_HISTORY_LIMIT,
    ):
        # RLock (không phải Lock) để một helper vô tình gọi lồng nhau chỉ chậm
        # chứ không treo cứng cả queue — xem _save_pending/_save_history_job,
        # cả hai tự lấy lock nên từng bị deadlock khi gọi từ trong critical section.
        self._lock = threading.RLock()
        self._cv = threading.Condition(self._lock)
        # Allow 0 workers (paused state)
        norm_workers = {_normalize_category(k): v for k, v in (workers or {}).items()}
        self._workers = {c: max(0, int(norm_workers.get(c, 1))) for c in CATEGORIES}
        # Legacy alias (translate → ai-translate) được phản chiếu để route/test cũ
        # đọc `_workers["translate"]` vẫn ra đúng giá trị hiện hành.
        for alias, target in _CATEGORY_ALIASES.items():
            self._workers[alias] = self._workers.get(target, 1)
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
        self._retired_ebooks: set[str] = set()
        # SQLite db (bảng job_queue_history / job_queue_pending)
        self._db_path = Path(db_path) if db_path else None
        self._kind_factories: dict[str, Callable[[dict], Callable[[Callable[[str], None]], object]]] = {}
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
        spec: dict | None = None,
    ) -> Job:
        if _normalize_category(category) not in (*CATEGORIES, "both"):
            raise ValueError(f"category không hợp lệ: {category!r}")
        normalized = _normalize_category(category)
        job = Job(
            id=str(uuid.uuid4()),
            category=normalized,
            step=step,
            label=label,
            target=target,
            ebook=ebook,
            lock_ebook=lock_ebook,
            chapter_indexes=chapter_indexes or [],
            spec=spec,
        )
        if ebook and self._db_path:
            code, chapters = ebook_identity(get_thread_connection(self._db_path), ebook)
            job.ebook_code = code
            job.chapter_codes = [chapters.get(int(i), f"{code}-{int(i):04d}") for i in job.chapter_indexes]
        if cancel_event is not None:
            job.cancel_event = cancel_event
        with self._cv:
            if ebook and ebook in self._retired_ebooks:
                raise ValueError(f"ebook '{ebook}' đã bị xóa")
            self._pending[normalized].append(job)
            self._jobs[job.id] = job
            self._cv.notify_all()
        self._save_pending()
        return job

    def cancel(self, job_id: str) -> bool:
        retired: Job | None = None
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
                retired = job
                self._cv.notify_all()
                result = True
            elif job.state == "running":
                job.cancel_event.set()
                result = True
            else:
                result = False
        if retired is not None:
            self._save_history_job(retired)
        self._save_pending()
        return result

    def retry(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None or job.target is None:
            return None
        return self.enqueue(
            job.category, job.step, job.target,
            label=job.label, ebook=job.ebook,
            lock_ebook=job.lock_ebook, chapter_indexes=list(job.chapter_indexes),
            spec=job.spec,
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
        self._save_pending()
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
            self._cv.notify_all()
        self._save_pending()
        self._delete_history_row(job_id)
        return True

    def update_workers(self, category: str, count: int) -> int:
        """Cập nhật số worker của category tại chỗ. 0 = tạm dừng."""
        category = _normalize_category(category)
        if category not in CATEGORIES:
            raise ValueError(f"category không hợp lệ: {category!r}")
        count = max(0, int(count))
        with self._cv:
            self._workers[category] = count
            for alias, target in _CATEGORY_ALIASES.items():
                if target == category:
                    self._workers[alias] = count
            # Chỉ spawn thread mới nếu count vượt quá số thread đã spawn
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
            # khi start_now được gọi nhiều lần lúc queue đang paused.
            if category != "both":
                extra = self._extra_workers.get(category, 0)
                base = self._workers[category] - extra
                need_extra = base <= 0 or self._active[category] >= self._workers[category]
                if need_extra:
                    new_extra = extra + 1
                    self._extra_workers[category] = new_extra
                    # Bump workers để tất cả extra workers có thể chạy song song
                    self._workers[category] = self._active[category] + new_extra
                    self._spawn_worker(category)
            self._cv.notify_all()
        return True

    def bulk_cancel(self, job_ids: list[str]) -> int:
        return sum(1 for jid in job_ids if self.cancel(jid))

    def bulk_delete(self, job_ids: list[str]) -> int:
        return sum(1 for jid in job_ids if self.delete(jid))

    def bulk_clear_failed(self, category: str) -> int:
        """Xóa tất cả job failed trong 1 category. Trả số job đã xóa."""
        category = "all" if category == "all" else _normalize_category(category)
        with self._lock:
            failed_ids = [
                j.id for j in self._jobs.values()
                if j.state == "failed" and (category == "all" or j.category == category)
            ]
        return sum(1 for jid in failed_ids if self.delete(jid))

    def clear_history(self) -> int:
        """Xóa toàn bộ job đã kết thúc, giữ nguyên job pending/running."""
        with self._cv:
            history_ids = [job.id for job in self._history]
            if not history_ids:
                return 0
            self._history.clear()
            for job_id in history_ids:
                self._jobs.pop(job_id, None)
            self._cv.notify_all()
        self._delete_history_rows(history_ids)
        return len(history_ids)

    def bulk_retry_failed(self, category: str) -> int:
        """Retry tất cả job failed trong 1 category. Trả số job đã retry."""
        category = "all" if category == "all" else _normalize_category(category)
        with self._lock:
            failed = [
                j for j in self._jobs.values()
                if j.state == "failed" and (category == "all" or j.category == category)
            ]
        count = 0
        for job in failed:
            if self.retry(job.id):
                count += 1
        return count

    def snapshot(self) -> dict:
        with self._lock:
            running = [j.to_dict() for j in self._running.values()]
            pending = {cat: [j.to_dict() for j in q] for cat, q in self._pending.items()}
            history = [j.to_dict() for j in list(self._history)]
            for alias, target in _CATEGORY_ALIASES.items():
                pending[alias] = pending.get(target, [])
        return {
            "categories": list(CATEGORIES),
            "running": running,
            "pending": pending,
            "history": history,
            "workers": dict(self._workers),
            "locks": self.artifact_locks(),
        }

    def artifact_locks(self) -> list[dict]:
        """Artifact lock đang giữ: `[{category, ebook, artifacts}]` cho job đang
        chạy (write-set từ `CATEGORY_WRITES`). Đọc để UI hiển thị lý do chờ."""
        with self._lock:
            return [
                {
                    "category": j.category,
                    "step": j.step,
                    "ebook": j.ebook,
                    "artifacts": sorted(CATEGORY_WRITES.get(j.category, set())),
                }
                for j in self._running.values()
            ]

    def has_pending_step(self, step: str, ebook: str = "") -> bool:
        """Kiểm tra có job pending/running với step và ebook cho trước không."""
        with self._lock:
            for job in self._running.values():
                if job.step == step and (not ebook or job.ebook == ebook):
                    return True
            for q in self._pending.values():
                for job in q:
                    if job.step == step and (not ebook or job.ebook == ebook):
                        return True
        return False

    def has_active_ebook(self, ebook: str) -> bool:
        """Kiểm tra ebook có job đang chạy hoặc đang chờ hay không."""
        with self._lock:
            if any(job.ebook == ebook for job in self._running.values()):
                return True
            return any(
                job.ebook == ebook
                for pending in self._pending.values()
                for job in pending
            )

    def retire_ebook(self, ebook: str) -> bool:
        """Chặn job mới nếu ebook hiện không có job pending/running."""
        with self._lock:
            active = any(job.ebook == ebook for job in self._running.values()) or any(
                job.ebook == ebook
                for pending in self._pending.values()
                for job in pending
            )
            if active:
                return False
            self._retired_ebooks.add(ebook)
            return True

    def restore_ebook(self, ebook: str) -> None:
        """Cho phép enqueue lại slug sau khi tạo lại ebook hoặc xóa thất bại."""
        with self._lock:
            self._retired_ebooks.discard(ebook)

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

    # ----- shim cho JobRunner cũ (status theo "crawl"/"translate"/"build") -----

    def request_cancel_category(self, category: str) -> bool:
        category = _normalize_category(category)
        with self._lock:
            running = [j for j in self._running.values() if category in _categories_for(j.category)]
            for j in running:
                j.cancel_event.set()
        return bool(running)

    def category_status(self, category: str) -> dict:
        category = _normalize_category(category)
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
                "locks": [
                    {"category": j.category, "step": j.step, "ebook": j.ebook,
                     "artifacts": sorted(CATEGORY_WRITES.get(j.category, set()))}
                    for j in running_jobs
                ],
            }

    # ---------- worker loop ----------

    def is_ebook_busy(self, category: str, ebook: str) -> bool:
        """Kiểm tra có job đang chạy cho ebook cụ thể trong category này không."""
        category = _normalize_category(category)
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
            if any(self._active[c] for c in CATEGORIES) or self._both_active:
                return None
            return self._pending["both"][0]
        if self._active[category] >= self._workers[category]:
            return None
        if not self._pending[category]:
            return None
        # Build set of ebooks locked by running "both" jobs
        both_ebooks: set[str] = set()
        if self._both_active:
            both_ebooks = {
                j.ebook for j in self._running.values()
                if j.category == "both" and j.ebook
            }
        ebook_locks = self._ebook_locks.get(category, set())
        for candidate in self._pending[category]:
            # Chapter-scoped jobs dùng artifact lock bên dưới; ebook lock cũ chỉ
            # dành cho job không khai phạm vi (toàn ebook).
            whole_ebook = candidate.lock_ebook and not candidate.chapter_indexes
            cat_blocked = whole_ebook and candidate.ebook and candidate.ebook in ebook_locks
            both_blocked = candidate.lock_ebook and candidate.ebook and candidate.ebook in both_ebooks
            if cat_blocked or both_blocked:
                continue
            if self._artifact_conflict(candidate):
                continue
            return candidate
        return None

    def _artifact_conflict(self, job: Job) -> bool:
        """True khi writer đụng cùng `(ebook, chapter, artifact)`.

        `chapter_indexes=[]` nghĩa là phạm vi toàn ebook/không biết rõ nên xung
        đột với mọi writer cùng artifact. Hai job cùng artifact nhưng tập chapter
        rời nhau được chạy song song; Local MT và AI translate luôn ghi artifact
        khác nhau nên có thể cùng đọc raw.
        """
        if not job.ebook or not job.lock_ebook:
            return False
        writes = CATEGORY_WRITES.get(job.category, set())
        if not writes:
            return False
        job_indexes = {int(i) for i in job.chapter_indexes}
        for other in self._running.values():
            if other.ebook != job.ebook:
                continue
            if other.category == "both":
                return True
            if not other.lock_ebook:
                continue
            if not (writes & CATEGORY_WRITES.get(other.category, set())):
                continue
            other_indexes = {int(i) for i in other.chapter_indexes}
            if not job_indexes or not other_indexes or job_indexes & other_indexes:
                return True
        return False

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
            self._save_pending()

            final_state = self._execute(job)

            stop_worker = False
            with self._cv:
                # Ghi state/ended_at TRONG critical section, ngay trước
                # _push_history — snapshot() đọc cả hai dưới cùng self._lock nên
                # không thể quan sát "done nhưng chưa vào history" (race cũ).
                job.state = final_state
                job.ended_at = time.time()
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
                    stop_worker = True
                self._cv.notify_all()
            # Ghi SQLite LUÔN nằm ngoài self._cv: giữ lock trong lúc I/O sẽ chặn
            # snapshot()/category_status() và treo toàn bộ web UI.
            self._save_history_job(job)
            self._save_pending()
            if stop_worker:
                return

    def _execute(self, job: Job) -> str:
        """Chạy `job.target`, tích luỹ log/outcome/error. Trả TRẠNG THÁI cuối
        (done/failed/cancelled) — caller ghi `job.state` + `job.ended_at` TRONG
        critical section trước `_push_history` để `snapshot()` không bao giờ
        thấy trạng thái done nhưng chưa có trong history (race xem ghép
        test_start_now_job_finishes_without_deadlocking_queue)."""
        def log_fn(msg: str) -> None:
            job.log.append(msg)
            logger.info(msg)

        identity = ", ".join(job.chapter_codes) or job.ebook_code or job.ebook or "global"
        logger.info("Bắt đầu job %r [%s] (%s)", job.step, identity, job.id)
        try:
            assert job.target is not None
            # Log nội bộ của novel2epub.* (crawler, search...) chảy vào job.log
            # để hiện trên UI, thay vì biến mất.
            with job_log_capture(job.log):
                result = job.target(log_fn)
            if isinstance(result, dict):
                job.outcome = result
            logger.info("Job %r [%s] hoàn tất", job.step, identity)
            return "cancelled" if job.cancel_event.is_set() else "done"
        except Exception as e:  # noqa: BLE001 - hiển thị lỗi bất kỳ lên UI
            job.error = str(e)
            log_fn(f"[lỗi] {e}")
            log_fn(traceback.format_exc())
            logger.exception("Job %r [%s] thất bại: %s", job.step, identity, e)
            return "failed"

    def _push_history(self, job: Job) -> None:
        """Chỉ đụng deque trong bộ nhớ (gọi khi đang giữ self._cv). Caller phải
        gọi _save_history_job(job) SAU khi nhả lock để ghi xuống SQLite."""
        self._history.appendleft(job)

    # ---------- resume sau restart ----------

    def register_kind(
        self, kind: str, factory: Callable[[dict], Callable[[Callable[[str], None]], object]]
    ) -> None:
        """Đăng ký cách tái tạo `target(log)` từ `spec['params']` cho 1 loại
        job tuỳ biến. Phải gọi TRƯỚC load_pending()."""
        self._kind_factories[kind] = factory

    def load_pending(self) -> int:
        """Enqueue lại job pending/running đã lưu từ lần chạy trước."""
        if self._db_path is None:
            return 0
        conn = get_thread_connection(self._db_path)
        rows = conn.execute(
            "SELECT category, step, label, ebook, spec_json FROM job_queue_pending"
        ).fetchall()
        restored = 0
        for row in rows:
            try:
                spec = json.loads(row["spec_json"] or "{}")
            except json.JSONDecodeError:
                spec = {}
            kind = (spec or {}).get("kind", "")
            factory = self._kind_factories.get(kind)
            if factory is None:
                logger.warning(
                    "Bỏ qua job pending kind=%r chưa register (mất sau restart)", kind
                )
                continue
            try:
                target = factory(spec.get("params", {}))
            except Exception:
                logger.exception("Không tái tạo được job pending kind=%r", kind)
                continue
            self.enqueue(
                row["category"],
                row["step"] or kind,
                target,
                label=row["label"] or kind,
                ebook=row["ebook"],
                spec=spec,
            )
            restored += 1
        return restored

    def _save_pending(self) -> None:
        if self._db_path is None:
            return
        with self._lock:
            jobs = [j for q in self._pending.values() for j in q if j.spec] + [
                j for j in self._running.values() if j.spec
            ]
        conn = get_thread_connection(self._db_path)
        try:
            with conn:
                conn.execute("DELETE FROM job_queue_pending")
                for j in jobs:
                    conn.execute(
                        "INSERT INTO job_queue_pending (id, category, step, label, ebook, spec_json) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (j.id, j.category, j.step, j.label, j.ebook, json.dumps(j.spec, ensure_ascii=False)),
                    )
        except Exception:
            logger.exception("Không lưu được hàng đợi pending vào %s", self._db_path)

    # ---------- persistence ----------

    def _save_history_job(self, job: Job) -> None:
        """Ghi 1 job vào lịch sử + prune. Rẻ hơn _save_history() (viết lại toàn
        bộ deque, O(n) mỗi lần job kết thúc) nên phải dùng ở hot path."""
        if self._db_path is None:
            return
        with self._lock:
            if job.id not in self._jobs:
                return  # job bị delete() trong lúc nó vừa chạy xong — đừng ghi lại
        data_json = json.dumps(job.to_dict(), ensure_ascii=False)
        conn = get_thread_connection(self._db_path)
        limit = self._history.maxlen or DEFAULT_HISTORY_LIMIT
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO job_queue_history (id, data_json, ended_at) VALUES (?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET data_json = excluded.data_json, ended_at = excluded.ended_at
                    """,
                    (job.id, data_json, job.ended_at),
                )
                conn.execute(
                    "DELETE FROM job_queue_history WHERE id NOT IN "
                    "(SELECT id FROM job_queue_history ORDER BY ended_at DESC LIMIT ?)",
                    (limit,),
                )
        except Exception:
            logger.exception("Không lưu được job %s vào lịch sử (%s)", job.id, self._db_path)

    def _delete_history_row(self, job_id: str) -> None:
        self._delete_history_rows([job_id])

    def _delete_history_rows(self, job_ids: list[str]) -> None:
        if self._db_path is None or not job_ids:
            return
        conn = get_thread_connection(self._db_path)
        try:
            with conn:
                conn.executemany(
                    "DELETE FROM job_queue_history WHERE id = ?",
                    [(job_id,) for job_id in job_ids],
                )
        except Exception:
            logger.exception("Không xóa được lịch sử job khỏi %s", self._db_path)

    def _save_history(self) -> None:
        """Viết lại toàn bộ deque lịch sử (dùng lúc khởi động/kiểm thử, KHÔNG
        dùng trong hot path — xem _save_history_job)."""
        if self._db_path is None:
            return
        conn = get_thread_connection(self._db_path)
        limit = self._history.maxlen or DEFAULT_HISTORY_LIMIT
        try:
            with conn:
                for j in self._history:
                    conn.execute(
                        """
                        INSERT INTO job_queue_history (id, data_json, ended_at) VALUES (?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET data_json = excluded.data_json, ended_at = excluded.ended_at
                        """,
                        (j.id, json.dumps(j.to_dict(), ensure_ascii=False), j.ended_at),
                    )
                conn.execute(
                    "DELETE FROM job_queue_history WHERE id NOT IN "
                    "(SELECT id FROM job_queue_history ORDER BY ended_at DESC LIMIT ?)",
                    (limit,),
                )
        except Exception:
            logger.exception("Không lưu được lịch sử job vào %s", self._db_path)

    def _load_history(self) -> None:
        if self._db_path is None:
            return
        conn = get_thread_connection(self._db_path)
        rows = conn.execute(
            "SELECT data_json FROM job_queue_history ORDER BY ended_at ASC"
        ).fetchall()
        for row in rows:
            try:
                item = json.loads(row["data_json"])
            except json.JSONDecodeError:
                continue
            job = Job(
                id=item.get("id", str(uuid.uuid4())),
                category=item.get("category", "crawl"),
                step=item.get("step", ""),
                label=item.get("label", item.get("step", "")),
                ebook=item.get("ebook", ""),
                ebook_code=item.get("ebook_code", ""),
                lock_ebook=item.get("lock_ebook", True),
                chapter_indexes=item.get("chapter_indexes", []),
                chapter_codes=item.get("chapter_codes", []),
                outcome=item.get("outcome"),
            )
            job.state = item.get("state", "done")
            job.enqueued_at = item.get("enqueued_at") or time.time()
            job.started_at = item.get("started_at")
            job.ended_at = item.get("ended_at")
            job.error = item.get("error", "")
            self._history.appendleft(job)
            self._jobs[job.id] = job
