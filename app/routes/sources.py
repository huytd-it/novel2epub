"""Thư viện site preset: liệt kê, thêm/sửa, xóa, nhân bản, export/import, dry-run
test các cấu hình crawl dùng lại (xem spec source-management)."""
from __future__ import annotations

import json
from dataclasses import asdict, fields

import yaml
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse, RedirectResponse

from novel2epub.config import CrawlConfig
from novel2epub.crawler import make_crawler
from novel2epub.sources import SourcePreset, save_presets

from .. import deps

router = APIRouter()

VALIDATION_PATH = deps.WORKSPACE_DIR / "source_validation.json"


def _load_validation() -> dict:
    if not VALIDATION_PATH.exists():
        return {}
    try:
        return json.loads(VALIDATION_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_validation(data: dict) -> None:
    VALIDATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    VALIDATION_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _record_validation(name: str, ok: bool, message: str) -> None:
    import time

    data = _load_validation()
    data[name] = {"ok": ok, "message": message, "checked_at": time.time()}
    _save_validation(data)


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
            "validation": _load_validation(),
            "job": request.app.state.job.status(),
        },
    )


@router.post("/sources")
def save_source_preset(
    name: str = Form(""),
    engine: str = Form("http"),
    url: str = Form(""),
    domains: str = Form(""),
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
    scrapling_mode: str = Form("stealthy"),
    solve_cloudflare: bool = Form(False),
    network_idle: bool = Form(False),
    impersonate: str = Form(""),
    concurrency_cap: int = Form(0),
):
    name = name.strip()
    presets = deps.presets()
    if name:
        kwargs = dict(
            name=name,
            engine=engine,
            url=url.strip(),
            domains=domains.strip(),
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
            scrapling_mode=scrapling_mode,
            solve_cloudflare=solve_cloudflare,
            network_idle=network_idle,
            impersonate=impersonate.strip(),
            concurrency_cap=max(0, concurrency_cap),
        )
        if user_agent.strip():
            kwargs["user_agent"] = user_agent
        presets[name] = SourcePreset(**kwargs)
        save_presets(deps.SOURCES_PATH, presets)
    return RedirectResponse(url="/sources", status_code=303)


@router.post("/sources/{name}/delete")
def delete_source_preset(name: str):
    presets = deps.presets()
    usage = _preset_usage(presets, deps.library())
    if usage.get(name):
        raise HTTPException(
            status_code=409,
            detail=f"Nguồn '{name}' đang dùng bởi: {', '.join(usage[name])}. Hãy đổi nguồn cho các ebook đó trước.",
        )
    if presets.pop(name, None) is not None:
        save_presets(deps.SOURCES_PATH, presets)
    return RedirectResponse(url="/sources", status_code=303)


@router.post("/sources/{name}/clone")
def clone_source_preset(name: str, new_name: str = Form("")):
    presets = deps.presets()
    src = presets.get(name)
    if src is None:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy nguồn '{name}'.")
    new_name = new_name.strip() or f"{name}-copy"
    suffix = 2
    base_name = new_name
    while new_name in presets:
        new_name = f"{base_name}-{suffix}"
        suffix += 1
    data = asdict(src)
    data["name"] = new_name
    presets[new_name] = SourcePreset(**data)
    save_presets(deps.SOURCES_PATH, presets)
    return RedirectResponse(url="/sources", status_code=303)


@router.post("/sources/{name}/test")
def test_source_preset(request: Request, name: str, toc_url: str = Form(...)):
    """Dry-run: fetch_toc + 1 fetch_chapter, không ghi gì xuống đĩa. Chạy như
    job nền ngắn (category "crawl") để không chặn request; kết quả lưu vào
    `source_validation.json` để hiển thị lại trên trang /sources."""
    presets = deps.presets()
    preset = presets.get(name)
    if preset is None:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy nguồn '{name}'.")

    def _target(log):
        crawler = None
        try:
            overrides = preset.crawl_overrides()
            overrides.pop("chapter_link_pattern", None)
            crawl_cfg = CrawlConfig(toc_url=toc_url, chapter_link_pattern=preset.chapter_link_pattern, **overrides)
            crawler = make_crawler(crawl_cfg)
            toc = crawler.fetch_toc()
            if not toc.chapters:
                _record_validation(name, False, "fetch_toc không trả về chương nào.")
                log(f"[test nguồn] {name}: không có chương.")
                return
            sample = crawler.fetch_chapter(toc.chapters[0])
            preview = (sample or "")[:200]
            _record_validation(
                name, True,
                f"OK — tiêu đề {toc.title!r}, {len(toc.chapters)} chương, mẫu: {preview[:80]!r}",
            )
            log(f"[test nguồn] {name}: OK ({len(toc.chapters)} chương, tiêu đề {toc.title!r}).")
        except Exception as e:  # noqa: BLE001 - ghi lại lý do lỗi để hiển thị UI
            _record_validation(name, False, str(e))
            log(f"[test nguồn] {name}: lỗi — {e}")
        finally:
            if crawler is not None:
                crawler.close()

    request.app.state.job.start_custom(f"test-source-{name}", _target, category="crawl")
    return RedirectResponse(url="/sources", status_code=303)


@router.get("/sources/export")
def export_source_presets():
    presets = deps.presets()
    data = {"sources": {name: {k: v for k, v in asdict(p).items() if k != "name"} for name, p in presets.items()}}
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    return PlainTextResponse(text, media_type="application/x-yaml", headers={
        "Content-Disposition": 'attachment; filename="sources-export.yaml"',
    })


@router.post("/sources/import")
async def import_source_presets(file: UploadFile = File(...), on_collision: str = Form("rename")):
    """on_collision: 'overwrite' | 'rename' — merge-by-name, không xóa preset hiện có."""
    content = await file.read()
    try:
        data = yaml.safe_load(content.decode("utf-8")) or {}
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"YAML không hợp lệ: {e}") from e
    incoming = data.get("sources") or {}
    if not isinstance(incoming, dict):
        raise HTTPException(status_code=400, detail="File phải có khối 'sources:' dạng mapping.")

    presets = deps.presets()
    for name, item in incoming.items():
        item = dict(item or {})
        item.pop("name", None)
        final_name = name
        if final_name in presets and on_collision == "rename":
            suffix = 2
            while f"{name}-{suffix}" in presets:
                suffix += 1
            final_name = f"{name}-{suffix}"
        item["name"] = final_name
        field_names = {f.name for f in fields(SourcePreset)}
        presets[final_name] = SourcePreset(**{k: v for k, v in item.items() if k in field_names})
    save_presets(deps.SOURCES_PATH, presets)
    return RedirectResponse(url="/sources", status_code=303)
