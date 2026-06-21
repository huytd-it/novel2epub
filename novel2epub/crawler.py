"""Crawl mục lục + nội dung chương.

Hai engine:
  - http       : requests + BeautifulSoup, KHÔNG cần API key (mặc định, free).
  - firecrawl  : Firecrawl trả Markdown sạch (cần API key hoặc self-host).

Cả hai cùng trả về nội dung dạng văn bản/markdown đơn giản để bước dịch xử lý.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urljoin

from .config import CrawlConfig
from .storage import Chapter

# [text](url)
_MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


@dataclass
class TocResult:
    """Kết quả đọc trang mục lục: metadata truyện + danh sách chương."""

    title: str = ""
    author: str = ""
    description: str = ""
    cover_url: str = ""
    chapters: list[Chapter] = field(default_factory=list)


class Crawler(Protocol):
    def fetch_toc(self) -> TocResult: ...
    def fetch_chapter(self, ch: Chapter) -> str: ...
    def sleep(self) -> None: ...
    def close(self) -> None: ...


def _dedupe_keep_last(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Khử trùng lặp URL nhưng GIỮ LẦN XUẤT HIỆN CUỐI.

    Trang mục lục kiểu biquge thường có khối "chương mới nhất" ở đầu trang lặp
    lại vài chương cuối. Giữ lần cuối => các chương đó về đúng vị trí trong phần
    chính văn, cho thứ tự đọc đúng (Chương 1, 2, 3...).
    """
    last_idx = {url: i for i, (url, _) in enumerate(pairs)}
    return [(url, text) for i, (url, text) in enumerate(pairs) if last_idx[url] == i]


def _get(obj, key, default=None):
    """Lấy thuộc tính từ dict hoặc object một cách an toàn."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _meta_get(meta, *keys: str) -> str:
    """Trả về giá trị chuỗi không rỗng đầu tiên theo các khóa metadata cho trước.

    Một số provider trả giá trị dạng list (vd nhiều og:image) — lấy phần tử đầu.
    """
    if not isinstance(meta, dict):
        return ""
    for key in keys:
        val = meta.get(key)
        if isinstance(val, (list, tuple)):
            val = val[0] if val else ""
        if val:
            return str(val).strip()
    return ""


class FirecrawlCrawler:
    def __init__(self, cfg: CrawlConfig):
        self.cfg = cfg
        try:
            from firecrawl import FirecrawlApp
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "Chưa cài firecrawl-py. Chạy: pip install firecrawl-py"
            ) from e

        kwargs: dict = {}
        if cfg.api_key:
            kwargs["api_key"] = cfg.api_key
        if cfg.api_url:
            kwargs["api_url"] = cfg.api_url
        self.app = FirecrawlApp(**kwargs)

    # ---------- low-level scrape ----------
    def _scrape(self, url: str, formats: list[str]) -> dict:
        """Trả về dict gồm các khóa 'markdown', 'links', 'metadata' nếu có."""
        result = None
        # SDK mới: scrape_url(url, formats=[...]); SDK cũ: params={'formats':[...]}
        try:
            result = self.app.scrape_url(url, formats=formats)
        except TypeError:
            result = self.app.scrape_url(url, params={"formats": formats})

        # Một số phiên bản bọc dữ liệu trong .data
        data = _get(result, "data", result)
        return {
            "markdown": _get(data, "markdown", "") or "",
            "links": _get(data, "links", []) or [],
            "metadata": _get(data, "metadata", {}) or {},
        }

    # ---------- mục lục ----------
    def fetch_toc(self) -> TocResult:
        """Trả về metadata truyện + danh sách chương theo thứ tự xuất hiện."""
        res = self._scrape(self.cfg.toc_url, formats=["markdown", "links"])
        markdown = res["markdown"]
        meta = res["metadata"]

        pattern = re.compile(self.cfg.chapter_link_pattern)
        chapters: list[Chapter] = []
        seen: set[str] = set()

        # Ưu tiên link trong markdown vì giữ đúng thứ tự đọc + có tiêu đề chương.
        for m in _MD_LINK.finditer(markdown):
            text, href = m.group(1).strip(), m.group(2).strip()
            full = urljoin(self.cfg.toc_url, href)
            if not pattern.search(full) or full in seen:
                continue
            seen.add(full)
            chapters.append(Chapter(index=len(chapters) + 1, url=full, title_zh=text))

        # Fallback: dùng mảng links nếu markdown không có link nào khớp.
        if not chapters:
            for href in res["links"]:
                full = urljoin(self.cfg.toc_url, str(href))
                if not pattern.search(full) or full in seen:
                    continue
                seen.add(full)
                chapters.append(Chapter(index=len(chapters) + 1, url=full))

        if self.cfg.max_chapters and self.cfg.max_chapters > 0:
            chapters = chapters[: self.cfg.max_chapters]
        return TocResult(
            title=_meta_get(meta, "og:novel:book_name", "title", "ogTitle") or "",
            author=_meta_get(meta, "og:novel:author", "author") or "",
            description=_meta_get(meta, "description", "og:description", "ogDescription") or "",
            cover_url=_meta_get(meta, "og:image", "ogImage") or "",
            chapters=chapters,
        )

    # ---------- nội dung chương ----------
    def fetch_chapter(self, ch: Chapter) -> str:
        res = self._scrape(ch.url, formats=["markdown"])
        return self._clean(res["markdown"])

    def _clean(self, markdown: str) -> str:
        if not markdown:
            return ""
        patterns = [re.compile(p) for p in self.cfg.strip_patterns]
        lines = []
        for line in markdown.splitlines():
            if any(p.search(line) for p in patterns):
                continue
            lines.append(line)
        # Gộp nhiều dòng trống liên tiếp thành 1.
        text = "\n".join(lines)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text

    def sleep(self) -> None:
        if self.cfg.delay_seconds > 0:
            time.sleep(self.cfg.delay_seconds)

    def close(self) -> None:
        pass


class HttpCrawler:
    """Crawler thuần HTTP (requests + BeautifulSoup) — không cần API key.

    Hợp với các trang truyện tĩnh (biquge, 69shu, ...). Cấu hình selector
    qua config: content_selector, toc_selector, chapter_title_selector.
    """

    def __init__(self, cfg: CrawlConfig):
        self.cfg = cfg
        try:
            import requests  # noqa: F401
            from bs4 import BeautifulSoup  # noqa: F401
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "Chưa cài requests/beautifulsoup4. "
                "Chạy: pip install requests beautifulsoup4"
            ) from e
        import requests as _requests

        self._session = _requests.Session()
        self._session.headers.update({"User-Agent": cfg.user_agent})

    def _get_soup(self, url: str):
        from bs4 import BeautifulSoup

        resp = self._session.get(url, timeout=30)
        resp.raise_for_status()
        # Đoán bảng mã (nhiều trang Trung dùng gbk/gb2312).
        if self.cfg.encoding:
            resp.encoding = self.cfg.encoding
        elif not resp.encoding or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding
        return BeautifulSoup(resp.text, "html.parser")

    # ---------- metadata ----------
    def _meta_tag(self, soup, *queries: str) -> str:
        """Lấy content của thẻ <meta> đầu tiên khớp (property hoặc name)."""
        for q in queries:
            tag = soup.find("meta", attrs={"property": q}) or soup.find("meta", attrs={"name": q})
            content = (tag.get("content") if tag else "") or ""
            if content.strip():
                return content.strip()
        return ""

    def _sel_text(self, soup, selector: str) -> str:
        if not selector:
            return ""
        node = soup.select_one(selector)
        return node.get_text(strip=True) if node is not None else ""

    def _extract_meta(self, soup) -> tuple[str, str, str, str]:
        """Trả (title, author, description, cover_url) theo ưu tiên
        selector cấu hình -> thẻ OG/meta chuẩn -> fallback."""
        title = self._sel_text(soup, self.cfg.title_selector) \
            or self._meta_tag(soup, "og:novel:book_name", "og:title")
        if not title and soup.title and soup.title.string:
            title = soup.title.string.strip()

        author = self._sel_text(soup, self.cfg.author_selector) \
            or self._meta_tag(soup, "og:novel:author", "author")

        description = self._sel_text(soup, self.cfg.desc_selector) \
            or self._meta_tag(soup, "og:description", "description")

        cover_url = ""
        if self.cfg.cover_selector:
            img = soup.select_one(self.cfg.cover_selector)
            if img is not None:
                src = img.get("src") or img.get("data-src") or ""
                cover_url = urljoin(self.cfg.toc_url, src.strip()) if src else ""
        if not cover_url:
            og_img = self._meta_tag(soup, "og:image")
            cover_url = urljoin(self.cfg.toc_url, og_img) if og_img else ""

        return title, author, description, cover_url

    # ---------- mục lục ----------
    def fetch_toc(self) -> TocResult:
        soup = self._get_soup(self.cfg.toc_url)
        title, author, description, cover_url = self._extract_meta(soup)

        scope = soup
        if self.cfg.toc_selector:
            found = soup.select_one(self.cfg.toc_selector)
            if found is not None:
                scope = found

        pattern = re.compile(self.cfg.chapter_link_pattern)
        pairs: list[tuple[str, str]] = []
        for a in scope.find_all("a", href=True):
            full = urljoin(self.cfg.toc_url, a["href"].strip())
            if pattern.search(full):
                pairs.append((full, a.get_text(strip=True)))

        chapters = [
            Chapter(index=i, url=url, title_zh=text)
            for i, (url, text) in enumerate(_dedupe_keep_last(pairs), 1)
        ]
        if self.cfg.max_chapters and self.cfg.max_chapters > 0:
            chapters = chapters[: self.cfg.max_chapters]
        return TocResult(
            title=title,
            author=author,
            description=description,
            cover_url=cover_url,
            chapters=chapters,
        )

    # ---------- nội dung chương ----------
    def fetch_chapter(self, ch: Chapter) -> str:
        soup = self._get_soup(ch.url)
        node = None
        if self.cfg.content_selector:
            node = soup.select_one(self.cfg.content_selector)
        if node is None:
            # Fallback: thử vài id/class phổ biến của truyện Trung.
            for sel in ("#content", "#chaptercontent", ".content", ".read-content",
                        "#booktext", "#TextContent", ".showtxt"):
                node = soup.select_one(sel)
                if node is not None:
                    break
        if node is None:
            return ""

        # Bỏ script/style và các thẻ điều hướng.
        for tag in node(["script", "style", "a", "ins"]):
            tag.decompose()

        # <br> -> xuống dòng; mỗi <p> là một đoạn.
        for br in node.find_all("br"):
            br.replace_with("\n")
        paras = [p.get_text(strip=True) for p in node.find_all("p")]
        if paras:
            text = "\n\n".join(p for p in paras if p)
        else:
            text = node.get_text("\n", strip=True)
        return self._clean(text)

    def _clean(self, text: str) -> str:
        if not text:
            return ""
        patterns = [re.compile(p) for p in self.cfg.strip_patterns]
        lines = [ln for ln in text.splitlines()
                 if not any(p.search(ln) for p in patterns)]
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
        return text

    def sleep(self) -> None:
        if self.cfg.delay_seconds > 0:
            time.sleep(self.cfg.delay_seconds)

    def close(self) -> None:
        pass


class Crawl4AICrawler:
    """Crawler dùng Crawl4AI (AsyncWebCrawler, chạy trình duyệt thật).

    Mạnh hơn engine http: render JavaScript, vượt bot detection (magic mode),
    trả Markdown sạch. API của Crawl4AI là async; lớp này giữ một event loop +
    một AsyncWebCrawler dùng lại xuyên suốt để khỏi mở/đóng trình duyệt mỗi chương.
    """

    def __init__(self, cfg: CrawlConfig):
        self.cfg = cfg
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "Chưa cài crawl4ai. Chạy: pip install crawl4ai && crawl4ai-setup"
            ) from e
        import asyncio

        self._asyncio = asyncio
        self._loop = asyncio.new_event_loop()
        browser_cfg = BrowserConfig(headless=cfg.headless, user_agent=cfg.user_agent)
        self._crawler = AsyncWebCrawler(config=browser_cfg)
        self._loop.run_until_complete(self._crawler.__aenter__())

    def _run_cfg(self, css_selector: str | None):
        from crawl4ai import CacheMode, CrawlerRunConfig

        kwargs: dict = {"cache_mode": CacheMode.BYPASS}
        if css_selector:
            kwargs["css_selector"] = css_selector
        if self.cfg.js_code:
            kwargs["js_code"] = self.cfg.js_code
        return CrawlerRunConfig(**kwargs)

    def _arun(self, url: str, css_selector: str | None = None):
        cfg = self._run_cfg(css_selector)
        coro = self._crawler.arun(url=url, config=cfg, magic=self.cfg.magic)
        return self._loop.run_until_complete(coro)

    @staticmethod
    def _markdown(result) -> str:
        md = getattr(result, "markdown", "") or ""
        # crawl4ai mới: markdown là object có .raw_markdown
        return getattr(md, "raw_markdown", md) if not isinstance(md, str) else md

    # ---------- mục lục ----------
    def fetch_toc(self) -> TocResult:
        result = self._arun(self.cfg.toc_url)
        meta = getattr(result, "metadata", {}) or {}

        links = getattr(result, "links", {}) or {}
        internal = links.get("internal", []) if isinstance(links, dict) else []
        pattern = re.compile(self.cfg.chapter_link_pattern)
        pairs: list[tuple[str, str]] = []
        for link in internal:
            href = _get(link, "href", "") or ""
            full = urljoin(self.cfg.toc_url, href.strip())
            if href and pattern.search(full):
                text = (_get(link, "text", "") or "").strip()
                pairs.append((full, text))
        # Fallback: bóc link từ markdown nếu không có internal links.
        if not pairs:
            for m in _MD_LINK.finditer(self._markdown(result)):
                full = urljoin(self.cfg.toc_url, m.group(2).strip())
                if pattern.search(full):
                    pairs.append((full, m.group(1).strip()))

        chapters = [
            Chapter(index=i, url=url, title_zh=text)
            for i, (url, text) in enumerate(_dedupe_keep_last(pairs), 1)
        ]
        if self.cfg.max_chapters and self.cfg.max_chapters > 0:
            chapters = chapters[: self.cfg.max_chapters]

        cover_url = _meta_get(meta, "og:image", "image")
        if cover_url:
            cover_url = urljoin(self.cfg.toc_url, cover_url)
        return TocResult(
            title=_meta_get(meta, "og:novel:book_name", "title", "og:title"),
            author=_meta_get(meta, "og:novel:author", "author"),
            description=_meta_get(meta, "description", "og:description"),
            cover_url=cover_url,
            chapters=chapters,
        )

    # ---------- nội dung chương ----------
    def fetch_chapter(self, ch: Chapter) -> str:
        result = self._arun(ch.url, css_selector=self.cfg.content_selector or None)
        return self._clean(self._markdown(result))

    def _clean(self, markdown: str) -> str:
        if not markdown:
            return ""
        patterns = [re.compile(p) for p in self.cfg.strip_patterns]
        lines = [ln for ln in markdown.splitlines()
                 if not any(p.search(ln) for p in patterns)]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()

    def sleep(self) -> None:
        if self.cfg.delay_seconds > 0:
            time.sleep(self.cfg.delay_seconds)

    def close(self) -> None:
        try:
            self._loop.run_until_complete(
                self._crawler.__aexit__(None, None, None)
            )
        finally:
            self._loop.close()


def make_crawler(cfg: CrawlConfig) -> Crawler:
    engine = (cfg.engine or "http").lower()
    if engine == "http":
        return HttpCrawler(cfg)
    if engine == "crawl4ai":
        return Crawl4AICrawler(cfg)
    if engine == "firecrawl":
        return FirecrawlCrawler(cfg)
    raise ValueError(
        f"crawl.engine không hợp lệ: {cfg.engine!r} (http|crawl4ai|firecrawl)"
    )
