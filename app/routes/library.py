"""Quản lý thư viện ebook: liệt kê, thêm (scaffold config), gỡ khỏi library."""
from __future__ import annotations

import re
import unicodedata

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse

from novel2epub.config import CrawlConfig, load_config
from novel2epub.config_writer import add_ebook, remove_ebook
from novel2epub.crawler import make_crawler
from novel2epub.pipeline import _clean_title
from novel2epub.translator import RateLimited, make_translator

from .. import deps

router = APIRouter()


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value or "novel"


def _fetch_meta(toc_url: str, preset_name: str = "") -> dict:
    """Crawl TOC URL và trả về metadata detect được + slug gợi ý."""
    crawl_cfg = CrawlConfig(toc_url=toc_url)

    crawler = make_crawler(crawl_cfg)
    try:
        toc = crawler.fetch_toc()
    finally:
        crawler.close()

    name = toc.title or ""
    author = toc.author or ""
    cover_url = toc.cover_url or ""
    chapter_count = len(toc.chapters)

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
    return {
        "name": name,
        "author": author,
        "slug": slug,
        "cover_url": cover_url,
        "chapter_count": chapter_count,
    }


@router.get("/library")
def library_page():
    # Trang Thư viện đã gộp vào trang chủ.
    return RedirectResponse(url="/", status_code=302)


@router.post("/library/ebooks/preview")
def preview_ebook_api(
    toc_url: str = Form(""),
):
    """API: fetch metadata từ URL mục lục, trả JSON."""
    toc_url = toc_url.strip()
    if not toc_url:
        return JSONResponse({"error": "Thiếu URL mục lục."}, status_code=400)

    try:
        data = _fetch_meta(toc_url)
        return JSONResponse(data)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/library/ebooks")
def create_ebook(
    slug: str = Form(""),
    name: str = Form(""),
    author: str = Form(""),
    toc_url: str = Form(""),
):
    toc_url = toc_url.strip()
    if not toc_url:
        raise HTTPException(status_code=400, detail="Thiếu URL mục lục.")

    # name/author/slug thường gửi từ bước preview. Nếu thiếu (vd JS tắt) thì tự fetch.
    if not name and toc_url:
        try:
            fetched = _fetch_meta(toc_url)
            name = fetched.get("name", "")
            author = author or fetched.get("author", "")
            slug = slug or fetched.get("slug", "")
        except Exception:
            pass  # fallback: dùng slug từ name trống

    slug = slugify(slug or name)
    lib = deps.library()
    if slug in lib.ebooks:
        raise HTTPException(status_code=409, detail=f"Ebook '{slug}' đã tồn tại.")

    # File gộp: ghi thẳng ebook (chỉ phần override) vào khối `ebooks:`.
    add_ebook(
        deps.WORKSPACE_PATH,
        slug,
        name=name,
        title=name,
        author=author,
        toc_url=toc_url,
        engine="scrapling",
    )
    return RedirectResponse(url=f"/ebooks/{slug}/settings", status_code=303)


@router.post("/library/ebooks/{slug}/delete")
def delete_ebook(slug: str, delete_config: bool = Form(False)):
    lib = deps.library()
    if slug not in lib.ebooks:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy ebook '{slug}'.")
    # File gộp: xóa ebook = bỏ khối `ebooks.<slug>`. `delete_config` không còn ý
    # nghĩa riêng (config nằm inline) nhưng giữ tham số để form cũ không vỡ.
    remove_ebook(deps.WORKSPACE_PATH, slug)
    return RedirectResponse(url="/", status_code=303)
