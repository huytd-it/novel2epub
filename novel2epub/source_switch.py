"""Preview and explicitly reconcile a second website's TOC with an existing ebook.

Nothing is persisted until apply; chapter identity is the stable ebook index, not
the incoming site's TOC position. Chapter content and translation columns are
never touched by this operation.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from urllib.parse import urlparse

from .storage import Manifest, Storage


_ORDINAL = re.compile(r"(?:chương|chapter|chap|第)\s*([0-9]+)(?:\s*章)?", re.IGNORECASE)


def ordinal(title: str) -> int | None:
    match = _ORDINAL.search(title or "")
    return int(match.group(1)) if match else None


def validate_url(url: str) -> str:
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("URL mục lục phải là HTTP(S) hợp lệ, không chứa thông tin đăng nhập.")
    return url


def fingerprint(manifest: Manifest) -> str:
    payload = {
        "source_url": manifest.source_url,
        "chapters": [(ch.index, ch.url, ch.title, ch.title_zh) for ch in manifest.chapters],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def missing_indexes(old: Manifest) -> dict[int, int]:
    """Missing chapter number → free index, only between unambiguous neighbors."""
    numbered = [
        (n, ch.index) for ch in old.chapters
        if (n := ordinal(ch.title_zh or ch.title)) is not None
    ]
    counts = Counter(n for n, _ in numbered)
    numbered.sort()
    occupied = {ch.index for ch in old.chapters}
    gaps: dict[int, int] = {}
    for (before_n, before_idx), (after_n, after_idx) in zip(numbered, numbered[1:]):
        if counts[before_n] != 1 or counts[after_n] != 1:
            continue
        if after_n - before_n != after_idx - before_idx or after_n <= before_n + 1:
            continue
        for number in range(before_n + 1, after_n):
            idx = before_idx + number - before_n
            if idx > 0 and idx not in occupied:
                gaps[number] = idx
    return gaps


def propose(old: Manifest, incoming: Manifest, storage: Storage) -> dict:
    """Conservative one-to-one suggestions. Ambiguous/missing ordinals stay skipped."""
    old_numbers: dict[int, list[int]] = defaultdict(list)
    new_counts = Counter(ordinal(ch.title_zh or ch.title) for ch in incoming.chapters)
    for ch in old.chapters:
        number = ordinal(ch.title_zh or ch.title)
        if number is not None:
            old_numbers[number].append(ch.index)
    max_number = max(old_numbers, default=0)
    gaps = missing_indexes(old)
    all_old_numbered = sum(map(len, old_numbers.values())) == len(old.chapters)
    state = storage.bulk_chapter_stats()
    rows = []
    for ch in incoming.chapters:
        number = ordinal(ch.title_zh or ch.title)
        candidates = old_numbers.get(number, []) if number is not None else []
        gap_index = gaps.get(number) if number is not None and not candidates else None
        if len(candidates) == 1 and new_counts[number] == 1:
            action, old_index = "match", candidates[0]
        elif (number is not None and new_counts[number] == 1
              and (gap_index is not None or number > max_number or all_old_numbered)):
            action, old_index = "add", None
        else:
            action, old_index = "skip", None
        rows.append({
            "position": ch.index, "title": ch.title, "url": ch.url,
            "ordinal": number, "action": action, "old_index": old_index,
            "new_index": gap_index if action == "add" else None,
            "has_raw": bool(state.get(old_index, {}).get("has_raw")) if old_index else False,
            "ambiguous": bool(candidates and (len(candidates) != 1 or new_counts[number] != 1)),
        })
    return {"old_fingerprint": fingerprint(old), "toc_fingerprint": fingerprint(incoming),
            "old_chapters": [{"index": ch.index, "title": ch.title, "url": ch.url}
                             for ch in old.chapters], "rows": rows}


def apply_switch(storage: Storage, old: Manifest, incoming: Manifest, choices: list[dict],
                 old_fingerprint: str, toc_fingerprint: str, source_name: str, toc_url: str,
                 *, crawl_mode: str | None = None, headless: bool | None = None) -> dict:
    """Validate the whole reconciliation then commit chapter URLs + source config atomically."""
    if fingerprint(old) != old_fingerprint or fingerprint(incoming) != toc_fingerprint:
        raise ValueError("Mục lục đã thay đổi kể từ lúc xem trước. Hãy xem trước lại.")
    by_position = {ch.index: ch for ch in incoming.chapters}
    old_by_index = {ch.index: ch for ch in old.chapters}
    if len(choices) != len(by_position) or {c.get("position") for c in choices} != set(by_position):
        raise ValueError("Phải quyết định đúng một lần cho mỗi chương nguồn mới.")
    used: set[int] = set()
    updates: list[tuple[str, str, str | None, int]] = []
    additions: list[tuple[int, str, str]] = []
    next_index = max(old_by_index, default=0) + 1
    reserved = set(old_by_index)
    incoming_counts = Counter(ordinal(ch.title_zh or ch.title) for ch in incoming.chapters)
    gaps = missing_indexes(old)
    for choice in choices:
        action = choice.get("action")
        ch = by_position[choice["position"]]
        if action == "match":
            if choice.get("new_index") is not None:
                raise ValueError("Chương ghép không được chọn index thêm mới.")
            idx = choice.get("old_index")
            if type(idx) is not int or idx not in old_by_index or idx in used:
                raise ValueError("Một chương cũ không tồn tại hoặc được ghép nhiều lần.")
            source_title = (ch.title_zh or ch.title).strip()
            if not source_title:
                raise ValueError("Chương nguồn mới thiếu tiêu đề; không thể ghép an toàn khi cập nhật mục lục.")
            used.add(idx)
            old_ch = old_by_index[idx]
            # `title_zh` là khóa TOC (chapter_title_key); `title` còn là tiêu
            # đề NHÁNH AI. Giữ tiêu đề đã dịch/chỉnh tay, chỉ cập nhật `title`
            # khi nó vẫn là tiêu đề nguồn cũ (hoặc chưa có tiêu đề).
            untranslated_title = not old_ch.title or old_ch.title == old_ch.title_zh
            updates.append((ch.url, source_title, ch.title if untranslated_title else None, idx))
        elif action == "add":
            if choice.get("old_index") is not None:
                raise ValueError("Chương thêm mới không được trỏ tới chương cũ.")
            requested = choice.get("new_index")
            number = ordinal(ch.title_zh or ch.title)
            if requested is not None and (type(requested) is not int or requested <= 0):
                raise ValueError("Index thêm mới phải là số nguyên dương.")
            idx = requested
            if idx is None and number is not None and incoming_counts[number] == 1:
                idx = gaps.get(number)
            if idx is None:
                while next_index in reserved:
                    next_index += 1
                idx = next_index
                next_index += 1
            if idx in reserved:
                raise ValueError(f"Index #{idx} đã có chương hoặc được chọn để thêm nhiều lần.")
            reserved.add(idx)
            additions.append((idx, ch.url, ch.title))
        elif action != "skip" or choice.get("old_index") is not None or choice.get("new_index") is not None:
            raise ValueError("Lựa chọn ghép chương không hợp lệ.")
    if not updates and not additions:
        raise ValueError("Chưa chọn chương nào để chuyển nguồn.")
    # Same SQLite connection/transaction for source settings and TOC. No
    # save_manifest(): that method rewrites every chapter and can drop rows.
    conn = storage.conn
    with conn:
        current = storage.load_manifest()
        if current is None or fingerprint(current) != old_fingerprint:
            raise ValueError("Ebook đã thay đổi. Hãy xem trước lại trước khi xác nhận.")
        row = conn.execute("SELECT crawl_overrides_json, source_preset FROM ebooks WHERE slug=?", (storage.slug,)).fetchone()
        if row is None:
            raise ValueError("Ebook không tồn tại.")
        # Switching sites resets site-specific selectors/regex/anti-bot settings
        # to the new preset; keep only the explicit new TOC URL.
        crawl_overrides: dict = {"toc_url": toc_url}
        if crawl_mode is not None:
            if crawl_mode not in ("fetcher", "stealthy", "dynamic"):
                raise ValueError("Chế độ crawl không hợp lệ.")
            crawl_overrides["scrapling"] = {"mode": crawl_mode}
        if headless is not None:
            crawl_overrides["headless"] = headless
        conn.execute("UPDATE ebooks SET source_preset=?, crawl_overrides_json=?, source_url=?, "
                     "updated_at=datetime('now') WHERE slug=?",
                     (source_name, json.dumps(crawl_overrides), toc_url, storage.slug))
        for url, source_title, untranslated_title, idx in updates:
            if untranslated_title is None:
                conn.execute("UPDATE chapters SET url=?, title_zh=? WHERE ebook_slug=? AND idx=?",
                             (url, source_title, storage.slug, idx))
            else:
                conn.execute("UPDATE chapters SET url=?, title_zh=?, title=? WHERE ebook_slug=? AND idx=?",
                             (url, source_title, untranslated_title, storage.slug, idx))
        for idx, url, title in additions:
            conn.execute("INSERT INTO chapters (ebook_slug, idx, url, title, title_zh) VALUES (?,?,?,?,?)",
                         (storage.slug, idx, url, title, title))
    return {"matched": len(updates), "added": len(additions), "untouched": len(old.chapters) - len(updates)}
