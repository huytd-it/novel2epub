"""ScraplingCrawler truyền proxy / dns_over_https đúng theo mode."""
import pytest

from novel2epub.config import CrawlConfig, ScraplingConfig
from novel2epub.crawler import ScraplingCrawler

pytest.importorskip("scrapling.fetchers")


class _FakePage:
    html_content = "<html><body>ok</body></html>"
    status = 200


class _StubFetcher:
    """Ghi lại kwargs của lần gọi get/fetch gần nhất."""

    def __init__(self):
        self.last_kwargs = None

    def get(self, url, **kwargs):
        self.last_kwargs = kwargs
        return _FakePage()

    def fetch(self, url, **kwargs):
        self.last_kwargs = kwargs
        return _FakePage()


def _make_crawler(mode: str, **scrapling_kwargs) -> tuple[ScraplingCrawler, _StubFetcher]:
    cfg = CrawlConfig(toc_url="https://example.cn/")
    cfg.scrapling = ScraplingConfig(mode=mode, **scrapling_kwargs)
    crawler = ScraplingCrawler(cfg)
    stub = _StubFetcher()
    crawler._fetcher_cls = stub
    return crawler, stub


def test_fetcher_mode_passes_proxy():
    crawler, stub = _make_crawler("fetcher", proxy="socks5://100.64.0.1:1080")
    crawler._fetch_page("https://example.cn/1.html")
    assert stub.last_kwargs["proxy"] == "socks5://100.64.0.1:1080"
    # dns_over_https không áp dụng mode fetcher
    assert "dns_over_https" not in stub.last_kwargs


def test_fetcher_mode_without_proxy_omits_kwarg():
    crawler, stub = _make_crawler("fetcher")
    crawler._fetch_page("https://example.cn/1.html")
    assert "proxy" not in stub.last_kwargs


def test_stealthy_mode_passes_proxy_and_doh():
    crawler, stub = _make_crawler(
        "stealthy", proxy="http://proxy:8080", dns_over_https=True,
    )
    crawler._fetch_page("https://example.cn/1.html")
    assert stub.last_kwargs["proxy"] == "http://proxy:8080"
    assert stub.last_kwargs["dns_over_https"] is True


def test_dynamic_mode_passes_doh_without_proxy():
    crawler, stub = _make_crawler("dynamic", dns_over_https=True)
    crawler._fetch_page("https://example.cn/1.html")
    assert stub.last_kwargs["dns_over_https"] is True
    assert "proxy" not in stub.last_kwargs


def test_stealthy_mode_doh_off_omits_kwarg():
    crawler, stub = _make_crawler("stealthy")
    crawler._fetch_page("https://example.cn/1.html")
    assert "dns_over_https" not in stub.last_kwargs
