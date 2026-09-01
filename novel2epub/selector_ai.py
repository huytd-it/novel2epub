"""Dùng AI phân tích 1 URL nguồn (trang mục lục + 1 trang chương) để tự động
đề xuất CSS selector / pattern cho một `SourcePreset` mới — người dùng khỏi
phải tự mò selector bằng DevTools.

Module này CHỈ chứa helper thuần (HTML/text vào, dict ra) để dễ test và tách
khỏi I/O mạng: `app/routes/webui.py` (`sources_suggest_selectors_api`) lo gọi
AI (`openai_client.run_chat`) và trả kết quả. Cùng phong cách với
`bulk_transfer.py`.

Thay vì gửi HTML thô cho AI (tốn token, TOC hàng nghìn chương sẽ bị cắt cụt
trước khi AI thấy được `content_selector` thật), `build_dom_digest` duyệt
DOM một lần, tính điểm heuristic (mật độ link cho wrapper mục lục, mật độ
chữ cho nội dung chương, từ khoá id/class cho tác giả/mô tả/ảnh bìa...) và
chỉ gửi một danh sách ứng viên đã đánh nhãn — AI chỉ cần CHỌN nhãn, không tự
bịa selector. `parse_suggestion` đổi nhãn AI chọn ngược lại thành selector
thật (đã được sinh và có thể verify khớp trên chính DOM đã fetch).

Các field đề xuất khớp tên field của `SourcePreset`:
- `content_selector`      — vùng chứa nội dung chương (dùng cho crawl)
- `chapter_link_pattern`  — regex Python match URL chương tuyệt đối (dùng cho crawl)
- `next_page_selector`    — link "trang sau" trong 1 chương (phân trang)
- `toc_selector`          — vùng danh sách chương ở trang mục lục
- `toc_next_page_selector`— link "trang sau" ở trang mục lục
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
    "toc_next_page_selector",
    "chapter_title_selector",
    "title_selector",
    "author_selector",
    "desc_selector",
    "cover_selector",
    "cover_url_pattern",
)

_DROP_TAGS = ("script", "style", "noscript", "svg", "iframe", "template", "canvas", "form")


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


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

# ═══════════════════════ DOM digest (thay cho gửi HTML thô) ═══════════════
#
# Mỗi field selector được gắn 1 "kind" chấm điểm heuristic + từ khoá id/class
# tuỳ chọn. `build_dom_digest` duyệt DOM một lần, chọn top ứng viên mỗi field
# và trả về (digest text để nhét vào prompt, {nhãn: selector thật}). AI chỉ
# cần chọn nhãn — không tự sinh selector nên không thể "khớp 0 phần tử".

_CSS_ESCAPE_RE = re.compile(r'([ !"#$%&\'()*+,./:;<=>?@\[\\\]^`{|}~])')


def _css_escape(value: str) -> str:
    return _CSS_ESCAPE_RE.sub(r"\\\1", value)


def _build_selector(el, max_depth: int = 4) -> str:
    """Sinh CSS selector ngắn cho 1 element bs4 — cùng thuật toán với
    `buildSelector` phía frontend (CrawlSelectorLab.tsx) để 2 bên nhất quán:
    đi lên tối đa `max_depth` tổ tiên, dừng sớm khi gặp id, chỉ thêm
    `:nth-child` khi có anh em cùng tag+class (tránh selector rối không cần
    thiết)."""
    parts: list[str] = []
    cur = el
    depth = 0
    while cur is not None and getattr(cur, "name", None) and cur.name != "html" and depth < max_depth:
        tag = cur.name
        el_id = cur.get("id")
        if el_id:
            parts.insert(0, f"{tag}#{_css_escape(str(el_id))}")
            break
        classes = [c for c in (cur.get("class") or []) if c][:2]
        base = f"{tag}.{'.'.join(_css_escape(c) for c in classes)}" if classes else tag
        parent = cur.parent
        if parent is not None and getattr(parent, "name", None):
            children = list(parent.find_all(True, recursive=False))
            same = [
                c for c in children
                if c.name == tag and [x for x in (c.get("class") or []) if x][:2] == classes
            ]
            if len(same) > 1:
                base = f"{base}:nth-child({children.index(cur) + 1})"
        parts.insert(0, base)
        cur = parent
        depth += 1
    return " > ".join(parts)


def _id_class_text(el) -> str:
    return " ".join(
        filter(None, [str(el.get("id") or ""), " ".join(el.get("class") or []), str(el.get("itemprop") or "")])
    ).lower()


def _preview_text(el, length: int = 60) -> str:
    text = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()
    return text[:length]


def _link_count(el) -> int:
    return len(el.find_all("a", href=True))


def _text_len(el) -> int:
    return len(re.sub(r"\s+", " ", el.get_text(" ", strip=True)))


def find_link_wrapper_candidates(soup, max_candidates: int = 3) -> list[tuple[str, str]]:
    """Ứng viên wrapper mục lục: container hẹp nhất vẫn giữ >=80% tổng số
    link tìm thấy trên trang (elbow), cộng thêm vài container link-dày khác
    ở nhánh khác để AI có lựa chọn khi có nhiều danh sách (vd theo tập)."""
    body = soup.body or soup
    elements = body.find_all(True)
    max_links = max((_link_count(el) for el in elements), default=0)
    if max_links < 3:
        return []
    threshold = max(3, int(max_links * 0.8))
    cur = body
    while True:
        nxt = next((c for c in cur.find_all(True, recursive=False) if _link_count(c) >= threshold), None)
        if nxt is None:
            break
        cur = nxt
    ranked = sorted(
        (el for el in elements if _link_count(el) >= 3),
        key=_link_count,
        reverse=True,
    )
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for el in [cur, *ranked]:
        sel = _build_selector(el)
        if not sel or sel in seen:
            continue
        seen.add(sel)
        hrefs = [str(a.get("href", "")) for a in el.find_all("a", href=True)[:2]]
        detail = f"{_link_count(el)} link" + (f", mẫu: {', '.join(hrefs)}" if hrefs else "")
        out.append((sel, detail))
        if len(out) >= max_candidates:
            break
    return out


def find_text_wrapper_candidates(soup, max_candidates: int = 3) -> list[tuple[str, str]]:
    """Ứng viên wrapper nội dung chương: container hẹp nhất vẫn giữ >=80%
    tổng ký tự chữ trên trang, cộng thêm vài container nhiều <p> khác."""
    body = soup.body or soup
    elements = body.find_all(True)
    max_text = max((_text_len(el) for el in elements), default=0)
    if max_text < 40:
        return []
    threshold = int(max_text * 0.8)
    cur = body
    while True:
        nxt = next((c for c in cur.find_all(True, recursive=False) if _text_len(c) >= threshold), None)
        if nxt is None:
            break
        cur = nxt
    ranked = sorted(
        (el for el in elements if len(el.find_all("p")) >= 3),
        key=_text_len,
        reverse=True,
    )
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for el in [cur, *ranked]:
        sel = _build_selector(el)
        if not sel or sel in seen:
            continue
        seen.add(sel)
        pcount = len(el.find_all("p"))
        out.append((sel, f"{_text_len(el)} ký tự, {pcount} <p>, mở đầu: \"{_preview_text(el, 40)}\""))
        if len(out) >= max_candidates:
            break
    return out


_TITLE_KEYWORDS = ("title", "bookname", "book-name", "chapter-name", "chaptername")


def find_heading_candidates(soup, max_candidates: int = 3) -> list[tuple[str, str]]:
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for el in soup.find_all("h1"):
        sel = _build_selector(el)
        if not sel or sel in seen:
            continue
        seen.add(sel)
        out.append((sel, f"\"{_preview_text(el)}\""))
        if len(out) >= max_candidates:
            return out
    for el in soup.find_all(True):
        if not any(k in _id_class_text(el) for k in _TITLE_KEYWORDS):
            continue
        sel = _build_selector(el)
        if not sel or sel in seen:
            continue
        seen.add(sel)
        out.append((sel, f"\"{_preview_text(el)}\""))
        if len(out) >= max_candidates:
            break
    return out


def find_keyword_candidates(soup, keywords: tuple[str, ...], max_candidates: int = 3) -> list[tuple[str, str]]:
    if not keywords:
        return []
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for el in soup.find_all(True):
        if el.name in _DROP_TAGS or not any(k in _id_class_text(el) for k in keywords):
            continue
        sel = _build_selector(el)
        if not sel or sel in seen:
            continue
        seen.add(sel)
        out.append((sel, f"\"{_preview_text(el)}\""))
        if len(out) >= max_candidates:
            break
    return out


_IMAGE_KEYWORDS = ("cover", "book-img", "bookimg", "fm", "pic", "thumb")


def find_image_candidates(
    soup, keywords: tuple[str, ...] = _IMAGE_KEYWORDS, max_candidates: int = 3
) -> list[tuple[str, str]]:
    def score(el) -> int:
        parent_idc = _id_class_text(el.parent) if el.parent else ""
        return 1 if any(k in _id_class_text(el) or k in parent_idc for k in keywords) else 0

    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for el in sorted(soup.find_all("img"), key=score, reverse=True):
        sel = _build_selector(el)
        if not sel or sel in seen:
            continue
        seen.add(sel)
        src = str(el.get("src") or el.get("data-src") or "")
        out.append((sel, f"src={src[:80]}"))
        if len(out) >= max_candidates:
            break
    return out


_NEXT_KEYWORDS = ("sau", "next", "»", "下一页", "下一章", "下一頁", ">>")


def find_next_link_candidates(soup, max_candidates: int = 3) -> list[tuple[str, str]]:
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for el in soup.find_all("a", href=True):
        text = re.sub(r"\s+", " ", el.get_text(strip=True)).strip().lower()
        if not any(k in text or k in _id_class_text(el) for k in _NEXT_KEYWORDS):
            continue
        sel = _build_selector(el)
        if not sel or sel in seen:
            continue
        seen.add(sel)
        out.append((sel, f"text=\"{text[:30]}\""))
        if len(out) >= max_candidates:
            break
    return out


# kind -> finder(soup, keywords) -> [(selector, detail)]
_FINDERS = {
    "link-wrapper": lambda soup, kw: find_link_wrapper_candidates(soup),
    "text-wrapper": lambda soup, kw: find_text_wrapper_candidates(soup),
    "heading": lambda soup, kw: find_heading_candidates(soup),
    "keyword": lambda soup, kw: find_keyword_candidates(soup, kw or ()),
    "image": lambda soup, kw: find_image_candidates(soup, kw or _IMAGE_KEYWORDS),
    "next-link": lambda soup, kw: find_next_link_candidates(soup),
}

# Field selector nào dùng chiến lược chấm điểm nào + từ khoá id/class đi kèm.
# Tách theo trang vì toc_selector chỉ có nghĩa trên trang mục lục, còn
# content_selector chỉ có nghĩa trên trang chương.
TOC_FIELD_SPECS: dict[str, tuple[str, tuple[str, ...] | None]] = {
    "toc_selector": ("link-wrapper", None),
    "title_selector": ("heading", None),
    "author_selector": ("keyword", ("author", "zuozhe", "tac-gia", "tacgia")),
    "desc_selector": ("keyword", ("desc", "intro", "summary", "gioi-thieu", "gioithieu")),
    "cover_selector": ("image", None),
    "toc_next_page_selector": ("next-link", None),
}

CHAPTER_FIELD_SPECS: dict[str, tuple[str, tuple[str, ...] | None]] = {
    "content_selector": ("text-wrapper", None),
    "chapter_title_selector": ("heading", None),
    "next_page_selector": ("next-link", None),
}


def build_dom_digest(
    html: str,
    field_specs: dict[str, tuple[str, tuple[str, ...] | None]],
    max_chars: int = 3000,
) -> tuple[str, dict[str, str]]:
    """Tóm tắt DOM thành danh sách ứng viên đã đánh nhãn cho từng field trong
    `field_specs` (dùng `TOC_FIELD_SPECS` hoặc `CHAPTER_FIELD_SPECS`).

    Trả `(digest_text, label_to_selector)` — `digest_text` nhét thẳng vào
    prompt AI, `label_to_selector` dùng ở `parse_suggestion` để đổi nhãn AI
    chọn (vd "TOC-1") thành selector CSS thật.
    """
    if not html or not html.strip():
        return "(trống)", {}
    try:
        from bs4 import BeautifulSoup, Comment
    except ImportError:  # pragma: no cover - bs4 là dependency chính
        return "(thiếu bs4)", {}

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(list(_DROP_TAGS)):
        tag.decompose()
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    lines: list[str] = []
    label_map: dict[str, str] = {}
    for field, (kind, keywords) in field_specs.items():
        finder = _FINDERS.get(kind)
        if finder is None:
            continue
        prefix = field.replace("_selector", "").replace("_", "-").upper()
        for i, (sel, detail) in enumerate(finder(soup, keywords), start=1):
            label = f"{prefix}-{i}"
            label_map[label] = sel
            lines.append(f"[{label}] {sel} — {detail}")

    digest = "\n".join(lines) if lines else "(không tìm thấy ứng viên nào — cần chọn thủ công)"
    return digest[:max_chars], label_map


SUGGEST_PROMPT = """Bạn là chuyên gia web scraping. Dưới đây là danh sách ứng viên (container/element) đã được trích sẵn bằng heuristic từ 2 trang của một website đọc tiểu thuyết mạng (thường tiếng Trung): trang mục lục và 1 trang chương mẫu. Mỗi ứng viên có nhãn dạng [XXX-N], kèm selector CSS thật và vài số liệu.

Trang mục lục: {toc_url}
Trang chương mẫu: {chapter_url}

--- Ứng viên trang mục lục ---
{toc_digest}

--- Ứng viên trang chương ---
{chapter_digest}

Một số link chương mẫu (dùng để suy regex):
{sample_links}

YÊU CẦU — trả về DUY NHẤT một object JSON (không markdown, không giải thích ngoài JSON) với các key sau:
- "toc_selector": nhãn ứng viên khớp vùng danh sách chương (vd "TOC-1").
- "title_selector": nhãn ứng viên tên truyện.
- "author_selector": nhãn ứng viên tác giả.
- "desc_selector": nhãn ứng viên mô tả truyện.
- "cover_selector": nhãn ứng viên ảnh bìa.
- "cover_url_pattern": regex Python (dùng re.search) khớp URL TUYỆT ĐỐI của ảnh bìa, dựa vào src các ảnh bìa ứng viên liệt kê ở trên. Chỉ đặt khi ảnh bìa cần lọc theo đuôi file/id riêng (vd \\.webp$ hoặc /cover/). Đây là regex thật, KHÔNG phải nhãn. Mặc định "".
- "toc_next_page_selector": nhãn ứng viên link "trang sau" ở mục lục.
- "content_selector": nhãn ứng viên vùng nội dung chương.
- "chapter_title_selector": nhãn ứng viên tiêu đề chương.
- "next_page_selector": nhãn ứng viên link "trang sau" trong chương.
- "chapter_link_pattern": regex Python (dùng re.search) khớp URL TUYỆT ĐỐI của link chương, KHÔNG khớp link menu/trang khác, dựa vào các link mẫu ở trên. Đây là regex thật, KHÔNG phải nhãn. Nếu mọi link mẫu đều là link chương, để ".*".

Chỉ chọn nhãn CÓ TRONG danh sách ứng viên ở trên (đúng chính tả, vd "TOC-1"). Để "" nếu không có ứng viên nào phù hợp — TUYỆT ĐỐI không tự bịa selector hay nhãn không tồn tại.
"""


def build_suggest_prompt(
    toc_url: str,
    chapter_url: str,
    toc_digest: str,
    chapter_digest: str,
    sample_links: list[str],
) -> str:
    links_block = "\n".join(f"- {u}" for u in sample_links) or "(không có)"
    return SUGGEST_PROMPT.format(
        toc_url=toc_url or "(không rõ)",
        chapter_url=chapter_url or "(không có)",
        toc_digest=toc_digest or "(trống)",
        chapter_digest=chapter_digest or "(trống)",
        sample_links=links_block,
    )


def parse_suggestion(raw: str, label_map: dict[str, str]) -> dict[str, str]:
    """Parse JSON AI trả về (dạng {field: nhãn hoặc regex}) thành
    {field: selector/regex thật}. `label_map` đổi nhãn (vd "TOC-1") sang
    selector CSS thật đã được sinh sẵn bởi `build_dom_digest` — nếu AI trả
    một nhãn không tồn tại trong `label_map`, field đó về "" (không đoán mò).
    `chapter_link_pattern` là regex thật nên giữ nguyên, không tra label_map.
    Raise ValueError nếu không tìm được JSON object hợp lệ.
    """
    if not raw or not raw.strip():
        raise ValueError("AI trả về rỗng.")
    text = raw.strip()
    text = _FENCE_RE.sub("", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"Không tìm thấy JSON trong phản hồi AI: {raw[:200]!r}")
    try:
        data = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"JSON AI không hợp lệ: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("Phản hồi AI không phải JSON object.")
    result: dict[str, str] = {}
    # Regex thật (không tra label_map) — giống chapter_link_pattern.
    _RAW_REGEX_FIELDS = {"chapter_link_pattern", "cover_url_pattern"}
    for field in SELECTOR_FIELDS:
        value = str(data.get(field) or "").strip()
        if field in _RAW_REGEX_FIELDS:
            result[field] = value
            continue
        result[field] = label_map.get(value, "")
    return result


def count_matches(html: str, selector: str) -> int:
    """Số phần tử khớp `selector` trên `html` bằng bs4 `.select()`. Trả -1
    nếu selector lỗi cú pháp hoặc thiếu bs4, 0 nếu html/selector rỗng — dùng
    để chấm chẩn đoán selector AI vừa chọn mà không cần Scrapling/mạng."""
    selector = (selector or "").strip()
    if not selector or not html or not html.strip():
        return 0
    try:
        from bs4 import BeautifulSoup
    except ImportError:  # pragma: no cover - bs4 là dependency chính
        return -1
    try:
        soup = BeautifulSoup(html, "html.parser")
        return len(soup.select(selector))
    except Exception:  # noqa: BLE001 - selector AI chọn có thể vẫn lỗi cú pháp
        return -1


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
