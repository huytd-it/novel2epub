"""Từ điển entity (tên riêng: nhân vật, địa danh, ...) — logic thuần.

Entity giúp AI edit không "đổi tên" nhân vật/địa danh khi viết lại bản dịch. Mỗi
entity có `protect`: nếu bật, khi tạo AI edit draft ta thay literal bằng
placeholder CHỮ HOA ASCII (giống idiom protect — model copy như tên riêng, không
dịch nghiền) rồi khôi phục sau khi AI trả kết quả. Bản dịch mà AI edit đọc là
bản Local workspace với literal đã bị che, nên AI không thể sửa chữ.

Hai tầng nguồn:
- `entity_dictionary` — toàn cục (dùng chung mọi ebook).
- `ebook_entity_overrides` — override riêng cho từng ebook (thắng mục toàn cục
  cùng `source`).

Logic ở đây THUẦN (không I/O); Storage giữ tầng đọc/ghi 2 bảng này.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Placeholder prefix cho entity protect — chữ HOA ASCII như idiom protect.
_ENTITY_PREFIX = "ENT"


@dataclass(frozen=True)
class Entity:
    source: str
    target: str
    protect: bool = False


def make_entity(source: str, target: str, protect: bool = False) -> Entity | None:
    """Dựng Entity từ source/target; trả None nếu thiếu source."""
    source = (source or "").strip()
    target = (target or "").strip()
    if not source:
        return None
    return Entity(source=source, target=target, protect=bool(protect))


def merge_entries(global_entries, override_entries) -> list[Entity]:
    """Gộp entity toàn cục + override theo ebook; override thắng cùng `source`.

    Nhận các row dạng `(source, target, protect)` (như `idioms_from_rows`);
    trả danh sách Entity đã hợp nhất, sắp theo `source` để ổn định.
    """
    merged: dict[str, Entity] = {}
    for source, target, protect in global_entries:
        ent = make_entity(source, target, protect)
        if ent is not None:
            merged[ent.source] = ent
    for source, target, protect in override_entries:
        ent = make_entity(source, target, protect)
        if ent is not None:
            merged[ent.source] = ent
    return [merged[key] for key in sorted(merged)]


def filter_for_text(entities: list[Entity], vi_text: str) -> list[Entity]:
    """Chỉ giữ entity có `source` (literal VI) xuất hiện trong `vi_text`.

    Văn bản tiếng Việt có ranh giới từ nên so khớp theo từ (không phải
    substring) — `source` thường là chuỗi ngắn dễ false-positive nếu so substring
    (vd "Diệp" khớp trong "Diệp Trần"). Ranh giới từ coi dấu câu là ranh giới.
    """
    if not vi_text:
        return []
    words = set(re.findall(r"[\w\u00C0-\u1EF9]+", vi_text.lower()))
    out: list[Entity] = []
    for ent in entities:
        if not ent.source:
            continue
        if _word_matches(ent.source, words, vi_text):
            out.append(ent)
    return out


def _word_matches(source: str, words: set[str], text: str) -> bool:
    """Khớp `source` theo ranh giới từ; source chứa ký tự đặc biệt (chữ Hán,
    dấu, ...) thì fallback về substring."""
    import unicodedata
    if any('\u4e00' <= c <= '\u9fff' or '\u3400' <= c <= '\u4dbf' for c in source):
        return source in text
    token = source.lower().strip()
    if not token:
        return False
    if " " in token:
        return _spaced_match(token, text.lower())
    return token in words


def _spaced_match(token: str, lower_text: str) -> bool:
    for cand in re.findall(r"[\w\u00C0-\u1EF9 ]+", lower_text):
        if token in " " + cand.lower() + " ":
            return True
    return False


def format_llm_block(entities: list[Entity]) -> str:
    """Khối tham chiếu entity cho prompt AI edit (mềm — nếu entity protect đã
    được che bằng placeholder ở workspace thì khối này chỉ để AI hiểu ngữ cảnh).
    """
    if not entities:
        return ""
    lines = "\n".join(f"{ent.target}" for ent in entities if ent.target)
    return "Tên riêng/địa danh cần giữ nguyên:\n" + lines


def _placeholder(n: int) -> str:
    return f"{_ENTITY_PREFIX}{n}"


def protect_entities(text: str, entities: list[Entity]) -> tuple[str, dict[str, str]]:
    """Thay literal của entity `protect` trong `text` bằng placeholder.

    Trả `(text_đã_che, restore_map)` — restore_map: placeholder → target.
    Chỉ che entity protect; entity thường để AI edit thấy literal và giữ tự nhiên.
    Áp longest-first để entity dài không bị entity con phá.
    """
    restore: dict[str, str] = {}
    protect_ents = sorted(
        (ent for ent in entities if ent.protect and ent.source in text),
        key=lambda ent: len(ent.source),
        reverse=True,
    )
    n = 0
    for ent in protect_ents:
        if ent.source not in text:
            continue
        ph = _placeholder(n)
        text = text.replace(ent.source, ph)
        restore[ph] = ent.target
        n += 1
    return text, restore


def restore_entities(text: str, restore_map: dict[str, str]) -> str:
    """Khôi phục placeholder → target sau khi AI trả kết quả.

    Khoan dung với khoảng trắng model chèn giữa prefix và số; không phân biệt
    hoa/thường. Áp longest-first để ENT1 không nuốt ENT10. Placeholder không tìm
    thấy (bị model nghiền) → bỏ qua, tránh để lại token lạ.
    """
    for ph in sorted(restore_map, key=len, reverse=True):
        target = restore_map[ph]
        if ph in text:
            text = text.replace(ph, target)
            continue
        num = ph[len(_ENTITY_PREFIX):]
        pattern = re.escape(_ENTITY_PREFIX) + r"\s*" + re.escape(num) + r"(?!\d)"
        text = re.sub(pattern, target.replace("\\", "\\\\"), text, flags=re.IGNORECASE)
    return text
