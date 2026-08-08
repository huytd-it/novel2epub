"""Chạy pipeline (crawl/translate/build/run) nền qua JobQueue + giữ API cũ
(start/start_custom/request_cancel/status) làm shim mỏng cho route chưa cập
nhật sang queue (xem design.md D1 của change pro-management-suite).
"""
from __future__ import annotations

import threading
from typing import Callable

from novel2epub.config import Config
from novel2epub.pipeline import (
    run_all,
    step_build,
    step_crawl,
    step_fetch_toc,
    step_reindex,
    step_translate,
)

from .queue import JobQueue

_STEPS: dict[str, Callable[[Config, Callable[[str], None]], object]] = {
    "crawl": step_crawl,
    "fetch-toc": step_fetch_toc,
    "translate": step_translate,
    "build": step_build,
    "run": run_all,
    "reindex": step_reindex,
}

# Step nào chiếm category nào — "both" chiếm cả crawl+translate (build/run
# đụng tới cả raw/ và translated/, run_all còn tự gọi crawl+dịch nối tiếp).
# `translate` → `ai-translate` (category mới); nhánh Local NMT dùng `local-mt`;
# AI biên tập (rewrite preview) dùng `ai-edit`.
_STEP_CATEGORY: dict[str, str] = {
    "crawl": "crawl",
    "fetch-toc": "crawl",
    "translate": "ai-translate",
    "build": "build",
    "run": "both",
    "reindex": "both",
}


class JobRunner:
    """Shim tương thích ngược trên JobQueue — route cũ gọi start()/status() như trước."""

    def __init__(self, max_log_lines: int = 500, workers: dict[str, int] | None = None, db_path=None):
        if workers is None:
            workers = {"translate": 2}
        self.queue = JobQueue(workers=workers, db_path=db_path, history_limit=max(max_log_lines, 200))

    def status(self) -> dict:
        """Trạng thái theo category. Giữ key `translate` (alias cũ) để template/
        route cũ đọc không vỡ; thêm `ai_translate`, `local_mt`, `ai_edit`."""
        return {
            "crawl": self.queue.category_status("crawl"),
            "translate": self.queue.category_status("ai-translate"),
            "ai_translate": self.queue.category_status("ai-translate"),
            "local_mt": self.queue.category_status("local-mt"),
            "ai_edit": self.queue.category_status("ai-edit"),
            "build": self.queue.category_status("build"),
        }

    def start(self, step: str, cfg: Config) -> bool:
        """Bắt đầu 1 step chuẩn (xem _STEPS). Luôn vào hàng đợi, trả True (xem D2)."""
        fn = _STEPS.get(step)
        category = _STEP_CATEGORY.get(step)
        if fn is None or category is None:
            raise ValueError(f"step không hợp lệ: {step!r}")

        cancel_event = threading.Event()

        def _target(log, _fn=fn, _cfg=cfg, _ev=cancel_event):
            _fn(_cfg, log, should_cancel=_ev.is_set)

        self.queue.enqueue(category, step, _target, label=step, cancel_event=cancel_event)
        return True

    def is_ebook_busy(self, category: str, ebook: str) -> bool:
        return self.queue.is_ebook_busy(category, ebook)

    def request_cancel(self, category: str) -> bool:
        return self.queue.request_cancel_category(category)

    def start_custom(
        self,
        step: str,
        target_fn: Callable[[Callable[[str], None]], object],
        category: str,
        *,
        ebook: str = "",
        spec: dict | None = None,
        cancel_event: threading.Event | None = None,
        chapter_indexes: list[int] | None = None,
        lock_ebook: bool = True,
    ) -> bool:
        self.queue.enqueue(
            category, step, target_fn, label=step, ebook=ebook, spec=spec,
            cancel_event=cancel_event, chapter_indexes=chapter_indexes,
            lock_ebook=lock_ebook,
        )
        return True

    def enqueue_step(self, step: str, cfg: Config, *, label: str = "", ebook: str = "") -> dict | None:
        fn = _STEPS.get(step)
        category = _STEP_CATEGORY.get(step)
        if fn is None or category is None:
            return None
        cancel_event = threading.Event()

        def _target(log, _fn=fn, _cfg=cfg, _ev=cancel_event):
            _fn(_cfg, log, should_cancel=_ev.is_set)

        job = self.queue.enqueue(category, step, _target, label=label or step, ebook=ebook, cancel_event=cancel_event)
        return {"job_id": job.id, "category": category}
