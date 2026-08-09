"""Trang "Từ điển chung" — kho idiom/thành ngữ DÙNG CHUNG mọi ebook (bảng
`idioms` global, không gắn slug). CRUD inline + import/export text + seed.

Idiom 3 phần: Hán (source) · bản đẹp (target/natural) · bản máy hay ra
(literals, ngăn `|`) hoặc cờ `protect`. LLM nhận idiom làm tham chiếu prompt;
MT 57M hậu-chuẩn-hoá literal→natural + protect zh→placeholder.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Form, HTTPException, Request
from fastapi.responses import JSONResponse

from novel2epub import idioms as idioms_mod
from novel2epub.storage import Storage, parse_glossary_line

from .. import deps

router = APIRouter()

# Slug sentinel: bảng idioms là global (không có cột ebook_slug) nên slug chỉ để
# dựng Storage — các method idiom bỏ qua slug và KHÔNG tạo row ebooks.
_GLOBAL = "__global__"


def _storage() -> Storage:
    return Storage(deps.cfg().output.data_dir, _GLOBAL)


def _entry_dict(source: str, target: str, literals: str, protect: int) -> dict:
    return {
        "source": source,
        "target": target,
        "literals": literals,
        "protect": bool(protect),
    }


@router.get("/api/idioms/list")
def idioms_list(page: int = 1, per_page: int = 50, q: str = "", sort: str = "", dir: str = "asc"):
    storage = _storage()
    # SPA là giao diện duy nhất; seed mặc định khi API được đọc lần đầu thay vì
    # phụ thuộc side effect của route HTML `/idioms` đã bị loại bỏ.
    storage.seed_idioms_if_empty(idioms_mod.DEFAULT_IDIOM_SEED)
    per_page = max(1, min(int(per_page), 500))
    total = storage.count_idioms(q)
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(int(page), pages))
    offset = (page - 1) * per_page
    rows = storage.read_idioms_page(offset, per_page, q, sort, dir)
    return JSONResponse(
        {
            "entries": [_entry_dict(s, t, lit, p) for s, t, lit, p in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": pages,
        }
    )


@router.post("/api/idioms/entry")
def idioms_upsert_entry(
    source: str = Form(...),
    target: str = Form(...),
    literals: str = Form(""),
    protect: str = Form(""),
    original_source: str = Form(""),
):
    """Autosave MỘT idiom (thêm/sửa). `protect` truthy → cờ protect. Đổi Hán
    (original_source khác source) → xoá mục cũ trước."""
    source, target = source.strip(), target.strip()
    if not source or not target:
        raise HTTPException(status_code=400, detail="Cần cả Hán và bản dịch đẹp.")
    protect_int = 1 if str(protect).strip().lower() in ("1", "true", "on", "yes") else 0
    storage = _storage()
    orig = original_source.strip()
    if orig and orig != source:
        storage.delete_idiom(orig)
    storage.upsert_idiom(source, target, literals.strip(), protect_int)
    return JSONResponse({"ok": True})


@router.post("/api/idioms/entry/delete")
def idioms_delete_entry(source: str = Form(...)):
    source = source.strip()
    if not source:
        raise HTTPException(status_code=400, detail="Thiếu mục cần xoá.")
    _storage().delete_idiom(source)
    return JSONResponse({"ok": True})


@router.post("/api/idioms/entries/delete")
def idioms_delete_entries(payload: dict = Body(...)):
    sources = [str(s).strip() for s in payload.get("sources", []) if str(s).strip()]
    if not sources:
        raise HTTPException(status_code=400, detail="Chưa chọn mục nào để xoá.")
    storage = _storage()
    deleted = sum(1 for s in sources if storage.delete_idiom(s))
    return JSONResponse({"deleted": deleted})


@router.post("/api/idioms/seed")
def idioms_seed():
    """Nạp lại bộ mẫu (test.md) — CHỈ khi kho trống. Trả số mục đã nạp."""
    n = _storage().seed_idioms_if_empty(idioms_mod.DEFAULT_IDIOM_SEED)
    return JSONResponse({"seeded": n})


def _format_note(literals: str, protect: int) -> str:
    parts = [p.strip() for p in (literals or "").split("|") if p.strip()]
    if protect:
        parts.append(idioms_mod.PROTECT_TOKEN)
    return " | ".join(parts)


@router.post("/api/idioms/export")
def idioms_export():
    """Xuất toàn bộ idiom dạng text `Hán = bản đẹp | bản máy… / @protect`."""
    rows = _storage().read_idiom_entries()
    lines = []
    for source, target, literals, protect in rows:
        note = _format_note(literals, protect)
        lines.append(f"{source} = {target}" + (f" | {note}" if note else ""))
    text = "\n".join(lines)
    return JSONResponse({"text": text, "count": len(rows)})


@router.post("/api/idioms/import")
def idioms_import(text: str = Form(...)):
    """Nhập (gộp) idiom từ text. Mỗi dòng `Hán = bản đẹp | bản máy | @protect`.
    Trùng Hán → cập nhật. Trả {added, updated}."""
    storage = _storage()
    existing = {s for s, _t, _l, _p in storage.read_idiom_entries()}
    added = updated = 0
    for line in text.replace("\r\n", "\n").split("\n"):
        parsed = parse_glossary_line(line)
        if not parsed:
            continue
        source, target, note = parsed
        literals, protect = idioms_mod.parse_idiom_note(note)
        if storage.upsert_idiom(source, target, " | ".join(literals), 1 if protect else 0):
            if source in existing:
                updated += 1
            else:
                added += 1
                existing.add(source)
    return JSONResponse({"added": added, "updated": updated})
