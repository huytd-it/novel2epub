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


def count_han_chars(text: str) -> int:
    return len(_HAN_RE.findall(text))


@dataclass
class ChapterRow:
    index: int
    title: str
    visible_title: str
    url: str
    has_raw: bool
    has_translated: bool
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

    @property
    def has_missing(self) -> bool:
        return bool(self.missing_fields)


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


def mark_duplicate_chapters(chapters: list[Chapter]) -> list[Chapter]:
    seen: dict[str, int] = {}
    for ch in chapters:
        ch.missing_fields = chapter_missing(ch)
        if ch.url:
            first = seen.get(ch.url)
            if first is None:
                seen[ch.url] = ch.index
            else:
                ch.duplicate_of = first
                if "duplicate" not in ch.missing_fields:
                    ch.missing_fields.append("duplicate")
    return chapters


def count_words(text: str) -> int:
    return len(text.split())


def chapter_rows(
    chapters: Iterable[Chapter],
    storage: Storage,
    stats_map: dict[int, dict] | None = None,
) -> list[ChapterRow]:
    import json as _json
    rows = []
    for ch in chapters:
        if stats_map is not None:
            s = stats_map.get(ch.index, {})
            has_raw = s.get("has_raw", False)
            has_translated = s.get("has_translated", False)
            # ponytail: byte-length estimates for display only, not business logic
            word_count = (s.get("translated_len") or 0) // 5 if has_translated else 0
            zh_char_count = (s.get("raw_len") or 0) // 3 if has_raw else 0
            try:
                meta = _json.loads(s.get("meta_json") or "{}")
            except Exception:
                meta = {}
        else:
            has_translated = storage.has_translated(ch)
            word_count = count_words(storage.read_translated(ch)) if has_translated else 0
            has_raw = storage.has_raw(ch)
            zh_char_count = count_han_chars(storage.read_raw(ch)) if has_raw else 0
            meta = storage.read_meta(ch) if (has_translated and storage.has_meta(ch)) else {}

        bientap = ""
        bientap_tooltip = ""
        if has_translated and meta:
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
            except Exception:
                pass

        rows.append(ChapterRow(
            index=ch.index,
            title=ch.title,
            visible_title=ch.title or f"Chương {ch.index}",
            url=ch.url,
            has_raw=has_raw,
            has_translated=has_translated,
            missing_fields=chapter_missing(ch),
            duplicate_of=ch.duplicate_of,
            last_action_status=ch.last_action_status,
            word_count=word_count,
            zh_char_count=zh_char_count,
            bientap=bientap,
            bientap_tooltip=bientap_tooltip,
            skipped=ch.skipped,
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


def crawl_problem_indexes(chapters: Iterable[Chapter], storage: Storage, min_chars: int = 30) -> list[int]:
    """Index các chương 'missing' hoặc 'empty' — dùng cho hành động "Retry lỗi"."""
    return [ch.index for ch in chapters if chapter_crawl_status(ch, storage, min_chars) != "ok"]


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
) -> list[ChapterRow]:
    q = (search or "").strip().lower()
    out = []
    for row in rows:
        if q and q not in row.visible_title.lower() and q not in row.url.lower():
            continue
        if not _matches_filter(row.has_raw, filter_raw):
            continue
        if not _matches_filter(row.has_translated, filter_translated):
            continue
        if not _matches_filter(row.has_missing, filter_missing):
            continue
        if not _matches_filter(row.skipped, filter_skipped):
            continue
        out.append(row)
    key = (sort or "source").lower()
    if key == "title":
        key_fn = lambda r: (r.visible_title.lower(), r.index)
        return sorted(out, key=key_fn, reverse=(direction or "asc").lower() == "desc")
    if key == "raw":
        key_fn = lambda r: (r.has_raw, r.index)
        return sorted(out, key=key_fn, reverse=(direction or "asc").lower() == "desc")
    if key == "translated":
        key_fn = lambda r: (r.has_translated, r.index)
        return sorted(out, key=key_fn, reverse=(direction or "asc").lower() == "desc")
    # "source" (default): preserve manifest list order, chỉ reverse nếu desc
    if (direction or "asc").lower() == "desc":
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
