"""Trang chủ (danh sách ebook) + trang tổng quan 1 ebook."""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Annotated

import yaml
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse, RedirectResponse

from novel2epub.config_writer import update_ebook
from novel2epub.storage import Storage
from novel2epub.toc import apply_chapter_query, chapter_rows

from .. import deps
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
):
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        return []
    return apply_chapter_query(
        chapter_rows(manifest.chapters, storage),
        sort=sort,
        direction=direction,
        search=search,
        filter_raw=filter_raw,
        filter_translated=filter_translated,
        filter_missing=filter_missing,
    )


@router.get("/")
def index(request: Request, show_archived: bool = False):
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
        raw_count = sum(1 for ch in (manifest.chapters if manifest else []) if storage.has_raw(ch))
        translated_count = sum(1 for ch in (manifest.chapters if manifest else []) if storage.has_translated(ch))
        ebooks.append(
            {
                "slug": slug,
                "name": name,
                "cfg": cfg,
                "manifest": manifest,
                "raw_count": raw_count,
                "translated_count": translated_count,
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
    return RedirectResponse(url="/", status_code=303)


@router.post("/library/ebooks/{slug}/unarchive")
def unarchive_ebook(slug: str):
    set_archived(deps.LIBRARY_STATE_PATH, slug, False)
    return RedirectResponse(url="/?show_archived=1", status_code=303)


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
    return RedirectResponse(url="/", status_code=303)


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
async def import_ebook_config(slug: str = Form(...), file: UploadFile = File(...)):
    content = await file.read()
    try:
        data = yaml.safe_load(content.decode("utf-8")) or {}
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"YAML không hợp lệ: {e}") from e
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="File config phải là 1 YAML mapping.")
    data.setdefault("novel", {})
    data["novel"]["slug"] = slug
    update_ebook(deps.WORKSPACE_PATH, slug, data)
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
):
    from novel2epub.toc import crawl_problem_indexes

    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    epub_path = Path(cfg.epub_path)
    crawl_problems = crawl_problem_indexes(manifest.chapters, storage) if manifest else []
    all_chapters = _chapter_rows(cfg)
    chapters_json = [dataclasses.asdict(r) for r in all_chapters]
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
            },
            "epub_exists": epub_path.exists(),
            "epub_path": str(epub_path),
            "epub_size": epub_path.stat().st_size if epub_path.exists() else None,
            "job": request.app.state.job.status(),
        },
    )
