"""Trang đọc chương — giao diện sách, tách biệt khỏi editor."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from novel2epub.storage import Storage
from novel2epub.toc import count_words

from .. import deps

router = APIRouter()


def _load_chapter_or_404(slug: str, index: int):
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")
    ch = next((c for c in manifest.chapters if c.index == index), None)
    if ch is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy chương.")
    return cfg, storage, manifest, ch


@router.get("/ebooks/{slug}/read")
def reader_root(request: Request, slug: str):
    """Redirect tới chương đầu tiên (hoặc bookmark gần nhất)."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None or not manifest.chapters:
        raise HTTPException(status_code=404, detail="Chưa có chương nào.")
    # Tìm chương đầu tiên có bản dịch
    for ch in manifest.chapters:
        if storage.has_translated(ch):
            return RedirectResponse(url=f"/ebooks/{slug}/read/{ch.index}", status_code=302)
    # Không có bản dịch nào → redirect chương đầu
    return RedirectResponse(url=f"/ebooks/{slug}/read/{manifest.chapters[0].index}", status_code=302)


@router.get("/ebooks/{slug}/read/{index}")
def reader_chapter(request: Request, slug: str, index: int):
    """Trang đọc chương với giao diện sách."""
    cfg, storage, manifest, ch = _load_chapter_or_404(slug, index)

    has_translated = storage.has_translated(ch)
    translated = storage.read_translated(ch) if has_translated else ""
    translated_paras = [p for p in translated.split("\n") if p.strip()] if translated else []

    # Danh sách chương cho navigation
    chapters_info = []
    for c in manifest.chapters:
        chapters_info.append({
            "index": c.index,
            "title": c.title or f"Chương {c.index}",
            "has_translated": storage.has_translated(c),
        })

    prev_ch = None
    next_ch = None
    for i, c in enumerate(manifest.chapters):
        if c.index == index:
            if i > 0:
                prev_ch = manifest.chapters[i - 1]
            if i < len(manifest.chapters) - 1:
                next_ch = manifest.chapters[i + 1]
            break

    return deps.templates.TemplateResponse(
        request,
        "reader.html",
        {
            "slug": slug,
            "ch": ch,
            "has_translated": has_translated,
            "translated_paras": translated_paras,
            "translated_word_count": count_words(translated) if translated else 0,
            "chapters_info": chapters_info,
            "prev_ch": prev_ch,
            "next_ch": next_ch,
        },
    )
