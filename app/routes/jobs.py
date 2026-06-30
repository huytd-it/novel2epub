"""Chạy job nền (crawl/dịch/build/run) + trạng thái + tải EPUB."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse

from novel2epub.pipeline import step_crawl_selected
from novel2epub.pipeline import step_translate_selected
from novel2epub.pipeline import step_translate_toc_selected
from novel2epub.storage import Storage
from novel2epub.toc import apply_chapter_query, chapter_rows, select_visible_range

from .. import deps
from ..job import _STEPS, _STEP_CATEGORY

router = APIRouter()


def _parse_optional_int(value: str) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


@router.post("/jobs/{step}")
def start_job(request: Request, step: str):
    cfg = deps.cfg()
    request.app.state.job.start(step, cfg)
    return RedirectResponse(url="/", status_code=303)


@router.post("/ebooks/{slug}/jobs/crawl-range")
def start_ebook_crawl_range(
    request: Request,
    slug: str,
    start: str = Form(""),
    end: str = Form(""),
    force: bool = Form(False),
    retries: int = Form(0),
    engine: str = Form(""),
    delay: str = Form(""),
):
    """Crawl theo phạm vi chương + tùy chọn nâng cao (delay, retry, force)."""
    cfg = deps.resolved_cfg(slug)

    delay_val = (delay or "").strip()
    if delay_val:
        try:
            cfg.crawl.delay_seconds = max(0.0, float(delay_val))
        except ValueError:
            pass

    start_idx = _parse_optional_int(start)
    end_idx = _parse_optional_int(end)
    retries = max(0, min(retries, 10))

    def _target(log):
        step_crawl_selected(
            cfg,
            log,
            start=start_idx,
            end=end_idx,
            force=force,
            retries=retries,
        )

    request.app.state.job.start_custom("crawl", _target, category="crawl")
    return RedirectResponse(url=f"/ebooks/{slug}", status_code=303)


@router.post("/ebooks/{slug}/jobs/chapter-action")
def start_ebook_chapter_action(
    request: Request,
    slug: str,
    action: str = Form(...),
    sort: str = Form("source"),
    direction: str = Form("asc"),
    search: str = Form(""),
    filter_raw: str = Form("any"),
    filter_translated: str = Form("any"),
    filter_missing: str = Form("any"),
    range_start: str = Form(""),
    range_end: str = Form(""),
    checked_indexes: Annotated[list[int], Form()] = [],
    targeting_mode: str = Form("range"),
    override: bool = Form(False),
):
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")
    rows = apply_chapter_query(
        chapter_rows(manifest.chapters, storage),
        sort=sort,
        direction=direction,
        search=search,
        filter_raw=filter_raw,
        filter_translated=filter_translated,
        filter_missing=filter_missing,
    )
    visible_indexes = {row.index for row in rows}
    if targeting_mode == "checked":
        selected = [idx for idx in checked_indexes if idx in visible_indexes]
    else:
        selected = select_visible_range(rows, _parse_optional_int(range_start), _parse_optional_int(range_end))
    if not selected:
        raise HTTPException(status_code=400, detail="Không có chương nào được chọn.")

    def _target(log):
        if action == "crawl":
            log(
                f"[config] action=crawl "
                f"ai_fallback={cfg.crawl.ai_fallback!r} force={override!r} "
                f"selected={len(selected)} chương"
            )
            try:
                step_crawl_selected(cfg, log, force=override, selected_indexes=selected)
            except Exception as e:  # noqa: BLE001 - log chi tiết config trước khi job.py ghi traceback
                log(f"[config] Lỗi khi crawl: {e}")
                raise
        elif action == "translate":
            log(
                f"[config] action=translate type={cfg.translate.type!r} "
                f"preset={cfg.translate.preset!r} force={override!r} "
                f"selected={len(selected)} chương"
            )
            try:
                step_translate_selected(cfg, log, force=override, selected_indexes=selected)
            except Exception as e:  # noqa: BLE001 - log chi tiết config trước khi job.py ghi traceback
                log(f"[config] Lỗi khi dịch với type={cfg.translate.type!r} preset={cfg.translate.preset!r}: {e}")
                raise
        else:
            raise ValueError(f"action không hợp lệ: {action!r}")

    request.app.state.job.start_custom(f"chapter-{action}", _target, category=action)
    return RedirectResponse(url=f"/ebooks/{slug}", status_code=303)


@router.post("/ebooks/{slug}/jobs/translate-toc-selected")
def start_ebook_translate_toc_selected(
    request: Request,
    slug: str,
    checked_indexes: Annotated[list[int], Form()] = [],
    override: bool = Form(False),
):
    """Dịch tiêu đề chương (TOC) cho các chương đã tick, không đụng nội dung."""
    cfg = deps.resolved_cfg(slug)
    if not checked_indexes:
        raise HTTPException(status_code=400, detail="Không có chương nào được chọn.")

    def _target(log):
        step_translate_toc_selected(cfg, log, force=override, selected_indexes=checked_indexes)

    request.app.state.job.start_custom("translate-toc-selected", _target, category="translate")
    return RedirectResponse(url=f"/ebooks/{slug}", status_code=303)


@router.post("/ebooks/{slug}/jobs/build-selected")
def start_ebook_build_selected(
    request: Request,
    slug: str,
    checked_indexes: Annotated[list[int], Form()] = [],
):
    """Build EPUB chỉ từ các chương đã tick."""
    cfg = deps.resolved_cfg(slug)
    if not checked_indexes:
        raise HTTPException(status_code=400, detail="Không có chương nào được chọn.")

    def _target(log):
        from novel2epub.pipeline import step_build_selected

        step_build_selected(cfg, log, selected_indexes=checked_indexes)

    request.app.state.job.start_custom("build-selected", _target, category="both")
    return RedirectResponse(url=f"/ebooks/{slug}", status_code=303)


@router.post("/ebooks/{slug}/jobs/{category}/cancel")
def cancel_ebook_job(request: Request, slug: str, category: str):
    """Yêu cầu dừng job crawl/dịch đang chạy (job tự kiểm tra cờ này giữa các chương)."""
    if category not in ("crawl", "translate"):
        raise HTTPException(status_code=400, detail=f"category không hợp lệ: {category!r}")
    cancelled = request.app.state.job.request_cancel(category)
    if not cancelled:
        raise HTTPException(status_code=409, detail="Không có job nào đang chạy để dừng.")
    return RedirectResponse(url=f"/ebooks/{slug}", status_code=303)


@router.post("/ebooks/{slug}/jobs/{step}")
def start_ebook_job(request: Request, slug: str, step: str, force: bool = Form(False)):
    cfg = deps.resolved_cfg(slug)
    if step == "fetch-toc" and force:
        def _target(log):
            from novel2epub.pipeline import step_fetch_toc

            step_fetch_toc(cfg, log, force=True)

        request.app.state.job.start_custom(step, _target, category="crawl")
    else:
        request.app.state.job.start(step, cfg)
    return RedirectResponse(url=f"/ebooks/{slug}", status_code=303)


@router.get("/api/status")
def api_status(request: Request):
    """Shim tương thích: ánh xạ payload queue mới sang shape cũ {crawl, translate}."""
    return request.app.state.job.status()


@router.get("/queue")
def queue_page(request: Request):
    from ..deps import library

    lib = library()
    ebook_list = sorted(lib.ebooks.keys()) if lib.ebooks else []
    return deps.templates.TemplateResponse(
        request,
        "queue.html",
        {
            "queue": request.app.state.job.queue.snapshot(),
            "steps": list(_STEPS.keys()),
            "ebooks": ebook_list,
        },
    )


@router.get("/api/queue")
def api_queue(request: Request):
    return request.app.state.job.queue.snapshot()


@router.post("/api/queue/{job_id}/cancel")
def api_queue_cancel(request: Request, job_id: str):
    ok = request.app.state.job.queue.cancel(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job không tồn tại hoặc đã kết thúc.")
    return {"ok": True}


@router.post("/api/queue/{job_id}/retry")
def api_queue_retry(request: Request, job_id: str):
    job = request.app.state.job.queue.retry(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Không thể retry job này.")
    return {"ok": True, "job_id": job.id}


@router.post("/api/queue/{job_id}/reorder")
def api_queue_reorder(request: Request, job_id: str, before_id: str = Form("")):
    ok = request.app.state.job.queue.reorder(job_id, before_id or None)
    if not ok:
        raise HTTPException(status_code=400, detail="Không thể reorder job này.")
    return {"ok": True}


@router.post("/api/queue/enqueue")
def api_queue_enqueue(
    request: Request,
    step: str = Form(...),
    ebook: str | None = Form(None),
):
    if step not in _STEPS:
        raise HTTPException(status_code=400, detail=f"Step không hợp lệ: {step!r}")
    category = _STEP_CATEGORY.get(step, "crawl")
    if ebook:
        cfg = deps.resolved_cfg(ebook)
    else:
        cfg = deps.cfg()
    result = request.app.state.job.enqueue_step(step, cfg, label=step, ebook=ebook or "")
    if result is None:
        raise HTTPException(status_code=400, detail=f"Không thể enqueue step {step!r}.")
    return result


@router.get("/api/queue/{job_id}/log")
def api_queue_log(request: Request, job_id: str):
    log_lines = request.app.state.job.queue.job_log(job_id)
    if log_lines is None:
        raise HTTPException(status_code=404, detail="Job không tồn tại.")
    return {"log": log_lines}


@router.get("/api/logs")
def api_logs(request: Request):
    return request.app.state.job.queue.logs_snapshot(limit=30)


@router.get("/logs")
def logs_page(request: Request):
    from ..deps import library

    lib = library()
    ebook_list = sorted(lib.ebooks.keys()) if lib.ebooks else []
    return deps.templates.TemplateResponse(
        request,
        "logs.html",
        {
            "ebooks": ebook_list,
            "steps": list(_STEPS.keys()),
        },
    )


@router.get("/download")
def download():
    cfg = deps.cfg()
    path = Path(cfg.epub_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Chưa có EPUB, hãy chạy bước build.")
    return FileResponse(path, filename=path.name, media_type="application/epub+zip")


@router.get("/ebooks/{slug}/cover")
def ebook_cover(slug: str):
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    path = storage.cover_fs_path(manifest) if manifest else None
    if path is None:
        raise HTTPException(status_code=404, detail="Chưa có ảnh bìa.")
    return FileResponse(path, filename=path.name)


@router.get("/ebooks/{slug}/download")
def ebook_download(slug: str):
    cfg = deps.resolved_cfg(slug)
    path = Path(cfg.epub_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Chưa có EPUB, hãy chạy bước build.")
    return FileResponse(path, filename=path.name, media_type="application/epub+zip")
