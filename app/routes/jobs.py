"""Chạy job nền (crawl/dịch/build/run) + trạng thái + tải EPUB."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse

from novel2epub.pipeline import step_crawl_selected
from novel2epub.storage import Storage

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


@router.post("/ebooks/{slug}/jobs/{step}")
def start_ebook_job(request: Request, slug: str, step: str):
    cfg = deps.resolved_cfg(slug)
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
