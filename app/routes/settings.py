"""Cấu hình ebook: metadata truyện + nguồn crawl per-ebook; AI dịch (`translate`)
và AI biên tập (`ai`) là cấu hình GLOBAL dùng chung mọi ebook (ghi vào `defaults:`)."""
from __future__ import annotations

import re

import requests
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from novel2epub import openai_client
from novel2epub.config_writer import clean_prompt_text, update_defaults, update_ebook

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
    description: str = Form(""),
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
            "description": description,
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
    max_workers: int = Form(1),
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
        "toc_url": toc_url,
        "chapter_link_pattern": chapter_link_pattern,
        "max_chapters": max_chapters,
        "max_workers": max(1, max_workers),
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


@router.post("/ebooks/{slug}/settings/translate/test")
def test_translate_connection(
    slug: str,
    base_url: str = Form(...),
    api_key: str = Form(""),
    timeout_seconds: int = Form(15),
):
    """Test kết nối translate.openai base_url — gọi GET /models, đo latency,
    detect OmniRoute qua header `X-OmniRoute-Version`.

    Trả {ok, latency_ms, model_count, omniroute_version?, error?}. UI dùng
    để hiển thị "✓ Kết nối OK — 50 models" hoặc "✗ Lỗi kết nối".
    """
    from types import SimpleNamespace
    import time as _time

    try:
        start = _time.monotonic()
        resp = requests.get(
            base_url.rstrip("/") + "/models",
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=timeout_seconds,
        )
        latency_ms = int((_time.monotonic() - start) * 1000)
    except requests.exceptions.Timeout as e:
        return JSONResponse({"ok": False, "error": f"Timeout: {e}"}, status_code=200)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=200)

    if resp.status_code != 200:
        return JSONResponse({
            "ok": False,
            "latency_ms": latency_ms,
            "error": f"HTTP {resp.status_code}: {resp.text.strip()[:200]}",
        }, status_code=200)

    # Parse models
    data = resp.json()
    items = data.get("data", data) if isinstance(data, dict) else data
    if not isinstance(items, list):
        items = []
    model_count = len(items)

    # Detect OmniRoute
    headers_obj = resp.headers if hasattr(resp.headers, "get") else SimpleNamespace(get=lambda k, d=None: d)
    omniroute_version = headers_obj.get("X-OmniRoute-Version")
    result: dict = {
        "ok": True,
        "latency_ms": latency_ms,
        "model_count": model_count,
    }
    if omniroute_version:
        result["omniroute_version"] = omniroute_version
    return JSONResponse(result, status_code=200)


@router.post("/ebooks/{slug}/settings/translate")
def save_translate(
    slug: str,
    type: str = Form("openai"),
    base_url: str = Form("https://opencode.ai/zen/go/v1"),
    api_key: str = Form(""),
    model: str = Form("opencode-go/kimi-k2.6"),
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
    max_workers: int = Form(1),
    # Local NMT model selector
    local_model: str = Form(""),
    retry_attempts: int = Form(1),
    retry_delay_seconds: float = Form(0.0),
    chunk_max_chars: int = Form(0),
    chunk_overlap_paragraphs: int = Form(0),
    # HachimiMT fields
    hachimimt_model_key: str = Form("HachimiMT-60"),
    hachimimt_backend: str = Form("ctranslate2"),
    hachimimt_beam_size: int = Form(2),
    hachimimt_chunk_mode: str = Form("sentence"),
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

    hachimimt_cfg: dict = {
        "model_key": hachimimt_model_key,
        "backend": hachimimt_backend,
        "beam_size": hachimimt_beam_size,
        "chunk_mode": hachimimt_chunk_mode,
    }

    translate: dict = {
        "type": type,
        "model": local_model,
        "openai": openai_cfg,
        "hachimimt": hachimimt_cfg,
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
        "max_workers": max(1, max_workers),
    }
    path = deps.ebook_config_path(slug)
    logger.info(
        "[config][AI/DỊCH] global (từ %s) lưu vào defaults của %s: type=%s local_model=%s base_url=%r model=%r "
        "hachimimt=%s timeout=%ss temperature=%s tone=%r pronoun=%s title_mode=%s han_viet=%s "
        "keep_paragraphs=%s retry=%s chunk_max_chars=%s delay=%ss",
        slug, path, type, local_model, base_url, model,
        hachimimt_model_key, timeout_seconds, temperature, tone,
        pronoun_policy, title_mode, han_viet_level, keep_paragraphs, retry_attempts,
        chunk_max_chars, delay_seconds,
    )
    # Cấu hình AI dịch dùng chung cho MỌI ebook: ghi vào `defaults:` và gỡ bản
    # copy per-ebook cũ (update_defaults tự dọn).
    update_defaults(deps.WORKSPACE_PATH, {"translate": translate})
    return RedirectResponse(url=f"/ebooks/{slug}/settings", status_code=303)


@router.post("/ebooks/{slug}/settings/ai")
def save_ai(
    slug: str,
    base_url: str = Form("https://opencode.ai/zen/go/v1"),
    api_key: str = Form(""),
    model: str = Form("opencode-go/kimi-k2.6"),
    timeout_seconds: int = Form(300),
    temperature: float = Form(0.7),
):
    """Lưu cấu hình AI biên tập (`ai.openai`) — tách riêng khỏi translate.openai.

    Dùng cho: glossary suggest/rewrite/evaluate. Không lưu prompt_template
    vì AI biên tập dùng prompt cứng trong glossary_ai.py. Cấu hình dùng chung
    cho MỌI ebook (ghi vào `defaults:`).
    """
    ai_openai_cfg: dict = {
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "timeout_seconds": timeout_seconds,
        "temperature": temperature,
    }
    path = deps.ebook_config_path(slug)
    logger.info(
        "[config][AI/BIÊN TẬP] global (từ %s) lưu vào defaults của %s: base_url=%r model=%r timeout=%ss temperature=%s",
        slug, path, base_url, model, timeout_seconds, temperature,
    )
    update_defaults(deps.WORKSPACE_PATH, {"ai": {"openai": ai_openai_cfg}})
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
    path = deps.ebook_config_path(slug)
    logger.info(
        "[config][OUTPUT] slug=%s lưu vào %s: data_dir=%r epub_path=%r "
        "crawl.max_workers=%s translate.max_workers=%s",
        slug, path, data_dir, epub_path, crawl_max_workers, translate_max_workers,
    )
    update_ebook(deps.WORKSPACE_PATH, slug, {
        "output": output,
        "crawl": crawl,
    })
    # translate.* là cấu hình global — max_workers ghi vào defaults như tab Dịch.
    update_defaults(deps.WORKSPACE_PATH, {
        "translate": {"max_workers": max(1, translate_max_workers)},
    })
    return RedirectResponse(url=f"/ebooks/{slug}/settings", status_code=303)
