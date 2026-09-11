"""Pure helpers cho tab "Nghi vấn" trang Glossary: gom mục đáng ngờ (2+ Hán
cùng 1 target Việt, source lồng nhau) + map conflicts từ lần dịch tự mở rộng
glossary, và kế hoạch sửa hàng loạt cho nút "Áp dụng" của bảng glossary.
Thuần dữ liệu — không DB/route để test không cần app."""
from __future__ import annotations

import re

from .han_cleanup import count_han

Entry = tuple[str, str, str]  # (source, target, note)


def _entry_dict(e: Entry) -> dict:
    return {"source": e[0], "target": e[1], "note": e[2]}


def same_target_groups(entries: list[Entry]) -> list[dict]:
    """Nhóm 2+ source có cùng target (so sau trim, không phân biệt hoa
    thường). Giữ thứ tự xuất hiện; target hiển thị lấy từ mục đầu nhóm."""
    by_key: dict[str, list[Entry]] = {}
    order: list[str] = []
    for e in entries:
        key = e[1].strip().lower()
        if not key:
            continue
        if key not in by_key:
            by_key[key] = []
            order.append(key)
        by_key[key].append(e)
    return [
        {
            "target": by_key[k][0][1].strip(),
            "entries": [_entry_dict(e) for e in by_key[k]],
        }
        for k in order
        if len(by_key[k]) >= 2
    ]


def nested_source_pairs(entries: list[Entry]) -> list[dict]:
    """Cặp mục mà source này là chuỗi con thực sự của source kia (张三 ⊂
    张三爷). O(n²) — vài nghìn mục vẫn tức thì, không cần index."""
    pairs: list[dict] = []
    for i, a in enumerate(entries):
        for b in entries[i + 1 :]:
            sa, sb = a[0], b[0]
            if sa == sb or not sa or not sb:
                continue
            if sa in sb:
                pairs.append({"outer": _entry_dict(b), "inner": _entry_dict(a)})
            elif sb in sa:
                pairs.append({"outer": _entry_dict(a), "inner": _entry_dict(b)})
    return pairs


def map_conflicts(raw) -> list[dict]:
    """Map conflicts từ extra json (`{"source","existing","new"}`; entry cũ có
    thể mang thêm `target_file` — bỏ) về format UI `{source, kept, new}`."""
    out: list[dict] = []
    for c in raw if isinstance(raw, list) else []:
        if not isinstance(c, dict):
            continue
        source = str(c.get("source", "")).strip()
        kept = str(c.get("existing", "")).strip()
        new = str(c.get("new", "")).strip()
        if source and new:
            out.append({"source": source, "kept": kept, "new": new})
    return out


def find_suspects(entries: list[Entry], conflicts_raw) -> dict:
    """Gộp cả 3 nhóm nghi vấn cho route /glossary/suspects."""
    return {
        "same_target": same_target_groups(entries),
        "nested_source": nested_source_pairs(entries),
        "conflicts": map_conflicts(conflicts_raw),
    }


# ── Kế hoạch sửa hàng loạt (nút "Áp dụng" trên bảng glossary) ──────────

INVALID_SOURCE_DETAIL = "Source phải chứa chữ Hán, không nhập tiếng Việt."

EMPTY_FIELD_DETAIL = "Cần cả Hán và Việt."
DUPLICATE_IN_BATCH_DETAIL = "Trùng Hán với một dòng khác trong đợt sửa này."
RENAME_COLLIDES_DETAIL = "Hán mới đã có sẵn trong glossary."


def plan_glossary_edits(existing: list[Entry], edits: list[dict]) -> list[dict]:
    """Chuẩn hoá + phân loại từng bản nháp sửa glossary TRƯỚC khi ghi.

    `existing` là glossary hiện có (đã merge 2 list), mỗi `edits` là một dòng
    người dùng đã sửa trong bảng: `{source, target, note, original_source}`.
    Trả về đúng thứ tự đó, mỗi dòng kèm giá trị cũ, `kind`
    (new/update/rename/unchanged) và `error` (rỗng nếu ghi được).

    Thuần dữ liệu, không đụng DB: route preview và route ghi dùng chung hàm này
    nên modal xem trước và kết quả áp dụng không thể lệch nhau.
    """
    by_source = {source: (target, note) for source, target, note in existing}
    planned: list[dict] = []
    seen: set[str] = set()

    for edit in edits:
        source = str(edit.get("source", "")).strip()
        target = str(edit.get("target", "")).strip()
        note = str(edit.get("note", "")).strip()
        original = str(edit.get("original_source", "")).strip()
        # Dòng thêm mới không có original_source; dòng sửa tra theo khoá cũ để
        # còn biết giá trị đang bị thay (dùng cho diff + lan truyền).
        lookup = original or source
        old_target, old_note = by_source.get(lookup, ("", ""))

        row = {
            "source": source,
            "target": target,
            "note": note,
            "original_source": original,
            "existing_source": lookup if lookup in by_source else "",
            "existing_target": old_target,
            "existing_note": old_note,
            "kind": "unchanged",
            "error": "",
        }

        renamed = bool(original) and source != original
        if not source or not target:
            row["error"] = EMPTY_FIELD_DETAIL
        elif count_han(source) == 0:
            row["error"] = INVALID_SOURCE_DETAIL
        elif source in seen:
            row["error"] = DUPLICATE_IN_BATCH_DETAIL
        elif (renamed or not original) and source in by_source and source != lookup:
            row["error"] = RENAME_COLLIDES_DETAIL
        else:
            seen.add(source)
            if lookup not in by_source:
                row["kind"] = "new"
            elif renamed:
                row["kind"] = "rename"
            elif target != old_target or note != old_note:
                row["kind"] = "update"

        planned.append(row)

    return planned


def replacement_pairs(planned: list[dict]) -> list[tuple[str, str]]:
    """Các cặp `Việt cũ → Việt mới` cần lan truyền vào bản dịch đã có, lấy từ
    kế hoạch của `plan_glossary_edits` (bỏ dòng lỗi, dòng mới và dòng giữ
    nguyên target). Dedup theo `old` — `Storage.replacement_counts` và
    `apply_replacements` quét một lượt nên `old` trùng chỉ được tính một lần."""
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for row in planned:
        if row["error"] or row["kind"] == "unchanged":
            continue
        old, new = row["existing_target"], row["target"]
        if not old or old == new or old in seen:
            continue
        seen.add(old)
        pairs.append((old, new))
    return pairs


# ── Lọc mục có giá trị đáng ngờ (nút "Lọc" trên bảng glossary) ─────────

# Chữ cái Latin kể cả nguyên âm có dấu tiếng Việt (Latin-1 Supplement,
# Extended-A/B và Extended Additional — nơi chứa ạ ả ấ ầ ...).
_LATIN_RE = re.compile(r"[A-Za-z\u00c0-\u024f\u1e00-\u1eff]")

# Mỗi cờ: (nhãn hiển thị, mô tả ngắn cho tooltip UI).
GLOSSARY_FLAGS: dict[str, tuple[str, str]] = {
    "vi_han": ("Việt còn chữ Hán", "Cột Việt còn sót ký tự Trung — chưa dịch hết."),
    "han_latin": ("Hán lẫn Latin", "Cột Hán chứa chữ cái Latin/tiếng Việt — source sai."),
    "same": ("Việt trùng Hán", "Cột Việt chép y hệt cột Hán — chưa dịch."),
    "no_han": ("Hán không có chữ Hán", "Cột Hán không chứa ký tự Trung nào."),
}


def entry_flags(source: str, target: str) -> set[str]:
    """Các cờ "giá trị đáng ngờ" của MỘT mục glossary.

    Thuần chuỗi, không DB: dùng chung cho bộ đếm ở đầu bảng và cho bộ lọc phân
    trang, nên con số trên chip lọc luôn khớp số dòng lọc ra.
    """
    source, target = (source or "").strip(), (target or "").strip()
    flags: set[str] = set()
    if count_han(target):
        flags.add("vi_han")
    if _LATIN_RE.search(source):
        flags.add("han_latin")
    if source and source == target:
        flags.add("same")
    if not count_han(source):
        flags.add("no_han")
    return flags


def count_entry_flags(entries: list[Entry]) -> dict[str, int]:
    """Số mục dính từng cờ (một mục có thể dính nhiều cờ)."""
    counts = {name: 0 for name in GLOSSARY_FLAGS}
    for source, target, _note in entries:
        for flag in entry_flags(source, target):
            counts[flag] += 1
    return counts


def parse_flags(raw: str) -> list[str]:
    """`"vi_han,same"` → các cờ hợp lệ, giữ thứ tự, bỏ trùng và tên lạ."""
    out: list[str] = []
    for part in (raw or "").split(","):
        name = part.strip()
        if name in GLOSSARY_FLAGS and name not in out:
            out.append(name)
    return out


def filter_by_flags(entries: list[Entry], flags: list[str]) -> list[Entry]:
    """Giữ mục dính ÍT NHẤT MỘT cờ trong `flags` (OR). Danh sách cờ rỗng =
    không lọc (trả nguyên danh sách)."""
    if not flags:
        return list(entries)
    wanted = set(flags)
    return [e for e in entries if entry_flags(e[0], e[1]) & wanted]
