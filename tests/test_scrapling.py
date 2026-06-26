"""Tests cho ScraplingCrawler engine — make_crawler, fetch_toc, fetch_chapter."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from novel2epub.config import CrawlConfig, ScraplingConfig
from novel2epub.crawler import ScraplingCrawler, make_crawler


class TestScraplingImport:
    def test_import_error_when_scrapling_missing(self):
        """Khi scrapling chưa cài, ScraplingCrawler raise ImportError rõ ràng."""
        cfg = CrawlConfig(toc_url="http://example.com/toc")
        with patch.dict(sys.modules, {"scrapling": None, "scrapling.fetchers": None}):
            with pytest.raises(ImportError, match="scrapling"):
                make_crawler(cfg)


class TestMakeCrawlerScrapling:
    def test_make_crawler_scrapling_returns_scrapling_crawler(self):
        """make_crawler(engine='scrapling') trả về ScraplingCrawler."""
        mock_fetchers_module = MagicMock()
        mock_fetchers_module.Fetcher = MagicMock()
        mock_fetchers_module.StealthyFetcher = MagicMock()
        mock_fetchers_module.DynamicFetcher = MagicMock()

        with patch.dict(sys.modules, {"scrapling": MagicMock(), "scrapling.fetchers": mock_fetchers_module}):
            cfg = CrawlConfig(toc_url="http://example.com/toc")
            crawler = make_crawler(cfg)
            from novel2epub.crawler import ScraplingCrawler
            assert isinstance(crawler, ScraplingCrawler)

    def test_make_crawler_rejects_http(self):
        """engine='http' bị từ chối với thông báo rõ ràng."""
        cfg = CrawlConfig(toc_url="http://example.com/toc", engine="http")
        with pytest.raises(ValueError, match="đã bị loại bỏ"):
            make_crawler(cfg)

    def test_make_crawler_rejects_crawl4ai(self):
        """engine='crawl4ai' bị từ chối."""
        cfg = CrawlConfig(toc_url="http://example.com/toc", engine="crawl4ai")
        with pytest.raises(ValueError, match="đã bị loại bỏ"):
            make_crawler(cfg)

    def test_make_crawler_rejects_firecrawl(self):
        """engine='firecrawl' bị từ chối."""
        cfg = CrawlConfig(toc_url="http://example.com/toc", engine="firecrawl")
        with pytest.raises(ValueError, match="đã bị loại bỏ"):
            make_crawler(cfg)

    def test_make_crawler_invalid_engine_message(self):
        """Error message cho engine không hợp lệ."""
        cfg = CrawlConfig(toc_url="http://example.com/toc", engine="invalid")
        with pytest.raises(ValueError, match="scrapling"):
            make_crawler(cfg)


def _make_mock_page(html_links=None, meta_tags=None):
    """Tạo mock Adaptor object cho ScraplingCrawler."""
    page = MagicMock()

    def mock_css(selector):
        if selector.startswith("meta["):
            if meta_tags:
                for key, val in meta_tags.items():
                    if key in selector:
                        tag = MagicMock()
                        tag.attrib = {"content": val}
                        return [tag]
            return []
        if selector == "title":
            tag = MagicMock()
            tag.text = meta_tags.get("title", "") if meta_tags else ""
            return [tag]
        if selector == "a[href]" and html_links:
            result = []
            for href, text in html_links:
                a = MagicMock()
                a.attrib = {"href": href}
                a.text = text
                result.append(a)
            return result
        if selector == "p":
            return []
        return []

    page.css = mock_css
    page.html_content = "<html></html>"
    page.status = 200
    page.text = ""
    return page


class TestScraplingFetchToc:
    def test_fetch_toc_extracts_chapters(self):
        """fetch_toc() parse chapter links từ response."""
        mock_fetchers = MagicMock()
        mock_stealthy = MagicMock()

        links = [
            ("/book/1/ch1.html", "Chương 1"),
            ("/book/1/ch2.html", "Chương 2"),
            ("/book/1/ch3.html", "Chương 3"),
        ]
        meta = {"og:title": "Test Novel", "og:novel:author": "Author"}

        page = _make_mock_page(html_links=links, meta_tags=meta)
        mock_stealthy.fetch = MagicMock(return_value=page)

        mock_fetchers.Fetcher = MagicMock()
        mock_fetchers.StealthyFetcher = mock_stealthy
        mock_fetchers.DynamicFetcher = MagicMock()

        with patch.dict(sys.modules, {
            "scrapling": MagicMock(),
            "scrapling.fetchers": mock_fetchers,
        }):
            cfg = CrawlConfig(
                toc_url="http://example.com/book/1/",
                chapter_link_pattern=r"/book/1/ch\d+\.html",
                scrapling=ScraplingConfig(mode="stealthy"),
            )
            crawler = ScraplingCrawler(cfg)
            result = crawler.fetch_toc()
            assert len(result.chapters) == 3
            assert result.chapters[0].title_zh == "Chương 1"
            assert result.title == "Test Novel"
            assert result.author == "Author"


class TestScraplingFetchChapter:
    def test_fetch_chapter_extracts_text(self):
        """fetch_chapter() extract text từ content_selector."""
        mock_fetchers = MagicMock()
        mock_stealthy = MagicMock()

        page = MagicMock()
        content_node = MagicMock()
        content_node.text = "Nội dung chương 1.\n\nĐoạn thứ hai."
        content_node.css = MagicMock(return_value=[])

        def mock_css(selector):
            if selector == "#content":
                return [content_node]
            return []

        page.css = mock_css
        page.html_content = "<html><div id='content'>text</div></html>"
        page.status = 200
        mock_stealthy.fetch = MagicMock(return_value=page)

        mock_fetchers.Fetcher = MagicMock()
        mock_fetchers.StealthyFetcher = mock_stealthy
        mock_fetchers.DynamicFetcher = MagicMock()

        with patch.dict(sys.modules, {
            "scrapling": MagicMock(),
            "scrapling.fetchers": mock_fetchers,
        }):
            from novel2epub.crawler import ScraplingCrawler
            from novel2epub.storage import Chapter
            cfg = CrawlConfig(
                toc_url="http://example.com/",
                content_selector="#content",
                scrapling=ScraplingConfig(mode="stealthy"),
            )
            crawler = ScraplingCrawler(cfg)
            ch = Chapter(index=1, url="http://example.com/ch1.html", title_zh="第一章")
            text = crawler.fetch_chapter(ch)
            assert "Nội dung chương 1" in text


class TestScraplingConfig:
    def test_scrapling_config_defaults(self):
        """ScraplingConfig có default hợp lý."""
        sc = ScraplingConfig()
        assert sc.mode == "fetcher"
        assert sc.solve_cloudflare is False
        assert sc.network_idle is True
        assert sc.impersonate == ""

    def test_scrapling_config_custom(self):
        """ScraplingConfig nhận giá trị custom."""
        sc = ScraplingConfig(mode="stealthy", solve_cloudflare=True)
        assert sc.mode == "stealthy"
        assert sc.solve_cloudflare is True

    def test_crawl_config_default_concurrency_cap_fetcher(self):
        """default_concurrency_cap cho fetcher = 20."""
        cfg = CrawlConfig(toc_url="http://example.com/")
        cfg.scrapling = ScraplingConfig(mode="fetcher")
        assert cfg.default_concurrency_cap() == 20

    def test_crawl_config_default_concurrency_cap_stealthy(self):
        """default_concurrency_cap cho stealthy = 5."""
        cfg = CrawlConfig(toc_url="http://example.com/")
        cfg.scrapling = ScraplingConfig(mode="stealthy")
        assert cfg.default_concurrency_cap() == 5

    def test_crawl_config_default_concurrency_cap_dynamic(self):
        """default_concurrency_cap cho dynamic = 5."""
        cfg = CrawlConfig(toc_url="http://example.com/")
        cfg.scrapling = ScraplingConfig(mode="dynamic")
        assert cfg.default_concurrency_cap() == 5
