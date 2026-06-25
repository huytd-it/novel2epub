"""Crawl mục lục + nội dung chương.

Hai engine:
  - http       : requests + BeautifulSoup, KHÔNG cần API key (mặc định, free).
  - crawl4ai   : Crawl4AI (Playwright browser) cho site JS-render hoặc bot detection.

Cả hai cùng trả về nội dung dạng văn bản/markdown đơn giản để bước dịch xử lý.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urljoin

from .config import CliTranslatorConfig, CrawlConfig
from .storage import Chapter
from .toc import mark_duplicate_chapters, missing_metadata

# [text](url)
_MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


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


def _get(obj, key, default=None):
    """Lấy thuộc tính từ dict hoặc object một cách an toàn."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


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
    # (vì extract có thể mutate page_obj — vd HttpCrawler._extract_text
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

    Hỗ trợ 2 dạng ``page_obj``:
      - BeautifulSoup (HttpCrawler)
      - crawl4ai ``CrawlResult`` (Crawl4AICrawler) — dùng ``links`` +
        ``markdown`` fallback.
    """
    if page_obj is None:
        return ""
    # BeautifulSoup has .select_one; crawl4ai result does not.
    select_one = getattr(page_obj, "select_one", None)
    if select_one is not None:
        node = select_one(selector)
        if node is None:
            return ""
        href = node.get("href")
        if href:
            return str(href).strip()
        return ""
    # crawl4ai result: search internal links for one whose ``text`` or
    # ``title`` matches the selector (best-effort) or whose href appears
    # in a "next" / "pager_next" pattern.
    links = getattr(page_obj, "links", None) or {}
    if isinstance(links, dict):
        internal = links.get("internal", []) or []
    else:
        internal = list(links) if links else []
    sel = selector.lstrip(".").lstrip("#").lower()
    for link in internal:
        href = (_get(link, "href", "") or "").strip()
        if not href or href.startswith("javascript:") or href.startswith("#"):
            continue
        if sel in (href.lower(), sel):
            return href
    return ""





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


class HttpCrawler:
    """Crawler thuần HTTP (requests + BeautifulSoup) — không cần API key.

    Hợp với các trang truyện tĩnh (biquge, 69shu, ...). Cấu hình selector
    qua config: content_selector, toc_selector, chapter_title_selector.
    """

    def __init__(self, cfg: CrawlConfig):
        self.cfg = cfg
        self._fallback_cli: CliTranslatorConfig | None = None
        self._last_response_text: str = ""
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
        # 429 (Too Many Requests) / 503 (thường gặp khi anti-bot tạm chặn) ->
        # ném RateLimitError mang theo Retry-After để tầng retry lùi dần.
        if resp.status_code in (429, 503):
            raise RateLimitError(
                f"Bị chặn do quá nhiều request: HTTP {resp.status_code} {resp.reason}",
                retry_after=_parse_retry_after(resp.headers.get("Retry-After")),
            )
        resp.raise_for_status()
        # Đoán bảng mã (nhiều trang Trung dùng gbk/gb2312).
        if self.cfg.encoding:
            resp.encoding = self.cfg.encoding
        elif not resp.encoding or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding
        self._last_response_text = resp.text
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

        def fetch_page(url: str):
            return self._get_soup(url)

        def extract_text(page_obj) -> str:
            return self._extract_text(page_obj)

        css_resolver = _make_css_resolver(self.cfg)
        pattern_resolver = _next_page_url_from_pattern(self.cfg)
        call_count = [0]

        def next_page_url(current_url: str, page_obj) -> str | None:
            # Mỗi engine pass: thử CSS trước, fallback pattern.
            nxt = css_resolver(current_url, page_obj) if css_resolver else None
            if nxt:
                call_count[0] += 1
                return nxt
            if pattern_resolver:
                nxt = pattern_resolver(current_url, page_obj)
                if nxt:
                    call_count[0] += 1
                    return nxt
            return None

        text = fetch_chapter_paginated(
            self.cfg,
            ch,
            fetch_page=fetch_page,
            extract_text=extract_text,
            next_page_url=next_page_url,
        )
        if text or not self.cfg.ai_fallback or self.cfg._cli_fallback is None:
            return text
        return self._ai_fallback_extract(ch.url)

    def _fetch_chapter_single(self, ch: Chapter) -> str:
        soup = self._get_soup(ch.url)
        text = self._extract_text(soup)
        if text or not self.cfg.ai_fallback or self.cfg._cli_fallback is None:
            return text
        return self._ai_fallback_extract(ch.url)

    def _extract_text(self, soup) -> str:
        node = None
        if self.cfg.content_selector:
            node = soup.select_one(self.cfg.content_selector)
        if node is None:
            for sel in ("#content", "#chaptercontent", ".content", ".read-content",
                        "#booktext", "#TextContent", ".showtxt"):
                node = soup.select_one(sel)
                if node is not None:
                    break
        if node is None:
            return ""

        for tag in node(["script", "style", "a", "ins"]):
            tag.decompose()

        for br in node.find_all("br"):
            br.replace_with("\n")
        paras = [p.get_text(strip=True) for p in node.find_all("p")]
        if paras:
            text = "\n\n".join(p for p in paras if p)
        else:
            text = node.get_text("\n", strip=True)
        return self._clean(text)

    def _ai_fallback_extract(self, url: str) -> str:
        from . import cli_runner
        from .presets.go import GO_EXTRACT_PROMPT

        html = self._last_response_text
        if not html:
            return ""
        html = html[:self.cfg.ai_fallback_max_html]
        prompt = GO_EXTRACT_PROMPT.format(html=html)
        try:
            return cli_runner.run_cli(self.cfg._cli_fallback, prompt)
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
        pass


class Crawl4AICrawler:
    """Crawler dùng Crawl4AI (AsyncWebCrawler, chạy trình duyệt thật).

    Mạnh hơn engine http: render JavaScript, vượt bot detection (magic mode),
    trả Markdown sạch. API của Crawl4AI là async; lớp này giữ một event loop +
    một AsyncWebCrawler dùng lại xuyên suốt để khỏi mở/đóng trình duyệt mỗi chương.
    """

    def __init__(self, cfg: CrawlConfig):
        self.cfg = cfg
        self._last_result = None
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "Chưa cài crawl4ai. Chạy: pip install crawl4ai && crawl4ai-setup"
            ) from e
        import asyncio

        self._asyncio = asyncio
        self._loop = asyncio.new_event_loop()
        browser_cfg = BrowserConfig(
            headless=cfg.headless,
            user_agent=cfg.user_agent,
            enable_stealth=cfg.stealth,
        )
        self._crawler = AsyncWebCrawler(config=browser_cfg)
        self._loop.run_until_complete(self._crawler.__aenter__())

    def _run_cfg(self, css_selector: str | None):
        from crawl4ai import CacheMode, CrawlerRunConfig

        kwargs: dict = {"cache_mode": CacheMode.BYPASS, "magic": self.cfg.magic}
        if css_selector:
            kwargs["css_selector"] = css_selector
        if self.cfg.js_code:
            kwargs["js_code"] = self.cfg.js_code
        return CrawlerRunConfig(**kwargs)

    def _arun(self, url: str, css_selector: str | None = None):
        cfg = self._run_cfg(css_selector)
        coro = self._crawler.arun(url=url, config=cfg)
        result = self._loop.run_until_complete(coro)
        self._raise_if_blocked(result)
        return result

    @staticmethod
    def _raise_if_blocked(result) -> None:
        """crawl4ai thường KHÔNG ném exception mà trả result.success=False kèm
        error_message khi bị anti-bot/429. Chuyển thành RateLimitError để tầng
        retry lùi dần thay vì âm thầm coi như chương rỗng."""
        if getattr(result, "success", True):
            return
        status = getattr(result, "status_code", None)
        err_msg = getattr(result, "error_message", "") or ""
        if status == 429 or _RATE_LIMIT_SIGNS.search(err_msg):
            raise RateLimitError(
                f"Bị chặn anti-bot/429: {err_msg or f'HTTP {status}'}"
            )

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
        cover_url = _meta_get(meta, "og:image", "image")
        if cover_url:
            cover_url = urljoin(self.cfg.toc_url, cover_url)
        title = _meta_get(meta, "og:novel:book_name", "title", "og:title")
        author = _meta_get(meta, "og:novel:author", "author")
        description = _meta_get(meta, "description", "og:description")
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
            return self._arun(url, css_selector=self.cfg.content_selector or None)

        def extract_text(page_obj) -> str:
            return self._clean(self._markdown(page_obj))

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
        if text or not self.cfg.ai_fallback or self.cfg._cli_fallback is None:
            return text
        return self._ai_fallback_extract(ch.url)

    def _fetch_chapter_single(self, ch: Chapter) -> str:
        self._last_result = self._arun(ch.url, css_selector=self.cfg.content_selector or None)
        text = self._clean(self._markdown(self._last_result))
        if text:
            return text
        if _result_success(self._last_result) and self.cfg.content_selector:
            self._last_result = self._arun(ch.url, css_selector=None)
            text = self._clean(self._markdown(self._last_result))
            if text:
                return text
        if not _result_success(self._last_result):
            _log_crawl4ai_failure(self._last_result, ch)
        if self.cfg.ai_fallback and self.cfg._cli_fallback is not None:
            return self._ai_fallback_extract(ch.url)
        return ""

    def _ai_fallback_extract(self, url: str) -> str:
        from . import cli_runner
        from .presets.go import GO_EXTRACT_PROMPT

        raw = getattr(self._last_result, "raw_html", "") or ""
        if not raw:
            return ""
        raw = raw[:self.cfg.ai_fallback_max_html]
        prompt = GO_EXTRACT_PROMPT.format(html=raw)
        try:
            return cli_runner.run_cli(self.cfg._cli_fallback, prompt)
        except Exception:
            return ""

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


def _result_success(result) -> bool:
    """Kiểm tra crawl4ai result.success an toàn (có thể result là None)."""
    return bool(getattr(result, "success", True))


def _log_crawl4ai_failure(result, ch: "Chapter") -> None:
    """Log chi tiết khi crawl4ai trả về thất bại (success=False) để dễ debug."""
    from .pipeline import _print

    status = getattr(result, "status_code", None)
    err = getattr(result, "error_message", "") or ""
    _print(
        f"[crawl]   ! crawl4ai không tải được {ch.url}: "
        f"status_code={status}, error={err!r}"
    )


class ScraplingCrawler:
    """Crawler dùng Scrapling (stealth browser, anti-bot bypass).

    Hỗ trợ 3 mode qua ``cfg.scrapling_mode``:
      - ``"fetcher"``: HTTP thuần, giả lập TLS fingerprint (nhanh, nhẹ).
      - ``"stealthy"``: Browser stealth (Camoufox), bypass Cloudflare Turnstile.
      - ``"dynamic"``: Full Playwright automation.

    Tất cả trả về Adaptor object hỗ trợ ``.css()``, ``.xpath()``, ``.find_all()``.
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

        mode = (cfg.scrapling_mode or "stealthy").lower()
        if mode == "fetcher":
            self._fetcher_cls = Fetcher
        elif mode == "dynamic":
            self._fetcher_cls = DynamicFetcher
        else:  # stealthy (mặc định)
            self._fetcher_cls = StealthyFetcher
        self._mode = mode

    # ---------- internal ----------
    def _fetch_page(self, url: str):
        """Fetch 1 URL bằng Scrapling fetcher, trả về Adaptor (response object).

        Xử lý HTTP 429 / anti-bot → raise RateLimitError để tầng retry lùi dần.
        """
        kwargs: dict = {"headless": self.cfg.headless}
        if self._mode == "stealthy":
            kwargs["network_idle"] = self.cfg.network_idle
            if self.cfg.solve_cloudflare:
                kwargs["solve_cloudflare"] = True
        elif self._mode == "dynamic":
            kwargs["network_idle"] = self.cfg.network_idle
        elif self._mode == "fetcher":
            if self.cfg.impersonate:
                kwargs["impersonate"] = self.cfg.impersonate
            # Fetcher dùng method .get() thay vì .fetch()
            kwargs.pop("headless", None)

        try:
            if self._mode == "fetcher":
                page = self._fetcher_cls.get(url, **kwargs)
            else:
                page = self._fetcher_cls.fetch(url, **kwargs)
        except Exception as e:
            msg = str(e).lower()
            if "429" in msg or "too many" in msg or "rate" in msg or "blocked" in msg:
                raise RateLimitError(
                    f"Bị chặn anti-bot/429: {e}"
                ) from e
            raise

        # Lưu raw HTML cho AI fallback
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
            text = el.text if hasattr(el, 'text') else ""
            return text.strip() if text else ""
        return ""

    def _extract_meta(self, page) -> tuple[str, str, str, str]:
        """Trả (title, author, description, cover_url) theo ưu tiên
        selector cấu hình -> thẻ OG/meta chuẩn -> fallback."""
        title = self._sel_text(page, self.cfg.title_selector) \
            or self._meta_tag(page, "og:novel:book_name", "og:title")
        if not title:
            title_tags = page.css("title")
            if title_tags:
                el = title_tags[0] if hasattr(title_tags, '__getitem__') else title_tags
                text = el.text if hasattr(el, 'text') else ""
                title = text.strip() if text else ""

        author = self._sel_text(page, self.cfg.author_selector) \
            or self._meta_tag(page, "og:novel:author", "author")

        description = self._sel_text(page, self.cfg.desc_selector) \
            or self._meta_tag(page, "og:description", "description")

        cover_url = ""
        if self.cfg.cover_selector:
            imgs = page.css(self.cfg.cover_selector)
            if imgs:
                img = imgs[0] if hasattr(imgs, '__getitem__') else imgs
                src = img.attrib.get("src") or img.attrib.get("data-src") or ""
                cover_url = urljoin(self.cfg.toc_url, src.strip()) if src else ""
        if not cover_url:
            og_img = self._meta_tag(page, "og:image")
            cover_url = urljoin(self.cfg.toc_url, og_img) if og_img else ""

        return title, author, description, cover_url

    # ---------- mục lục ----------
    def fetch_toc(self) -> TocResult:
        page = self._fetch_page(self.cfg.toc_url)
        title, author, description, cover_url = self._extract_meta(page)

        scope = page
        if self.cfg.toc_selector:
            found = page.css(self.cfg.toc_selector)
            if found:
                scope = found[0] if hasattr(found, '__getitem__') else found

        pattern = re.compile(self.cfg.chapter_link_pattern)
        pairs: list[tuple[str, str]] = []
        links = scope.css("a[href]")
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
            Chapter(index=i, url=url, title_zh=text)
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
        if text or not self.cfg.ai_fallback or self.cfg._cli_fallback is None:
            return text
        return self._ai_fallback_extract(ch.url)

    def _fetch_chapter_single(self, ch: Chapter) -> str:
        page = self._fetch_page(ch.url)
        text = self._extract_text(page)
        if text or not self.cfg.ai_fallback or self.cfg._cli_fallback is None:
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

        # Lấy text từ node, dọn thẻ rác
        # Scrapling Adaptor hỗ trợ .text (text gộp) và .get_text()
        text = ""
        # Thử lấy từ các thẻ <p>
        paras = node.css("p")
        if paras:
            parts = []
            for p in paras:
                p_text = p.text if hasattr(p, 'text') else ""
                if p_text and p_text.strip():
                    parts.append(p_text.strip())
            if parts:
                text = "\n\n".join(parts)
        if not text:
            text = node.text if hasattr(node, 'text') else ""
            text = text or ""

        return self._clean(text)

    def _ai_fallback_extract(self, url: str) -> str:
        from . import cli_runner
        from .presets.go import GO_EXTRACT_PROMPT

        html = self._last_response_html
        if not html:
            return ""
        html = html[:self.cfg.ai_fallback_max_html]
        prompt = GO_EXTRACT_PROMPT.format(html=html)
        try:
            return cli_runner.run_cli(self.cfg._cli_fallback, prompt)
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
    engine = (cfg.engine or "http").lower()
    if engine == "http":
        return HttpCrawler(cfg)
    if engine == "crawl4ai":
        return Crawl4AICrawler(cfg)
    if engine == "scrapling":
        return ScraplingCrawler(cfg)
    if engine == "firecrawl":
        raise ValueError(
            f"crawl.engine={cfg.engine!r} has been removed. "
            "Migration: set engine: crawl4ai (or http) and remove api_key."
        )
    raise ValueError(
        f"crawl.engine không hợp lệ: {cfg.engine!r} (http|crawl4ai|scrapling)"
    )
