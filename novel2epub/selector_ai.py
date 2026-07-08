"""Dùng AI phân tích 1 URL nguồn (trang mục lục + 1 trang chương) để tự động
đề xuất CSS selector / pattern cho một `SourcePreset` mới — người dùng khỏi
phải tự mò selector bằng DevTools.

Module này CHỈ chứa helper thuần (HTML/text vào, dict ra) để dễ test và tách
khỏi I/O mạng: `app/routes/sources.py` lo phần fetch trang (ScraplingCrawler)
và gọi AI (`openai_client.run_chat`), rồi validate selector trả về lên chính
trang đã fetch. Cùng phong cách với `bulk_transfer.py`.

Các field đề xuất khớp tên field của `SourcePreset`:
- `content_selector`      — vùng chứa nội dung chương (dùng cho crawl)
- `chapter_link_pattern`  — regex Python match URL chương tuyệt đối (dùng cho crawl)
- `next_page_selector`    — link "trang sau" trong 1 chương (phân trang)
- `toc_selector`          — vùng danh sách chương ở trang mục lục
- `chapter_title_selector`— tiêu đề chương ở trang chương
- `title_selector`        — tên truyện ở trang mục lục
- `author_selector`       — tác giả
- `desc_selector`         — mô tả/giới thiệu
- `cover_selector`        — ảnh bìa
"""
from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlparse

# Field selector AI được phép đề xuất — khớp tên field SourcePreset để route
# nhét thẳng vào form. Whitelist để bỏ mọi key lạ AI có thể bịa thêm.
SELECTOR_FIELDS = (
    "content_selector",
    "chapter_link_pattern",
    "next_page_selector",
    "toc_selector",
    "chapter_title_selector",
    "title_selector",
    "author_selector",
    "desc_selector",
    "cover_selector",
)

# Thuộc tính giữ lại khi làm sạch HTML — đủ để suy ra selector (class/id),
# derive pattern link (href) và meta (property/name/content), bỏ phần còn lại
# cho gọn prompt.
_KEEP_ATTRS = {"class", "id", "href", "rel", "property", "name", "content", "src", "itemprop"}
_DROP_TAGS = ("script", "style", "noscript", "svg", "iframe", "template", "canvas", "form")

_WS_RE = re.compile(r"[ \t]{2,}")
_BLANKLINE_RE = re.compile(r"\n{3,}")


def clean_html_for_ai(html: str, max_chars: int = 16000) -> str:
    """Rút gọn HTML về phần cấu trúc quan trọng cho việc suy selector.

    Bỏ script/style/svg..., strip attribute thừa (giữ class/id/href/meta),
    gộp khoảng trắng, rồi cắt còn `max_chars` ký tự. Nếu không có bs4 thì
    fallback: strip thô bằng regex.
    """
    if not html:
        return ""
    try:
        from bs4 import BeautifulSoup, Comment
    except ImportError:  # pragma: no cover - bs4 là dependency chính
        return _clean_html_regex(html, max_chars)

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(list(_DROP_TAGS)):
        tag.decompose()
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()
    for tag in soup.find_all(True):
        kept = {k: v for k, v in tag.attrs.items() if k in _KEEP_ATTRS}
        tag.attrs = kept
    text = str(soup)
    text = _WS_RE.sub(" ", text)
    text = _BLANKLINE_RE.sub("\n\n", text)
    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars]
    return text


def _clean_html_regex(html: str, max_chars: int) -> str:
    text = re.sub(r"(?is)<(script|style|noscript|svg|template)\b.*?</\1>", " ", html)
    text = re.sub(r"(?is)<!--.*?-->", " ", text)
    text = _WS_RE.sub(" ", text)
    text = _BLANKLINE_RE.sub("\n\n", text).strip()
    return text[:max_chars]


def guess_chapter_url(toc_url: str, hrefs: list[str]) -> str:
    """Đoán URL chương đầu tiên từ danh sách href của trang mục lục.

    Heuristic: cùng host với `toc_url`, khác chính `toc_url`, path chứa số
    (chương thường có id/số), ưu tiên path sâu hơn. Trả "" nếu không đoán được
    — khi đó caller nên yêu cầu người dùng nhập tay `chapter_url`.
    """
    toc_host = urlparse(toc_url).hostname or ""
    toc_path = urlparse(toc_url).path.rstrip("/")
    best_score: tuple[int, int, int] | None = None
    best_full = ""
    for i, raw in enumerate(hrefs):
        if not raw:
            continue
        full = urljoin(toc_url, raw.strip())
        parsed = urlparse(full)
        if parsed.scheme not in ("http", "https"):
            continue
        if (parsed.hostname or "") != toc_host:
            continue
        path = parsed.path.rstrip("/")
        if not path or path == toc_path:
            continue
        low = full.lower()
        if any(bad in low for bad in ("login", "register", "signup", "logout")):
            continue
        has_digit = 1 if re.search(r"\d", path.rsplit("/", 1)[-1]) else 0
        depth = path.count("/")
        # Ưu tiên: có số ở segment cuối > path sâu > xuất hiện sớm (i nhỏ).
        score = (has_digit, depth, -i)
        if best_score is None or score > best_score:
            best_score = score
            best_full = full
    return best_full


def collect_sample_links(toc_url: str, hrefs: list[str], limit: int = 40) -> list[str]:
    """Danh sách URL tuyệt đối (cùng host, có số) làm mẫu để AI suy regex
    `chapter_link_pattern`. Giữ thứ tự, khử trùng lặp, cắt còn `limit`."""
    toc_host = urlparse(toc_url).hostname or ""
    out: list[str] = []
    seen: set[str] = set()
    for raw in hrefs:
        if not raw:
            continue
        full = urljoin(toc_url, raw.strip())
        parsed = urlparse(full)
        if parsed.scheme not in ("http", "https") or (parsed.hostname or "") != toc_host:
            continue
        if not re.search(r"\d", parsed.path):
            continue
        if full in seen:
            continue
        seen.add(full)
        out.append(full)
        if len(out) >= limit:
            break
    return out


DETECT_PROMPT = """Bạn là chuyên gia web scraping. Phân tích HTML của một website đọc tiểu thuyết mạng (thường tiếng Trung) và trả về CSS selector + regex để một crawler tự động lấy nội dung.

Trang mục lục (TOC): {toc_url}
Trang chương mẫu:   {chapter_url}

Một số link chương mẫu lấy từ trang mục lục (dùng để suy regex):
{sample_links}

YÊU CẦU — trả về DUY NHẤT một object JSON (không markdown, không giải thích ngoài JSON) với các key sau, để "" nếu không xác định được:
- "content_selector": CSS selector CHÍNH XÁC MỘT vùng chứa toàn bộ nội dung chương (các <p> hoặc text chính). Chọn container hẹp nhất bao trọn phần chữ, tránh dính nav/quảng cáo. Vd "#content", "div.read-content", "#chaptercontent".
- "chapter_link_pattern": regex Python (dùng re.search) khớp URL TUYỆT ĐỐI của link chương, và KHÔNG khớp link menu/trang khác. Dựa vào các link mẫu ở trên. Vd "/book/\\\\d+/\\\\d+\\\\.html$". Nếu mọi link chương đều hợp lệ, để ".*".
- "next_page_selector": CSS selector link "trang sau" khi một chương bị chia nhiều trang. Để "" nếu chương chỉ có 1 trang.
- "toc_selector": CSS selector vùng danh sách chương ở trang mục lục (vd "#list", ".volume", "div.chapter-list").
- "chapter_title_selector": CSS selector tiêu đề chương ở TRANG CHƯƠNG (vd "h1", ".bookname h1").
- "title_selector": CSS selector tên truyện ở trang mục lục.
- "author_selector": CSS selector tên tác giả ở trang mục lục.
- "desc_selector": CSS selector phần mô tả/giới thiệu truyện.
- "cover_selector": CSS selector thẻ <img> ảnh bìa.

Selector phải hợp lệ với BeautifulSoup .select()/CSS thường (không dùng :contains, :has, hay XPath). Chỉ trả JSON.

--- HTML TRANG MỤC LỤC (đã rút gọn) ---
{toc_html}

--- HTML TRANG CHƯƠNG (đã rút gọn) ---
{chapter_html}
"""


def build_detect_prompt(
    toc_url: str,
    chapter_url: str,
    toc_html: str,
    chapter_html: str,
    sample_links: list[str],
) -> str:
    links_block = "\n".join(f"- {u}" for u in sample_links) or "(không có)"
    return DETECT_PROMPT.format(
        toc_url=toc_url or "(không rõ)",
        chapter_url=chapter_url or "(không có)",
        sample_links=links_block,
        toc_html=toc_html or "(trống)",
        chapter_html=chapter_html or "(trống)",
    )


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_detection(raw: str) -> dict[str, str]:
    """Parse JSON AI trả về thành dict {field: selector}. Bỏ code-fence nếu có,
    chỉ giữ key trong SELECTOR_FIELDS, ép về str và strip. Raise ValueError nếu
    không tìm được JSON object hợp lệ.
    """
    if not raw or not raw.strip():
        raise ValueError("AI trả về rỗng.")
    text = raw.strip()
    text = _FENCE_RE.sub("", text).strip()
    # Cắt lấy object JSON đầu tiên (phòng khi AI kèm chữ thừa quanh JSON).
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"Không tìm thấy JSON trong phản hồi AI: {raw[:200]!r}")
    snippet = text[start : end + 1]
    try:
        data = json.loads(snippet)
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"JSON AI không hợp lệ: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("Phản hồi AI không phải JSON object.")
    result: dict[str, str] = {}
    for field in SELECTOR_FIELDS:
        value = data.get(field, "")
        if value is None:
            value = ""
        result[field] = str(value).strip()
    return result


def validate_pattern(pattern: str, sample_links: list[str]) -> tuple[bool, int]:
    """(regex hợp lệ?, số link mẫu khớp). Pattern rỗng/".*" coi là hợp lệ."""
    if not pattern:
        return True, 0
    try:
        rx = re.compile(pattern)
    except re.error:
        return False, 0
    matched = sum(1 for u in sample_links if rx.search(u))
    return True, matched
