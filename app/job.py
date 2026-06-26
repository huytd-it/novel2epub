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
    step_translate,
    step_translate_meta,
)

from .queue import JobQueue

_STEPS: dict[str, Callable[[Config, Callable[[str], None]], object]] = {
    "crawl": step_crawl,
    "fetch-toc": step_fetch_toc,
    "translate": step_translate,
    "translate-meta": step_translate_meta,
    "build": step_build,
    "run": run_all,
}

# Step nào chiếm category nào — "both" chiếm cả crawl+translate (build/run
# đụng tới cả raw/ và translated/, run_all còn tự gọi crawl+dịch nối tiếp).
_STEP_CATEGORY: dict[str, str] = {
    "crawl": "crawl",
    "fetch-toc": "crawl",
    "translate": "translate",
    "translate-meta": "translate",
    "build": "both",
    "run": "both",
}


class JobRunner:
    """Shim tương thích ngược trên JobQueue — route cũ gọi start()/status() như trước."""

    def __init__(self, max_log_lines: int = 500, workers: dict[str, int] | None = None, history_path=None):
        self.queue = JobQueue(workers=workers, history_path=history_path, history_limit=max(max_log_lines, 200))

    def status(self) -> dict:
        return {
            "crawl": self.queue.category_status("crawl"),
            "translate": self.queue.category_status("translate"),
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

    def request_cancel(self, category: str) -> bool:
        return self.queue.request_cancel_category(category)

    def start_custom(
        self,
        step: str,
        target_fn: Callable[[Callable[[str], None]], object],
        category: str,
    ) -> bool:
        self.queue.enqueue(category, step, target_fn, label=step)
        return True
