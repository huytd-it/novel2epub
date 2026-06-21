"""Trang chủ (danh sách ebook) + trang tổng quan 1 ebook."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request

from novel2epub.config import load_config
from novel2epub.storage import Storage
from novel2epub.toc import apply_chapter_query, chapter_rows

from .. import deps

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
def index(request: Request):
    library = deps.library()
    ebooks = []
    if library.ebooks:
        entries = library.ebooks.items()
    else:
        entries = [("default", None)]
    for slug, entry in entries:
        if entry is None:
            cfg = deps.cfg()
            name = cfg.novel.title or cfg.novel.slug
        else:
            cfg = load_config(deps.ebook_config_path(slug))
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
        },
    )


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
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    epub_path = Path(cfg.epub_path)
    return deps.templates.TemplateResponse(
        request,
        "ebook.html",
        {
            "slug": slug,
            "config_path": deps.ebook_config_path(slug),
            "cfg": cfg,
            "manifest": manifest,
            "chapters": _chapter_rows(
                cfg,
                sort=sort,
                direction=direction,
                search=search,
                filter_raw=filter_raw,
                filter_translated=filter_translated,
                filter_missing=filter_missing,
            ),
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
            "job": request.app.state.job.status(),
        },
    )
