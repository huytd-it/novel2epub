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
from novel2epub.sources import detect_preset, preset_matches_url
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
    suggest_url = ""
    if not preset_name:
        suggest_url = f"/preset-builder?toc_url={toc_url}"
    return {
        "name": name,
        "author": author,
        "slug": slug,
        "cover_url": cover_url,
        "chapter_count": chapter_count,
        "preset": preset_name,
        "suggested_preset": None,
        "suggest_url": suggest_url,
    }


@router.get("/library")
def library_page():
    # Trang Thư viện đã gộp vào trang chủ.
    return RedirectResponse(url="/", status_code=302)


@router.post("/library/ebooks/preview")
def preview_ebook_api(
    toc_url: str = Form(""),
    preset: str = Form(""),
):
    """API: validate link khớp nguồn đã chọn rồi fetch metadata, trả JSON.

    Luồng thêm ebook: chọn nguồn (preset) trước → paste link. Link phải khớp
    domain của nguồn đã chọn mới fetch metadata để preview.
    """
    toc_url = toc_url.strip()
    if not toc_url:
        return JSONResponse({"error": "Thiếu URL mục lục."}, status_code=400)
    if not preset:
        return JSONResponse({"error": "Hãy chọn nguồn trước."}, status_code=400)

    p = deps.presets().get(preset)
    if p is None:
        return JSONResponse({"error": f"Không tìm thấy nguồn '{preset}'."}, status_code=400)

    if not preset_matches_url(p, toc_url):
        return JSONResponse(
            {
                "error": f"Link không thuộc nguồn '{preset}' (domain: {p.domains}). "
                "Nếu đây là nguồn mới, hãy tạo preset trước.",
                "suggest_url": f"/preset-builder?toc_url={toc_url}",
            },
            status_code=400,
        )

    try:
        data = _fetch_meta(toc_url, preset)
        data["engine"] = p.engine
        return JSONResponse(data)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/library/ebooks")
def create_ebook(
    slug: str = Form(""),
    name: str = Form(""),
    author: str = Form(""),
    toc_url: str = Form(""),
    preset: str = Form(""),
):
    toc_url = toc_url.strip()
    preset = preset.strip()
    if not preset:
        raise HTTPException(status_code=400, detail="Hãy chọn nguồn trước.")
    p = deps.presets().get(preset)
    if p is None:
        raise HTTPException(status_code=400, detail=f"Không tìm thấy nguồn '{preset}'.")
    if not preset_matches_url(p, toc_url):
        raise HTTPException(
            status_code=400,
            detail=f"Link không thuộc nguồn '{preset}' (domain: {p.domains}).",
        )

    # name/author/slug thường gửi từ bước preview. Nếu thiếu (vd JS tắt) thì tự fetch.
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

    # File gộp: ghi thẳng ebook (chỉ phần override) vào khối `ebooks:`.
    add_ebook(
        deps.WORKSPACE_PATH,
        slug,
        name=name,
        title=name,
        author=author,
        toc_url=toc_url,
        engine=p.engine,
        preset=p.crawl_overrides(),
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
