"""Chạy pipeline (crawl/translate/build/run) nền + giữ log để UI poll.

Chỉ chạy 1 job tại một thời điểm (threading.Lock), giống tinh thần PatchWorker
của epub-audiobook-app nhưng đơn giản hơn vì novel2epub là pipeline đồng bộ,
không cần hàng đợi nhiều job.
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

_STEPS: dict[str, Callable[[Config, Callable[[str], None]], object]] = {
    "crawl": step_crawl,
    "fetch-toc": step_fetch_toc,
    "translate": step_translate,
    "translate-meta": step_translate_meta,
    "build": step_build,
    "run": run_all,
}


class JobRunner:
    """Giữ trạng thái 1 job nền + buffer log (deque giới hạn) dùng cho UI."""

    def __init__(self, max_log_lines: int = 500):
        self._lock = threading.Lock()
        self._log: deque[str] = deque(maxlen=max_log_lines)
        self.running = False
        self.step = ""
        self.error = ""

    def status(self) -> dict:
        with self._lock:
            return {
                "running": self.running,
                "step": self.step,
                "error": self.error,
                "log": list(self._log),
            }

    def start(self, step: str, cfg: Config) -> bool:
        """Bắt đầu job nếu chưa có job nào chạy. Trả False nếu đang bận."""
        fn = _STEPS.get(step)
        if fn is None:
            raise ValueError(f"step không hợp lệ: {step!r}")

        with self._lock:
            if self.running:
                return False
            self.running = True
            self.step = step
            self.error = ""
            self._log.clear()

        thread = threading.Thread(target=self._run, args=(fn, cfg), daemon=True)
        thread.start()
        return True

    def start_custom(self, step: str, target_fn: Callable[[Callable[[str], None]], object]) -> bool:
        """Bắt đầu job nền tùy biến (vd rewrite chương) — target_fn chỉ nhận log_fn,
        cfg/tham số khác phải được bind sẵn qua closure ở caller."""
        with self._lock:
            if self.running:
                return False
            self.running = True
            self.step = step
            self.error = ""
            self._log.clear()

        thread = threading.Thread(target=self._run_custom, args=(target_fn,), daemon=True)
        thread.start()
        return True

    def _run_custom(self, target_fn: Callable[[Callable[[str], None]], object]) -> None:
        try:
            target_fn(self._log_line)
        except Exception as e:  # noqa: BLE001
            self._log_line(f"[lỗi] {e}")
            self._log_line(traceback.format_exc())
            with self._lock:
                self.error = str(e)
        finally:
            with self._lock:
                self.running = False

    def _log_line(self, msg: str) -> None:
        with self._lock:
            self._log.append(msg)

    def _run(self, fn, cfg: Config) -> None:
        try:
            fn(cfg, self._log_line)
        except Exception as e:  # noqa: BLE001 - hiển thị lỗi bất kỳ lên UI
            self._log_line(f"[lỗi] {e}")
            self._log_line(traceback.format_exc())
            with self._lock:
                self.error = str(e)
        finally:
            with self._lock:
                self.running = False
