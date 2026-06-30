"""Quản lý thư viện ebook: liệt kê, thêm (scaffold config), gỡ khỏi library."""
from __future__ import annotations

import re
import unicodedata

import json

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse

from novel2epub.config import CrawlConfig
from novel2epub.config_writer import add_ebook, remove_ebook
from novel2epub.crawler import ScraplingCrawler
from novel2epub.search import search_all, search_all_stream
from novel2epub.sources import load_presets

from .. import deps

router = APIRouter()


_VN_CHAR_MAP = str.maketrans(
    "àáảãạăằắẳẵặâầấẩẫậđèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ"
    "ÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬĐÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴ",
    "aaaaaaaaaaaaaaaaadeeeeeeeeeeeiiiiiooooooooooooooooouuuuuuuuuuuyyyyy"
    "AAAAAAAAAAAAAAAAADEEEEEEEEEEEIIIIIOOOOOOOOOOOOOOOOOUUUUUUUUUUUYYYYY",
)


def vn_slugify(value: str) -> str:
    value = value.translate(_VN_CHAR_MAP)
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value or "novel"


def slugify(value: str) -> str:
    return vn_slugify(value)


def _fetch_meta(toc_url: str, preset_name: str = "") -> dict:
    """Crawl TOC URL và trả về metadata detect được + slug gợi ý."""
    crawl_cfg = CrawlConfig(toc_url=toc_url)

    crawler = ScraplingCrawler(crawl_cfg)
    try:
        toc = crawler.fetch_toc()
    finally:
        crawler.close()

    title_raw = toc.title or ""
    author = toc.author or ""
    description = toc.description or ""
    cover_url = toc.cover_url or ""
    chapter_count = len(toc.chapters)

    slug = slugify(title_raw or slugify(toc_url))
    return {
        "name": title_raw,
        "title_raw": title_raw,
        "author": author,
        "description": description,
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


@router.get("/library/ebooks/search/sources")
def search_sources():
    """Trả về danh sách source đã cấu hình tìm kiếm."""
    presets = load_presets(deps.SOURCES_PATH)
    sources = []
    for name, p in presets.items():
        if p.search_url_pattern:
            sources.append({
                "name": name,
                "search_url": p.search_url_pattern,
                "domains": p.domains,
            })
    return JSONResponse({"sources": sources})


@router.post("/library/ebooks/search")
def search_ebooks(
    query: str = Form(""),
    sources: str = Form(""),
    limit: int = Form(5),
):
    """API: tìm kiếm tiểu thuyết — SSE stream, mỗi nguồn xong gửi ngay."""
    query = query.strip()
    if not query:
        return JSONResponse({"error": "Thiếu từ khóa tìm kiếm."}, status_code=400)

    presets = load_presets(deps.SOURCES_PATH)
    source_names = [s.strip() for s in sources.split(",") if s.strip()] if sources else None

    def generate():
        for event in search_all_stream(
            presets,
            query,
            source_names=source_names,
            enrich=True,
            max_workers=5,
        ):
            yield f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


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

    if not slug:
        slug = vn_slugify(name)
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
