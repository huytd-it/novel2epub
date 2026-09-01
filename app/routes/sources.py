"""Thư viện site preset: liệt kê, thêm/sửa, xóa, nhân bản, export/import, dry-run
test các cấu hình crawl dùng lại (xem spec source-management)."""
from __future__ import annotations

import json
from dataclasses import asdict, fields

import yaml
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse

from novel2epub.config import next_page_url_pattern_error
from novel2epub.sources import SourcePreset, delete_preset, save_preset, save_presets

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
    """Map preset name -> list of ebook slugs có ``source == preset_name``.

    Đọc field ``source`` trực tiếp từ ebook config (không brute-force so sánh).
    """
    usage = {name: [] for name in presets}
    if not library.ebooks or not presets:
        return usage
    for slug in library.ebooks:
        try:
            cfg = deps.resolved_cfg(slug)
        except Exception:
            continue
        source = getattr(cfg, "source", "")
        if source and source in usage:
            usage[source].append(slug)
    return usage


@router.post("/sources")
def save_source_preset(
    name: str = Form(""),
    engine: str = Form("scrapling"),
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
    cover_url_pattern: str = Form(""),
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
    proxy: str = Form(""),
    dns_over_https: bool = Form(False),
    concurrency_cap: int = Form(0),
    strip_patterns: str = Form(""),
    # AI glossary/analysis
    ai_glossary_enabled: bool = Form(False),
    ai_glossary_extract_prompt: str = Form(""),
    ai_glossary_merge_prompt: str = Form(""),
    ai_cleanup_enabled: bool = Form(False),
    ai_cleanup_prompt: str = Form(""),
    ai_eval_enabled: bool = Form(False),
    ai_eval_prompt: str = Form(""),
):
    name = name.strip()
    pattern_err = next_page_url_pattern_error(next_page_url_pattern)
    if pattern_err:
        raise HTTPException(status_code=400, detail=pattern_err)
    strip_list = [line.strip() for line in strip_patterns.splitlines() if line.strip()]
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
            cover_url_pattern=cover_url_pattern,
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
            proxy=proxy.strip(),
            dns_over_https=dns_over_https,
            concurrency_cap=max(0, concurrency_cap),
            strip_patterns=strip_list,
            ai_glossary_enabled=ai_glossary_enabled,
            ai_glossary_extract_prompt=ai_glossary_extract_prompt,
            ai_glossary_merge_prompt=ai_glossary_merge_prompt,
            ai_cleanup_enabled=ai_cleanup_enabled,
            ai_cleanup_prompt=ai_cleanup_prompt,
            ai_eval_enabled=ai_eval_enabled,
            ai_eval_prompt=ai_eval_prompt,
        )
        if user_agent.strip():
            kwargs["user_agent"] = user_agent
        preset = SourcePreset(**kwargs)
        save_preset(deps.DB_PATH, preset)
        # Không propagate: ebook chỉ lưu TÊN preset, `load_config` resolve giá trị
        # preset live nên sửa preset là ebook ăn theo ngay.
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
            crawl_cfg = preset.to_crawl_config(toc_url)
            crawler = ScraplingCrawler(crawl_cfg)
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


def _page_hrefs(page) -> list[str]:
    """Danh sách href thô từ mọi <a> của một trang scrapling."""
    hrefs: list[str] = []
    links = page.css("a[href]")
    if links:
        for a in links:
            href = a.attrib.get("href", "")
            if href:
                hrefs.append(href)
    return hrefs


def _count_matches(page, selector: str) -> int:
    """Số phần tử khớp `selector` trên `page`. -1 nếu selector không hợp lệ."""
    if not selector:
        return 0
    try:
        results = page.css(selector)
    except Exception:  # noqa: BLE001 - selector AI có thể sai cú pháp
        return -1
    if not results:
        return 0
    try:
        return len(results)
    except TypeError:
        return 1


def _api_suggest_selectors_core(
    toc_url: str,
    chapter_url: str,
    toc_html_raw: str,
    chapter_html_raw: str,
    sample_links: list[str],
    scrapling_page=None,  # Scrapling Selector khi có caller cung cấp
) -> dict:
    """Nội lõi `suggest` (digest→AI→parse→validate), dùng chung cho route webui
    và bất kỳ caller nào khác. Không lo fetch hay lỗi HTTP."""
    from novel2epub import openai_client, selector_ai

    try:
        ai_cfg = deps.cfg().ai.openai
    except HTTPException:
        raise
    if not ai_cfg.base_url or not ai_cfg.model:
        raise HTTPException(
            status_code=400,
            detail="Chưa cấu hình AI (base_url/model) ở Settings › AI biên tập.",
        )

    # 🔑 Tuỳ chọn: mode/label nếu caller muốn đổi prompt nhanh
    toc_digest, toc_map = selector_ai.build_dom_digest(toc_html_raw, selector_ai.TOC_FIELD_SPECS)
    chapter_digest, chapter_map = selector_ai.build_dom_digest(chapter_html_raw, selector_ai.CHAPTER_FIELD_SPECS)
    label_map = {**toc_map, **chapter_map}
    # Hỗ trợ fallback khi cả 2 digest rỗng (trang lỗi/Cloudflare): vẫn cho AI suy regex từ link.
    if not label_map and not sample_links:
        raise HTTPException(status_code=422, detail="Không trích được ứng viên DOM nào — trang có thể lỗi/Cloudflare. Thử tải lại với chế độ dynamic.")

    prompt = selector_ai.build_suggest_prompt(
        toc_url=toc_url,
        chapter_url=chapter_url,
        toc_digest=toc_digest,
        chapter_digest=chapter_digest,
        sample_links=sample_links,
    )
    try:
        raw = openai_client.run_chat(ai_cfg, prompt)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Gọi AI thất bại: {e}") from e
    try:
        fields = selector_ai.parse_suggestion(raw, label_map)
    except ValueError as e:
        raise HTTPException(status_code=502, detail=f"AI trả về không đọc được: {e}") from e

    # Validate ngay trên chính DOM đã fetch (scrapling nếu có, fallback bs4).
    chapter_html_fields = {"content_selector", "chapter_title_selector", "next_page_selector"}
    diagnostics: dict[str, int] = {}
    for field, sel in fields.items():
        if field == "chapter_link_pattern" or not sel:
            continue
        html = chapter_html_raw if field in chapter_html_fields else toc_html_raw
        diagnostics[field] = selector_ai.count_matches(html, sel) if html else 0

    pattern_ok, pattern_hits = selector_ai.validate_pattern(
        fields.get("chapter_link_pattern", ""), sample_links
    )

    return {
        "ok": True,
        "fields": fields,
        "diagnostics": diagnostics,
        "chapter_url": chapter_url,
        "sample_count": len(sample_links),
        "pattern_ok": pattern_ok,
        "pattern_hits": pattern_hits,
        "toc_digest": toc_digest,
        "chapter_digest": chapter_digest,
    }


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
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="File phải là YAML dạng mapping.")
    # Chấp nhận cả 2 định dạng:
    #   - Có khối bọc `sources:` (định dạng export)
    #   - Mapping phẳng ở cấp cao nhất (sources.yaml cũ) — mỗi key là 1 preset
    if isinstance(data.get("sources"), dict):
        incoming = data["sources"]
    else:
        incoming = {k: v for k, v in data.items() if isinstance(v, dict)}
    if not incoming:
        raise HTTPException(
            status_code=400,
            detail="Không tìm thấy preset nào — file phải là mapping preset (có/không có khối 'sources:').",
        )

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
