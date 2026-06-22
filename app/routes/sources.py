"""Thư viện site preset: liệt kê, thêm/sửa, xóa các cấu hình crawl dùng lại."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from novel2epub.sources import SourcePreset, save_presets

from .. import deps

router = APIRouter()


def _preset_usage(presets, library):
    """Map preset name -> list of ebook slugs whose resolved CrawlConfig matches
    tất cả cặp key/value trong preset.crawl_overrides(). Chỉ đọc, không ghi."""
    usage = {name: [] for name in presets}
    if not library.ebooks or not presets:
        return usage
    for slug in library.ebooks:
        try:
            crawl = deps.resolved_cfg(slug).crawl
        except Exception:
            continue
        for name, preset in presets.items():
            overrides = preset.crawl_overrides()
            if all(getattr(crawl, k, None) == v for k, v in overrides.items()):
                usage[name].append(slug)
    return usage


@router.get("/sources")
def sources_page(request: Request, edit: str = ""):
    presets = deps.presets()
    return deps.templates.TemplateResponse(
        request,
        "sources.html",
        {
            "sources_path": deps.SOURCES_PATH,
            "presets": presets,
            "edit": presets.get(edit),
            "usage": _preset_usage(presets, deps.library()),
            "job": request.app.state.job.status(),
        },
    )


@router.post("/sources")
def save_source_preset(
    name: str = Form(""),
    engine: str = Form("http"),
    chapter_link_pattern: str = Form(".*"),
    content_selector: str = Form(""),
    toc_selector: str = Form(""),
    chapter_title_selector: str = Form(""),
    title_selector: str = Form(""),
    author_selector: str = Form(""),
    desc_selector: str = Form(""),
    cover_selector: str = Form(""),
    encoding: str = Form(""),
    user_agent: str = Form(""),
    headless: bool = Form(False),
    magic: bool = Form(False),
    js_code: str = Form(""),
    delay_seconds: float = Form(1.0),
    next_page_selector: str = Form(""),
    next_page_url_pattern: str = Form(""),
    max_pages_per_chapter: int = Form(10),
):
    name = name.strip()
    presets = deps.presets()
    if name:
        kwargs = dict(
            name=name,
            engine=engine,
            chapter_link_pattern=chapter_link_pattern,
            content_selector=content_selector,
            toc_selector=toc_selector,
            chapter_title_selector=chapter_title_selector,
            title_selector=title_selector,
            author_selector=author_selector,
            desc_selector=desc_selector,
            cover_selector=cover_selector,
            encoding=encoding,
            headless=headless,
            magic=magic,
            js_code=js_code,
            delay_seconds=delay_seconds,
            next_page_selector=next_page_selector,
            next_page_url_pattern=next_page_url_pattern,
            max_pages_per_chapter=max_pages_per_chapter,
        )
        if user_agent.strip():
            kwargs["user_agent"] = user_agent
        presets[name] = SourcePreset(**kwargs)
        save_presets(deps.SOURCES_PATH, presets)
    return RedirectResponse(url="/sources", status_code=303)


@router.post("/sources/{name}/delete")
def delete_source_preset(name: str):
    presets = deps.presets()
    if presets.pop(name, None) is not None:
        save_presets(deps.SOURCES_PATH, presets)
    return RedirectResponse(url="/sources", status_code=303)
