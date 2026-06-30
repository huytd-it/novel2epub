"""Quản lý thư viện ebook: liệt kê, thêm (scaffold config), gỡ khỏi library."""
from __future__ import annotations

import dataclasses
import re
import unicodedata

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse

from novel2epub.config import CrawlConfig, load_config
from novel2epub.config_writer import add_ebook, remove_ebook
from novel2epub.crawler import make_crawler
from novel2epub.pipeline import _clean_title
from novel2epub.search import search_all
from novel2epub.sources import load_presets
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

    title_raw = toc.title or ""
    author = toc.author or ""
    description = toc.description or ""
    cover_url = toc.cover_url or ""
    chapter_count = len(toc.chapters)

    # Dịch title/author/description nếu có AI
    name = title_raw
    title_vi = ""
    author_vi = ""
    description_vi = ""
    if title_raw or author or description:
        try:
            global_cfg = load_config(deps.CONFIG_PATH)
            if global_cfg.translate.type.lower() != "none":
                # Preview: dùng prompt đơn giản để tránh lặp với metadata ngắn
                preview_cfg = dataclasses.replace(global_cfg.translate)
                if preview_cfg.type == "openai":
                    preview_cfg.openai = dataclasses.replace(preview_cfg.openai)
                    preview_cfg.openai.title_prompt_template = (
                        "Dịch {kind} sau từ Trung sang Việt, chỉ trả lời phần dịch:\n\n{text}"
                    )
                    preview_cfg.openai.prompt_template = (
                        "Dịch đoạn văn sau từ Trung sang Việt, chỉ trả lời phần dịch:\n\n{text}"
                    )
                translator = RateLimited(
                    make_translator(preview_cfg),
                    global_cfg.translate.delay_seconds,
                )
                if title_raw:
                    t, _n = translator.translate_title(title_raw, kind="tên truyện")
                    if t:
                        name = _clean_title(t)
                        title_vi = name
                if author:
                    try:
                        author_vi = translator.translate(author).strip()
                    except Exception:
                        pass
                if description:
                    try:
                        description_vi = translator.translate(description).strip()
                    except Exception:
                        pass
        except Exception:
            pass

    # Lấy thông tin model dịch
    translate_type = ""
    translate_model = ""
    try:
        global_cfg = load_config(deps.CONFIG_PATH)
        tc = global_cfg.translate
        translate_type = tc.type
        if tc.type == "hachimimt":
            translate_model = tc.hachimimt.model_key or "HachimiMT-60"
        elif tc.type == "openai":
            translate_model = tc.openai.model
        elif tc.type == "google":
            translate_model = "Google Translate"
        elif tc.type == "libretranslate":
            translate_model = "LibreTranslate"
        elif tc.type == "none":
            translate_model = "Không dịch"
        if tc.preset:
            translate_model = (translate_model + " · preset: " + tc.preset) if translate_model else tc.preset
    except Exception:
        pass

    slug = slugify(name or slugify(toc_url))
    return {
        "name": name,
        "title_raw": title_raw,
        "title_vi": title_vi,
        "author": author,
        "author_vi": author_vi,
        "description": description,
        "description_vi": description_vi,
        "slug": slug,
        "cover_url": cover_url,
        "chapter_count": chapter_count,
        "translate_type": translate_type,
        "translate_model": translate_model,
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


@router.post("/library/ebooks/search")
def search_ebooks(
    query: str = Form(""),
    sources: str = Form(""),
    limit: int = Form(5),
):
    """API: tìm kiếm tiểu thuyết trên các source đã cấu hình search, trả JSON."""
    query = query.strip()
    if not query:
        return JSONResponse({"error": "Thiếu từ khóa tìm kiếm."}, status_code=400)

    presets = load_presets(deps.SOURCES_PATH)
    source_names = [s.strip() for s in sources.split(",") if s.strip()] if sources else None

    try:
        response = search_all(
            presets,
            query,
            source_names=source_names,
            enrich=True,
            max_workers=5,
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    results = []
    for r in response.results[:limit * len(presets)]:
        results.append({
            "title": r.title,
            "author": r.author,
            "url": r.url,
            "source_name": r.source_name,
            "cover_url": r.cover_url,
            "chapter_count": r.chapter_count,
            "description": r.description,
        })

    errors = [{"source": e.source_name, "message": e.message} for e in response.errors]
    return JSONResponse({"results": results, "errors": errors})


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
