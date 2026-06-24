"""Thử lại + lùi dần khi crawl bị HTTP 429 / anti-bot (chống lỗi Too Many Requests)."""
from __future__ import annotations

import pytest

from novel2epub import crawler, pipeline
from novel2epub.config import CrawlConfig, CrawlRetryConfig, load_config
from novel2epub.crawler import HttpCrawler, RateLimitError, is_rate_limited
from novel2epub.storage import Chapter


# ---------- nhận diện rate-limit ----------

def test_is_rate_limited_detects_rate_limit_error():
    matched, retry_after = is_rate_limited(RateLimitError("blah", retry_after=12.0))
    assert matched is True
    assert retry_after == 12.0


@pytest.mark.parametrize("msg", [
    "Blocked by anti-bot protection: HTTP 429 Too Many Requests",
    "HTTP 429",
    "rate limit exceeded",
])
def test_is_rate_limited_detects_by_message(msg):
    matched, retry_after = is_rate_limited(RuntimeError(msg))
    assert matched is True
    assert retry_after is None


def test_is_rate_limited_ignores_unrelated_errors():
    matched, _ = is_rate_limited(ValueError("selector not found"))
    assert matched is False


# ---------- tính thời gian chờ ----------

def test_retry_wait_exponential_backoff():
    rc = CrawlRetryConfig(delay_seconds=5.0, backoff=2.0, max_delay_seconds=120.0)
    assert pipeline._retry_wait_seconds(rc, 1, None) == 5.0
    assert pipeline._retry_wait_seconds(rc, 2, None) == 10.0
    assert pipeline._retry_wait_seconds(rc, 3, None) == 20.0


def test_retry_wait_capped_by_max_delay():
    rc = CrawlRetryConfig(delay_seconds=50.0, backoff=10.0, max_delay_seconds=60.0)
    assert pipeline._retry_wait_seconds(rc, 3, None) == 60.0


def test_retry_wait_respects_retry_after_header():
    rc = CrawlRetryConfig(delay_seconds=5.0, backoff=2.0, max_delay_seconds=120.0, respect_retry_after=True)
    assert pipeline._retry_wait_seconds(rc, 1, retry_after=30.0) == 30.0


def test_retry_wait_ignores_retry_after_when_disabled():
    rc = CrawlRetryConfig(delay_seconds=5.0, respect_retry_after=False)
    assert pipeline._retry_wait_seconds(rc, 1, retry_after=30.0) == 5.0


# ---------- vòng lặp thử lại ----------

class _FlakyCrawler:
    """Lỗi 429 vài lần đầu rồi mới thành công."""

    def __init__(self, fails: int, content: str = "noi dung"):
        self._remaining = fails
        self._content = content
        self.calls = 0

    def fetch_chapter(self, ch):
        self.calls += 1
        if self._remaining > 0:
            self._remaining -= 1
            raise RateLimitError("HTTP 429 Too Many Requests")
        return self._content


def test_retry_recovers_after_rate_limit(monkeypatch):
    monkeypatch.setattr(pipeline.time, "sleep", lambda s: None)  # khỏi chờ thật
    crawler_obj = _FlakyCrawler(fails=2)
    rc = CrawlRetryConfig(attempts=3, delay_seconds=0.0)
    ch = Chapter(index=1, url="http://x/1", title_zh="t")
    logs: list[str] = []

    out = pipeline._fetch_chapter_with_retry(crawler_obj, ch, rc, logs.append)

    assert out == "noi dung"
    assert crawler_obj.calls == 3  # 2 lần lỗi + 1 lần thành công
    assert any("rate-limit 429" in m for m in logs)


def test_retry_gives_up_after_attempts(monkeypatch):
    monkeypatch.setattr(pipeline.time, "sleep", lambda s: None)
    crawler_obj = _FlakyCrawler(fails=99)
    rc = CrawlRetryConfig(attempts=2, delay_seconds=0.0)
    ch = Chapter(index=1, url="http://x/1", title_zh="t")

    out = pipeline._fetch_chapter_with_retry(crawler_obj, ch, rc, lambda m: None)

    assert out is None
    assert crawler_obj.calls == 3  # 1 lần đầu + 2 lần thử lại


# ---------- override từ CLI vs config ----------

def test_resolve_crawl_retry_defaults_to_config():
    base = CrawlRetryConfig(attempts=3, delay_seconds=5.0)
    assert pipeline._resolve_crawl_retry(base, None, None) is base


def test_resolve_crawl_retry_cli_override():
    base = CrawlRetryConfig(attempts=3, delay_seconds=5.0, backoff=2.0)
    out = pipeline._resolve_crawl_retry(base, retries=1, retry_delay=0.5)
    assert out.attempts == 1
    assert out.delay_seconds == 0.5
    assert out.backoff == 2.0  # các trường khác giữ nguyên từ config


# ---------- HttpCrawler ném RateLimitError trên 429 ----------

class _Resp:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.reason = "Too Many Requests"
        self.headers = headers or {}
        self.text = ""
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"

    def raise_for_status(self):
        pass


def test_http_crawler_raises_rate_limit_on_429():
    cfg = CrawlConfig(toc_url="http://x/book/", delay_seconds=0)
    c = HttpCrawler(cfg)
    c._session = type("S", (), {"get": lambda self, url, timeout: _Resp(429, {"Retry-After": "42"})})()
    with pytest.raises(RateLimitError) as ei:
        c._get_soup("http://x/book/1")
    assert ei.value.retry_after == 42.0


# ---------- config YAML parse ----------

def test_config_parses_crawl_retry(tmp_path):
    cfg_file = tmp_path / "novel2epub.yaml"
    cfg_file.write_text(
        "novel: { slug: t }\n"
        "crawl:\n"
        "  toc_url: http://x/book/\n"
        "  retry: { attempts: 5, delay_seconds: 8, backoff: 3, max_delay_seconds: 200, respect_retry_after: false }\n"
        "translate: { type: none }\n"
        "output: { data_dir: data }\n",
        encoding="utf-8",
    )
    cfg = load_config(str(cfg_file))
    assert cfg.crawl.retry.attempts == 5
    assert cfg.crawl.retry.delay_seconds == 8.0
    assert cfg.crawl.retry.backoff == 3.0
    assert cfg.crawl.retry.max_delay_seconds == 200.0
    assert cfg.crawl.retry.respect_retry_after is False


def test_config_crawl_retry_defaults(tmp_path):
    cfg_file = tmp_path / "novel2epub.yaml"
    cfg_file.write_text(
        "novel: { slug: t }\n"
        "crawl: { toc_url: http://x/book/ }\n"
        "translate: { type: none }\n"
        "output: { data_dir: data }\n",
        encoding="utf-8",
    )
    cfg = load_config(str(cfg_file))
    assert cfg.crawl.retry.attempts == 3
    assert cfg.crawl.retry.respect_retry_after is True
