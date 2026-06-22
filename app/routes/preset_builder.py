"""Web UI cho preset builder: tạo/validate site preset bằng AI."""
from __future__ import annotations

import json
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from novel2epub.preset_builder import build_preset, preview_toc, save_preset
from novel2epub.sources import SourcePreset

from .. import deps

router = APIRouter()


def _build_overrides(
    encoding: str,
    js_code: str,
    engine: str,
    user_agent: str,
    delay_seconds: str,
    next_page_selector: str,
    next_page_url_pattern: str,
    max_pages_per_chapter: str,
) -> dict[str, object]:
    overrides: dict[str, object] = {}
    if encoding:
        overrides["encoding"] = encoding
    if js_code:
        overrides["js_code"] = js_code
    if engine in {"http", "crawl4ai"}:
        overrides["engine"] = engine
    if user_agent:
        overrides["user_agent"] = user_agent
    if delay_seconds:
        try:
            overrides["delay_seconds"] = float(delay_seconds)
        except ValueError:
            pass
    if next_page_selector:
        overrides["next_page_selector"] = next_page_selector
    if next_page_url_pattern:
        overrides["next_page_url_pattern"] = next_page_url_pattern
    if max_pages_per_chapter:
        try:
            overrides["max_pages_per_chapter"] = int(max_pages_per_chapter)
        except ValueError:
            pass
    return overrides


@router.get("/preset-builder")
def preset_builder_page(request: Request, toc_url: str = ""):
    return deps.templates.TemplateResponse(
        request,
        "preset_builder.html",
        {
            "sources_path": deps.SOURCES_PATH,
            "toc_url": toc_url,
            "job": request.app.state.job.status(),
        },
    )


@router.post("/preset-builder/preview")
def preset_builder_preview(
    request: Request,
    toc_url: str = Form(""),
    novel_title: str = Form("赤心巡天"),
    preset_name: str = Form(""),
    encoding: str = Form(""),
    js_code: str = Form(""),
    engine: str = Form(""),
    user_agent: str = Form(""),
    delay_seconds: str = Form(""),
    next_page_selector: str = Form(""),
    next_page_url_pattern: str = Form(""),
    max_pages_per_chapter: str = Form(""),
    max_rounds: int = Form(3),
    low: int = Form(5),
    high: int = Form(2000),
    timeout: int = Form(120),
):
    if not toc_url:
        return JSONResponse({"error": "Thiếu toc_url"}, status_code=400)

    overrides = _build_overrides(
        encoding, js_code, engine, user_agent, delay_seconds,
        next_page_selector, next_page_url_pattern, max_pages_per_chapter,
    )

    result = build_preset(
        toc_url=toc_url,
        novel_title=novel_title,
        preset_name=preset_name,
        overrides=overrides,
        config_path=deps.CONFIG_PATH,
        max_rounds=max_rounds,
        low=low,
        high=high,
        timeout_seconds=timeout,
    )
    if result.error:
        return JSONResponse({"error": result.error}, status_code=500)

    preset = result.preset
    payload = {
        "preset": {
            "name": preset.name,
            "engine": preset.engine,
            "domains": preset.domains,
            "chapter_link_pattern": preset.chapter_link_pattern,
            "content_selector": preset.content_selector,
            "toc_selector": preset.toc_selector,
            "chapter_title_selector": preset.chapter_title_selector,
            "title_selector": preset.title_selector,
            "author_selector": preset.author_selector,
            "desc_selector": preset.desc_selector,
            "cover_selector": preset.cover_selector,
            "encoding": preset.encoding,
            "user_agent": preset.user_agent,
            "headless": preset.headless,
            "magic": preset.magic,
            "js_code": preset.js_code,
            "delay_seconds": preset.delay_seconds,
            "next_page_selector": preset.next_page_selector,
            "next_page_url_pattern": preset.next_page_url_pattern,
            "max_pages_per_chapter": preset.max_pages_per_chapter,
        },
        "preview": {
            "title": result.preview.title if result.preview else "",
            "author": result.preview.author if result.preview else "",
            "description": result.preview.description if result.preview else "",
            "cover_url": result.preview.cover_url if result.preview else "",
            "chapter_count": len(result.preview.chapters) if result.preview else 0,
            "chapters": [
                {"index": c.index, "title_zh": c.title_zh, "url": c.url}
                for c in (result.preview.chapters[:50] if result.preview else [])
            ],
        },
        "engine": result.engine,
        "validation": result.validation,
        "rounds": result.rounds,
        "overrides_applied": result.overrides_applied,
    }
    return JSONResponse(payload)


@router.post("/preset-builder/save")
def preset_builder_save(
    request: Request,
    preset_json: str = Form(""),
):
    if not preset_json:
        return JSONResponse({"error": "Thiếu preset_json"}, status_code=400)
    try:
        data = json.loads(preset_json)
    except json.JSONDecodeError as e:
        return JSONResponse({"error": f"preset_json không hợp lệ: {e}"}, status_code=400)

    name = data.get("name", "")
    if not name:
        return JSONResponse({"error": "Thiếu tên preset"}, status_code=400)

    preset = SourcePreset(
        name=name,
        engine=data.get("engine", "http"),
        domains=data.get("domains", ""),
        chapter_link_pattern=data.get("chapter_link_pattern", r".*"),
        content_selector=data.get("content_selector", ""),
        toc_selector=data.get("toc_selector", ""),
        chapter_title_selector=data.get("chapter_title_selector", ""),
        title_selector=data.get("title_selector", ""),
        author_selector=data.get("author_selector", ""),
        desc_selector=data.get("desc_selector", ""),
        cover_selector=data.get("cover_selector", ""),
        encoding=data.get("encoding", ""),
        user_agent=data.get("user_agent", ""),
        headless=bool(data.get("headless", True)),
        magic=bool(data.get("magic", True)),
        js_code=data.get("js_code", ""),
        delay_seconds=float(data.get("delay_seconds", 1.0)),
        next_page_selector=data.get("next_page_selector", ""),
        next_page_url_pattern=data.get("next_page_url_pattern", ""),
        max_pages_per_chapter=int(data.get("max_pages_per_chapter", 10)),
    )
    save_preset(preset, deps.SOURCES_PATH)
    return RedirectResponse(url="/sources", status_code=303)


@router.post("/preset-builder/toc-preview")
def preset_builder_toc_preview_api(
    toc_url: str = Form(""),
    preset: str = Form(""),
):
    if not toc_url or not preset:
        return JSONResponse({"error": "Thiếu toc_url hoặc preset"}, status_code=400)
    result = preview_toc(toc_url, preset, deps.SOURCES_PATH)
    if result.error:
        return JSONResponse({"error": result.error}, status_code=400)
    return JSONResponse({
        "title": result.preview.title if result.preview else "",
        "author": result.preview.author if result.preview else "",
        "chapter_count": len(result.preview.chapters) if result.preview else 0,
        "chapters": [
            {"index": c.index, "title_zh": c.title_zh, "url": c.url}
            for c in (result.preview.chapters[:50] if result.preview else [])
        ],
    })


def suggest_preset_url(toc_url: str) -> str:
    """Trả về URL /preset-builder?toc_url=... cho library page."""
    return f"/preset-builder?{urlencode({'toc_url': toc_url})}"
