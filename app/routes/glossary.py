"""Trang quản lý glossary: CRUD thủ công + AI gợi ý + AI rewrite chương."""
from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from novel2epub import glossary_ai
from novel2epub.pipeline import step_find_replace, step_rewrite_chapters
from novel2epub.storage import Storage

from .. import deps

router = APIRouter()

_MAX_SUGGEST_CHAPTERS = 5
_MAX_EVALUATE_CHAPTERS = 5
_GLOSSARY_FILES = ("names.txt", "vietphrase.txt")


def _append_glossary_entry(
    storage: Storage, target_file: str, source: str, suggested: str, note: str = ""
) -> bool:
    """Thêm 1 dòng `source = suggested [| note]` vào file glossary, bỏ qua nếu thiếu
    dữ liệu hoặc mục đã tồn tại với đúng giá trị đó. Trả True nếu có ghi thật."""
    source, suggested, note = source.strip(), suggested.strip(), note.strip()
    if not source or not suggested or target_file not in _GLOSSARY_FILES:
        return False
    if storage.read_glossary_file(target_file).get(source) == suggested and not note:
        return False

    path = storage.glossary_path(target_file)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    line = f"{source} = {suggested}" + (f" | {note}" if note else "")
    storage.write_glossary_file(target_file, f"{existing}{line}\n")
    return True


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


@router.post("/ebooks/{slug}/glossary/evaluate")
def ebook_glossary_evaluate(
    request: Request, slug: str, chapter_from: int = Form(...), chapter_to: int = Form(...)
):
    """AI đánh giá glossary + bản dịch của một phạm vi chương — chỉ trả báo cáo
    (read-only), không sửa file, không áp dụng gì."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    names = storage.glossary_path("names.txt")
    vietphrase = storage.glossary_path("vietphrase.txt")
    error = ""
    report: dict | None = None

    if manifest is None:
        error = "Chưa có manifest — hãy crawl trước."
    else:
        selected = [
            c for c in manifest.chapters if chapter_from <= c.index <= chapter_to and storage.has_translated(c)
        ]
        if not selected:
            error = "Không có chương đã dịch nào trong phạm vi đã chọn."
        elif len(selected) > _MAX_EVALUATE_CHAPTERS:
            error = f"Chỉ đánh giá tối đa {_MAX_EVALUATE_CHAPTERS} chương/lần — hãy chọn phạm vi hẹp hơn."
        else:
            chapters_text = [
                (storage.read_raw(c) if storage.has_raw(c) else "", storage.read_translated(c))
                for c in selected
            ]
            glossary = glossary_ai.load_glossary(cfg.translate)
            report = glossary_ai.evaluate_translation(cfg.translate, chapters_text, glossary)
            if not report.get("summary") and not report.get("issues"):
                error = "AI không trả về đánh giá (hoặc gọi CLI lỗi) — kiểm tra log server."

    return deps.templates.TemplateResponse(
        request,
        "glossary.html",
        {
            "slug": slug,
            "names": names.read_text(encoding="utf-8") if names.exists() else "",
            "vietphrase": vietphrase.read_text(encoding="utf-8") if vietphrase.exists() else "",
            "suggestions": [],
            "report": report,
            "evaluate_error": error,
            "eval_chapter_from": chapter_from,
            "eval_chapter_to": chapter_to,
            "job": request.app.state.job.status(),
        },
    )


@router.post("/ebooks/{slug}/glossary/apply")
async def ebook_glossary_apply(slug: str, request: Request):
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
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

    return RedirectResponse(url=f"/ebooks/{slug}/glossary", status_code=303)


@router.post("/ebooks/{slug}/glossary/quick-add")
def ebook_glossary_quick_add(
    slug: str,
    chapter_index: int = Form(...),
    source: str = Form(""),
    suggested: str = Form(""),
    note: str = Form(""),
    target_file: str = Form("vietphrase.txt"),
):
    """Thêm nhanh 1 mục glossary ngay từ trang chương — dùng khi đang đọc bản
    dịch và phát hiện thuật ngữ/tên riêng cần thống nhất, không cần qua trang
    Glossary riêng."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    _append_glossary_entry(storage, target_file, source, suggested, note)
    return RedirectResponse(url=f"/ebooks/{slug}/chapters/{chapter_index}", status_code=303)


@router.post("/ebooks/{slug}/glossary/find-replace")
def ebook_glossary_find_replace(
    request: Request,
    slug: str,
    find: str = Form(...),
    replace: str = Form(""),
    chapter_from: int = Form(0),
    chapter_to: int = Form(0),
    also_raw: bool = Form(False),
):
    """Tìm & thay thế literal trên các chương đã dịch (chạy nền qua job system)."""
    cfg = deps.resolved_cfg(slug)
    start = chapter_from or None
    end = chapter_to or None

    def _target(log):
        step_find_replace(
            cfg, log, find=find, replace=replace, start=start, end=end, also_raw=also_raw
        )

    started = request.app.state.job.start_custom("find_replace", _target)
    if not started:
        raise HTTPException(status_code=409, detail="Đang có job khác chạy, vui lòng đợi.")
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
