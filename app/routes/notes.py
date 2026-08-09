"""API ghi chú lỗi dịch của trang đọc: CRUD + gửi AI sửa + áp dụng vào bản biên tập.

Ghi chú lưu server-side per-ebook trong `<data_dir>/<slug>/notes.json`
(`Storage.read_notes`/`write_notes`). Luồng AI: gộp các ghi chú CÙNG 1 chương
thành 1 yêu cầu (đồng bộ, như parapolish — không job nền vì kết quả persist
vào notes.json trước khi trả response), người dùng duyệt Áp dụng/Bỏ qua từng
đề xuất. Áp dụng ghi vào `translated/` (bản biên tập), KHÔNG đụng snapshot
`translated_mt/`.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import JSONResponse

from novel2epub import glossary_ai
from novel2epub.notes import apply_note_fix
from novel2epub.storage import Storage

from .. import deps

router = APIRouter()

_VALID_STATUSES = {"open", "resolved", "dismissed", "stale"}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load(slug: str):
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")
    return cfg, storage, manifest


def _find_chapter(manifest, index: int):
    ch = next((c for c in manifest.chapters if c.index == index), None)
    if ch is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy chương.")
    return ch


def _find_note(notes: list[dict], note_id: str) -> dict:
    note = next((n for n in notes if n.get("id") == note_id), None)
    if note is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy ghi chú.")
    return note


@router.get("/api/ebooks/{slug}/notes")
def list_notes(slug: str, chapter: int | None = None):
    _cfg, storage, _manifest = _load(slug)
    notes = storage.read_notes()
    if chapter is not None:
        notes = [n for n in notes if n.get("chapter_index") == chapter]
    return JSONResponse({"notes": notes})


@router.post("/api/ebooks/{slug}/notes")
def create_note(
    slug: str,
    chapter_index: int = Form(...),
    para_index: int = Form(...),
    selected_text: str = Form(...),
    para_text: str = Form(""),
    note: str = Form(""),
):
    _cfg, storage, manifest = _load(slug)
    _find_chapter(manifest, chapter_index)
    selected_text = selected_text.strip()
    if not selected_text:
        raise HTTPException(status_code=400, detail="Chưa chọn đoạn văn bản nào.")

    new_note = {
        "id": uuid.uuid4().hex[:8],
        "chapter_index": chapter_index,
        "para_index": para_index,
        "selected_text": selected_text,
        "para_text": para_text,
        "note": note.strip(),
        "status": "open",
        "created_at": _now_iso(),
        "resolved_at": None,
        "suggestion": None,
    }
    notes = storage.read_notes()
    notes.append(new_note)
    storage.write_notes(notes)
    return JSONResponse(new_note)


@router.post("/api/ebooks/{slug}/notes/ai-fix")
def ai_fix_notes(slug: str, note_ids: str = Form(...), chapter_index: int = Form(...)):
    """Gửi 1 yêu cầu AI sửa các ghi chú đã chọn của ĐÚNG 1 chương.

    Đề xuất được ghi vào notes.json TRƯỚC khi trả response — đóng tab giữa
    chừng không mất kết quả, reload lại vẫn thấy.
    """
    cfg, storage, manifest = _load(slug)
    ch = _find_chapter(manifest, chapter_index)
    if not cfg.ai.openai.api_key and not cfg.ai.openai.base_url:
        raise HTTPException(status_code=400, detail="Chưa cấu hình AI biên tập (mục AI trong Settings).")

    id_list = [i.strip() for i in note_ids.split(",") if i.strip()]
    if not id_list:
        raise HTTPException(status_code=400, detail="Chưa chọn ghi chú nào.")

    notes = storage.read_notes()
    selected: list[dict] = []
    for note_id in id_list:
        note = _find_note(notes, note_id)
        if note.get("chapter_index") != chapter_index:
            raise HTTPException(
                status_code=400,
                detail="Chỉ gửi được ghi chú của cùng 1 chương trong mỗi yêu cầu.",
            )
        if note.get("status") != "open":
            raise HTTPException(
                status_code=400, detail=f"Ghi chú {note_id} không ở trạng thái chờ xử lý."
            )
        selected.append(note)

    branch = storage.active_branch(ch)
    if not storage.has_branch_text(ch, branch):
        raise HTTPException(status_code=400, detail="Chương chưa có bản dịch.")
    raw = storage.read_raw(ch) if storage.has_raw(ch) else ""
    translated = storage.read_branch_text(ch, branch)
    glossary = glossary_ai.load_glossary(cfg.translate, storage)

    try:
        fixes = glossary_ai.fix_passages(
            cfg.ai.openai, raw, translated, selected, glossary,
            filter_glossary=cfg.translate.glossary_filter,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    fixes_by_id = {f["id"]: f for f in fixes}
    generated_at = _now_iso()
    for note in selected:
        fix = fixes_by_id.get(note["id"])
        if fix:
            note["suggestion"] = {
                "fixed_text": fix["fixed_text"],
                "explanation": fix["explanation"],
                "generated_at": generated_at,
            }
    storage.write_notes(notes)
    return JSONResponse({"notes": selected})


@router.post("/api/ebooks/{slug}/notes/{note_id}/apply")
def apply_note(slug: str, note_id: str):
    """Áp dụng đề xuất AI: thay đoạn được đánh dấu trong `translated/`.

    Không tìm thấy đoạn (bản dịch đã đổi) → note chuyển `stale`, trả 409.
    """
    _cfg, storage, manifest = _load(slug)
    notes = storage.read_notes()
    note = _find_note(notes, note_id)
    suggestion = note.get("suggestion") or {}
    if note.get("status") != "open" or not suggestion.get("fixed_text"):
        raise HTTPException(status_code=409, detail="Ghi chú chưa có đề xuất AI hoặc đã xử lý.")

    ch = _find_chapter(manifest, note.get("chapter_index"))
    branch = storage.active_branch(ch)
    if not storage.has_branch_text(ch, branch):
        raise HTTPException(status_code=409, detail="Chương không còn bản dịch.")

    translated = storage.read_branch_text(ch, branch)
    new_text, err = apply_note_fix(translated, note, suggestion["fixed_text"])
    if new_text is None:
        note["status"] = "stale"
        storage.write_notes(notes)
        raise HTTPException(status_code=409, detail=err)

    storage.write_branch_text(ch, branch, new_text)
    note["status"] = "resolved"
    note["resolved_at"] = _now_iso()
    storage.write_notes(notes)
    return JSONResponse({"note": note, "applied": True})


@router.post("/api/ebooks/{slug}/notes/{note_id}/update")
def update_note(slug: str, note_id: str, note: str = Form("")):
    _cfg, storage, _manifest = _load(slug)
    notes = storage.read_notes()
    target = _find_note(notes, note_id)
    target["note"] = note.strip()
    storage.write_notes(notes)
    return JSONResponse(target)


@router.post("/api/ebooks/{slug}/notes/{note_id}/dismiss")
def dismiss_note(slug: str, note_id: str):
    _cfg, storage, _manifest = _load(slug)
    notes = storage.read_notes()
    target = _find_note(notes, note_id)
    target["status"] = "dismissed"
    target["resolved_at"] = _now_iso()
    storage.write_notes(notes)
    return JSONResponse(target)


@router.post("/api/ebooks/{slug}/notes/{note_id}/delete")
def delete_note(slug: str, note_id: str):
    _cfg, storage, _manifest = _load(slug)
    notes = storage.read_notes()
    _find_note(notes, note_id)
    storage.write_notes([n for n in notes if n.get("id") != note_id])
    return JSONResponse({"ok": True})
