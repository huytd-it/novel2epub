"""Domain nguồn hết hạn/bị park trả 200 rồi đẩy sang trang quảng cáo: crawler
phải nhận ra "đang ở site khác" và báo đúng nguyên nhân khi lấy mục lục."""
import pytest

from novel2epub.config import CrawlConfig, ScraplingConfig
from novel2epub.crawler import ScraplingCrawler, offsite_redirect_host

pytest.importorskip("scrapling.fetchers")


@pytest.mark.parametrize(
    ("requested", "final", "expected"),
    [
        ("https://www.sudugu.com/1921/", "https://crmrc.livejasmin.com/pu/x", "crmrc.livejasmin.com"),
        ("https://www.sudugu.com/1921/", "http://gbo.autos/", "gbo.autos"),
        ("https://www.sudugu.com/1921/", "https://m.sudugu.com/1921/", ""),
        ("https://sudugu.com/1921/", "https://www.sudugu.com/1921/", ""),
        ("https://www.a.com.cn/1/", "https://m.a.com.cn/1/", ""),
        ("https://www.a.com.cn/1/", "https://www.b.com.cn/1/", "www.b.com.cn"),
        ("https://www.sudugu.com/1921/", "", ""),
    ],
)
def test_offsite_redirect_host(requested, final, expected):
    assert offsite_redirect_host(requested, final) == expected


def _crawler(final_url: str, html: str) -> ScraplingCrawler:
    from scrapling.parser import Selector

    class _Fetcher:
        def get(self, url, **kwargs):
            page = Selector(content=html.encode(), url=final_url, encoding="utf-8")
            return page

    cfg = CrawlConfig(toc_url="https://www.sudugu.com/1921/", chapter_link_pattern=r"/\d+\.html$")
    cfg.scrapling = ScraplingConfig(mode="fetcher")
    crawler = ScraplingCrawler(cfg)
    crawler._fetcher_cls = _Fetcher()
    return crawler


def test_fetch_toc_bao_ro_khi_bi_chuyen_huong_sang_site_khac():
    crawler = _crawler(
        "https://crmrc.livejasmin.com/pu/lfclow",
        "<html><head><title>Ads</title></head><body><a href='/x'>x</a></body></html>",
    )

    with pytest.raises(RuntimeError, match=r"chuyển hướng sang site khác \(crmrc\.livejasmin\.com\)"):
        crawler.fetch_toc()


def test_fetch_toc_binh_thuong_khi_van_o_dung_site():
    crawler = _crawler(
        "https://www.sudugu.com/1921/",
        "<html><head><title>T</title></head><body>"
        "<a href='/1921/1.html'>Chương 1</a><a href='/1921/2.html'>Chương 2</a></body></html>",
    )

    toc = crawler.fetch_toc()

    assert [ch.url for ch in toc.chapters] == [
        "https://www.sudugu.com/1921/1.html",
        "https://www.sudugu.com/1921/2.html",
    ]
    assert crawler.last_offsite_host == ""
