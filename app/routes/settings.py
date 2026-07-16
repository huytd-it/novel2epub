"""Cấu hình ebook: metadata truyện + nguồn crawl per-ebook; AI dịch (`translate`)
và AI biên tập (`ai`) là cấu hình GLOBAL dùng chung mọi ebook (ghi vào `defaults:`)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import requests
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse

from novel2epub import openai_client
from novel2epub.config_writer import clean_prompt_text, update_defaults, update_ebook
from novel2epub.sources import (
    SCRAPLING_FIELD_MAP,
    load_presets,
    save_preset,
    strip_preset_defaults,
)
from novel2epub.storage import Storage

from .. import deps
from ..logging_config import logger

# Default values for OutputConfig fields
DEFAULT_DATA_DIR = "data"
DEFAULT_EPUB_PATH = ""

router = APIRouter()


@router.get("/ebooks/{slug}/settings")
def settings_page(request: Request, slug: str):
    cfg = deps.resolved_cfg(slug)
    # Source preset context: resolved preset + overridden fields
    source_preset = None
    overridden_fields: set[str] = set()
    source_name = getattr(cfg, "source", "")
    if source_name:
        presets = load_presets(deps.SOURCES_PATH)
        source_preset = presets.get(source_name)
        # Đọc crawl_overrides_json từ DB để xác định field ebook đã override
        if source_preset:
            import json
            from novel2epub.db import get_thread_connection
            conn = get_thread_connection(deps.WORKSPACE_PATH)
            row = conn.execute(
                "SELECT crawl_overrides_json FROM ebooks WHERE slug = ?", (slug,)
            ).fetchone()
            if row is not None:
                crawl_data = json.loads(row["crawl_overrides_json"] or "{}")
                overridden_fields = set(crawl_data.keys())
    return deps.templates.TemplateResponse(
        request,
        "settings.html",
        {
            "slug": slug,
            "config_path": deps.ebook_config_path(slug),
            "cfg": cfg,
            "source_preset": source_preset,
            "overridden_fields": overridden_fields,
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
    cover_url: str = Form(""),
):
    path = deps.ebook_config_path(slug)
    subject_list = [s.strip() for s in re.split(r"[\n,]", subjects) if s.strip()]
    logger.info(
        "[config][NOVEL] slug=%s lưu vào %s: title=%r author=%r language=%r "
        "publisher=%r pubdate=%r subjects=%r series=%r series_index=%r cover_url=%r",
        slug, path, title, author, language,
        publisher, pubdate, subject_list, series, series_index, cover_url,
    )

    novel_update = {
        "title": title,
        "author": author,
        "description": description,
        "language": language,
        "publisher": publisher,
        "pubdate": pubdate,
        "subjects": subject_list,
        "series": series,
        "series_index": series_index,
        "cover_url": cover_url,
        # identifier: chỉ ghi đè khi người dùng thật sự nhập — field rỗng
        # không xóa identifier tự sinh trước đó (xem spec ebook-metadata
        # "Identifier stable across rebuilds").
        **({"identifier": identifier} if identifier.strip() else {}),
    }
    update_ebook(deps.WORKSPACE_PATH, slug, {"novel": novel_update})

    # Tải ảnh bìa ngay lập tức khi có URL, lưu local bằng Scrapling.
    if cover_url.strip():
        try:
            cfg = deps.resolved_cfg(slug)
            storage = Storage(cfg.output.data_dir, cfg.novel.slug)
            content, ctype = _fetch_cover_content(cover_url)
            if content:
                ext = _cover_ext(cover_url, ctype)
                cover_name = storage.write_cover(content, ext)
                logger.info(
                    "[config][COVER] slug=%s tải ảnh bìa từ %s: %s (%d bytes)",
                    slug, cover_url, cover_name, len(content),
                )
                manifest = storage.load_manifest()
                if manifest:
                    manifest.cover_url = cover_url
                    manifest.cover_file = cover_name
                    storage.save_manifest(manifest)
            else:
                logger.warning("[config][COVER] slug=%s không tải được ảnh từ %s", slug, cover_url)
        except Exception:
            logger.warning("[config][COVER] slug=%s lỗi tải ảnh bìa từ %s", slug, cover_url, exc_info=True)
    else:
        # Xoá URL khỏi manifest nhưng giữ cover_file nếu có (ảnh đã upload).
        try:
            cfg = deps.resolved_cfg(slug)
            storage = Storage(cfg.output.data_dir, cfg.novel.slug)
            manifest = storage.load_manifest()
            if manifest:
                manifest.cover_url = ""
                storage.save_manifest(manifest)
        except Exception:
            pass
    return RedirectResponse(url=f"/ebooks/{slug}/settings", status_code=303)


def _cover_ext(url: str, content_type: str) -> str:
    """Đoán đuôi file ảnh từ Content-Type rồi tới URL, mặc định jpg."""
    ct = (content_type or "").lower()
    for key, ext in (("png", "png"), ("webp", "webp"), ("gif", "gif"), ("jpeg", "jpg"), ("jpg", "jpg")):
        if key in ct:
            return ext
    m = re.search(r"\.(png|webp|gif|jpe?g)(?:\?|$)", url, re.IGNORECASE)
    if m:
        ext = m.group(1).lower()
        return "jpg" if ext == "jpeg" else ext
    return "jpg"


def _fetch_cover_content(url: str) -> tuple[bytes | None, str]:
    """Tải ảnh bìa bằng Scrapling Fetcher (fallback requests)."""
    try:
        from scrapling.fetchers import Fetcher
        page = Fetcher.get(url, timeout=30)
        status = getattr(page, "status", None)
        if status and status >= 400:
            logger.warning("[cover] Scrapling HTTP %s cho %s", status, url)
            return None, ""
        content = getattr(page, "content", None)
        if content:
            ctype = (getattr(page, "headers", {}) or {}).get("Content-Type", "")
            return content, ctype
    except Exception as e:
        logger.warning("[cover] Scrapling lỗi %s, fallback requests: %s", url, e)

    try:
        import requests as _requests
        resp = _requests.get(url, timeout=30)
        resp.raise_for_status()
        return resp.content, resp.headers.get("Content-Type", "")
    except Exception as e:
        logger.warning("[cover] requests cũng lỗi %s: %s", url, e)
    return None, ""


@router.post("/ebooks/{slug}/settings/cover-upload")
def upload_cover(slug: str, cover_file: UploadFile = File(...)):
    """Tải ảnh bìa lên, lưu vào storage, cập nhật manifest."""
    if not cover_file.content_type or not cover_file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Chỉ chấp nhận file ảnh.")

    ext = "jpg"
    ct = cover_file.content_type.lower()
    for key, e in (("png", "png"), ("webp", "webp"), ("gif", "gif"), ("jpeg", "jpg"), ("jpg", "jpg")):
        if key in ct:
            ext = e
            break

    contents = cover_file.file.read()
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)

    cover_name = storage.write_cover(contents, ext)

    manifest = storage.load_manifest()
    if manifest:
        manifest.cover_file = cover_name
        # Xoá cover_url cũ vì đã có file upload.
        manifest.cover_url = ""
        storage.save_manifest(manifest)
        logger.info(
            "[config][COVER] slug=%s upload ảnh bìa: %s (%d bytes)",
            slug, cover_name, len(contents),
        )

    # Xoá cover_url trong config YAML để tránh nhầm lẫn.
    try:
        update_ebook(deps.WORKSPACE_PATH, slug, {"novel": {"cover_url": ""}})
    except Exception:
        pass

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
    proxy: str = Form(""),
    dns_over_https: bool = Form(False),
    next_page_selector: str = Form(""),
    next_page_url_pattern: str = Form(""),
    max_pages_per_chapter: int = Form(10),
    toc_next_page_selector: str = Form(""),
    toc_max_pages: int = Form(5),
    retry_attempts: int = Form(3),
    retry_delay_seconds: float = Form(5.0),
    retry_backoff: float = Form(2.0),
    retry_max_delay_seconds: float = Form(120.0),
    retry_respect_retry_after: bool = Form(False),
    headless: bool = Form(False),
    strip_patterns: str = Form(""),
):
    strip_list = [line.strip() for line in strip_patterns.splitlines() if line.strip()]
    crawl: dict = {
        "toc_url": toc_url,
        "chapter_link_pattern": chapter_link_pattern,
        "max_chapters": max_chapters,
        "max_workers": max(1, max_workers),
        "delay_seconds": delay_seconds,
        "content_selector": content_selector,
        "headless": headless,
        "strip_patterns": strip_list,
        "scrapling": {
            "mode": scrapling_mode,
            "solve_cloudflare": solve_cloudflare,
            "network_idle": network_idle,
            "impersonate": impersonate,
            "proxy": proxy.strip(),
            "dns_over_https": dns_over_https,
        },
        "next_page_selector": next_page_selector,
        "next_page_url_pattern": next_page_url_pattern,
        "max_pages_per_chapter": max_pages_per_chapter,
        "toc_next_page_selector": toc_next_page_selector,
        "toc_max_pages": toc_max_pages,
        "retry": {
            "attempts": retry_attempts,
            "delay_seconds": retry_delay_seconds,
            "backoff": retry_backoff,
            "max_delay_seconds": retry_max_delay_seconds,
            "respect_retry_after": retry_respect_retry_after,
        },
    }

    # Ebook gắn source chỉ lưu field nó CỐ Ý override — field trùng preset là
    # thừa và sẽ đóng băng ebook ở giá trị preset lúc ghi. `retry` không đến từ
    # preset nên luôn giữ; `toc_url` không có trong SourcePreset nên
    # strip_preset_defaults tự khắc giữ.
    cfg = deps.resolved_cfg(slug)
    source_name = getattr(cfg, "source", "")
    if source_name:
        preset = load_presets(deps.DB_PATH).get(source_name)
        if preset:
            retry = crawl.pop("retry", None)
            crawl, _removed = strip_preset_defaults(crawl, preset)
            if retry is not None:
                crawl["retry"] = retry

    path = deps.ebook_config_path(slug)
    logger.info(
        "[config][CRAWL] slug=%s lưu vào %s: engine=scrapling mode=%s toc_url=%r content_selector=%r "
        "max_chapters=%s delay=%ss pagination=%s",
        slug, path, scrapling_mode, toc_url, content_selector, max_chapters, delay_seconds,
        next_page_selector or next_page_url_pattern or "off",
    )
    update_ebook(deps.WORKSPACE_PATH, slug, {"crawl": crawl})
    return RedirectResponse(url=f"/ebooks/{slug}/settings", status_code=303)


def _read_crawl_overrides(db_path, slug: str) -> dict:
    """Đọc raw `crawl_overrides_json` của ebook (KHÔNG resolve preset)."""
    from novel2epub.db import get_thread_connection

    conn = get_thread_connection(Path(db_path).resolve())
    row = conn.execute(
        "SELECT crawl_overrides_json FROM ebooks WHERE slug = ?", (slug,)
    ).fetchone()
    return json.loads(row["crawl_overrides_json"] or "{}") if row else {}


@router.post("/ebooks/{slug}/settings/sync-to-source")
def sync_to_source(slug: str):
    """Nâng override riêng của ebook thành cấu hình chung của preset.

    Sau khi đẩy field lên preset, XOÁ chính các override đó khỏi ebook: preset
    đã mang giá trị ấy nên override chỉ còn là bản sao thừa, và là thứ khiến
    ebook không còn ăn theo preset về sau.

    Không cần propagate sang ebook khác — `load_config` resolve preset live.
    """
    cfg = deps.resolved_cfg(slug)
    source_name = getattr(cfg, "source", "")
    if not source_name:
        raise HTTPException(status_code=400, detail="Ebook không có source preset.")

    presets = load_presets(deps.DB_PATH)
    preset = presets.get(source_name)
    if preset is None:
        raise HTTPException(status_code=404, detail=f"Nguồn '{source_name}' không tồn tại.")

    crawl = cfg.crawl
    changed_fields: list[str] = []

    # Field phẳng: so crawl đã resolve với preset; khác nghĩa là ebook đã override.
    for key, preset_val in preset.crawl_overrides().items():
        if key in SCRAPLING_FIELD_MAP.values():
            continue  # xử lý riêng bên dưới (tên lồng khác tên phẳng)
        ebook_val = getattr(crawl, key, None)
        if ebook_val is not None and ebook_val != preset_val:
            setattr(preset, key, ebook_val)
            changed_fields.append(key)

    # Field scrapling: crawl dùng tên lồng (`mode`), preset dùng tên phẳng
    # (`scrapling_mode`) — quy đổi qua SCRAPLING_FIELD_MAP.
    if crawl.scrapling:
        for nested_key, flat_key in SCRAPLING_FIELD_MAP.items():
            ebook_val = getattr(crawl.scrapling, nested_key, None)
            if ebook_val is not None and ebook_val != getattr(preset, flat_key, None):
                setattr(preset, flat_key, ebook_val)
                changed_fields.append(flat_key)

    if not changed_fields:
        return RedirectResponse(url=f"/ebooks/{slug}/settings", status_code=303)

    save_preset(deps.DB_PATH, preset)

    # Ebook về tham chiếu thuần: bỏ override giờ đã trùng khít preset.
    raw = _read_crawl_overrides(deps.DB_PATH, slug)
    cleaned, removed = strip_preset_defaults(raw, preset)
    if removed:
        update_ebook(deps.DB_PATH, slug, {"crawl": cleaned}, replace_crawl=True)

    logger.info(
        "[source] sync ebook=%s → preset=%s: đẩy lên %s, dọn override %s",
        slug, source_name, changed_fields, removed,
    )
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
    # Glossary / batch / cleanup Hán
    auto_glossary: bool = Form(False),
    glossary_filter: bool = Form(False),
    batch_size: int = Form(1),
    prompt_max_chars: int = Form(7000),
    auto_cleanup_han: bool = Form(False),
    cleanup_han_max_chars: int = Form(8000),
    cleanup_han_retries: int = Form(1),
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
        "auto_glossary": auto_glossary,
        "glossary_filter": glossary_filter,
        "batch_size": max(1, batch_size),
        "prompt_max_chars": max(0, prompt_max_chars),
        "auto_cleanup_han": auto_cleanup_han,
        "cleanup_han": {
            "max_chars": max(0, cleanup_han_max_chars),
            "retries": max(0, cleanup_han_retries),
        },
    }
    path = deps.ebook_config_path(slug)
    logger.info(
        "[config][AI/DỊCH] global (từ %s) lưu vào defaults của %s: type=%s local_model=%s base_url=%r model=%r "
        "hachimimt=%s timeout=%ss temperature=%s tone=%r pronoun=%s title_mode=%s han_viet=%s "
        "keep_paragraphs=%s retry=%s chunk_max_chars=%s delay=%ss "
        "auto_glossary=%s glossary_filter=%s batch_size=%s prompt_max_chars=%s auto_cleanup_han=%s cleanup_han=%s/%s",
        slug, path, type, local_model, base_url, model,
        hachimimt_model_key, timeout_seconds, temperature, tone,
        pronoun_policy, title_mode, han_viet_level, keep_paragraphs, retry_attempts,
        chunk_max_chars, delay_seconds,
        auto_glossary, glossary_filter, batch_size, prompt_max_chars, auto_cleanup_han,
        cleanup_han_max_chars, cleanup_han_retries,
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


@router.post("/ebooks/{slug}/settings/reader")
def save_reader(
    slug: str,
    url: str = Form(""),
    service_key: str = Form(""),
    timeout_seconds: int = Form(60),
    batch_size: int = Form(50),
    reader_slug: str = Form(""),
    free_chapters: int = Form(5),
    published: bool = Form(False),
):
    """Lưu cấu hình đẩy chương lên app đọc novel-reader.

    Khối này tách đôi: phần kết nối Supabase (`url`/`service_key`/`timeout`/
    `batch_size`) dùng chung MỌI ebook nên ghi vào `defaults:`; phần
    `slug`/`free_chapters`/`published` là của riêng từng truyện nên ghi vào
    override của ebook.

    KHÔNG log `service_key`.
    """
    path = deps.ebook_config_path(slug)
    logger.info(
        "[config][READER] global (từ %s) lưu vào defaults của %s: url=%r timeout=%ss batch_size=%s "
        "| ebook %s: slug=%r free_chapters=%s published=%s",
        slug, path, url, timeout_seconds, batch_size,
        slug, reader_slug, free_chapters, published,
    )
    update_defaults(deps.WORKSPACE_PATH, {"reader": {
        "url": url,
        "service_key": service_key,
        "timeout_seconds": timeout_seconds,
        "batch_size": batch_size,
    }})
    update_ebook(deps.WORKSPACE_PATH, slug, {"reader": {
        "slug": reader_slug,
        "free_chapters": free_chapters,
        "published": published,
    }})
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
