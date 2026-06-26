"""Giới hạn tốc độ theo domain + giảm/tăng song song hóa thích ứng khi crawl
gặp burst lỗi 429/anti-bot. Dùng chung giữa các luồng của 1 job crawl song
song (xem `_crawl_chapters_parallel` trong pipeline.py).
"""
from __future__ import annotations

import random
import threading
import time


class DomainRateLimiter:
    """Token-bucket đơn giản: giãn các request cách nhau tối thiểu `interval`
    giây + jitter ngẫu nhiên, chia sẻ giữa nhiều luồng cùng nhắm 1 domain để
    tránh tất cả luồng bắn request đồng thời ngay khi job bắt đầu."""

    def __init__(self, interval: float, jitter: float = 0.3):
        self._interval = max(0.0, interval)
        self._jitter = max(0.0, jitter)
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def acquire(self) -> None:
        if self._interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            wait = self._next_allowed - now
            jitter = random.uniform(0, self._jitter * self._interval)
            self._next_allowed = max(now, self._next_allowed) + self._interval + jitter
        if wait > 0:
            time.sleep(wait + jitter)


class AdaptiveConcurrency:
    """Trần song song "co giãn": `acquire()` chặn luồng mới khi số luồng đang
    hoạt động >= trần hiện tại (<= max_workers). Một chuỗi lỗi 429/anti-bot
    dồn dập (>= `burst_threshold` lỗi trong `window_seconds`) hạ trần xuống
    một nửa (tối thiểu 1); mỗi `recover_every` lần thành công liên tiếp sau
    đó tăng trần lại 1, cho tới khi về lại max_workers.

    Không hủy bỏ luồng đang chạy khi hạ trần — chỉ chặn luồng MỚI bắt đầu,
    nên đơn giản và không cần thu hồi resource đang dùng.
    """

    def __init__(
        self,
        max_workers: int,
        burst_threshold: int = 3,
        window_seconds: float = 30.0,
        recover_every: int = 5,
    ):
        self.max_workers = max(1, int(max_workers))
        self._allowed = self.max_workers
        self._active = 0
        self._burst_threshold = burst_threshold
        self._window_seconds = window_seconds
        self._recover_every = recover_every
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._fail_times: list[float] = []
        self._success_streak = 0

    @property
    def allowed(self) -> int:
        with self._lock:
            return self._allowed

    def acquire(self) -> None:
        with self._cv:
            while self._active >= self._allowed:
                self._cv.wait(timeout=1.0)
            self._active += 1

    def release(self) -> None:
        with self._cv:
            self._active -= 1
            self._cv.notify_all()

    def report_failure(self, log=None) -> None:
        now = time.monotonic()
        with self._cv:
            self._success_streak = 0
            self._fail_times = [t for t in self._fail_times if now - t <= self._window_seconds]
            self._fail_times.append(now)
            if len(self._fail_times) >= self._burst_threshold and self._allowed > 1:
                new_allowed = max(1, self._allowed // 2)
                if new_allowed < self._allowed:
                    self._allowed = new_allowed
                    self._fail_times.clear()
                    if log:
                        log(
                            f"[crawl] ! Phát hiện nhiều lỗi rate-limit/anti-bot — "
                            f"giảm song song xuống {self._allowed} luồng."
                        )

    def report_success(self, log=None) -> None:
        with self._cv:
            self._success_streak += 1
            if self._success_streak >= self._recover_every and self._allowed < self.max_workers:
                self._allowed += 1
                self._success_streak = 0
                self._cv.notify_all()
                if log:
                    log(f"[crawl] … phục hồi song song lên {self._allowed} luồng.")
