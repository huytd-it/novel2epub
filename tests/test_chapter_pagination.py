"""Test chapter pagination across the three concrete crawlers."""
from __future__ import annotations

from bs4 import BeautifulSoup

from novel2epub.config import CrawlConfig
from novel2epub.crawler import (
    HttpCrawler,
    _next_page_url_from_pattern,
    fetch_chapter_paginated,
)
from novel2epub.storage import Chapter


# ---------- helpers ----------

def _soup(html: str):
    return BeautifulSoup(html, "html.parser")


def _page(html: str, next_href: str = "", title_prefix: str = ""):
    """Trả HTML có #content và (tuỳ chọn) link pager_next.

    ``html`` là nội dung body được nhúng trong <p>Body text</p> - thực ra
    là toàn bộ markup của body. Để đơn giản, mỗi test sẽ tự build HTML.
    Hàm này giữ lại để tương thích ngược với test cũ.
    """
    next_link = (
        f'<a id="pager_next" href="{next_href}">Trang tiếp</a>' if next_href else ""
    )
    title = title_prefix or "Chương 1: Tiêu đề"
    return (
        f'<html><body><div id="content"><h1>{title}</h1>{next_link}'
        f'<p>Body text</p></div></body></html>'
    )


def _make_http_crawler(**kw) -> HttpCrawler:
    return HttpCrawler(CrawlConfig(toc_url="http://example.com/book/", **kw))


class _FakeResp:
    def __init__(self, text: str):
        self.text = text


def _patch_http_session(monkeypatch, crawler: HttpCrawler, responses: dict[str, str]):
    """Patch ``crawler._get_soup`` thành từ điển URL -> HTML."""
    soup_cache: dict[str, BeautifulSoup] = {
        url: _soup(html) for url, html in responses.items()
    }

    def fake_get_soup(url: str):
        if url not in soup_cache:
            raise RuntimeError(f"Unexpected URL: {url}")
        crawler._last_response_text = responses[url]
        return soup_cache[url]

    monkeypatch.setattr(crawler, "_get_soup", fake_get_soup)


# ---------- tests for fetch_chapter_paginated helper directly ----------


def test_single_page_no_pagination():
    """Khi không có selector / pattern, helper gọi fetch_page 1 lần."""
    cfg = CrawlConfig(toc_url="http://x.com")
    ch = Chapter(index=1, url="http://x.com/p1", title_zh="t")
    calls = []

    def fetch_page(url):
        calls.append(url)
        return _soup(_page("page 1"))

    def extract_text(page):
        return page.select_one("#content").get_text(" ", strip=True)

    def next_page_url(url, page):
        return None

    text = fetch_chapter_paginated(
        cfg, ch,
        fetch_page=fetch_page,
        extract_text=extract_text,
        next_page_url=next_page_url,
    )
    assert calls == ["http://x.com/p1"]
    assert "Chương 1" in text
    assert "Body text" in text


def test_three_page_chapter_follows_selector():
    """3 trang, mỗi trang có link 'pager_next' tới trang kế."""
    cfg = CrawlConfig(
        toc_url="http://x.com",
        next_page_selector="a#pager_next",
    )
    ch = Chapter(index=1, url="http://x.com/p1", title_zh="t")
    pages = {
        "http://x.com/p1": (
            '<html><body><div id="content">'
            '<p>Body of page 1.</p>'
            '<a id="pager_next" href="p2">Trang tiếp</a>'
            '</div></body></html>'
        ),
        "http://x.com/p2": (
            '<html><body><div id="content">'
            '<p>Body of page 2.</p>'
            '<a id="pager_next" href="p3">Trang tiếp</a>'
            '</div></body></html>'
        ),
        "http://x.com/p3": (
            '<html><body><div id="content">'
            '<p>Body of page 3.</p>'
            '</div></body></html>'
        ),
    }
    visited = []

    def fetch_page(url):
        visited.append(url)
        return _soup(pages[url])

    def extract_text(page):
        return page.select_one("#content p").get_text(strip=True)

    def next_page_url(url, page):
        node = page.select_one("a#pager_next")
        if not node:
            return None
        href = node.get("href", "").strip()
        from urllib.parse import urljoin
        return urljoin(url, href)

    text = fetch_chapter_paginated(
        cfg, ch,
        fetch_page=fetch_page,
        extract_text=extract_text,
        next_page_url=next_page_url,
    )
    assert visited == [
        "http://x.com/p1",
        "http://x.com/p2",
        "http://x.com/p3",
    ]
    assert text == "Body of page 1.\n\nBody of page 2.\n\nBody of page 3."


def test_url_pattern_fallback_substitutes_group():
    """Khi không có selector, dùng pattern để sinh URL kế tiếp.

    Pattern ``_(\\d+)\\.html$`` chỉ khớp URL có hậu tố ``_N``. Test này
    bắt đầu từ URL trang 1 có sẵn hậu tố (``ch7_1.html``) — đó là URL
    chương ta đã tải sẵn, nên helper vẫn có body. Resolver được gọi
    cho lần fetch tiếp theo và sinh ``ch7_2.html``, ``ch7_3.html``.
    """
    cfg = CrawlConfig(
        toc_url="http://x.com",
        next_page_url_pattern=r"_(\d+)\.html$",
    )
    ch = Chapter(index=1, url="http://x.com/ch7_1.html", title_zh="t")
    pages = {
        "http://x.com/ch7_1.html": "BODY-1",
        "http://x.com/ch7_2.html": "BODY-2",
        "http://x.com/ch7_3.html": "BODY-3",
    }
    visited = []

    def fetch_page(url):
        visited.append(url)
        if url not in pages:
            raise RuntimeError("404")
        return _soup(f"<div id='content'>{pages[url]}</div>")

    def extract_text(page):
        return page.select_one("#content").get_text(strip=True)

    pattern_resolver = _next_page_url_from_pattern(cfg)
    assert pattern_resolver is not None

    def next_page_url(url, page):
        return pattern_resolver(url, page)

    text = fetch_chapter_paginated(
        cfg, ch,
        fetch_page=fetch_page,
        extract_text=extract_text,
        next_page_url=next_page_url,
    )
    assert "BODY-1" in text
    assert "BODY-2" in text
    assert "BODY-3" in text
    # Trang 4 không tồn tại -> fetch raise -> helper dừng. Tổng 4 attempts
    # (3 thành công + 1 thất bại).
    assert len(visited) == 4


def test_url_pattern_returns_none_when_no_match():
    """Pattern không khớp URL hiện tại -> resolver trả None -> dừng."""
    cfg = CrawlConfig(
        toc_url="http://x.com",
        next_page_url_pattern=r"(\d+)\.html$",
    )
    ch = Chapter(index=1, url="http://x.com/other", title_zh="t")
    fetch_calls = []

    def fetch_page(url):
        fetch_calls.append(url)
        return _soup(f"<div id='content'>body {url}</div>")

    def extract_text(page):
        return page.select_one("#content").get_text(strip=True)

    pattern_resolver = _next_page_url_from_pattern(cfg)

    def next_page_url(url, page):
        return pattern_resolver(url, page)

    text = fetch_chapter_paginated(
        cfg, ch,
        fetch_page=fetch_page,
        extract_text=extract_text,
        next_page_url=next_page_url,
    )
    assert "body http://x.com/other" in text
    assert len(fetch_calls) == 1  # không fetch trang 2


def test_url_pattern_stops_when_pattern_no_longer_matches():
    """Khi URL hiện tại không khớp pattern -> resolver trả None -> dừng."""
    cfg = CrawlConfig(
        toc_url="http://x.com",
        next_page_url_pattern=r"p(\d+)$",
    )
    ch = Chapter(index=1, url="http://x.com/p1", title_zh="t")
    pages = {
        "http://x.com/p1": "BODY-1",
        "http://x.com/p2": "BODY-2",
    }
    visited = []

    def fetch_page(url):
        visited.append(url)
        return _soup(f"<div id='content'>{pages[url]}</div>")

    def extract_text(page):
        return page.select_one("#content").get_text(strip=True)

    pattern_resolver = _next_page_url_from_pattern(cfg)

    def next_page_url(url, page):
        return pattern_resolver(url, page)

    text = fetch_chapter_paginated(
        cfg, ch,
        fetch_page=fetch_page,
        extract_text=extract_text,
        next_page_url=next_page_url,
    )
    assert "BODY-1" in text
    assert "BODY-2" in text
    assert len(visited) == 3  # p1, p2, p3 (sau đó fetch raise -> dừng)


def test_url_pattern_stops_when_pattern_no_longer_matches():
    """Khi URL hiện tại không khớp pattern -> resolver trả None -> dừng."""
    cfg = CrawlConfig(
        toc_url="http://x.com",
        next_page_url_pattern=r"p(\d+)$",
    )
    ch = Chapter(index=1, url="http://x.com/p1", title_zh="t")
    pages = {
        "http://x.com/p1": "BODY-1",
        "http://x.com/p2": "BODY-2",
    }
    visited = []

    def fetch_page(url):
        visited.append(url)
        return _soup(f"<div id='content'>{pages[url]}</div>")

    def extract_text(page):
        return page.select_one("#content").get_text(strip=True)

    pattern_resolver = _next_page_url_from_pattern(cfg)

    def next_page_url(url, page):
        return pattern_resolver(url, page)

    text = fetch_chapter_paginated(
        cfg, ch,
        fetch_page=fetch_page,
        extract_text=extract_text,
        next_page_url=next_page_url,
    )
    assert "BODY-1" in text
    assert "BODY-2" in text
    # Sau khi sang p2, p3 không tồn tại. fetch_page raise -> helper dừng.
    assert len(visited) == 3


def test_duplicate_content_stops_pagination():
    """Trang kế tiếp trả về cùng text -> helper dừng."""
    cfg = CrawlConfig(
        toc_url="http://x.com",
        next_page_selector="a#pager_next",
    )
    ch = Chapter(index=1, url="http://x.com/p1", title_zh="t")
    pages = {
        "http://x.com/p1": (
            '<html><body><div id="content">'
            '<p>Page A.</p>'
            '<a id="pager_next" href="p2">next</a>'
            '</div></body></html>'
        ),
        "http://x.com/p2": (
            '<html><body><div id="content">'
            '<p>Page A.</p>'   # trùng nội dung trang 1
            '<a id="pager_next" href="p3">next</a>'
            '</div></body></html>'
        ),
        "http://x.com/p3": (
            '<html><body><div id="content">'
            '<p>Page C.</p>'
            '</div></body></html>'
        ),
    }
    visited = []

    def fetch_page(url):
        visited.append(url)
        return _soup(pages[url])

    def extract_text(page):
        return page.select_one("#content p").get_text(strip=True)

    def next_page_url(url, page):
        node = page.select_one("a#pager_next")
        if not node:
            return None
        from urllib.parse import urljoin
        return urljoin(url, node.get("href", "").strip())

    text = fetch_chapter_paginated(
        cfg, ch,
        fetch_page=fetch_page,
        extract_text=extract_text,
        next_page_url=next_page_url,
    )
    # 2 trang đầu giống nhau -> dừng sau trang 2, không fetch trang 3.
    assert len(visited) == 2
    assert "Page A." in text


def test_max_pages_caps_pagination():
    """max_pages_per_chapter=3 cứng ngắt vòng lặp dù còn next link."""
    cfg = CrawlConfig(
        toc_url="http://x.com",
        next_page_selector="a#pager_next",
        max_pages_per_chapter=3,
    )
    ch = Chapter(index=1, url="http://x.com/p1", title_zh="t")
    pages = {
        f"http://x.com/p{i}": (
            f'<html><body><div id="content">'
            f'<p>Page {i}.</p>'
            f'<a id="pager_next" href="p{i + 1}">next</a>'
            f'</div></body></html>'
        )
        for i in range(1, 6)
    }
    # Trang 5 cũng có next (sang p6) nhưng cap 3 sẽ chặn trước đó.
    pages["http://x.com/p6"] = (
        '<html><body><div id="content"><p>Page 6.</p></div></body></html>'
    )

    visited = []

    def fetch_page(url):
        visited.append(url)
        return _soup(pages[url])

    def extract_text(page):
        return page.select_one("#content p").get_text(strip=True)

    def next_page_url(url, page):
        node = page.select_one("a#pager_next")
        if not node:
            return None
        from urllib.parse import urljoin
        return urljoin(url, node.get("href", "").strip())

    text = fetch_chapter_paginated(
        cfg, ch,
        fetch_page=fetch_page,
        extract_text=extract_text,
        next_page_url=next_page_url,
    )
    assert len(visited) == 3
    assert "Page 1." in text
    assert "Page 2." in text
    assert "Page 3." in text
    assert "Page 4." not in text


def test_repeated_title_is_stripped_from_subpage():
    """Trang 2 bắt đầu bằng cùng tiêu đề -> bị strip."""
    cfg = CrawlConfig(
        toc_url="http://x.com",
        next_page_selector="a#pager_next",
    )
    ch = Chapter(index=1, url="http://x.com/p1", title_zh="t")
    pages = {
        "http://x.com/p1": (
            '<html><body><div id="content">'
            '<p>第N章 章名</p>'  # title line on page 1
            '<p>Body A.</p>'
            '<a id="pager_next" href="p2">next</a>'
            '</div></body></html>'
        ),
        "http://x.com/p2": (
            '<html><body><div id="content">'
            '<p>第N章 章名</p>'  # repeated title on page 2
            '<p>Body B.</p>'
            '<a id="pager_next" href="p3">next</a>'
            '</div></body></html>'
        ),
        "http://x.com/p3": (
            '<html><body><div id="content">'
            '<p>Body C.</p>'  # no repeated title on page 3
            '</div></body></html>'
        ),
    }

    def fetch_page(url):
        return _soup(pages[url])

    def extract_text(page):
        ps = page.select("#content p")
        return "\n".join(p.get_text(" ", strip=True) for p in ps)

    def next_page_url(url, page):
        node = page.select_one("a#pager_next")
        if not node:
            return None
        from urllib.parse import urljoin
        return urljoin(url, node.get("href", "").strip())

    text = fetch_chapter_paginated(
        cfg, ch,
        fetch_page=fetch_page,
        extract_text=extract_text,
        next_page_url=next_page_url,
    )
    # Tiêu đề chỉ xuất hiện đúng 1 lần, dù trang 2 cũng có nó.
    assert text.count("第N章 章名") == 1
    assert "Body A." in text
    assert "Body B." in text
    assert "Body C." in text


# ---------- tests for HttpCrawler.fetch_chapter integration ----------


def test_http_crawler_follows_three_pages(monkeypatch):
    """End-to-end: HttpCrawler.fetch_chapter duyệt 3 trang con."""
    crawler = _make_http_crawler(
        content_selector="#content",
        next_page_selector="a#pager_next",
    )
    pages = {
        "http://x.com/p1": (
            '<html><body><div id="content">'
            '<p>Page 1 body.</p>'
            '<a id="pager_next" href="p2">next</a>'
            '</div></body></html>'
        ),
        "http://x.com/p2": (
            '<html><body><div id="content">'
            '<p>Page 2 body.</p>'
            '<a id="pager_next" href="p3">next</a>'
            '</div></body></html>'
        ),
        "http://x.com/p3": (
            '<html><body><div id="content">'
            '<p>Page 3 body.</p>'
            '</div></body></html>'
        ),
    }
    _patch_http_session(monkeypatch, crawler, pages)
    ch = Chapter(index=1, url="http://x.com/p1", title_zh="t")
    text = crawler.fetch_chapter(ch)
    assert "Page 1 body." in text
    assert "Page 2 body." in text
    assert "Page 3 body." in text


def test_http_crawler_single_page_when_no_pagination_config(monkeypatch):
    """Không có next_page_* thì chỉ fetch 1 lần (backward compat)."""
    crawler = _make_http_crawler(content_selector="#content")
    pages = {
        "http://x.com/p1": (
            '<html><body><div id="content"><p>Only page.</p></div></body></html>'
        ),
    }
    _patch_http_session(monkeypatch, crawler, pages)
    ch = Chapter(index=1, url="http://x.com/p1", title_zh="t")
    text = crawler.fetch_chapter(ch)
    assert "Only page." in text


def test_http_crawler_pagination_with_url_pattern(monkeypatch):
    """HttpCrawler dùng URL pattern khi không có CSS selector.

    Pattern ``_(\\d+)\\.html$`` cần URL đã có hậu tố ``_N`` để khớp.
    Chapter URL trỏ thẳng vào trang 1 có hậu tố (``ch7_1.html``).
    """
    crawler = _make_http_crawler(
        content_selector="#content",
        next_page_url_pattern=r"_(\d+)\.html$",
    )
    pages = {
        "http://x.com/ch7_1.html": (
            '<html><body><div id="content"><p>Body 1.</p></div></body></html>'
        ),
        "http://x.com/ch7_2.html": (
            '<html><body><div id="content"><p>Body 2.</p></div></body></html>'
        ),
        "http://x.com/ch7_3.html": (
            '<html><body><div id="content"><p>Body 3.</p></div></body></html>'
        ),
    }
    _patch_http_session(monkeypatch, crawler, pages)
    ch = Chapter(index=1, url="http://x.com/ch7_1.html", title_zh="t")
    text = crawler.fetch_chapter(ch)
    assert "Body 1." in text
    assert "Body 2." in text
    assert "Body 3." in text
