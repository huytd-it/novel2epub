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


@router.get("/library")
def index(request: Request, show_archived: bool = False):
    """Trang Thư viện của giao diện Jinja2.

    Từng nằm ở `/`; đã nhường chỗ đó cho SPA (xem `app/main.py`). Giữ lại
    dưới `/library` — đúng tên cũ của nó trước khi gộp vào trang chủ — để các
    tính năng chưa port sang SPA vẫn có đường vào.
    """
    library = deps.library()
    archived = archived_slugs(deps.LIBRARY_STATE_PATH)
    ebooks = []
    if library.ebooks:
        entries = library.ebooks.items()
    else:
        entries = [("default", None)]
    for slug, entry in entries:
        is_archived = slug in archived
        if is_archived and not show_archived:
            continue
        if entry is None:
            cfg = deps.cfg()
            name = cfg.novel.title or cfg.novel.slug
        else:
            cfg = deps.resolved_cfg(slug)
            name = entry.name or cfg.novel.title or slug
        storage = Storage(cfg.output.data_dir, cfg.novel.slug)
        manifest = storage.load_manifest()
        progress = chapter_progress(storage, manifest, stats_map=storage.bulk_chapter_stats())
        ebooks.append(
            {
                "slug": slug,
                "name": name,
                "cfg": cfg,
                "manifest": manifest,
                "raw_count": progress["raw_count"],
                "translated_count": progress["translated_count"],
                "epub_exists": Path(cfg.epub_path).exists(),
                "in_library": entry is not None,
                "archived": is_archived,
            }
        )
    return deps.templates.TemplateResponse(
        request,
        "index.html",
        {
            "config_path": deps.CONFIG_PATH,
            "library_path": deps.LIBRARY_PATH,
            "ebooks": ebooks,
            "job": request.app.state.job.status(),
            "show_archived": show_archived,
            "archived_count": len(archived),
        },
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

        request.app.state.job.queue.enqueue(category, action, _target, label=f"{action}:{slug}", ebook=slug)
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


@router.get("/ebooks/{slug}")
def ebook_home(
    request: Request,
    slug: str,
    sort: str = "source",
    direction: str = "asc",
    search: str = "",
    filter_raw: str = "any",
    filter_translated: str = "any",
    filter_missing: str = "any",
    filter_skipped: str = "no",
):
    from novel2epub.toc import crawl_problem_indexes

    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    epub_path = Path(cfg.epub_path)
    stats_map = storage.bulk_chapter_stats()
    crawl_problems = (
        crawl_problem_indexes(manifest.chapters, storage, stats_map=stats_map)
        if manifest
        else []
    )
    all_chapters = _chapter_rows(cfg, stats_map=stats_map)
    chapters_json = [dataclasses.asdict(r) for r in all_chapters]
    cost_summary = read_cost_summary(storage)
    return deps.templates.TemplateResponse(
        request,
        "ebook.html",
        {
            "slug": slug,
            "config_path": deps.ebook_config_path(slug),
            "cfg": cfg,
            "manifest": manifest,
            "crawl_problems": crawl_problems,
            "chapters": all_chapters,
            "chapters_json": chapters_json,
            "controls": {
                "sort": sort,
                "direction": direction,
                "search": search,
                "filter_raw": filter_raw,
                "filter_translated": filter_translated,
                "filter_missing": filter_missing,
                "filter_skipped": filter_skipped,
            },
            "epub_exists": epub_path.exists(),
            "epub_path": str(epub_path),
            "epub_size": epub_path.stat().st_size if epub_path.exists() else None,
            "job": request.app.state.job.status(),
            "cost_summary": cost_summary,
            "reader_configured": cfg.reader.configured,
        },
    )


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
    )
    return JSONResponse({"started": True})
