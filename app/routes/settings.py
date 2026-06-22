"""Cấu hình per-ebook: metadata truyện, nguồn crawl, AI CLI dịch."""
from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from novel2epub.config_writer import update_config_file

from .. import deps
from ..logging_config import logger

router = APIRouter()


@router.get("/ebooks/{slug}/settings")
def settings_page(request: Request, slug: str):
    cfg = deps.resolved_cfg(slug)
    return deps.templates.TemplateResponse(
        request,
        "settings.html",
        {
            "slug": slug,
            "config_path": deps.ebook_config_path(slug),
            "cfg": cfg,
            "presets": deps.presets(),
            "job": request.app.state.job.status(),
        },
    )


@router.post("/ebooks/{slug}/settings/novel")
def save_novel(
    slug: str,
    title: str = Form(""),
    author: str = Form(""),
    language: str = Form("vi"),
):
    path = deps.ebook_config_path(slug)
    logger.info(
        "[config][NOVEL] slug=%s lưu vào %s: title=%r author=%r language=%r",
        slug, path, title, author, language,
    )
    update_config_file(path, {"novel": {"title": title, "author": author, "language": language}})
    return RedirectResponse(url=f"/ebooks/{slug}/settings", status_code=303)


@router.post("/ebooks/{slug}/settings/source")
def save_source(
    slug: str,
    engine: str = Form("http"),
    toc_url: str = Form(""),
    chapter_link_pattern: str = Form(".*"),
    max_chapters: int = Form(0),
    delay_seconds: float = Form(1.0),
    content_selector: str = Form(""),
    toc_selector: str = Form(""),
    chapter_title_selector: str = Form(""),
    title_selector: str = Form(""),
    author_selector: str = Form(""),
    desc_selector: str = Form(""),
    cover_selector: str = Form(""),
    encoding: str = Form(""),
    headless: bool = Form(False),
    magic: bool = Form(False),
    js_code: str = Form(""),
    next_page_selector: str = Form(""),
    next_page_url_pattern: str = Form(""),
    max_pages_per_chapter: int = Form(10),
):
    crawl: dict = {
        "engine": engine,
        "toc_url": toc_url,
        "chapter_link_pattern": chapter_link_pattern,
        "max_chapters": max_chapters,
        "delay_seconds": delay_seconds,
        "content_selector": content_selector,
        "toc_selector": toc_selector,
        "chapter_title_selector": chapter_title_selector,
        "title_selector": title_selector,
        "author_selector": author_selector,
        "desc_selector": desc_selector,
        "cover_selector": cover_selector,
        "encoding": encoding,
        "headless": headless,
        "magic": magic,
        "js_code": js_code,
        "next_page_selector": next_page_selector,
        "next_page_url_pattern": next_page_url_pattern,
        "max_pages_per_chapter": max_pages_per_chapter,
    }
    path = deps.ebook_config_path(slug)
    logger.info(
        "[config][CRAWL] slug=%s lưu vào %s: engine=%s toc_url=%r content_selector=%r "
        "max_chapters=%s delay=%ss pagination=%s ai_fallback... encoding=%r headless=%s magic=%s",
        slug, path, engine, toc_url, content_selector, max_chapters, delay_seconds,
        next_page_selector or next_page_url_pattern or "off", encoding, headless, magic,
    )
    update_config_file(path, {"crawl": crawl})
    return RedirectResponse(url=f"/ebooks/{slug}/settings", status_code=303)


@router.post("/ebooks/{slug}/settings/source/apply-preset")
def apply_preset(slug: str, preset: str = Form("")):
    p = deps.presets().get(preset)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy preset '{preset}'.")
    path = deps.ebook_config_path(slug)
    logger.info("[config][CRAWL/PRESET] slug=%s áp preset %r vào %s: %s",
                slug, preset, path, p.crawl_overrides())
    update_config_file(path, {"crawl": p.crawl_overrides()})
    return RedirectResponse(url=f"/ebooks/{slug}/settings", status_code=303)


@router.post("/ebooks/{slug}/settings/ai")
def save_ai(
    slug: str,
    type: str = Form("cli"),
    command: str = Form("claude -p"),
    model: str = Form(""),
    mode: str = Form("stdin"),
    timeout_seconds: int = Form(300),
    prompt_template: str = Form(""),
    title_prompt_template: str = Form(""),
    tone: str = Form(""),
    pronoun_policy: str = Form(""),
    title_mode: str = Form(""),
    han_viet_level: str = Form(""),
    keep_paragraphs: bool = Form(False),
    delay_seconds: float = Form(0.5),
    retry_attempts: int = Form(1),
    retry_delay_seconds: float = Form(0.0),
    chunk_max_chars: int = Form(0),
    chunk_overlap_paragraphs: int = Form(0),
):
    cli: dict = {
        "command": command,
        "model": model,
        "mode": mode,
        "timeout_seconds": timeout_seconds,
    }
    if prompt_template.strip():
        cli["prompt_template"] = prompt_template
    if title_prompt_template.strip():
        cli["title_prompt_template"] = title_prompt_template

    translate: dict = {
        "type": type,
        "cli": cli,
        "style": {
            "tone": tone,
            "pronoun_policy": pronoun_policy,
            "title_mode": title_mode,
            "han_viet_level": han_viet_level,
            "keep_paragraphs": keep_paragraphs,
        },
        "retry": {"attempts": retry_attempts, "delay_seconds": retry_delay_seconds},
        "chunk": {
            "max_chars": chunk_max_chars,
            "overlap_paragraphs": chunk_overlap_paragraphs,
        },
        "delay_seconds": delay_seconds,
    }
    path = deps.ebook_config_path(slug)
    logger.info(
        "[config][AI/DỊCH] slug=%s lưu vào %s: type=%s command=%r model=%r mode=%s "
        "timeout=%ss tone=%r pronoun=%s title_mode=%s han_viet=%s keep_paragraphs=%s "
        "retry=%s chunk_max_chars=%s delay=%ss",
        slug, path, type, command, model, mode, timeout_seconds, tone, pronoun_policy,
        title_mode, han_viet_level, keep_paragraphs, retry_attempts, chunk_max_chars,
        delay_seconds,
    )
    update_config_file(path, {"translate": translate})
    return RedirectResponse(url=f"/ebooks/{slug}/settings", status_code=303)
