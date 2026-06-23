"""Chạy pipeline (crawl/translate/build/run) nền + giữ log để UI poll.

2 slot độc lập — "crawl" và "translate" — để job crawl và job dịch chạy song
song (vd dịch chương 1-50 trong khi đang crawl chương 51-100). Step "build"
và "run" chiếm CẢ HAI slot vì run_all nối tiếp crawl -> dịch -> build trong
1 thread, không được để job crawl/dịch khác chen ngang giữa lúc nó chạy.
"""
from __future__ import annotations

import threading
import traceback
from collections import deque
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

from .logging_config import logger

_STEPS: dict[str, Callable[[Config, Callable[[str], None]], object]] = {
    "crawl": step_crawl,
    "fetch-toc": step_fetch_toc,
    "translate": step_translate,
    "translate-meta": step_translate_meta,
    "build": step_build,
    "run": run_all,
}

# Step nào chiếm slot nào — "both" chiếm cả 2 slot (build/run đụng tới cả
# raw/ và translated/, run_all còn tự gọi crawl+dịch nối tiếp).
_STEP_CATEGORY: dict[str, str] = {
    "crawl": "crawl",
    "fetch-toc": "crawl",
    "translate": "translate",
    "translate-meta": "translate",
    "build": "both",
    "run": "both",
}

_CATEGORIES = ("crawl", "translate")


class _Slot:
    def __init__(self, max_log_lines: int):
        self.log: deque[str] = deque(maxlen=max_log_lines)
        self.running = False
        self.step = ""
        self.error = ""


class JobRunner:
    """Giữ trạng thái job nền theo 2 slot độc lập (crawl/translate) + buffer log."""

    def __init__(self, max_log_lines: int = 500):
        self._lock = threading.Lock()
        self._slots: dict[str, _Slot] = {name: _Slot(max_log_lines) for name in _CATEGORIES}

    def _slots_for(self, category: str) -> list[_Slot]:
        if category == "both":
            return [self._slots[name] for name in _CATEGORIES]
        if category not in self._slots:
            raise ValueError(f"category không hợp lệ: {category!r}")
        return [self._slots[category]]

    def status(self) -> dict:
        with self._lock:
            return {
                name: {
                    "running": slot.running,
                    "step": slot.step,
                    "error": slot.error,
                    "log": list(slot.log),
                }
                for name, slot in self._slots.items()
            }

    def start(self, step: str, cfg: Config) -> bool:
        """Bắt đầu 1 step chuẩn (xem _STEPS). Trả False nếu slot liên quan đang bận."""
        fn = _STEPS.get(step)
        category = _STEP_CATEGORY.get(step)
        if fn is None or category is None:
            raise ValueError(f"step không hợp lệ: {step!r}")
        return self._claim_and_run(step, category, lambda log: fn(cfg, log))

    def start_custom(
        self,
        step: str,
        target_fn: Callable[[Callable[[str], None]], object],
        category: str,
    ) -> bool:
        """Bắt đầu job nền tùy biến — target_fn chỉ nhận log_fn.

        Dùng cho các action cần tham số riêng như chapter-action, crawl-range,
        find-replace, AI review/rewrite/suggest...

        category: "crawl" | "translate" | "both" — slot nào job này chiếm
        (chọn theo nội dung action thực sự đụng tới: ghi raw/ -> "crawl",
        ghi translated/ hoặc translation_meta/ -> "translate").
        """
        return self._claim_and_run(step, category, target_fn)

    def _claim_and_run(
        self,
        step: str,
        category: str,
        target_fn: Callable[[Callable[[str], None]], object],
    ) -> bool:
        slots = self._slots_for(category)
        with self._lock:
            if any(s.running for s in slots):
                return False
            for s in slots:
                s.running = True
                s.step = step
                s.error = ""
                s.log.clear()

        thread = threading.Thread(target=self._run, args=(target_fn, step, slots), daemon=True)
        thread.start()
        return True

    def _log_line(self, slots: list[_Slot], msg: str) -> None:
        with self._lock:
            for s in slots:
                s.log.append(msg)
        logger.info(msg)

    def _run(
        self,
        target_fn: Callable[[Callable[[str], None]], object],
        step: str,
        slots: list[_Slot],
    ) -> None:
        logger.info("Bắt đầu job %r", step)
        log_fn = lambda msg: self._log_line(slots, msg)  # noqa: E731
        try:
            target_fn(log_fn)
            logger.info("Job %r hoàn tất", step)
        except Exception as e:  # noqa: BLE001 - hiển thị lỗi bất kỳ lên UI
            log_fn(f"[lỗi] {e}")
            log_fn(traceback.format_exc())
            logger.exception("Job %r thất bại: %s", step, e)
            with self._lock:
                for s in slots:
                    s.error = str(e)
        finally:
            with self._lock:
                for s in slots:
                    s.running = False
