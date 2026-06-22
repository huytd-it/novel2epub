"""Quản lý thư viện ebook: liệt kê, thêm (scaffold config), gỡ khỏi library."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse

from novel2epub.config import CrawlConfig, LibraryEntry, load_config
from novel2epub.config_writer import save_library, scaffold_config_file
from novel2epub.crawler import make_crawler
from novel2epub.pipeline import _clean_title
from novel2epub.sources import detect_preset
from novel2epub.translator import RateLimited, make_translator

from .. import deps

router = APIRouter()


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value or "novel"


def _fetch_meta(toc_url: str, preset_name: str = "") -> dict:
    """Crawl TOC URL và trả về metadata detect được + slug gợi ý.
    Tự động detect preset nếu chưa có.
    """
    all_presets = deps.presets()
    preset_name = preset_name or detect_preset(toc_url, all_presets) or ""
    p = all_presets.get(preset_name)
    overrides = p.crawl_overrides() if p else {}
    overrides.pop("chapter_link_pattern", None)
    crawl_cfg = CrawlConfig(toc_url=toc_url, **overrides)

    crawler = make_crawler(crawl_cfg)
    try:
        toc = crawler.fetch_toc()
    finally:
        crawler.close()

    name = toc.title or ""
    author = toc.author or ""

    # Dịch title nếu có AI CLI
    if name:
        try:
            global_cfg = load_config(deps.CONFIG_PATH)
            if global_cfg.translate.type.lower() != "none":
                translator = RateLimited(
                    make_translator(global_cfg.translate),
                    global_cfg.translate.delay_seconds,
                )
                title_vi, _note = translator.translate_title(name, kind="tên truyện")
                if title_vi:
                    name = _clean_title(title_vi)
        except Exception:
            pass

    slug = slugify(name or slugify(toc_url))
    suggest_url = ""
    if not preset_name:
        suggest_url = f"/preset-builder?toc_url={toc_url}"
    return {
        "name": name,
        "author": author,
        "slug": slug,
        "preset": preset_name,
        "suggested_preset": None,
        "suggest_url": suggest_url,
    }


@router.get("/library")
def library_page():
    # Trang Thư viện đã gộp vào trang chủ.
    return RedirectResponse(url="/", status_code=302)


@router.post("/library/ebooks/fetch-meta")
def fetch_meta_api(
    toc_url: str = Form(""),
    preset: str = Form(""),
):
    """API: detect metadata từ URL + preset, trả JSON."""
    if not toc_url:
        return JSONResponse({"error": "Thiếu toc_url"}, status_code=400)
    try:
        data = _fetch_meta(toc_url, preset)
        return JSONResponse(data)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/library/ebooks")
def create_ebook(
    slug: str = Form(""),
    name: str = Form(""),
    author: str = Form(""),
    toc_url: str = Form(""),
    engine: str = Form("http"),
    preset: str = Form(""),
):
    # Tự động detect nếu chưa có name nhưng có toc_url
    if not name and toc_url:
        try:
            fetched = _fetch_meta(toc_url, preset)
            name = fetched.get("name", "")
            author = author or fetched.get("author", "")
            slug = slug or fetched.get("slug", "")
        except Exception:
            pass  # fallback: dùng slug từ name trống

    slug = slugify(slug or name)
    lib = deps.library()
    if slug in lib.ebooks:
        raise HTTPException(status_code=409, detail=f"Ebook '{slug}' đã tồn tại.")

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
        author=author,
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
    return RedirectResponse(url="/", status_code=303)
