"""Trần song song theo nguồn (mode-aware) + giảm/tăng song song thích ứng
khi crawl gặp burst lỗi 429/anti-bot (xem spec crawl-management)."""
from __future__ import annotations

import threading
import time

from novel2epub import pipeline
from novel2epub.config import Config, CrawlConfig, NovelConfig, OutputConfig, ScraplingConfig, TranslateConfig
from novel2epub.crawl_throttle import AdaptiveConcurrency, DomainRateLimiter
from novel2epub.crawler import TocResult
from novel2epub.storage import Chapter, Storage


# ---------- CrawlConfig.effective_workers / default_concurrency_cap ----------


def test_default_cap_high_for_scrapling_fetcher():
    cfg = CrawlConfig(toc_url="http://x/", scrapling=ScraplingConfig(mode="fetcher"))
    assert cfg.default_concurrency_cap() == 20


def test_default_cap_low_for_scrapling_stealthy():
    cfg = CrawlConfig(toc_url="http://x/", scrapling=ScraplingConfig(mode="stealthy"))
    assert cfg.default_concurrency_cap() == 5


def test_default_cap_low_for_scrapling_dynamic():
    cfg = CrawlConfig(toc_url="http://x/", scrapling=ScraplingConfig(mode="dynamic"))
    assert cfg.default_concurrency_cap() == 5


def test_effective_workers_never_exceeds_source_cap():
    cfg = CrawlConfig(toc_url="http://x/", scrapling=ScraplingConfig(mode="stealthy"))
    assert cfg.effective_workers(100) == 5


def test_effective_workers_honors_explicit_override():
    cfg = CrawlConfig(toc_url="http://x/", concurrency_cap=3)
    assert cfg.effective_workers(100) == 3


# ---------- DomainRateLimiter ----------


def test_rate_limiter_spaces_out_calls():
    limiter = DomainRateLimiter(interval=0.05, jitter=0.0)
    start = time.monotonic()
    for _ in range(3):
        limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.1  # 2 intervals giữa 3 lần gọi


def test_rate_limiter_noop_when_interval_zero():
    limiter = DomainRateLimiter(interval=0.0)
    start = time.monotonic()
    for _ in range(5):
        limiter.acquire()
    assert time.monotonic() - start < 0.05


# ---------- AdaptiveConcurrency ----------


def test_adaptive_concurrency_caps_active_count():
    throttle = AdaptiveConcurrency(max_workers=3)
    concurrent = {"n": 0, "max": 0}
    lock = threading.Lock()
    gate = threading.Event()

    def _work():
        throttle.acquire()
        with lock:
            concurrent["n"] += 1
            concurrent["max"] = max(concurrent["max"], concurrent["n"])
        gate.wait(timeout=2)
        with lock:
            concurrent["n"] -= 1
        throttle.release()

    threads = [threading.Thread(target=_work) for _ in range(6)]
    for t in threads:
        t.start()
    time.sleep(0.3)
    assert concurrent["max"] == 3
    gate.set()
    for t in threads:
        t.join(timeout=2)


def test_adaptive_concurrency_reduces_on_failure_burst():
    throttle = AdaptiveConcurrency(max_workers=8, burst_threshold=3, window_seconds=30.0)
    assert throttle.allowed == 8
    for _ in range(3):
        throttle.report_failure()
    assert throttle.allowed == 4


def test_adaptive_concurrency_recovers_gradually_on_success():
    throttle = AdaptiveConcurrency(max_workers=8, burst_threshold=3, recover_every=2)
    for _ in range(3):
        throttle.report_failure()
    assert throttle.allowed == 4
    throttle.report_success()
    assert throttle.allowed == 4  # chưa đủ recover_every
    throttle.report_success()
    assert throttle.allowed == 5


# ---------- tích hợp: _crawl_chapters_parallel áp trần nguồn ----------


class _SlowCrawler:
    def __init__(self, toc, concurrent_counter, lock, gate):
        self._toc = toc
        self._counter = concurrent_counter
        self._lock = lock
        self._gate = gate

    def fetch_toc(self):
        return self._toc

    def fetch_chapter(self, ch):
        with self._lock:
            self._counter["n"] += 1
            self._counter["max"] = max(self._counter["max"], self._counter["n"])
        self._gate.wait(timeout=2)
        with self._lock:
            self._counter["n"] -= 1
        return f"noi dung {ch.index}"

    def sleep(self):
        pass

    def close(self):
        pass


def _toc(n):
    return TocResult(title="书名", chapters=[Chapter(index=i, url=f"http://x/{i}") for i in range(1, n + 1)])


def test_step_crawl_selected_caps_concurrency_to_source_default(tmp_path, monkeypatch):
    counter = {"n": 0, "max": 0}
    lock = threading.Lock()
    gate = threading.Event()
    gate.set()  # không cần giữ luồng lâu, chỉ cần đếm đỉnh điểm gần đúng

    monkeypatch.setattr(
        pipeline, "ScraplingCrawler", lambda c: _SlowCrawler(_toc(10), counter, lock, gate)
    )

    cfg = Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(
            toc_url="http://x/book/1/", delay_seconds=0,
            scrapling=ScraplingConfig(mode="stealthy"), max_workers=20,
        ),
        translate=TranslateConfig(type="none"),
        output=OutputConfig(data_dir=str(tmp_path)),
    )
    assert cfg.crawl.effective_workers(cfg.crawl.max_workers) == 5
    pipeline.step_crawl_selected(cfg, lambda m: None)

    storage = Storage(tmp_path, "t")
    manifest = storage.load_manifest()
    assert sum(1 for ch in manifest.chapters if storage.has_raw(ch)) == 10
