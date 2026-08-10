"""Trang chủ (danh sách ebook) + trang tổng quan 1 ebook."""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Annotated

import yaml
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse

from novel2epub.config_writer import update_ebook
from novel2epub.progress import chapter_progress
from novel2epub.queue_labels import job_label
from novel2epub.storage import Storage
from novel2epub.toc import apply_chapter_query, chapter_rows

from .. import deps
from ..cost_summary import read_cost_summary
from ..library_state import archived_slugs, set_archived

router = APIRouter()


def _chapter_rows(
    cfg,
    *,
    sort: str = "source",
    direction: str = "asc",
    search: str = "",
    filter_raw: str = "any",
    filter_translated: str = "any",
    filter_missing: str = "any",
    stats_map: dict | None = None,
):
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        return []
    return apply_chapter_query(
        chapter_rows(manifest.chapters, storage, stats_map=stats_map),
        sort=sort,
        direction=direction,
        search=search,
        filter_raw=filter_raw,
        filter_translated=filter_translated,
        filter_missing=filter_missing,
    )


@router.post("/library/ebooks/{slug}/archive")
def archive_ebook(slug: str):
    set_archived(deps.LIBRARY_STATE_PATH, slug, True)
    return RedirectResponse(url="/library", status_code=303)


@router.post("/library/ebooks/{slug}/unarchive")
def unarchive_ebook(slug: str):
    set_archived(deps.LIBRARY_STATE_PATH, slug, False)
    return RedirectResponse(url="/library?show_archived=1", status_code=303)


@router.post("/library/ebooks/bulk-action")
def bulk_action(
    request: Request,
    action: str = Form(...),
    slugs: Annotated[list[str], Form()] = [],
):
    if action not in ("crawl", "translate", "build", "run"):
        raise HTTPException(status_code=400, detail=f"action không hợp lệ: {action!r}")
    from novel2epub.pipeline import run_all, step_build, step_crawl, step_translate

    fn = {"crawl": step_crawl, "translate": step_translate, "build": step_build, "run": run_all}[action]
    category = {"crawl": "crawl", "translate": "translate", "build": "both", "run": "both"}[action]
    for slug in slugs:
        cfg = deps.resolved_cfg(slug)

        def _target(log, _fn=fn, _cfg=cfg):
            _fn(_cfg, log)

        request.app.state.job.queue.enqueue(
            category, action, _target,
            label=job_label(action, title=cfg.novel.title, slug=slug), ebook=slug,
        )
    return RedirectResponse(url="/library", status_code=303)


@router.get("/ebooks/{slug}/config/export")
def export_ebook_config(slug: str):
    cfg = deps.resolved_cfg(slug)
    from dataclasses import asdict

    data = {
        "novel": asdict(cfg.novel),
        "crawl": {k: v for k, v in asdict(cfg.crawl).items() if not k.startswith("_") and k != "retry"},
        "translate": {k: v for k, v in asdict(cfg.translate).items() if k not in ("openai", "hachimimt", "style", "chunk", "retry", "glossary_files")},
        "output": asdict(cfg.output),
    }
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    return PlainTextResponse(text, media_type="application/x-yaml", headers={
        "Content-Disposition": f'attachment; filename="{slug}-config.yaml"',
    })


@router.post("/library/ebooks/import")
async def import_ebook_config(request: Request, slug: str = Form(...), file: UploadFile = File(...)):
    content = await file.read()
    try:
        data = yaml.safe_load(content.decode("utf-8")) or {}
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"YAML không hợp lệ: {e}") from e
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="File config phải là 1 YAML mapping.")
    data.setdefault("novel", {})
    data["novel"]["slug"] = slug
    # `translate`/`ai` là cấu hình global (defaults) — không nhận qua import
    # per-ebook, tránh ghi lại bản copy mà load_config sẽ bỏ qua.
    data.pop("translate", None)
    data.pop("ai", None)
    update_ebook(deps.WORKSPACE_PATH, slug, data)
    request.app.state.job.queue.restore_ebook(slug)
    return RedirectResponse(url=f"/ebooks/{slug}/settings", status_code=303)


# ───────────────────────── đẩy lên app đọc novel-reader ─────────────────────


@router.get("/api/ebooks/{slug}/publish/preview")
def api_publish_preview(slug: str):
    """Xem trước: sẽ thêm/sửa/bỏ qua bao nhiêu chương. Không ghi gì.

    Chạy đồng bộ (không qua queue) vì chỉ có 2 request GET nhẹ lên Supabase —
    người dùng cần thấy số liệu ngay trước khi bấm đẩy thật.
    """
    from novel2epub.pipeline import step_publish_reader

    cfg = deps.resolved_cfg(slug)
    if not cfg.reader.configured:
        raise HTTPException(
            status_code=400,
            detail="Chưa cấu hình Reader — điền URL Supabase và service_role key ở Cài đặt > Reader.",
        )
    try:
        counts = step_publish_reader(cfg, lambda _msg: None, dry_run=True)
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse(counts)


def publish_reader_job_factory(params: dict):
    """Dựng lại job đẩy từ spec đã lưu — cho phép khôi phục sau khi restart
    (xem JobQueue.register_kind/load_pending)."""
    slug = params["slug"]

    def _target(log) -> None:
        from novel2epub.pipeline import step_publish_reader

        step_publish_reader(deps.resolved_cfg(slug), log)

    return _target


@router.post("/api/ebooks/{slug}/publish/push")
def api_publish_push(request: Request, slug: str):
    """Enqueue job đẩy chương lên Reader.

    Cố ý KHÔNG lọc chương ở đây: việc phân loại mới/sửa diễn ra lúc job chạy,
    nên job idempotent và tự khôi phục đúng sau restart (cùng lối với
    chapters.api_batch_translate).

    Category "build": đẩy là hành động đầu ra như build, không nên chiếm worker
    của translate. Không cần độc quyền với job dịch vì `has_translated` đã chặn
    bản dịch dở, và lần đẩy sau sẽ bắt được thay đổi qua content hash.
    """
    cfg = deps.resolved_cfg(slug)
    if not cfg.reader.configured:
        raise HTTPException(
            status_code=400,
            detail="Chưa cấu hình Reader — điền URL Supabase và service_role key ở Cài đặt > Reader.",
        )
    spec = {"kind": "publish-reader", "params": {"slug": slug}}
    request.app.state.job.start_custom(
        f"publish-reader:{slug}",
        publish_reader_job_factory(spec["params"]),
        category="build",
        ebook=slug,
        spec=spec,
        label=job_label("publish-reader", title=cfg.novel.title, slug=slug),
    )
    return JSONResponse({"started": True})
