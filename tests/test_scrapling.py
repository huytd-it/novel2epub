"""Tests cho ScraplingCrawler engine — lazy import, make_crawler, fetch_toc,
fetch_chapter, SourcePreset fields."""
from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from novel2epub.config import CrawlConfig
from novel2epub.crawler import make_crawler
from novel2epub.sources import SourcePreset


# ---------------------------------------------------------------------------
# 6.1 — __init__ lazy import + ImportError message
# ---------------------------------------------------------------------------

class TestScraplingImport:
    def test_import_error_when_scrapling_missing(self):
        """Khi scrapling chưa cài, ScraplingCrawler raise ImportError rõ ràng."""
        cfg = CrawlConfig(toc_url="http://example.com/toc", engine="scrapling")
        with patch.dict(sys.modules, {"scrapling": None, "scrapling.fetchers": None}):
            with pytest.raises(ImportError, match="scrapling"):
                make_crawler(cfg)


# ---------------------------------------------------------------------------
# 6.5 — make_crawler dispatch "scrapling"
# ---------------------------------------------------------------------------

class TestMakeCrawlerScrapling:
    def test_make_crawler_scrapling_returns_scrapling_crawler(self):
        """make_crawler(engine='scrapling') trả về ScraplingCrawler."""
        # Mock scrapling imports
        mock_fetcher = MagicMock()
        mock_stealthy = MagicMock()
        mock_dynamic = MagicMock()
        mock_fetchers_module = MagicMock()
        mock_fetchers_module.Fetcher = mock_fetcher
        mock_fetchers_module.StealthyFetcher = mock_stealthy
        mock_fetchers_module.DynamicFetcher = mock_dynamic

        with patch.dict(sys.modules, {"scrapling": MagicMock(), "scrapling.fetchers": mock_fetchers_module}):
            cfg = CrawlConfig(toc_url="http://example.com/toc", engine="scrapling")
            crawler = make_crawler(cfg)
            from novel2epub.crawler import ScraplingCrawler
            assert isinstance(crawler, ScraplingCrawler)

    def test_make_crawler_invalid_engine_includes_scrapling(self):
        """Error message cho engine không hợp lệ bao gồm 'scrapling'."""
        cfg = CrawlConfig(toc_url="http://example.com/toc", engine="invalid")
        with pytest.raises(ValueError, match="scrapling"):
            make_crawler(cfg)

    def test_make_crawler_http_still_works(self):
        """engine='http' vẫn hoạt động bình thường."""
        from novel2epub.crawler import HttpCrawler
        cfg = CrawlConfig(toc_url="http://example.com/toc", engine="http")
        crawler = make_crawler(cfg)
        assert isinstance(crawler, HttpCrawler)


# ---------------------------------------------------------------------------
# 6.2 — fetch_toc (mock Scrapling response)
# ---------------------------------------------------------------------------

def _make_mock_page(html_links=None, meta_tags=None):
    """Tạo mock Adaptor object cho ScraplingCrawler."""
    page = MagicMock()

    # Mock css() calls
    def mock_css(selector):
        if selector.startswith("meta["):
            # Parse property/name from selector
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
                engine="scrapling",
                chapter_link_pattern=r"/book/1/ch\d+\.html",
            )
            from novel2epub.crawler import ScraplingCrawler
            crawler = ScraplingCrawler(cfg)
            result = crawler.fetch_toc()
            assert len(result.chapters) == 3
            assert result.chapters[0].title_zh == "Chương 1"
            assert result.title == "Test Novel"
            assert result.author == "Author"


# ---------------------------------------------------------------------------
# 6.3 — fetch_chapter (text extraction + clean)
# ---------------------------------------------------------------------------

class TestScraplingFetchChapter:
    def test_fetch_chapter_extracts_text(self):
        """fetch_chapter() extract text từ content_selector."""
        mock_fetchers = MagicMock()
        mock_stealthy = MagicMock()

        page = MagicMock()
        content_node = MagicMock()
        content_node.text = "Nội dung chương 1.\n\nĐoạn thứ hai."
        content_node.css = MagicMock(return_value=[])  # no <p> tags

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
                engine="scrapling",
                content_selector="#content",
            )
            crawler = ScraplingCrawler(cfg)
            ch = Chapter(index=1, url="http://example.com/ch1.html", title_zh="第一章")
            text = crawler.fetch_chapter(ch)
            assert "Nội dung chương 1" in text


# ---------------------------------------------------------------------------
# 6.6 — SourcePreset với scrapling fields
# ---------------------------------------------------------------------------

class TestSourcePresetScrapling:
    def test_crawl_overrides_includes_scrapling_fields(self):
        """SourcePreset.crawl_overrides() bao gồm scrapling fields."""
        preset = SourcePreset(
            name="test",
            engine="scrapling",
            scrapling_mode="stealthy",
            solve_cloudflare=True,
            network_idle=True,
            impersonate="chrome",
        )
        overrides = preset.crawl_overrides()
        assert overrides["engine"] == "scrapling"
        assert overrides["scrapling_mode"] == "stealthy"
        assert overrides["solve_cloudflare"] is True
        assert overrides["network_idle"] is True
        assert overrides["impersonate"] == "chrome"
        # name, url, domains should be excluded
        assert "name" not in overrides
        assert "url" not in overrides
        assert "domains" not in overrides

    def test_scrapling_fields_default_values(self):
        """SourcePreset scrapling fields có default hợp lý."""
        preset = SourcePreset(name="test")
        assert preset.scrapling_mode == "stealthy"
        assert preset.solve_cloudflare is False
        assert preset.network_idle is True
        assert preset.impersonate == ""


# ---------------------------------------------------------------------------
# CrawlConfig scrapling fields
# ---------------------------------------------------------------------------

class TestCrawlConfigScraplingFields:
    def test_crawl_config_scrapling_defaults(self):
        """CrawlConfig scrapling fields có default hợp lý."""
        cfg = CrawlConfig(toc_url="http://example.com/")
        assert cfg.scrapling_mode == "stealthy"
        assert cfg.solve_cloudflare is False
        assert cfg.network_idle is True
        assert cfg.impersonate == ""

    def test_crawl_config_engine_comment(self):
        """engine field chấp nhận 'scrapling'."""
        cfg = CrawlConfig(toc_url="http://example.com/", engine="scrapling")
        assert cfg.engine == "scrapling"
