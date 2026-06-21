"""Chạy job nền (crawl/dịch/build/run) + trạng thái + tải EPUB."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse

from novel2epub.pipeline import step_crawl_selected
from novel2epub.pipeline import step_translate_selected
from novel2epub.storage import Storage
from novel2epub.toc import apply_chapter_query, chapter_rows, select_visible_range

from .. import deps

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
    started = request.app.state.job.start(step, cfg)
    if not started:
        raise HTTPException(status_code=409, detail="Đang có job khác chạy, vui lòng đợi.")
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
    """Crawl theo phạm vi chương + tùy chọn nâng cao (engine, delay, retry, force)."""
    cfg = deps.resolved_cfg(slug)

    # Override cấu hình crawl tại thời điểm chạy (cfg là bản load mới mỗi request).
    if engine:
        cfg.crawl.engine = engine
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

    started = request.app.state.job.start_custom("crawl", _target)
    if not started:
        raise HTTPException(status_code=409, detail="Đang có job khác chạy, vui lòng đợi.")
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
            step_crawl_selected(cfg, log, force=override, selected_indexes=selected)
        elif action == "translate":
            step_translate_selected(cfg, log, force=override, selected_indexes=selected)
        else:
            raise ValueError(f"action không hợp lệ: {action!r}")

    started = request.app.state.job.start_custom(f"chapter-{action}", _target)
    if not started:
        raise HTTPException(status_code=409, detail="Đang có job khác chạy, vui lòng đợi.")
    return RedirectResponse(url=f"/ebooks/{slug}", status_code=303)


@router.post("/ebooks/{slug}/jobs/{step}")
def start_ebook_job(request: Request, slug: str, step: str, force: bool = Form(False)):
    cfg = deps.resolved_cfg(slug)
    if step == "fetch-toc" and force:
        def _target(log):
            from novel2epub.pipeline import step_fetch_toc

            step_fetch_toc(cfg, log, force=True)

        started = request.app.state.job.start_custom(step, _target)
    else:
        started = request.app.state.job.start(step, cfg)
    if not started:
        raise HTTPException(status_code=409, detail="Đang có job khác chạy, vui lòng đợi.")
    return RedirectResponse(url=f"/ebooks/{slug}", status_code=303)


@router.get("/api/status")
def api_status(request: Request):
    return request.app.state.job.status()


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
