"""Cấu hình per-ebook: metadata truyện, nguồn crawl, AI CLI dịch."""
from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from novel2epub.config_writer import update_config_file

from .. import deps

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
    update_config_file(
        deps.ebook_config_path(slug),
        {"novel": {"title": title, "author": author, "language": language}},
    )
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
    api_key: str = Form(""),
    api_url: str = Form(""),
    headless: bool = Form(False),
    magic: bool = Form(False),
    js_code: str = Form(""),
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
    }
    # Chỉ ghi api_key/api_url khi có giá trị (tránh để lộ/đè khóa rỗng lên file).
    if api_key:
        crawl["api_key"] = api_key
    if api_url:
        crawl["api_url"] = api_url
    update_config_file(deps.ebook_config_path(slug), {"crawl": crawl})
    return RedirectResponse(url=f"/ebooks/{slug}/settings", status_code=303)


@router.post("/ebooks/{slug}/settings/source/apply-preset")
def apply_preset(slug: str, preset: str = Form("")):
    p = deps.presets().get(preset)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy preset '{preset}'.")
    update_config_file(deps.ebook_config_path(slug), {"crawl": p.crawl_overrides()})
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
    update_config_file(deps.ebook_config_path(slug), {"translate": translate})
    return RedirectResponse(url=f"/ebooks/{slug}/settings", status_code=303)
