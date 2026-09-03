"""Shared TOC list helpers used by CLI and Web UI."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .storage import Chapter, Storage

# Chi dem ky tu Han (bo qua khoang trang, xuong dong, dau cau markdown) de
# khop voi cach cac trang Trung tinh "so chu" cua 1 chuong, thay vi len() tho
# tren toan bo raw md.
_HAN_RE = re.compile(r"[一-鿿㐀-䶿豈-﫿]")

_TOC_ORDINAL_PREFIX_RE = re.compile(r"^\s*\d+\s*[.．、]\s*")
_TOC_TRAILING_PAREN_RE = re.compile(r"\s*[（(]([^（）()]*)[）)]\s*$")
# Phần đánh dấu truyện chia đoạn giữ nguyên cả bản Hán lẫn bản đã dịch:
# (上/中/下) máy dịch thường thành (Thượng/Trung/Hạ). So khớp KHÔNG phân biệt
# hoa/thường vì kiểu viết là chuyện trình bày.
_TOC_PART_MARKERS = {
    "上", "中", "下",
    "上篇", "中篇", "下篇",
    "上部", "中部", "下部",
    "thượng", "trung", "hạ",
    "thượng tập", "trung tập", "hạ tập",
}
# "(1)", "(2)"… cuối tiêu đề là số thứ tự phần trong cùng một chương gốc
# (tác giả chia nhỏ) — mang ý nghĩa thứ tự nên phải GIỮ, không phải ghi chú rác.
_TOC_NUMBER_MARKER_RE = re.compile(r"^\d+$")


def count_han_chars(text: str) -> int:
    return len(_HAN_RE.findall(text))


def normalize_toc_title(title: str) -> str:
    """Remove a list ordinal and trailing parenthetical note from a TOC title.

    Giữ lại ngoặc mang Ý NGHĨA THỨ TỰ: phần truyện (上)/(Thượng)/(Hạ) và số
    thứ tự "(1)", "(2)" — chỉ cắt ghi chú rác (quảng cáo, chú thích).
    """
    if not title:
        return title
    out = _TOC_ORDINAL_PREFIX_RE.sub("", title)
    trailing = _TOC_TRAILING_PAREN_RE.search(out)
    if trailing:
        marker = trailing.group(1).strip()
        keep = (
            marker.lower() in _TOC_PART_MARKERS
            or _TOC_NUMBER_MARKER_RE.match(marker) is not None
        )
        if not keep:
            out = out[:trailing.start()]
    return out.strip()


# ── Dọn từ rác kêu gọi độc giả trong tiêu đề chương ──────────────────────
# Nhiều site nhét cụm "cầu nguyệt phiếu / cầu vé tháng / 求月票..." vào cuối
# tiêu đề chương. Dùng chung cho _clean_title (tự động khi dịch tiêu đề) và
# hành động "Clear TOC" thủ công.

# Bản Việt: (cầu|xin...) NGAY trước một cụm kêu gọi cụ thể, ở CUỐI tiêu đề, có
# thể bọc trong ngoặc. Bắt buộc cầu/xin đứng sát cụm đích để không cắt nhầm
# tiêu đề thường (vd "Xin một vé về tuổi thơ" KHÔNG khớp vì sau "xin" là "một").
_TOC_JUNK_VI_RE = re.compile(
    r"\s*[（(【\[]?\s*"
    r"(?:cầu|xin|kính\s*xin|khẩn\s*cầu|quỳ\s*cầu|cầu\s*xin)\s+"
    r"(?:"
    r"nguyệt\s*phiếu|phiếu\s*tháng|vé\s*tháng|phiếu\s*đề\s*cử|phiếu\s*giới\s*thiệu|"
    r"đề\s*cử|giới\s*thiệu|ủng\s*hộ|bình\s*chọn|thu\s*tàng|đánh\s*giá|"
    r"phiếu|vé"
    r")"
    r"\s*[!！~～.。]*\s*[）)】\]]?\s*$",
    re.IGNORECASE,
)

# Ghi chú tăng chương thường được máy dịch thành "chương thêm" / "thêm chương",
# theo sau bởi lời kêu gọi và đôi khi bị thiếu dấu đóng ngoặc.
_TOC_JUNK_BONUS_RE = re.compile(
    r"\s*[（(]\s*(?:chương\s+thêm|thêm\s+chương)\b.*?[）)]?\s*$",
    re.IGNORECASE,
)

# Bản Hán thô còn sót: (跪求|日更|求) + danh từ kêu gọi (月票/推荐票/订阅...),
# strip ở BẤT KỲ vị trí nào, có thể bọc ngoặc.
_TOC_JUNK_ZH_RE = re.compile(
    r"[（(【\[]?\s*"
    r"(?:跪求|日更|求)\s*"
    r"(?:月票|推荐票|推薦票|订阅|訂閱|收藏|打赏|打賞|评价|評價|鲜花|鮮花|推荐|推薦|票)+"
    r"[!！~～]*\s*[）)】\]]?"
)


def strip_toc_junk(title: str) -> str:
    """Loại bỏ từ rác kêu gọi độc giả (cầu nguyệt phiếu, cầu vé tháng, 求月票…)
    khỏi tiêu đề chương, giữ nguyên phần nội dung thật.

    An toàn với chuỗi rỗng; trả về chuỗi đã strip. Không đụng tới số chương.
    """
    if not title:
        return title
    out = _TOC_JUNK_ZH_RE.sub("", title)
    out = _TOC_JUNK_VI_RE.sub("", out)
    # Chạy sau regex lời kêu gọi để xóa luôn phần "(chương thêm" mà regex đó
    # có thể để lại, tránh phải clean TOC lần thứ hai.
    out = _TOC_JUNK_BONUS_RE.sub("", out)
    # Dọn cặp ngoặc rỗng và separator thừa còn lại ở cuối.
    out = re.sub(r"\s*[（(【\[]\s*[）)】\]]\s*$", "", out)
    out = re.sub(r"\s*[:：\-–—,，;；]+\s*$", "", out)
    return out.strip()


# ── Kiểm tra format tiêu đề chương ───────────────────────────────────────
# Ba dạng được coi là ĐÚNG (xem docs/operations.md):
#   "Chương 5"              — chỉ số chương
#   "Chương 5: Tên chương"  — số chương, dấu ngăn, tên
#   "Chương 5 Tên chương"   — số chương, khoảng trắng, tên
# Số chương cho phép hậu tố ".1" / "-2" (chương chia nhỏ). Dấu ngăn nhận cả
# ":", "：", ".", "-", "–", "—". So khớp KHÔNG phân biệt hoa thường vì kiểu
# viết hoa là chuyện trình bày, không phải lỗi cấu trúc.
_TITLE_FORMAT_RE = re.compile(
    r"^Chương\s+\d+(?:[.\-]\d+)?"
    r"(?:\s*[:：.\-–—]\s*\S.*|\s+\S.*)?$",
    re.IGNORECASE,
)
_HAN_CHARACTER_RE = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\U00020000-\U0002EBEF]")


def title_format_ok(title: str) -> bool:
    """True nếu tiêu đề đúng mẫu và không còn chữ Hán.

    Tiêu đề rỗng luôn là lỗi — chương chưa có tiêu đề thì không có gì để đưa
    vào EPUB. Dùng cho cột trạng thái và bộ lọc "Tiêu đề lỗi" ở bảng chương.
    """
    title = (title or "").strip()
    if not title:
        return False
    return bool(_TITLE_FORMAT_RE.match(title)) and not _HAN_CHARACTER_RE.search(title)


@dataclass
class ChapterRow:
    index: int
    title: str
    visible_title: str
    url: str
    has_raw: bool
    # `has_translated` chỉ nhánh đang active (Reader/EPUB); hai field sau cho
    # biết dữ liệu hoàn tất ở từng nhánh để UI không đánh đồng các cột DB.
    has_translated: bool
    active_branch: str
    has_ai_translation: bool
    has_local_mt_translation: bool
    missing_fields: list[str]
    duplicate_of: int | None
    last_action_status: str
    word_count: int = 0
    zh_char_count: int = 0
    # Biên tập: trạng thái AI rewrite của chương. `bientap` là label compact
    # hiển thị trong table ("Nháp AI" / "Đã biên tập" / "-"), `bientap_tooltip`
    # là text đầy đủ cho title= (hover).
    bientap: str = ""
    bientap_tooltip: str = ""
    skipped: bool = False
    # Tiêu đề của nhánh đang active có đúng mẫu "Chương N[: tên]" không.
    # Tính trên `title` (tiêu đề thật) chứ không phải `visible_title` — cái sau
    # đã có fallback "Chương {index}" nên luôn đúng mẫu, che mất chương thiếu
    # tiêu đề.
    title_format_ok: bool = True
    # Tiêu đề nguồn tiếng Trung — dùng cho "Hiển thị zh_title" và suy luận số
    # chương thật khi tiêu đề dịch thiếu/mất số.
    title_zh: str = ""
    # Số trang con đã ghép khi crawl chương multi-page (0 = chưa đo/chưa crawl,
    # 1 = chương đơn trang, >1 = ghép từ nhiều URL).
    crawl_pages: int = 0

    @property
    def has_missing(self) -> bool:
        return bool(self.missing_fields)

    @property
    def has_title_error(self) -> bool:
        return not self.title_format_ok


def missing_metadata(title: str = "", author: str = "", description: str = "") -> list[str]:
    missing = []
    if not title:
        missing.append("title")
    if not author:
        missing.append("author")
    if not description:
        missing.append("description")
    return missing


def chapter_missing(ch: Chapter) -> list[str]:
    missing = list(ch.missing_fields or [])
    if not ch.url and "url" not in missing:
        missing.append("url")
    if not (ch.title) and "title" not in missing:
        missing.append("title")
    return missing


def chapter_title_key(ch: Chapter) -> str:
    return (ch.title_zh or ch.title or "").strip()


def mark_duplicate_chapters(chapters: list[Chapter]) -> list[Chapter]:
    seen: dict[tuple[str, str], int] = {}
    seen_urls: dict[str, int] = {}
    for ch in chapters:
        ch.missing_fields = chapter_missing(ch)
        if ch.url:
            title = chapter_title_key(ch)
            first = seen.get((ch.url, title))
            if not title:
                first = seen_urls.get(ch.url)
            if first is not None:
                ch.duplicate_of = first
                if "duplicate" not in ch.missing_fields:
                    ch.missing_fields.append("duplicate")
            else:
                seen[(ch.url, title)] = ch.index
                seen_urls.setdefault(ch.url, ch.index)
    return chapters


def count_words(text: str) -> int:
    return len(text.split())


def chapter_rows(
    chapters: Iterable[Chapter],
    storage: Storage,
    stats_map: dict[int, dict] | None = None,
) -> list[ChapterRow]:
    chapters = list(chapters)
    # Một query cho toàn bộ tiêu đề nhánh active — gọi `read_active_branch_title`
    # từng chương ở đây là 2 full-row (kèm blob raw/dịch) MỖI chương, nguyên
    # nhân chính khiến endpoint bảng chương chậm với truyện dài.
    active_titles = storage.bulk_active_titles() if chapters else {}
    rows = []
    for ch in chapters:
        if stats_map is not None:
            s = stats_map.get(ch.index, {})
            has_raw = s.get("has_raw", False)
            has_translated = s.get("has_translated", False)
            active_branch = s.get("active_branch", storage.active_branch(ch))
            has_ai_translation = s.get("has_ai_translation", False)
            has_local_mt_translation = s.get("has_local_mt_translation", False)
            # ponytail: byte-length estimates for display only, not business logic
            word_count = (s.get("translated_len") or 0) // 5 if has_translated else 0
            zh_char_count = (s.get("raw_len") or 0) // 3 if has_raw else 0
            edit_state = s.get("edit_state", "")
            crawl_pages = int(s.get("crawl_pages", 0) or 0)
        else:
            active_branch = storage.active_branch(ch)
            has_ai_translation = storage.has_branch_text(ch, "ai")
            has_local_mt_translation = storage.has_branch_text(ch, "local_mt")
            has_translated = (
                has_local_mt_translation
                if active_branch == "local_mt"
                else has_ai_translation
            )
            word_count = count_words(storage.read_translated(ch)) if has_translated else 0
            has_raw = storage.has_raw(ch)
            zh_char_count = count_han_chars(storage.read_raw(ch)) if has_raw else 0
            crawl_pages = storage.crawl_pages(ch)
            meta = storage.read_meta(ch) if (has_translated and storage.has_meta(ch)) else {}
            edit_state = ""

        bientap = ""
        bientap_tooltip = ""
        if stats_map is not None:
            if edit_state == "draft":
                bientap = "📝 Nháp AI"
                bientap_tooltip = "AI rewrite draft pending review"
            elif edit_state == "edited_ai":
                bientap = "✏️ Đã biên tập"
                bientap_tooltip = "AI rewrite đã được áp dụng"
            elif edit_state == "edited_local_mt":
                bientap = "✏️ Đã biên tập (Local MT)"
                bientap_tooltip = "AI biên tập đã áp dụng vào nhánh Local MT"
        elif has_translated and meta:
            try:
                if meta.get("ai_rewrite"):
                    ar = meta["ai_rewrite"]
                    when = ar.get("generated_at", "") if isinstance(ar, dict) else ""
                    bientap = "📝 Nháp AI"
                    tip = "AI rewrite draft pending review"
                    if when:
                        tip += f"\ngenerated_at: {when}"
                    bientap_tooltip = tip
                elif meta.get("before_rewrite"):
                    bientap = "✏️ Đã biên tập"
                    bientap_tooltip = "AI rewrite đã được áp dụng (giữ bản gốc trong before_rewrite để khôi phục)"
                elif meta.get("local_mt_ai_edited"):
                    edited = meta["local_mt_ai_edited"]
                    when = edited.get("generated_at", "") if isinstance(edited, dict) else ""
                    engine = edited.get("engine", "") if isinstance(edited, dict) else ""
                    bientap = "✏️ Đã biên tập (Local MT)"
                    tip = "AI biên tập GHI TRỰC TIẾP vào nhánh Local MT (bản gốc MT giữ trong snapshot)"
                    if engine:
                        tip += f"\nengine: {engine}"
                    if when:
                        tip += f"\ngenerated_at: {when}"
                    bientap_tooltip = tip
            except Exception:
                pass

        active_title = active_titles.get(ch.index) or ch.title
        rows.append(ChapterRow(
            index=ch.index,
            title=active_title,
            visible_title=active_title or f"Chương {ch.index}",
            url=ch.url,
            has_raw=has_raw,
            has_translated=has_translated,
            active_branch=active_branch,
            has_ai_translation=has_ai_translation,
            has_local_mt_translation=has_local_mt_translation,
            missing_fields=chapter_missing(ch),
            duplicate_of=ch.duplicate_of,
            last_action_status=ch.last_action_status,
            word_count=word_count,
            zh_char_count=zh_char_count,
            bientap=bientap,
            bientap_tooltip=bientap_tooltip,
            skipped=ch.skipped,
            title_format_ok=title_format_ok(active_title),
            title_zh=ch.title_zh or "",
            crawl_pages=crawl_pages,
        ))
    return rows


def chapter_crawl_status(ch: Chapter, storage: Storage, min_chars: int = 30) -> str:
    """'missing' (chưa crawl) | 'empty' (đã fetch nhưng rỗng/quá ngắn) | 'ok'.

    Phân biệt rõ "chưa crawl" với "đã crawl nhưng lỗi/rỗng" để crawl console
    (xem spec crawl-management) gộp cả 2 vào 1 danh sách "cần retry" mà không
    coi 2 trường hợp là như nhau khi hiển thị.
    """
    length = storage.raw_len(ch)
    if length is None:
        return "missing"
    if length < min_chars:
        return "empty"
    return "ok"


def crawl_problem_indexes(
    chapters: Iterable[Chapter],
    storage: Storage,
    min_chars: int = 30,
    stats_map: dict[int, dict] | None = None,
) -> list[int]:
    """Index các chương 'missing' hoặc 'empty' — dùng cho hành động "Retry lỗi".

    `stats_map` (từ `Storage.bulk_chapter_stats()`) gộp N query thành 1. Ở nhánh
    này 'missing' và 'empty' không phân biệt được (bulk stats quy cả NULL lẫn ''
    về 0) nhưng cũng không cần: cả hai đều != 'ok' nên đều là chương cần retry.
    """
    if stats_map is None:
        return [ch.index for ch in chapters if chapter_crawl_status(ch, storage, min_chars) != "ok"]
    return [
        ch.index
        for ch in chapters
        if stats_map.get(ch.index, {}).get("raw_len", 0) < min_chars
    ]


def _matches_filter(value: bool, flt: str) -> bool:
    flt = (flt or "any").lower()
    return flt == "any" or (flt == "yes" and value) or (flt == "no" and not value)


def apply_chapter_query(
    rows: list[ChapterRow],
    *,
    sort: str = "source",
    direction: str = "asc",
    search: str = "",
    filter_raw: str = "any",
    filter_translated: str = "any",
    filter_missing: str = "any",
    filter_skipped: str = "no",
    filter_local_mt: str = "any",
    filter_ai: str = "any",
    filter_title_error: str = "any",
) -> list[ChapterRow]:
    """Lọc + sắp xếp danh sách chương.

    `filter_translated` xét nhánh ĐANG ACTIVE (thứ đi vào EPUB/Reader), còn
    `filter_local_mt` / `filter_ai` xét từng nhánh riêng — ba bộ lọc này độc
    lập nên chọn "Bản dịch: có" cùng "AI: không" là hợp lệ và có nghĩa.
    `filter_title_error` = "yes" chỉ giữ chương có tiêu đề sai mẫu.
    """
    q = (search or "").strip().lower()
    out = []
    for row in rows:
        if q and q not in row.visible_title.lower() and q not in row.url.lower():
            continue
        if not _matches_filter(row.has_raw, filter_raw):
            continue
        if not _matches_filter(row.has_translated, filter_translated):
            continue
        if not _matches_filter(row.has_local_mt_translation, filter_local_mt):
            continue
        if not _matches_filter(row.has_ai_translation, filter_ai):
            continue
        if not _matches_filter(row.has_missing, filter_missing):
            continue
        if not _matches_filter(row.has_title_error, filter_title_error):
            continue
        if not _matches_filter(row.skipped, filter_skipped):
            continue
        out.append(row)
    key = (sort or "source").lower()
    desc = (direction or "asc").lower() == "desc"
    if key == "title":
        return sorted(out, key=lambda r: (r.visible_title.lower(), r.index), reverse=desc)
    if key == "raw":
        return sorted(out, key=lambda r: (r.has_raw, r.index), reverse=desc)
    if key == "translated":
        return sorted(out, key=lambda r: (r.has_translated, r.index), reverse=desc)
    if key in ("zh_chars", "words"):
        # Sắp theo ĐỘ DÀI nội dung: "zh_chars" = số chữ Hán bản gốc (raw),
        # "words" = số từ bản dịch. Index là tie-breaker để thứ tự ổn định.
        attr = "zh_char_count" if key == "zh_chars" else "word_count"
        return sorted(out, key=lambda r: (getattr(r, attr), r.index), reverse=desc)
    if key == "pages":
        # Số trang con đã ghép khi crawl (0 = chưa crawl/chưa đo).
        return sorted(out, key=lambda r: (r.crawl_pages, r.index), reverse=desc)
    # "source" (default): preserve manifest list order, chỉ reverse nếu desc
    if desc:
        out.reverse()
    return out


def select_visible_range(rows: list[ChapterRow], start: int | None, end: int | None) -> list[int]:
    if not rows:
        return []
    if start is None and end is None:
        return [r.index for r in rows]
    indexes = [r.index for r in rows]
    start = start if start is not None else indexes[0]
    end = end if end is not None else indexes[-1]
    if start not in indexes or end not in indexes:
        return []
    a, b = indexes.index(start), indexes.index(end)
    lo, hi = sorted((a, b))
    return indexes[lo:hi + 1]


def parse_filter(values: list[str] | None) -> dict[str, str]:
    result = {"raw": "any", "translated": "any", "missing": "any"}
    for item in values or []:
        if ":" not in item:
            continue
        key, value = item.split(":", 1)
        if key in result and value in {"yes", "no", "any"}:
            result[key] = value
    return result


def parse_range(value: str) -> tuple[int | None, int | None]:
    value = (value or "").strip()
    if not value:
        return None, None
    if ":" not in value:
        n = int(value)
        return n, n
    left, right = value.split(":", 1)
    return (int(left) if left else None, int(right) if right else None)
