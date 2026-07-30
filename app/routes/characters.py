"""Trang "Nhân vật" theo ebook — bảng nhân vật + ngôi xưng dùng cho prompt dịch.

Khác trang Glossary (map tên → tên), bảng này mang thuộc tính (giới tính, tự
xưng, cách lời kể gọi, alias) và quan hệ CÓ HƯỚNG giữa hai nhân vật kèm mốc
chương — thứ LLM không đoán được từ văn bản.
"""
from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse

from novel2epub.storage import Storage

from .. import deps

router = APIRouter()


def _storage(slug: str) -> Storage:
    # Per-ebook giống glossary.py: dùng resolved_cfg (override riêng ebook nếu
    # có) thay vì cfg() chung — output.data_dir có thể khác giữa các ebook.
    cfg = deps.resolved_cfg(slug)
    return Storage(cfg.output.data_dir, cfg.novel.slug)


@router.get("/ebook/{slug}/characters")
def characters_page(request: Request, slug: str):
    return deps.templates.TemplateResponse(
        request,
        "characters.html",
        {"slug": slug, "job": request.app.state.job.status()},
    )


@router.get("/api/ebook/{slug}/characters/list")
def characters_list(slug: str):
    storage = _storage(slug)
    targets = {row[0]: row[1] for row in storage.read_character_entries()}
    by_a: dict[str, list[dict]] = {}
    for a, b, from_chapter, a_calls_b, a_self, note in storage.read_relation_entries():
        by_a.setdefault(a, []).append({
            "b_source": b,
            "b_target": targets.get(b, ""),
            "from_chapter": from_chapter,
            "a_calls_b": a_calls_b,
            "a_self": a_self,
            "note": note,
        })
    entries = [
        {
            "source": source, "target": target, "aliases": aliases, "gender": gender,
            "self_pronoun": self_pronoun, "narrator_ref": narrator_ref,
            "role_note": role_note, "importance": importance,
            "relations": by_a.get(source, []),
        }
        for source, target, aliases, gender, self_pronoun, narrator_ref, role_note,
            importance in storage.read_character_entries()
    ]
    return JSONResponse({"entries": entries, "total": len(entries)})


@router.post("/api/ebook/{slug}/characters/entry")
def characters_upsert(
    slug: str,
    source: str = Form(...),
    target: str = Form(""),
    aliases: str = Form(""),
    gender: str = Form(""),
    self_pronoun: str = Form(""),
    narrator_ref: str = Form(""),
    role_note: str = Form(""),
    importance: str = Form("side"),
    original_source: str = Form(""),
):
    """Autosave MỘT nhân vật. Đổi tên gốc (original_source khác source) → xoá
    mục cũ trước, giống cách trang Idioms xử lý."""
    source = source.strip()
    if not source:
        raise HTTPException(status_code=400, detail="Cần tên gốc của nhân vật.")
    storage = _storage(slug)
    orig = original_source.strip()
    if orig and orig != source:
        storage.delete_character(orig)
    storage.upsert_character(source, target, aliases, gender, self_pronoun,
                             narrator_ref, role_note, importance)
    return JSONResponse({"ok": True})


@router.post("/api/ebook/{slug}/characters/delete")
def characters_delete(slug: str, sources: str = Form(...)):
    """Xoá một hoặc nhiều nhân vật (ngăn bằng `|`), kéo theo quan hệ liên quan."""
    storage = _storage(slug)
    removed = sum(1 for s in sources.split("|") if storage.delete_character(s))
    return JSONResponse({"ok": True, "removed": removed})


@router.post("/api/ebook/{slug}/characters/relation")
def characters_upsert_relation(
    slug: str,
    a_source: str = Form(...),
    b_source: str = Form(...),
    from_chapter: int = Form(0),
    a_calls_b: str = Form(""),
    a_self: str = Form(""),
    note: str = Form(""),
):
    if not _storage(slug).upsert_relation(a_source, b_source, from_chapter,
                                          a_calls_b, a_self, note):
        raise HTTPException(status_code=400, detail="Cần cả hai nhân vật.")
    return JSONResponse({"ok": True})


@router.post("/api/ebook/{slug}/characters/relation/delete")
def characters_delete_relation(
    slug: str,
    a_source: str = Form(...),
    b_source: str = Form(...),
    from_chapter: int = Form(0),
):
    removed = _storage(slug).delete_relation(a_source, b_source, from_chapter)
    return JSONResponse({"ok": True, "removed": removed})
