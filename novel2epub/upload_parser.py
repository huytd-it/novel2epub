"""Parser cho ebook upload: tách chương từ file TXT và EPUB.

TXT: regex dò tiêu đề chương ("Chương N", "Chapter N", "第N章"...);
không tìm thấy tiêu đề nào → raise lỗi.

EPUB: tách theo file con trong spine, lấy title + content + ảnh bìa.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

# ── Regex tiêu đề chương ──────────────────────────────────────────────────────

# Sau marker 章/回/卷 phải là hết dòng hoặc ký tự phân cách (khoảng trắng,
# dấu câu, ngoặc mở) — tránh nuốt dòng NỘI DUNG mở đầu bằng "第X章..." (vd
# "第三章内容。" là câu văn, còn "第3章 标题"/"第十章" mới là tiêu đề).
# Đánh đổi có chủ ý: heading dính liền kiểu "第一章重生" (không cách) sẽ
# không nhận diện được.
_ZH_TRAILER = r"(?=$|\s|[:：、，,．.·\-—–「『\"'(\[（])"

CHAPTER_HEADING_RE: list[re.Pattern[str]] = [
    # Tiêu đề Hán: 第N章, 第N回, 第N卷, 第N節
    re.compile(r"^\s*第\s*([0-9零〇一二三四五六七八九十百千万]+)\s*[章回卷節节]" + _ZH_TRAILER, re.UNICODE),
    # Tiêu đề Việt: Chương N (số arab)
    re.compile(r"^\s*chương\s+(\d+)\b", re.IGNORECASE),
    # Tiêu đề Việt số bằng chữ: "Chương một", "Chương mười hai" — nhận diện
    # làm heading, nhưng không rút được số (extract → None → caller gán tuần tự).
    re.compile(r"^\s*chương\s+(một|hai|ba|bốn|năm|sáu|bảy|tám|chín|mười|mươi|trăm|nghìn|ngàn|linh|lẻ)\b", re.IGNORECASE),
    # Tiêu đề Anh: Chapter N, Ch. N
    re.compile(r"^\s*chapter\s+(\d+)\b", re.IGNORECASE),
    re.compile(r"^\s*ch\.?\s*(\d+)\b", re.IGNORECASE),
    # Hồi N
    re.compile(r"^\s*hồi\s+(\d+)\b", re.IGNORECASE),
    # Quyển N
    re.compile(r"^\s*quyển\s+(\d+)\b", re.IGNORECASE),
]

# Regex để trích số từ chuỗi Hán thô
_ZH_NUM_MAP = {"零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4,
               "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
               "百": 100, "千": 1000, "万": 10000}


def _parse_zh_number(s: str) -> int | None:
    """Chuyển số Hán đơn giản (≤99999) sang int. Trả None nếu không parse được."""
    s = s.strip()
    if not s:
        return None
    # Nếu là digits thuần thì return trực tiếp
    if s.isdigit():
        return int(s)
    total = 0
    current = 0
    for ch in s:
        val = _ZH_NUM_MAP.get(ch)
        if val is None:
            return None
        if val >= 10:
            if current == 0:
                current = 1
            total += current * val
            current = 0
        else:
            current = val
    total += current
    return total if total > 0 else None


def extract_chapter_number(title: str) -> int | None:
    """Rút số thứ tự từ tiêu đề chương. Trả None nếu không tìm được."""
    title = title.strip()
    for pattern in CHAPTER_HEADING_RE:
        m = pattern.match(title)
        if m:
            num_str = m.group(1)
            # Thử parse số thập phân trước
            if num_str.isdigit():
                return int(num_str)
            # Thử parse số Hán
            zh_num = _parse_zh_number(num_str)
            if zh_num is not None:
                return zh_num
    # Fallback: tìm "số" bất kỳ trong dòng đầu
    m = re.search(r"\b(\d+)\b", title)
    if m:
        return int(m.group(1))
    return None


@dataclass
class ParsedChapter:
    title: str
    content: str
    index: int | None = None  # None = caller gán tuần tự


@dataclass
class ParsedBook:
    title: str = ""
    author: str = ""
    cover_bytes: bytes | None = None
    cover_ext: str = ""
    chapters: list[ParsedChapter] = field(default_factory=list)


class ParseError(Exception):
    """Lỗi parsing file upload."""


def _decode_text(raw: bytes) -> str:
    """Thử UTF-8, fallback GB18030, Big5."""
    for enc in ("utf-8", "gb18030", "big5"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    raise ParseError("Không thể giải mã file: không phải UTF-8, GB18030 hay Big5.")


def _match_chapter_heading(line: str) -> bool:
    """Kiểm tra dòng có phải tiêu đề chương không."""
    for pattern in CHAPTER_HEADING_RE:
        if pattern.match(line.strip()):
            return True
    return False


def split_txt_chapters(text: str) -> list[tuple[str, str]]:
    """Tách text TXT thành danh sách (title, content).

    Dò tiêu đề chương bằng regex. Nếu không tìm thấy tiêu đề nào → raise ParseError.
    """
    lines = text.split("\n")
    chapters: list[tuple[str, str]] = []
    current_title: str | None = None
    current_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped and _match_chapter_heading(stripped):
            # Lưu chương trước
            if current_title is not None:
                content = "\n".join(current_lines).strip()
                if content:
                    chapters.append((current_title, content))
            current_title = stripped
            current_lines = []
        else:
            if current_title is not None:
                current_lines.append(line)

    # Lưu chương cuối
    if current_title is not None:
        content = "\n".join(current_lines).strip()
        if content:
            chapters.append((current_title, content))

    if not chapters:
        raise ParseError(
            "Không tìm thấy tiêu đề chương nào trong file TXT. "
            "File phải chứa ít nhất 1 tiêu đề hợp lệ (VD: 'Chương 1', 'Chapter 1', '第1章')."
        )

    return chapters


def _parse_epub(file_bytes: bytes) -> ParsedBook:
    """Parse file EPUB: lấy title, author, cover, chapters."""
    try:
        from ebooklib import epub
    except ImportError:
        raise ParseError("Chưa cài ebooklib. Chạy: pip install ebooklib")

    import io

    try:
        book = epub.read_epub(io.BytesIO(file_bytes))
    except Exception as e:
        raise ParseError(f"File EPUB không hợp lệ: {e}")

    # Title & author
    title = ""
    try:
        title_meta = book.get_metadata("DC", "title")
        if title_meta:
            title = title_meta[0][0]
    except Exception:
        pass

    author = ""
    try:
        author_meta = book.get_metadata("DC", "creator")
        if author_meta:
            author = author_meta[0][0]
    except Exception:
        pass

    # Cover image
    cover_bytes: bytes | None = None
    cover_ext = ""
    try:
        cover_id = book.get_metadata("OPF", "cover") if hasattr(book, "get_metadata") else None
        if cover_id:
            cover_id_val = cover_id[0][1] if cover_id else None
            if cover_id_val:
                for item in book.get_items():
                    if item.get_id() == cover_id_val:
                        cover_bytes = item.get_content()
                        media = getattr(item, "media_type", "") or ""
                        if "png" in media:
                            cover_ext = "png"
                        elif "webp" in media:
                            cover_ext = "webp"
                        else:
                            cover_ext = "jpg"
                        break
    except Exception:
        pass

    # Fallback: tìm item có media_type là image/* đầu tiên
    if cover_bytes is None:
        for item in book.get_items():
            media = getattr(item, "media_type", "") or ""
            if media.startswith("image/"):
                cover_bytes = item.get_content()
                if "png" in media:
                    cover_ext = "png"
                elif "webp" in media:
                    cover_ext = "webp"
                else:
                    cover_ext = "jpg"
                break

    # Chapters — theo thứ tự spine, bỏ mục điều hướng (nav/ncx)
    chapters: list[ParsedChapter] = []
    spine_ids = [item_id for item_id, _ in book.spine]
    items_by_id = {item.get_id(): item for item in book.get_items()}

    for item_id in spine_ids:
        if item_id in ("nav", "ncx"):
            continue
        item = items_by_id.get(item_id)
        if item is None:
            continue
        media = getattr(item, "media_type", "") or ""
        if "html" not in media and "xml" not in media:
            continue
        file_name = getattr(item, "get_name", lambda: "")() or ""
        if file_name.lower().endswith(("nav.xhtml", "toc.xhtml")):
            continue
        raw_content = item.get_content()
        # Trích text thô từ HTML
        content = _strip_html(raw_content)
        content = content.strip()
        if not content:
            continue
        ch_title = _epub_item_title(item, raw_content, file_name)
        chapters.append(ParsedChapter(title=ch_title, content=content,
                                      index=extract_chapter_number(ch_title)))

    return ParsedBook(title=title.strip(), author=author.strip(),
                      cover_bytes=cover_bytes, cover_ext=cover_ext,
                      chapters=chapters)


def _epub_item_title(item, raw_content: bytes, file_name: str) -> str:
    """Tiêu đề chương EPUB: thuộc tính item → thẻ <h1>/<title> → tên file."""
    title = (getattr(item, "title", "") or "").strip()
    if title:
        return title
    try:
        html = raw_content.decode("utf-8", errors="replace")
    except Exception:
        html = ""
    for tag in ("h1", "title", "h2"):
        m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", html,
                      flags=re.IGNORECASE | re.DOTALL)
        if m:
            candidate = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            if candidate:
                return candidate
    stem = file_name.rsplit("/", 1)[-1]
    return stem.rsplit(".", 1)[0] if "." in stem else stem


def _strip_html(html_bytes: bytes) -> str:
    """Trích text thô từ HTML bytes, giữ xuống dòng ở block elements."""
    import re as _re
    html = html_bytes.decode("utf-8", errors="replace")
    # Thêm newline trước block elements để giữ cấu trúc paragraph
    html = _re.sub(r"<(?:br|br\s*/?\s*)\s*>", "\n", html, flags=_re.IGNORECASE)
    html = _re.sub(r"</(?:p|div|h[1-6]|li|tr|br)\s*>", "\n", html, flags=_re.IGNORECASE)
    html = _re.sub(r"<[^>]+>", "", html)
    # Decode entities cơ bản
    html = html.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    html = html.replace("&quot;", '"').replace("&nbsp;", " ").replace("&#39;", "'")
    # Gộp nhiều newline liên tiếp
    html = _re.sub(r"\n{3,}", "\n\n", html)
    return html.strip()


def parse_upload_file(filename: str, file_bytes: bytes) -> ParsedBook:
    """Parse file upload (TXT hoặc EPUB), trả ParsedBook."""
    name_lower = filename.lower()
    if name_lower.endswith(".epub"):
        return _parse_epub(file_bytes)
    elif name_lower.endswith(".txt"):
        text = _decode_text(file_bytes)
        chapters_data = split_txt_chapters(text)
        book = ParsedBook()
        for title, content in chapters_data:
            num = extract_chapter_number(title)
            book.chapters.append(ParsedChapter(title=title, content=content, index=num))
        # Gợi ý title từ tên file (bỏ đuôi .txt)
        stem = PurePosixPath(filename).stem
        book.title = stem
        return book
    else:
        raise ParseError(f"Định dạng không hỗ trợ: {filename}. Chỉ chấp nhận file .txt và .epub.")


def suggest_slug(title: str, filename: str) -> str:
    """Gợi ý slug từ title hoặc filename."""
    if title:
        slug = _vn_slugify_simple(title)
        if slug:
            return slug
    # Fallback: dùng tên file
    stem = PurePosixPath(filename).stem
    slug = _vn_slugify_simple(stem)
    return slug


def _vn_slugify_simple(value: str) -> str:
    """Slugify đơn giản (mirror backend vn_slugify)."""
    import unicodedata
    vn_map = str.maketrans(
        "àáảãạăằắẳẵặâầấẩẫậđèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ"
        "ÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬĐÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴ",
        "aaaaaaaaaaaaaaaaadeeeeeeeeeeeiiiiiooooooooooooooooouuuuuuuuuuuyyyyy"
        "AAAAAAAAAAAAAAAAADEEEEEEEEEEEIIIIIOOOOOOOOOOOOOOOOOUUUUUUUUUUUYYYYY",
    )
    value = value.translate(vn_map)
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    if not value or not re.search(r"[a-z]", value):
        return ""
    return value
