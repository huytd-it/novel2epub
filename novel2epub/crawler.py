"""Crawl mục lục + nội dung chương.

Engine duy nhất: Scrapling (3 mode: fetcher/stealthy/dynamic).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urljoin

from .config import CrawlConfig
from .storage import Chapter
from .toc import mark_duplicate_chapters, missing_metadata


def _detect_encoding(raw: bytes) -> str:
    """Detect HTML encoding from meta charset / BOM, falling back to charset_normalizer."""
    import re as _re

    head = raw[:4096]
    # <meta charset="gbk">
    m = _re.search(rb'<meta[^>]*\bcharset=["\']?([^"\'\s;>]+)', head, _re.IGNORECASE)
    if m:
        return m.group(1).decode("ascii", errors="ignore").strip()
    # <meta content="text/html; charset=gbk">
    m = _re.search(rb'content=["\'][^"\']*charset=([^"\'\s;]+)', head, _re.IGNORECASE)
    if m:
        return m.group(1).decode("ascii", errors="ignore").strip()
    if head[:3] == b'\xef\xbb\xbf':
        return "utf-8-sig"
    if head[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return "utf-16"
    try:
        from charset_normalizer import from_bytes
        results = from_bytes(raw[:8192])
        if results:
            best = results.best()
            if best:
                return best.encoding
    except ImportError:
        pass
    return "utf-8"


class RateLimitError(Exception):
    """Trang chặn do quá nhiều request (HTTP 429) hoặc anti-bot protection.

    Mang theo `retry_after` (giây) nếu server gửi header `Retry-After`, để tầng
    retry chờ đúng khoảng server yêu cầu thay vì backoff tự đoán.
    """

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


# Dấu hiệu bị giới hạn tốc độ trong message lỗi (vd lỗi text từ crawl4ai).
_RATE_LIMIT_SIGNS = re.compile(
    r"429|too many requests|rate.?limit|anti-bot|blocked by", re.IGNORECASE
)


def _parse_retry_after(value: str | None) -> float | None:
    """Đọc header Retry-After: dạng số giây (phổ biến nhất) -> float.

    Bỏ qua dạng HTTP-date (hiếm với 429) để giữ logic đơn giản; khi đó tầng
    retry tự dùng backoff.
    """
    if not value:
        return None
    value = value.strip()
    try:
        secs = float(value)
        return secs if secs >= 0 else None
    except ValueError:
        return None


def is_rate_limited(err: BaseException) -> tuple[bool, float | None]:
    """Phán đoán một exception có phải do bị giới hạn tốc độ / anti-bot không.

    Trả (matched, retry_after_seconds). Nhận diện cả RateLimitError (đã gắn sẵn
    retry_after) lẫn lỗi chung có chữ '429'/'too many requests'/'anti-bot' trong
    message (vd lỗi text crawl4ai trả về)."""
    if isinstance(err, RateLimitError):
        return True, err.retry_after
    return bool(_RATE_LIMIT_SIGNS.search(str(err))), None


@dataclass
class TocResult:
    """Kết quả đọc trang mục lục: metadata truyện + danh sách chương."""

    title: str = ""
    author: str = ""
    description: str = ""
    cover_url: str = ""
    source_url: str = ""
    metadata_missing: list[str] = field(default_factory=list)
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

_CHAPTER_BASE_ID_RE = re.compile(r"(\d+)(?:_\d+)?\.\w+(?:[?#].*)?$")


def _chapter_base_id(url: str) -> str | None:
    """Rút "ID chương" từ URL dạng ``.../<id>.html`` hoặc ``.../<id>_<page>.html``.

    Trả ``None`` nếu URL không khớp dạng này (không đủ tin cậy để so sánh,
    caller nên bỏ qua kiểm tra ranh giới chương trong trường hợp đó).
    """
    m = _CHAPTER_BASE_ID_RE.search(url)
    return m.group(1) if m else None


def _crosses_chapter_boundary(base_id: str | None, candidate_url: str | None) -> bool:
    """True nếu ``candidate_url`` trỏ sang một chương khác với ``base_id``.

    Một số site tái dùng cùng selector/class "next" cho cả hai ý nghĩa:
    trang kế của chương hiện tại VÀ link sang chương tiếp theo (khi trang
    hiện tại là trang cuối). Nếu rút được ID chương từ cả URL gốc và URL
    ứng viên mà hai ID khác nhau, coi đó là đã sang chương khác — không
    được dùng làm "trang kế tiếp".
    """
    if base_id is None or candidate_url is None:
        return False
    candidate_id = _chapter_base_id(candidate_url)
    return candidate_id is not None and candidate_id != base_id


def fetch_chapter_paginated(
    cfg: CrawlConfig,
    ch: Chapter,
    *,
    fetch_page,
    extract_text,
    next_page_url,
) -> str:
    """Tải và ghép nội dung nhiều trang con của một chương.

    Mỗi engine truyền vào 3 closure:
      - ``fetch_page(url) -> page_obj``: tải URL, trả về đối tượng engine
        (BeautifulSoup, crawl4ai result, dict scrape, ...).
      - ``extract_text(page_obj) -> str``: trích nội dung chương đã làm sạch.
      - ``next_page_url(url, page_obj) -> str | None``: tìm URL trang kế
        tiếp. Trả ``None`` nếu không có.

    Vòng lặp dừng khi gặp bất kỳ điều kiện nào:
      1. ``next_page_url`` trả về ``None``.
      2. URL đã xuất hiện trong chương này (tránh vòng lặp vô hạn).
      3. Nội dung trang mới trùng với một trang đã tải.
      4. Đã đạt ``cfg.max_pages_per_chapter`` trang.
      5. URL kế tiếp trỏ sang một chương khác (xem ``_crosses_chapter_boundary``).
    """
    max_pages = max(1, int(getattr(cfg, "max_pages_per_chapter", 1) or 1))

    current_url = ch.url
    seen_urls: set[str] = {current_url}
    base_chapter_id = _chapter_base_id(ch.url)

    # Lần fetch đầu: lấy text + khám phá next URL TRƯỚC khi extract
    # (vì extract có thể mutate page_obj — vd ScraplingCrawler._extract_text
    # decompose thẻ <a>).
    try:
        current_page = fetch_page(current_url)
    except Exception:
        return ""
    try:
        next_url = next_page_url(current_url, current_page)
    except Exception:
        next_url = None
    if _crosses_chapter_boundary(base_chapter_id, next_url):
        next_url = None
    first_text = (extract_text(current_page) or "").strip()
    if not first_text:
        return first_text

    pages: list[str] = [first_text]
    title_line = first_text.splitlines()[0].strip() if first_text else ""

    for _ in range(max_pages - 1):
        if not next_url or next_url in seen_urls:
            break
        seen_urls.add(next_url)
        current_url = next_url
        try:
            current_page = fetch_page(current_url)
        except Exception:
            break
        try:
            next_url = next_page_url(current_url, current_page)
        except Exception:
            next_url = None
        if _crosses_chapter_boundary(base_chapter_id, next_url):
            next_url = None
        new_text = (extract_text(current_page) or "").strip()
        if not new_text or new_text in pages:
            break
        if title_line:
            lines = new_text.splitlines()
            if lines and lines[0].strip() == title_line:
                new_text = "\n".join(lines[1:]).lstrip()
        pages.append(new_text)

    return "\n\n".join(p for p in pages if p)


def _next_page_url_from_html(current_url: str, page_obj, cfg: CrawlConfig):
    """Tìm URL trang kế tiếp từ CSS selector trong trang hiện tại.

    Dùng cho cả 3 engine — bóc link từ ``page_obj`` dù nó là BeautifulSoup,
    crawl4ai result hay dict scrape. Trả ``None`` nếu không tìm thấy hoặc
    link rỗng / là ``javascript:`` / không phải HTTP(S).
    """
    selector = (cfg.next_page_selector or "").strip()
    if not selector:
        return None
    href = _extract_href(page_obj, selector)
    if not href or href.startswith("javascript:") or href.startswith("#"):
        return None
    return urljoin(current_url, href.strip())


def _make_css_resolver(cfg: CrawlConfig):
    """Trả về closure ``(url, page_obj) -> str | None`` dùng CSS selector.

    Trả ``None`` nếu ``cfg.next_page_selector`` rỗng (caller sẽ thử
    pattern resolver tiếp theo).
    """
    selector = (cfg.next_page_selector or "").strip()
    if not selector:
        return None

    def _resolve(current_url: str, page_obj) -> str | None:
        href = _extract_href(page_obj, selector)
        if not href or href.startswith("javascript:") or href.startswith("#"):
            return None
        return urljoin(current_url, href.strip())

    return _resolve


def _next_page_url_from_pattern(cfg: CrawlConfig):
    """Tạo closure sinh URL kế tiếp từ ``next_page_url_pattern``.

    Pattern phải chứa đúng 1 capturing group — group này là **số trang
    hiện tại**. Closure thay text của group trong URL bằng số tăng dần
    (bắt đầu từ 2) và trả về URL mới.

    Ví dụ pattern ``_(\\d+)\\.html$`` trên URL ``ch7_1.html``:
    - Lần 1 (n=2): thay ``1`` bằng ``2`` → ``ch7_2.html``.
    - Lần 2 (n=3): thay ``2`` bằng ``3`` → ``ch7_3.html``.

    Trả ``None`` khi pattern không khớp URL hiện tại.
    """
    pattern = (cfg.next_page_url_pattern or "").strip()
    if not pattern:
        return None
    pat = re.compile(pattern)
    counter = [2]

    def _resolver(current_url: str, page_obj) -> str | None:
        m = pat.search(current_url)
        if not m:
            return None
        n = counter[0]
        counter[0] = n + 1
        # Lấy text đã match (literal, không chứa escape regex) rồi thay
        # group 1 bằng số mới.
        matched = m.group(0)
        new_matched = (
            matched[: m.start(1) - m.start()]
            + str(n)
            + matched[m.end(1) - m.start():]
        )
        return current_url[: m.start()] + new_matched + current_url[m.end():]

    return _resolver


def _extract_href(page_obj, selector: str) -> str:
    """Trích href từ phần tử đầu tiên khớp ``selector``.

    Hỗ trợ Scrapling Adaptor (có ``.css()``) và các object generic.
    """
    if page_obj is None:
        return ""
    css = getattr(page_obj, "css", None)
    if css is not None:
        results = css(selector)
        if results:
            el = results[0] if hasattr(results, '__getitem__') else results
            href = el.attrib.get("href", "") if hasattr(el, 'attrib') else ""
            return href.strip()
    select_one = getattr(page_obj, "select_one", None)
    if select_one is not None:
        node = select_one(selector)
        if node is None:
            return ""
        href = node.get("href")
        if href:
            return str(href).strip()
    return ""









class ScraplingCrawler:
    """Crawler dùng Scrapling — engine duy nhất, 3 mode.

    - ``fetcher``: HTTP thuần + TLS fingerprint (nhanh, nhẹ, mặc định).
    - ``stealthy``: Browser Camoufox, bypass Cloudflare Turnstile.
    - ``dynamic``: Full Playwright automation.

    Cấu hình qua ``cfg.scrapling`` (ScraplingConfig).
    Trả về Adaptor object hỗ trợ ``.css()``, ``.xpath()``.
    """

    def __init__(self, cfg: CrawlConfig):
        self.cfg = cfg
        self._last_response_html: str = ""
        try:
            from scrapling.fetchers import (  # noqa: F401
                DynamicFetcher,
                Fetcher,
                StealthyFetcher,
            )
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "Chưa cài scrapling. "
                "Chạy: pip install scrapling[fetchers] && scrapling install"
            ) from e

        mode = (cfg.scrapling.mode or "fetcher").lower()
        if mode == "fetcher":
            self._fetcher_cls = Fetcher
        elif mode == "dynamic":
            self._fetcher_cls = DynamicFetcher
        else:  # stealthy
            self._fetcher_cls = StealthyFetcher
        self._mode = mode

    # ---------- internal ----------
    def _reparse_with_detected_encoding(self, url: str, **kwargs):
        """Bypass scrapling parsing: fetch raw bytes via curl_cffi, detect encoding, build Selector."""
        from curl_cffi.requests import Session as CurlSession
        from scrapling.parser import Selector

        impersonate = kwargs.get("impersonate", "chrome")
        with CurlSession() as s:
            resp = s.get(url, impersonate=impersonate or "chrome")
            body = resp.content
        if not body:
            return Selector(content=b"<html/>", url=url, encoding="utf-8")
        encoding = _detect_encoding(body)
        return Selector(content=body, url=url, encoding=encoding)

    def _fetch_with_encoding(self, page):
        """Re-parse page with detected encoding when UTF-8 decode fails."""
        from scrapling.parser import Selector

        body = getattr(page, "body", None)
        if body is None:
            body = getattr(page, "_raw_body", b"")
        if not isinstance(body, bytes) or not body:
            return page

        encoding = _detect_encoding(body)
        if encoding and encoding.lower() not in ("utf-8", "ascii", ""):
            url = getattr(page, "url", "")
            return Selector(content=body, url=url, encoding=encoding)
        return page

    def _fetch_page(self, url: str):
        """Fetch 1 URL bằng Scrapling fetcher, trả về Adaptor.

        Xử lý HTTP 429 / anti-bot → raise RateLimitError để tầng retry lùi dần.
        """
        s = self.cfg.scrapling
        kwargs: dict = {"headless": self.cfg.headless}
        if self._mode == "stealthy":
            kwargs["network_idle"] = s.network_idle
            if s.solve_cloudflare:
                kwargs["solve_cloudflare"] = True
        elif self._mode == "dynamic":
            kwargs["network_idle"] = s.network_idle
        elif self._mode == "fetcher":
            if s.impersonate:
                kwargs["impersonate"] = s.impersonate
            kwargs.pop("headless", None)

        try:
            if self._mode == "fetcher":
                page = self._fetcher_cls.get(url, **kwargs)
            else:
                page = self._fetcher_cls.fetch(url, **kwargs)
        except UnicodeDecodeError:
            page = self._reparse_with_detected_encoding(url, **kwargs)
        except Exception as e:
            msg = str(e).lower()
            if "429" in msg or "too many" in msg or "rate" in msg or "blocked" in msg:
                raise RateLimitError(
                    f"Bị chặn anti-bot/429: {e}"
                ) from e
            raise

        # Lưu raw HTML cho AI fallback
        try:
            self._last_response_html = getattr(page, "html_content", "") or ""
        except UnicodeDecodeError:
            page = self._fetch_with_encoding(page)
            self._last_response_html = getattr(page, "html_content", "") or ""
        if not self._last_response_html:
            self._last_response_html = str(page) if page else ""

        # Kiểm tra status code nếu có
        status = getattr(page, "status", None)
        if status and status in (429, 503):
            raise RateLimitError(f"Bị chặn: HTTP {status}")

        return page

    def _meta_tag(self, page, *queries: str) -> str:
        """Lấy content của thẻ <meta> đầu tiên khớp (property hoặc name)."""
        for q in queries:
            tags = page.css(f'meta[property="{q}"]') or page.css(f'meta[name="{q}"]')
            if tags:
                tag = tags[0] if hasattr(tags, '__getitem__') else tags
                content = tag.attrib.get("content", "")
                if content and content.strip():
                    return content.strip()
        return ""

    def _sel_text(self, page, selector: str) -> str:
        if not selector:
            return ""
        results = page.css(selector)
        if results:
            el = results[0] if hasattr(results, '__getitem__') else results
            if hasattr(el, "get_all_text"):
                return el.get_all_text(strip=True)
            text = el.text if hasattr(el, 'text') else ""
            return text.strip() if text else ""
        return ""

    def _extract_meta(self, page) -> tuple[str, str, str, str]:
        """Trả (title, author, description, cover_url) từ thẻ OG/meta chuẩn."""
        title = self._meta_tag(page, "og:novel:book_name", "og:title")
        if not title:
            title_tags = page.css("title")
            if title_tags:
                el = title_tags[0] if hasattr(title_tags, '__getitem__') else title_tags
                text = el.text if hasattr(el, 'text') else ""
                title = text.strip() if text else ""

        author = self._meta_tag(page, "og:novel:author", "author")
        description = self._meta_tag(page, "og:description", "description")

        cover_url = ""
        og_img = self._meta_tag(page, "og:image")
        cover_url = urljoin(self.cfg.toc_url, og_img) if og_img else ""

        return title, author, description, cover_url

    # ---------- mục lục ----------
    def fetch_toc(self) -> TocResult:
        page = self._fetch_page(self.cfg.toc_url)
        title, author, description, cover_url = self._extract_meta(page)

        pattern = re.compile(self.cfg.chapter_link_pattern)
        pairs: list[tuple[str, str]] = []
        links = page.css("a[href]")
        if links:
            for a in links:
                href = a.attrib.get("href", "")
                if not href:
                    continue
                full = urljoin(self.cfg.toc_url, href.strip())
                if pattern.search(full):
                    text = a.text if hasattr(a, 'text') else ""
                    pairs.append((full, (text or "").strip()))

        chapters = [
            Chapter(index=i, url=url, title=text)
            for i, (url, text) in enumerate(_dedupe_keep_last(pairs), 1)
        ]
        return TocResult(
            title=title,
            author=author,
            description=description,
            cover_url=cover_url,
            source_url=self.cfg.toc_url,
            metadata_missing=missing_metadata(title, author, description),
            chapters=mark_duplicate_chapters(chapters),
        )

    # ---------- nội dung chương ----------
    def fetch_chapter(self, ch: Chapter) -> str:
        if not (self.cfg.next_page_selector or self.cfg.next_page_url_pattern):
            return self._fetch_chapter_single(ch)

        css_resolver = _make_css_resolver(self.cfg)
        pattern_resolver = _next_page_url_from_pattern(self.cfg)

        def fetch_page(url: str):
            return self._fetch_page(url)

        def extract_text(page_obj) -> str:
            return self._extract_text(page_obj)

        def next_page_url(current_url: str, page_obj) -> str | None:
            if css_resolver:
                nxt = css_resolver(current_url, page_obj)
                if nxt:
                    return nxt
            if pattern_resolver:
                return pattern_resolver(current_url, page_obj)
            return None

        text = fetch_chapter_paginated(
            self.cfg,
            ch,
            fetch_page=fetch_page,
            extract_text=extract_text,
            next_page_url=next_page_url,
        )
        if text or not self.cfg.ai_fallback or self.cfg._openai_fallback is None:
            return text
        return self._ai_fallback_extract(ch.url)

    def _fetch_chapter_single(self, ch: Chapter) -> str:
        page = self._fetch_page(ch.url)
        text = self._extract_text(page)
        if text or not self.cfg.ai_fallback or self.cfg._openai_fallback is None:
            return text
        return self._ai_fallback_extract(ch.url)

    def _extract_text(self, page) -> str:
        node = None
        if self.cfg.content_selector:
            results = page.css(self.cfg.content_selector)
            if results:
                node = results[0] if hasattr(results, '__getitem__') else results
        if node is None:
            for sel in ("#content", "#chaptercontent", ".content", ".read-content",
                        "#booktext", "#TextContent", ".showtxt"):
                results = page.css(sel)
                if results:
                    node = results[0] if hasattr(results, '__getitem__') else results
                    break
        if node is None:
            return ""

        text = ""
        paras = node.css("p")
        if paras:
            parts = []
            for p in paras:
                if hasattr(p, "get_all_text"):
                    p_text = p.get_all_text(strip=True)
                else:
                    p_text = p.text if hasattr(p, 'text') else ""
                    p_text = p_text.strip() if p_text else ""
                if p_text:
                    parts.append(p_text)
            if parts:
                text = "\n\n".join(parts)
        if not text:
            if hasattr(node, "get_all_text"):
                text = node.get_all_text(strip=True)
            else:
                text = node.text if hasattr(node, 'text') else ""
                text = text.strip() if text else ""

        return self._clean(text)

    def _ai_fallback_extract(self, url: str) -> str:
        from . import openai_client
        from .presets.go import GO_EXTRACT_PROMPT

        html = self._last_response_html
        if not html:
            return ""
        html = html[:self.cfg.ai_fallback_max_html]
        prompt = GO_EXTRACT_PROMPT.format(html=html)
        try:
            return openai_client.run_chat(self.cfg._openai_fallback, prompt)
        except Exception:
            return ""

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
        pass  # Scrapling one-off fetchers không cần đóng tường minh


def make_crawler(cfg: CrawlConfig) -> Crawler:
    engine = (cfg.engine or "scrapling").lower()
    if engine == "scrapling":
        return ScraplingCrawler(cfg)
    if engine in ("http", "crawl4ai", "firecrawl"):
        raise ValueError(
            f"crawl.engine={cfg.engine!r} đã bị loại bỏ. "
            "Engine duy nhất hiện tại là 'scrapling'. "
            "Xem README.md để biết cách migration."
        )
    raise ValueError(
        f"crawl.engine không hợp lệ: {cfg.engine!r} (chỉ hỗ trợ 'scrapling')"
    )
