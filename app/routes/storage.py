"""Báo cáo dung lượng đĩa + dọn dẹp/đóng gói archive theo ebook (xem spec
storage-management)."""
from __future__ import annotations

import tempfile
from dataclasses import asdict
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse

from novel2epub.storage import Storage

from .. import deps
from ..storage_report import build_archive_bundle, ebook_storage_report, purge_raw, purge_translated_mt, remove_epub

router = APIRouter()


def _ebook_slugs() -> list[str]:
    library = deps.library()
    return list(library.ebooks.keys()) if library.ebooks else []


@router.get("/storage")
def storage_page(request: Request):
    rows = []
    grand_total = 0
    for slug in (_ebook_slugs() or ["default"]):
        cfg = deps.resolved_cfg(slug)
        storage = Storage(cfg.output.data_dir, cfg.novel.slug)
        report = ebook_storage_report(storage, cfg.epub_path)
        grand_total += report["total"]
        rows.append({"slug": slug, "name": cfg.novel.title or slug, "report": report})
    return deps.templates.TemplateResponse(
        request, "storage.html", {"rows": rows, "grand_total": grand_total}
    )


@router.post("/storage/{slug}/purge-raw")
def storage_purge_raw(slug: str):
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    purge_raw(storage)
    return RedirectResponse(url="/storage", status_code=303)


@router.post("/storage/{slug}/purge-mt")
def storage_purge_mt(slug: str):
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    purge_translated_mt(storage)
    return RedirectResponse(url="/storage", status_code=303)


@router.post("/storage/{slug}/remove-epub")
def storage_remove_epub(slug: str):
    cfg = deps.resolved_cfg(slug)
    remove_epub(cfg.epub_path)
    return RedirectResponse(url="/storage", status_code=303)


@router.get("/storage/{slug}/archive")
def storage_archive(slug: str):
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    if not storage.root.exists():
        raise HTTPException(status_code=404, detail="Chưa có dữ liệu cho ebook này.")
    config_snippet = yaml.safe_dump(
        {"novel": asdict(cfg.novel), "crawl": {"toc_url": cfg.crawl.toc_url}},
        allow_unicode=True,
    )
    out_path = Path(tempfile.gettempdir()) / f"n2e-archive-{slug}.zip"
    build_archive_bundle(storage, out_path, config_snippet=config_snippet, epub_path=cfg.epub_path)
    return FileResponse(out_path, filename=f"{slug}-archive.zip", media_type="application/zip")
