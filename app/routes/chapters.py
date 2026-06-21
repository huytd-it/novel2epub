"""Xem & sửa tay 1 chương (raw + bản dịch)."""
from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from novel2epub.pipeline import step_crawl_selected, step_translate_selected
from novel2epub.storage import Storage

from .. import deps

router = APIRouter()


def _chapter_glossary(storage: Storage, raw: str, translated: str) -> list[dict[str, str | bool]]:
    """Return glossary rows with entries used in this chapter first."""
    haystack = f"{raw}\n{translated}".lower()
    rows: list[dict[str, str | bool]] = []
    for filename, label in (("names.txt", "Tên riêng"), ("vietphrase.txt", "Thuật ngữ")):
        for source, suggested in storage.read_glossary_file(filename).items():
            source_hit = source.lower() in haystack if source else False
            suggested_hit = suggested.lower() in haystack if suggested else False
            rows.append({
                "source": source,
                "suggested": suggested,
                "file": filename,
                "type": label,
                "relevant": source_hit or suggested_hit,
            })
    return sorted(rows, key=lambda row: (not row["relevant"], str(row["type"]), str(row["source"])))


def _chapter_context(storage: Storage, ch, raw: str, translated: str, slug: str, meta: dict | None = None) -> dict:
    glossary_rows = _chapter_glossary(storage, raw, translated)
    return {
        "ch": ch,
        "raw": raw,
        "translated": translated,
        "slug": slug,
        "meta": meta or {},
        "glossary_rows": glossary_rows,
        "glossary_relevant_count": sum(1 for row in glossary_rows if row["relevant"]),
    }


@router.get("/chapters/{index}")
def chapter_detail(request: Request, index: int):
    cfg = deps.cfg()
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")
    ch = next((c for c in manifest.chapters if c.index == index), None)
    if ch is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy chương.")

    raw = storage.read_raw(ch) if storage.has_raw(ch) else ""
    translated = storage.read_translated(ch) if storage.has_translated(ch) else ""
    return deps.templates.TemplateResponse(
        request,
        "chapter.html",
        _chapter_context(storage, ch, raw, translated, cfg.novel.slug),
    )


@router.get("/ebooks/{slug}/chapters/{index}")
def ebook_chapter_detail(request: Request, slug: str, index: int):
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")
    ch = next((c for c in manifest.chapters if c.index == index), None)
    if ch is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy chương.")

    raw = storage.read_raw(ch) if storage.has_raw(ch) else ""
    translated = storage.read_translated(ch) if storage.has_translated(ch) else ""
    meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
    return deps.templates.TemplateResponse(
        request,
        "chapter.html",
        _chapter_context(storage, ch, raw, translated, slug, meta),
    )


@router.post("/chapters/{index}")
def chapter_save(index: int, translated: str = Form(...)):
    """Lưu bản dịch sửa tay — chính là khâu 'edit' cuối cùng trước khi build."""
    cfg = deps.cfg()
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")
    ch = next((c for c in manifest.chapters if c.index == index), None)
    if ch is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy chương.")

    storage.write_translated(ch, translated)
    return RedirectResponse(url=f"/chapters/{index}", status_code=303)


@router.post("/ebooks/{slug}/chapters/{index}")
def ebook_chapter_save(slug: str, index: int, translated: str = Form(...)):
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")
    ch = next((c for c in manifest.chapters if c.index == index), None)
    if ch is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy chương.")

    storage.write_translated(ch, translated)
    return RedirectResponse(url=f"/ebooks/{slug}/chapters/{index}", status_code=303)


@router.post("/ebooks/{slug}/chapters/{index}/action")
def ebook_chapter_action(request: Request, slug: str, index: int, action: str = Form(...), override: bool = Form(False)):
    cfg = deps.resolved_cfg(slug)

    def _target(log):
        if action == "crawl":
            step_crawl_selected(cfg, log, force=override, selected_indexes=[index])
        elif action == "translate":
            step_translate_selected(cfg, log, force=override, selected_indexes=[index])
        else:
            raise ValueError(f"action không hợp lệ: {action!r}")

    started = request.app.state.job.start_custom(f"chapter-{action}", _target)
    if not started:
        raise HTTPException(status_code=409, detail="Đang có job khác chạy, vui lòng đợi.")
    return RedirectResponse(url=f"/ebooks/{slug}/chapters/{index}", status_code=303)
