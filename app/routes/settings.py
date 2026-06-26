"""Cấu hình per-ebook: metadata truyện, nguồn crawl, AI OpenAI-Compatible dịch."""
from __future__ import annotations

import re

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from novel2epub import openai_client
from novel2epub.config_writer import clean_prompt_text, update_ebook

from .. import deps
from ..logging_config import logger

# Default values for OutputConfig fields
DEFAULT_DATA_DIR = "data"
DEFAULT_EPUB_PATH = ""

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
            "job": request.app.state.job.status(),
        },
    )


@router.post("/ebooks/{slug}/settings/novel")
def save_novel(
    slug: str,
    title: str = Form(""),
    author: str = Form(""),
    language: str = Form("vi"),
    publisher: str = Form(""),
    pubdate: str = Form(""),
    subjects: str = Form(""),  # textarea/input, 1 chủ đề / dòng hoặc phân tách bằng dấu phẩy
    series: str = Form(""),
    series_index: str = Form(""),
    identifier: str = Form(""),
):
    path = deps.ebook_config_path(slug)
    subject_list = [s.strip() for s in re.split(r"[\n,]", subjects) if s.strip()]
    logger.info(
        "[config][NOVEL] slug=%s lưu vào %s: title=%r author=%r language=%r "
        "publisher=%r pubdate=%r subjects=%r series=%r series_index=%r",
        slug, path, title, author, language,
        publisher, pubdate, subject_list, series, series_index,
    )
    update_ebook(deps.WORKSPACE_PATH, slug, {
        "novel": {
            "title": title,
            "author": author,
            "language": language,
            "publisher": publisher,
            "pubdate": pubdate,
            "subjects": subject_list,
            "series": series,
            "series_index": series_index,
            # identifier: chỉ ghi đè khi người dùng thật sự nhập — field rỗng
            # không xóa identifier tự sinh trước đó (xem spec ebook-metadata
            # "Identifier stable across rebuilds").
            **({"identifier": identifier} if identifier.strip() else {}),
        },
    })
    return RedirectResponse(url=f"/ebooks/{slug}/settings", status_code=303)


@router.post("/ebooks/{slug}/settings/source")
def save_source(
    slug: str,
    toc_url: str = Form(""),
    chapter_link_pattern: str = Form(".*"),
    max_chapters: int = Form(0),
    delay_seconds: float = Form(1.0),
    content_selector: str = Form(""),
    scrapling_mode: str = Form("fetcher"),
    solve_cloudflare: bool = Form(False),
    network_idle: bool = Form(False),
    impersonate: str = Form(""),
    next_page_selector: str = Form(""),
    next_page_url_pattern: str = Form(""),
    max_pages_per_chapter: int = Form(10),
    retry_attempts: int = Form(3),
    retry_delay_seconds: float = Form(5.0),
    retry_backoff: float = Form(2.0),
    retry_max_delay_seconds: float = Form(120.0),
    retry_respect_retry_after: bool = Form(False),
    headless: bool = Form(False),
):
    crawl: dict = {
        "engine": "scrapling",
        "toc_url": toc_url,
        "chapter_link_pattern": chapter_link_pattern,
        "max_chapters": max_chapters,
        "delay_seconds": delay_seconds,
        "content_selector": content_selector,
        "headless": headless,
        "scrapling": {
            "mode": scrapling_mode,
            "solve_cloudflare": solve_cloudflare,
            "network_idle": network_idle,
            "impersonate": impersonate,
        },
        "next_page_selector": next_page_selector,
        "next_page_url_pattern": next_page_url_pattern,
        "max_pages_per_chapter": max_pages_per_chapter,
        "retry": {
            "attempts": retry_attempts,
            "delay_seconds": retry_delay_seconds,
            "backoff": retry_backoff,
            "max_delay_seconds": retry_max_delay_seconds,
            "respect_retry_after": retry_respect_retry_after,
        },
    }
    path = deps.ebook_config_path(slug)
    logger.info(
        "[config][CRAWL] slug=%s lưu vào %s: engine=scrapling mode=%s toc_url=%r content_selector=%r "
        "max_chapters=%s delay=%ss pagination=%s",
        slug, path, scrapling_mode, toc_url, content_selector, max_chapters, delay_seconds,
        next_page_selector or next_page_url_pattern or "off",
    )
    update_ebook(deps.WORKSPACE_PATH, slug, {"crawl": crawl})
    return RedirectResponse(url=f"/ebooks/{slug}/settings", status_code=303)


@router.get("/settings/ai/models")
def list_ai_models(base_url: str, api_key: str = ""):
    """Proxy GET {base_url}/models cho UI Settings hiển thị dropdown model id.

    Trả {"models": [...]} hoặc {"error": "..."} (200 cả 2 trường hợp — lỗi do
    provider không hỗ trợ /models là bình thường, để UI tự fallback input tự do).
    """
    try:
        models = openai_client.list_models(base_url, api_key)
        return JSONResponse({"models": models})
    except Exception as e:
        return JSONResponse({"models": [], "error": str(e)})


@router.post("/ebooks/{slug}/settings/ai")
def save_ai(
    slug: str,
    type: str = Form("openai"),
    base_url: str = Form("https://api.openai.com/v1"),
    api_key: str = Form(""),
    model: str = Form(""),
    timeout_seconds: int = Form(300),
    temperature: float = Form(0.7),
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
    openai_cfg: dict = {
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "timeout_seconds": timeout_seconds,
        "temperature": temperature,
    }
    if prompt_template.strip():
        openai_cfg["prompt_template"] = clean_prompt_text(prompt_template)
    if title_prompt_template.strip():
        openai_cfg["title_prompt_template"] = clean_prompt_text(title_prompt_template)

    translate: dict = {
        "type": type,
        "openai": openai_cfg,
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
        "[config][AI/DỊCH] slug=%s lưu vào %s: type=%s base_url=%r model=%r "
        "timeout=%ss temperature=%s tone=%r pronoun=%s title_mode=%s han_viet=%s "
        "keep_paragraphs=%s retry=%s chunk_max_chars=%s delay=%ss",
        slug, path, type, base_url, model, timeout_seconds, temperature, tone,
        pronoun_policy, title_mode, han_viet_level, keep_paragraphs, retry_attempts,
        chunk_max_chars, delay_seconds,
    )
    update_ebook(deps.WORKSPACE_PATH, slug, {"translate": translate})
    return RedirectResponse(url=f"/ebooks/{slug}/settings", status_code=303)


@router.post("/ebooks/{slug}/settings/output")
def save_output(
    slug: str,
    data_dir: str = Form(""),
    epub_path: str = Form(""),
    crawl_max_workers: int = Form(1),
    translate_max_workers: int = Form(1),
):
    output: dict = {
        "data_dir": data_dir or DEFAULT_DATA_DIR,
        "epub_path": epub_path,
    }
    crawl: dict = {
        "max_workers": max(1, crawl_max_workers),
    }
    translate: dict = {
        "max_workers": max(1, translate_max_workers),
    }
    path = deps.ebook_config_path(slug)
    logger.info(
        "[config][OUTPUT] slug=%s lưu vào %s: data_dir=%r epub_path=%r "
        "crawl.max_workers=%s translate.max_workers=%s",
        slug, path, data_dir, epub_path, crawl_max_workers, translate_max_workers,
    )
    update_ebook(deps.WORKSPACE_PATH, slug, {
        "output": output,
        "crawl": crawl,
        "translate": translate,
    })
    return RedirectResponse(url=f"/ebooks/{slug}/settings", status_code=303)
