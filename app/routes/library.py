"""Quản lý thư viện ebook: liệt kê, thêm (scaffold config), gỡ khỏi library."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from novel2epub.config import LibraryEntry, load_config
from novel2epub.config_writer import save_library, scaffold_config_file

from .. import deps

router = APIRouter()


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value or "novel"


@router.get("/library")
def library_page(request: Request):
    lib = deps.library()
    rows = []
    for slug, entry in lib.ebooks.items():
        config_path = deps.ebook_config_path(slug)
        rows.append(
            {
                "slug": slug,
                "name": entry.name or slug,
                "config": entry.config,
                "exists": Path(config_path).exists(),
            }
        )
    return deps.templates.TemplateResponse(
        request,
        "library.html",
        {
            "library_path": deps.LIBRARY_PATH,
            "ebooks": rows,
            "presets": deps.presets(),
            "job": request.app.state.job.status(),
        },
    )


@router.post("/library/ebooks")
def create_ebook(
    slug: str = Form(""),
    name: str = Form(""),
    toc_url: str = Form(""),
    engine: str = Form("http"),
    preset: str = Form(""),
):
    slug = slugify(slug or name)
    lib = deps.library()
    if slug in lib.ebooks:
        raise HTTPException(status_code=409, detail=f"Ebook '{slug}' đã tồn tại.")

    # Đường dẫn config tương đối so với library.yaml (deps.ebook_config_path resolve).
    rel_config = f"configs/{slug}.yaml"
    dest = deps.resolve_path(Path(deps.LIBRARY_PATH).resolve().parent, rel_config)

    preset_overrides = None
    if preset:
        p = deps.presets().get(preset)
        if p:
            preset_overrides = p.crawl_overrides()

    scaffold_config_file(
        dest,
        slug=slug,
        title=name,
        toc_url=toc_url,
        engine=engine,
        preset=preset_overrides,
    )

    lib.ebooks[slug] = LibraryEntry(slug=slug, name=name, config=rel_config)
    save_library(deps.LIBRARY_PATH, lib)
    return RedirectResponse(url=f"/ebooks/{slug}/settings", status_code=303)


@router.post("/library/ebooks/{slug}/delete")
def delete_ebook(slug: str, delete_config: bool = Form(False)):
    lib = deps.library()
    entry = lib.ebooks.pop(slug, None)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy ebook '{slug}'.")
    if delete_config and entry.config:
        config_path = Path(deps.resolve_path(Path(deps.LIBRARY_PATH).resolve().parent, entry.config))
        if config_path.exists():
            config_path.unlink()
    save_library(deps.LIBRARY_PATH, lib)
    return RedirectResponse(url="/library", status_code=303)
