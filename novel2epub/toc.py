"""Shared TOC list helpers used by CLI and Web UI."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .storage import Chapter, Storage


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


def chapter_rows(chapters: Iterable[Chapter], storage: Storage) -> list[ChapterRow]:
    rows = []
    for ch in chapters:
        has_translated = storage.has_translated(ch)
        word_count = count_words(storage.read_translated(ch)) if has_translated else 0
        rows.append(ChapterRow(
            index=ch.index,
            title=ch.title,
            visible_title=ch.title or f"Chương {ch.index}",
            url=ch.url,
            has_raw=storage.has_raw(ch),
            has_translated=has_translated,
            missing_fields=chapter_missing(ch),
            duplicate_of=ch.duplicate_of,
            last_action_status=ch.last_action_status,
            word_count=word_count,
        ))
    return rows


def chapter_crawl_status(ch: Chapter, storage: Storage, min_chars: int = 30) -> str:
    """'missing' (chưa crawl) | 'empty' (đã fetch nhưng rỗng/quá ngắn) | 'ok'.

    Phân biệt rõ "chưa crawl" với "đã crawl nhưng lỗi/rỗng" để crawl console
    (xem spec crawl-management) gộp cả 2 vào 1 danh sách "cần retry" mà không
    coi 2 trường hợp là như nhau khi hiển thị.
    """
    path = storage.raw_path(ch)
    if not path.exists():
        return "missing"
    if path.stat().st_size < min_chars:
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
        out.append(row)
    key = (sort or "source").lower()
    if key == "title":
        key_fn = lambda r: (r.visible_title.lower(), r.index)
    elif key == "raw":
        key_fn = lambda r: (r.has_raw, r.index)
    elif key == "translated":
        key_fn = lambda r: (r.has_translated, r.index)
    else:
        key_fn = lambda r: r.index
    return sorted(out, key=key_fn, reverse=(direction or "asc").lower() == "desc")


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
