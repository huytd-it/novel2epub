"""Pure helpers cho tab "Nghi vấn" trang Glossary: gom mục đáng ngờ (2+ Hán
cùng 1 target Việt, source lồng nhau) + map conflicts từ lần dịch tự mở rộng
glossary. Thuần dữ liệu — không DB/route để test không cần app."""
from __future__ import annotations

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
