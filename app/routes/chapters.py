"""Xem & sửa tay 1 chương (raw + bản dịch)."""
from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

import html

from novel2epub import footnotes
from novel2epub.pipeline import (
    step_crawl_selected,
    step_review_chapter,
    step_rewrite_preview,
    step_suggest_chapter,
    step_translate_selected,
)
from novel2epub.storage import Storage
from novel2epub.toc import count_words

from .. import deps
from .glossary import _append_glossary_entry

_AI_STEPS = {
    "review": step_review_chapter,
    "suggest": step_suggest_chapter,
    "rewrite": step_rewrite_preview,
}

router = APIRouter()


def _chapter_glossary(storage: Storage, raw: str, translated: str) -> list[dict[str, str | bool | int]]:
    """Return glossary rows with entries used in this chapter first.

    raw_count/translated_count đếm số lần xuất hiện literal trong chương, dùng
    để soi vị trí (jump-to) và phát hiện thiếu thống nhất (vd có trong raw mà
    không thấy trong bản dịch).
    """
    haystack = f"{raw}\n{translated}".lower()
    notes = storage.read_glossary_notes()
    rows: list[dict[str, str | bool | int]] = []
    for filename, label in (("names.txt", "Tên riêng"), ("vietphrase.txt", "Thuật ngữ")):
        for source, suggested in storage.read_glossary_file(filename).items():
            source_hit = source.lower() in haystack if source else False
            suggested_hit = suggested.lower() in haystack if suggested else False
            raw_count = raw.count(source) if source else 0
            translated_count = translated.count(suggested) if suggested else 0
            rows.append({
                "source": source,
                "suggested": suggested,
                "note": notes.get(suggested, ""),
                "file": filename,
                "type": label,
                "relevant": source_hit or suggested_hit,
                "raw_count": raw_count,
                "translated_count": translated_count,
                "mismatch": raw_count > 0 and translated_count == 0,
            })
    return sorted(rows, key=lambda row: (not row["relevant"], str(row["type"]), str(row["source"])))


# Nhãn tiếng Việt cho category của AI review, gắn với mục III docs/rule.md.
_CATEGORY_LABELS = {
    "glossary": "Glossary",
    "consistency": "Nhất quán",
    "mistranslation": "Sai nghĩa",
    "hanviet": "Hán Việt",
    "fluency": "Văn phong",
    "other": "Khác",
}


def _render_translated_preview(storage: Storage, translated: str) -> tuple[str, list[dict]]:
    """Đánh dấu footnote trong bản dịch để hiện preview kèm chú thích trên web.

    Chỉ dùng để hiển thị (textarea sửa tay vẫn giữ text thuần, không có marker).
    """
    notes = storage.read_glossary_notes()
    marked, footnote_list = footnotes.annotate(translated, notes)
    escaped = "\n".join(
        f"<p>{footnotes.markers_to_html(html.escape(line))}</p>" if line.strip() else ""
        for line in marked.splitlines()
    )
    return escaped, footnote_list


def _chapter_context(storage: Storage, ch, raw: str, translated: str, slug: str, meta: dict | None = None) -> dict:
    glossary_rows = _chapter_glossary(storage, raw, translated)
    translated_preview_html, footnote_list = _render_translated_preview(storage, translated)
    return {
        "ch": ch,
        "raw": raw,
        "translated": translated,
        "translated_preview_html": translated_preview_html,
        "footnote_list": footnote_list,
        "footnotes_html": footnotes.render_footnotes_html(footnote_list),
        "raw_char_count": len(raw),
        "translated_word_count": count_words(translated),
        "slug": slug,
        "meta": meta or {},
        "glossary_rows": glossary_rows,
        "glossary_relevant_count": sum(1 for row in glossary_rows if row["relevant"]),
        "CATEGORY_LABELS": _CATEGORY_LABELS,
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
    meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
    return deps.templates.TemplateResponse(
        request,
        "chapter.html",
        _chapter_context(storage, ch, raw, translated, cfg.novel.slug, meta),
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

    started = request.app.state.job.start_custom(f"chapter-{action}", _target, category=action)
    if not started:
        raise HTTPException(status_code=409, detail="Đang có job khác chạy, vui lòng đợi.")
    return RedirectResponse(url=f"/ebooks/{slug}/chapters/{index}", status_code=303)


# --- AI hỗ trợ ngay trong editor: review / rewrite-preview / suggest glossary ---


def _load_chapter_or_404(cfg, index: int):
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")
    ch = next((c for c in manifest.chapters if c.index == index), None)
    if ch is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy chương.")
    return storage, ch


@router.post("/ebooks/{slug}/chapters/{index}/ai/rewrite/apply")
def ebook_chapter_ai_rewrite_apply(slug: str, index: int):
    """Người review chấp nhận bản nháp AI: chuyển bản dịch hiện tại sang
    before_rewrite (để khôi phục), ghi bản nháp thành bản dịch, xóa preview."""
    cfg = deps.resolved_cfg(slug)
    storage, ch = _load_chapter_or_404(cfg, index)
    meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
    preview = (meta.get("ai_rewrite") or {}).get("text", "")
    if not preview.strip():
        raise HTTPException(status_code=400, detail="Không có bản nháp AI để áp dụng.")
    current = storage.read_translated(ch) if storage.has_translated(ch) else ""
    meta["before_rewrite"] = current
    meta.pop("ai_rewrite", None)
    storage.write_translated(ch, preview)
    storage.write_meta(ch, meta)
    return RedirectResponse(url=f"/ebooks/{slug}/chapters/{index}", status_code=303)


@router.post("/ebooks/{slug}/chapters/{index}/ai/rewrite/discard")
def ebook_chapter_ai_rewrite_discard(slug: str, index: int):
    cfg = deps.resolved_cfg(slug)
    storage, ch = _load_chapter_or_404(cfg, index)
    meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
    if meta.pop("ai_rewrite", None) is not None:
        storage.write_meta(ch, meta)
    return RedirectResponse(url=f"/ebooks/{slug}/chapters/{index}", status_code=303)


@router.post("/ebooks/{slug}/chapters/{index}/ai/review/dismiss")
def ebook_chapter_ai_review_dismiss(slug: str, index: int):
    cfg = deps.resolved_cfg(slug)
    storage, ch = _load_chapter_or_404(cfg, index)
    meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
    if meta.pop("ai_review", None) is not None:
        storage.write_meta(ch, meta)
    return RedirectResponse(url=f"/ebooks/{slug}/chapters/{index}", status_code=303)


@router.post("/ebooks/{slug}/chapters/{index}/ai/suggest/apply")
async def ebook_chapter_ai_suggest_apply(slug: str, index: int, request: Request):
    """Thêm các đề xuất glossary được tick vào names/vietphrase rồi xóa khỏi meta."""
    cfg = deps.resolved_cfg(slug)
    storage, ch = _load_chapter_or_404(cfg, index)
    form = await request.form()
    i = 0
    while f"source_{i}" in form:
        if f"selected_{i}" in form:
            _append_glossary_entry(
                storage,
                form.get(f"target_file_{i}", ""),
                form.get(f"source_{i}", ""),
                form.get(f"suggested_{i}", ""),
            )
        i += 1
    meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
    if meta.pop("ai_suggestions", None) is not None:
        storage.write_meta(ch, meta)
    return RedirectResponse(url=f"/ebooks/{slug}/chapters/{index}", status_code=303)


@router.post("/ebooks/{slug}/chapters/{index}/ai/{op}")
def ebook_chapter_ai(request: Request, slug: str, index: int, op: str):
    """Chạy AI review / rewrite-preview / suggest cho ĐÚNG chương này (job nền)."""
    cfg = deps.resolved_cfg(slug)
    step = _AI_STEPS.get(op)
    if step is None:
        raise HTTPException(status_code=400, detail=f"Thao tác AI không hợp lệ: {op!r}")

    def _target(log):
        step(cfg, log, index=index)

    started = request.app.state.job.start_custom(f"ai-{op}-{index}", _target, category="translate")
    if not started:
        raise HTTPException(status_code=409, detail="Đang có job khác chạy, vui lòng đợi.")
    return RedirectResponse(url=f"/ebooks/{slug}/chapters/{index}", status_code=303)
