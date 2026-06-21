"""Trang quản lý glossary: CRUD thủ công + AI gợi ý + AI rewrite chương."""
from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from novel2epub import glossary_ai
from novel2epub.pipeline import step_rewrite_chapters
from novel2epub.storage import Storage

from .. import deps

router = APIRouter()

_MAX_SUGGEST_CHAPTERS = 5


@router.get("/ebooks/{slug}/glossary")
def ebook_glossary(request: Request, slug: str):
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    names = storage.glossary_path("names.txt")
    vietphrase = storage.glossary_path("vietphrase.txt")
    return deps.templates.TemplateResponse(
        request,
        "glossary.html",
        {
            "slug": slug,
            "names": names.read_text(encoding="utf-8") if names.exists() else "",
            "vietphrase": vietphrase.read_text(encoding="utf-8") if vietphrase.exists() else "",
            "suggestions": [],
            "job": request.app.state.job.status(),
        },
    )


@router.post("/ebooks/{slug}/glossary")
def ebook_glossary_save(slug: str, names: str = Form(""), vietphrase: str = Form("")):
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    storage.write_glossary_file("names.txt", names)
    storage.write_glossary_file("vietphrase.txt", vietphrase)
    return RedirectResponse(url=f"/ebooks/{slug}/glossary", status_code=303)


@router.post("/ebooks/{slug}/glossary/suggest")
def ebook_glossary_suggest(
    request: Request, slug: str, chapter_from: int = Form(...), chapter_to: int = Form(...)
):
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    names = storage.glossary_path("names.txt")
    vietphrase = storage.glossary_path("vietphrase.txt")
    error = ""
    suggestions: list[dict] = []

    if manifest is None:
        error = "Chưa có manifest — hãy crawl trước."
    else:
        selected = [c for c in manifest.chapters if chapter_from <= c.index <= chapter_to]
        if len(selected) > _MAX_SUGGEST_CHAPTERS:
            error = f"Chỉ phân tích tối đa {_MAX_SUGGEST_CHAPTERS} chương/lần — hãy chọn phạm vi hẹp hơn."
        else:
            chapters_text = [
                (
                    storage.read_raw(c) if storage.has_raw(c) else "",
                    storage.read_translated(c) if storage.has_translated(c) else "",
                )
                for c in selected
            ]
            existing = glossary_ai.load_glossary(cfg.translate)
            suggestions = glossary_ai.suggest_glossary(cfg.translate, chapters_text, existing)
            if not suggestions:
                error = "AI không đề xuất được gì (hoặc gọi CLI lỗi) — kiểm tra log server."

    return deps.templates.TemplateResponse(
        request,
        "glossary.html",
        {
            "slug": slug,
            "names": names.read_text(encoding="utf-8") if names.exists() else "",
            "vietphrase": vietphrase.read_text(encoding="utf-8") if vietphrase.exists() else "",
            "suggestions": suggestions,
            "suggest_error": error,
            "chapter_from": chapter_from,
            "chapter_to": chapter_to,
            "job": request.app.state.job.status(),
        },
    )


@router.post("/ebooks/{slug}/glossary/apply")
async def ebook_glossary_apply(slug: str, request: Request):
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    form = await request.form()
    by_file: dict[str, list[str]] = {"names.txt": [], "vietphrase.txt": []}
    i = 0
    while f"source_{i}" in form:
        if f"selected_{i}" in form:
            source = form.get(f"source_{i}", "")
            suggested = form.get(f"suggested_{i}", "")
            target_file = form.get(f"target_file_{i}", "")
            if target_file in by_file and source and suggested:
                by_file[target_file].append(f"{source} = {suggested}")
        i += 1

    for name, lines in by_file.items():
        if not lines:
            continue
        path = storage.glossary_path(name)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        storage.write_glossary_file(name, existing + "\n".join(lines) + "\n")

    return RedirectResponse(url=f"/ebooks/{slug}/glossary", status_code=303)


@router.post("/ebooks/{slug}/glossary/rewrite")
def ebook_glossary_rewrite(request: Request, slug: str, chapter_from: int = Form(...), chapter_to: int = Form(...)):
    cfg = deps.resolved_cfg(slug)

    def _target(log):
        step_rewrite_chapters(cfg, log, start=chapter_from, end=chapter_to)

    started = request.app.state.job.start_custom("rewrite_chapters", _target)
    if not started:
        raise HTTPException(status_code=409, detail="Đang có job khác chạy, vui lòng đợi.")
    return RedirectResponse(url=f"/ebooks/{slug}/glossary", status_code=303)
