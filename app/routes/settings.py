"""Cấu hình ebook: metadata truyện + nguồn crawl + AI dịch (`translate`) +
AI biên tập (`ai`) đều là cấu hình RIÊNG từng ebook. `defaults:` (bảng
settings) chỉ còn là fallback cho ebook chưa cấu hình riêng và là giá trị
quay về khi bấm Reset."""
from __future__ import annotations

import json
import re
from pathlib import Path

import requests
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse

from novel2epub import openai_client
from novel2epub.config import LOCAL_MT_MODEL_PRESETS, next_page_url_pattern_error
from novel2epub.genre import GENRE_PRESETS
from novel2epub.config_writer import (
    clean_prompt_text,
    update_defaults,
    update_ebook,
)
from novel2epub.sources import (
    SCRAPLING_FIELD_MAP,
    detect_preset,
    load_presets,
    neutralize_defaults_crawl,
    save_preset,
    strip_preset_defaults,
)
from novel2epub.queue_labels import job_label
from novel2epub.storage import Storage

from .. import deps
from ..logging_config import logger

# Default values for OutputConfig fields
DEFAULT_DATA_DIR = "data"
DEFAULT_EPUB_PATH = ""

router = APIRouter()


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
    concurrency_cap: int = Form(0),
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
    pattern_err = next_page_url_pattern_error(next_page_url_pattern)
    if pattern_err:
        raise HTTPException(status_code=400, detail=pattern_err)
    strip_list = [line.strip() for line in strip_patterns.splitlines() if line.strip()]
    crawl: dict = {
        "toc_url": toc_url,
        "chapter_link_pattern": chapter_link_pattern,
        "max_chapters": max_chapters,
        "max_workers": max(1, max_workers),
        "concurrency_cap": max(0, concurrency_cap),
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
    # thừa và sẽ đóng băng ebook ở giá trị preset lúc ghi. `toc_url` không có
    # trong SourcePreset nên strip_preset_defaults tự khắc giữ.
    cfg = deps.resolved_cfg(slug)
    source_name = getattr(cfg, "source", "")
    if source_name:
        preset = load_presets(deps.DB_PATH).get(source_name)
        if preset:
            crawl, _removed = strip_preset_defaults(crawl, preset)

    path = deps.ebook_config_path(slug)
    logger.info(
        "[config][CRAWL] slug=%s lưu vào %s: engine=scrapling mode=%s toc_url=%r content_selector=%r "
        "max_chapters=%s delay=%ss pagination=%s",
        slug, path, scrapling_mode, toc_url, content_selector, max_chapters, delay_seconds,
        next_page_selector or next_page_url_pattern or "off",
    )
    # Đây là snapshot đầy đủ của form đã loại các giá trị trùng preset, nên phải
    # thay toàn bộ override. Merge sẽ giữ lại key cũ đã biến mất khỏi `crawl`;
    # ví dụ đổi headless từ override True về False (trùng preset) sẽ lọc key
    # khỏi snapshot nhưng giá trị True cũ vẫn còn trong DB.
    update_ebook(deps.WORKSPACE_PATH, slug, {"crawl": crawl}, replace_crawl=True)
    return RedirectResponse(url=f"/ebooks/{slug}/settings", status_code=303)


def _read_crawl_overrides(db_path, slug: str) -> dict:
    """Đọc raw `crawl_overrides_json` của ebook (KHÔNG resolve preset)."""
    from novel2epub.db import get_thread_connection

    conn = get_thread_connection(Path(db_path).resolve())
    row = conn.execute(
        "SELECT crawl_overrides_json FROM ebooks WHERE slug = ?", (slug,)
    ).fetchone()
    return json.loads(row["crawl_overrides_json"] or "{}") if row else {}


def _read_translate_openai_overrides(db_path, slug: str) -> dict:
    """Đọc raw `translate_overrides_json.openai` của ebook (KHÔNG resolve
    defaults/preset) — dùng để biết prompt nào đang thật sự ghi đè riêng, phân
    biệt với giá trị hiệu lực (có thể chỉ là kế thừa defaults)."""
    from novel2epub.db import get_thread_connection

    conn = get_thread_connection(Path(db_path).resolve())
    row = conn.execute(
        "SELECT translate_overrides_json FROM ebooks WHERE slug = ?", (slug,)
    ).fetchone()
    translate_over = json.loads(row["translate_overrides_json"] or "{}") if row else {}
    return translate_over.get("openai") or {}


def _read_defaults_crawl(db_path) -> dict:
    """Đọc raw khối `crawl` trong defaults (settings.crawl_json) — phần config
    chung legacy cần trung hoà khi Reset Nguồn."""
    from novel2epub.db import get_thread_connection

    conn = get_thread_connection(Path(db_path).resolve())
    row = conn.execute("SELECT crawl_json FROM settings WHERE id = 1").fetchone()
    return json.loads(row["crawl_json"] or "{}") if row else {}


@router.post("/ebooks/{slug}/settings/sync-to-source")
def sync_to_source(slug: str):
    """Nâng override riêng của ebook thành cấu hình chung của preset.

    Sau khi đẩy field lên preset, XOÁ chính các override đó khỏi ebook: preset
    đã mang giá trị ấy nên override chỉ còn là bản sao thừa, và là thứ khiến
    ebook không còn ăn theo preset về sau.

    Ebook chưa gắn nguồn nhưng `toc_url` khớp domain một preset (ebook tạo
    trước khi preset tồn tại, hoặc bị bug INSERT OR REPLACE cũ gỡ nguồn) thì
    tự gắn lại nguồn đó rồi sync như thường.

    Không cần propagate sang ebook khác — `load_config` resolve preset live.
    """
    cfg = deps.resolved_cfg(slug)
    presets = load_presets(deps.DB_PATH)
    source_name = getattr(cfg, "source", "") or ""
    if not source_name:
        toc_url = getattr(cfg.crawl, "toc_url", "")
        source_name = (detect_preset(toc_url, presets) or "") if toc_url else ""
    if not source_name:
        raise HTTPException(
            status_code=400,
            detail="Ebook không có source preset và URL mục lục không khớp nguồn nào.",
        )

    preset = presets.get(source_name)
    if preset is None:
        raise HTTPException(status_code=404, detail=f"Nguồn '{source_name}' không tồn tại.")

    crawl = cfg.crawl
    changed_fields: list[str] = []

    # Field phẳng: so crawl đã resolve với preset; khác nghĩa là ebook đã override.
    for key, preset_val in preset.crawl_overrides().items():
        if key in SCRAPLING_FIELD_MAP.values() or key == "retry":
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

    retry = crawl.retry
    preset_retry = preset.crawl_overrides()["retry"]
    retry_fields = {
        "attempts": "retry_attempts",
        "delay_seconds": "retry_delay_seconds",
        "backoff": "retry_backoff",
        "max_delay_seconds": "retry_max_delay_seconds",
        "respect_retry_after": "retry_respect_retry_after",
    }
    for retry_key, preset_key in retry_fields.items():
        ebook_val = getattr(retry, retry_key)
        if ebook_val != preset_retry[retry_key]:
            setattr(preset, preset_key, ebook_val)
            changed_fields.append(preset_key)

    if not changed_fields:
        # Không có gì để đẩy nhưng vẫn ghi lại liên kết nguồn (ebook có thể
        # vừa được detect từ URL, hoặc từng bị gỡ nguồn bởi bug cũ).
        update_ebook(deps.DB_PATH, slug, {"source": source_name})
        return RedirectResponse(url=f"/ebooks/{slug}/settings", status_code=303)

    save_preset(deps.DB_PATH, preset)

    # Ebook về tham chiếu thuần: bỏ override giờ đã trùng khít preset. Ghi kèm
    # `source` trong CÙNG lần update: gắn nguồn vừa detect, đồng thời tự lành
    # cột source_preset nếu DB cũ (FK ON DELETE SET NULL) từng gỡ mất.
    raw = _read_crawl_overrides(deps.DB_PATH, slug)
    cleaned, removed = strip_preset_defaults(raw, preset)
    update_ebook(
        deps.DB_PATH, slug,
        {"crawl": cleaned, "source": source_name},
        replace_crawl=True,
    )

    logger.info(
        "[source] sync ebook=%s → preset=%s: đẩy lên %s, dọn override %s",
        slug, source_name, changed_fields, removed,
    )
    return RedirectResponse(url=f"/ebooks/{slug}/settings", status_code=303)


@router.post("/ebooks/{slug}/settings/source/reset")
def reset_source_overrides(slug: str):
    """Xoá TOÀN BỘ override crawl của ebook — quay về ĐÚNG "source preset +
    mặc định". Chỉ giữ lại `toc_url` vì nó là định danh của ebook.

    Để reset chính xác, ngoài xoá override còn phải:
    - Dò lại nguồn theo `toc_url` nếu ebook chưa gắn preset (ebook tạo trước
      khi preset tồn tại) — có khớp thì gắn để "về nguồn" đúng nghĩa.
    - Trung hoà khối `crawl` còn sót trong defaults (config chung cũ) bằng
      `neutralize_defaults_crawl` — không thì các giá trị rác đó lại merge
      vào ebook ngay sau khi override bị xoá.
    """
    raw = _read_crawl_overrides(deps.DB_PATH, slug)
    toc_url = raw.get("toc_url", "")
    kept: dict = {"toc_url": toc_url} if toc_url else {}

    presets = load_presets(deps.DB_PATH)
    cfg = deps.resolved_cfg(slug)
    source_name = getattr(cfg, "source", "") or ""
    attached = False
    if not source_name and toc_url:
        source_name = detect_preset(toc_url, presets) or ""
        attached = bool(source_name)
    preset = presets.get(source_name) if source_name else None

    neutral = neutralize_defaults_crawl(_read_defaults_crawl(deps.DB_PATH), preset)
    updates: dict = {"crawl": {**neutral, **kept}}
    if attached:
        updates["source"] = source_name

    update_ebook(deps.WORKSPACE_PATH, slug, updates, replace_crawl=True)
    removed = sorted(set(raw) - set(kept))
    logger.info(
        "[config][RESET/CRAWL] slug=%s xoá override %s (giữ %s)%s%s",
        slug, removed, list(kept),
        f" — gắn lại nguồn '{source_name}'" if attached else "",
        f" — trung hoà defaults.crawl: {sorted(neutral)}" if neutral else "",
    )
    return RedirectResponse(url=f"/ebooks/{slug}/settings", status_code=303)


@router.post("/ebooks/{slug}/settings/translate/reset")
def reset_translate_overrides(slug: str):
    """Xoá cấu hình AI dịch RIÊNG của ebook — quay về config chung
    (`defaults.translate`, hoặc dataclass default nếu defaults trống).
    Chỉ đụng ebook này, các ebook khác giữ nguyên config riêng của chúng."""
    update_ebook(deps.WORKSPACE_PATH, slug, {"translate": {}}, replace_translate=True)
    logger.info("[config][RESET/DỊCH] slug=%s xoá translate riêng — về config chung", slug)
    return RedirectResponse(url=f"/ebooks/{slug}/settings", status_code=303)


@router.post("/ebooks/{slug}/settings/ai/reset")
def reset_ai_overrides(slug: str):
    """Xoá cấu hình AI biên tập RIÊNG của ebook — quay về config chung
    (`defaults.ai`, fallback translate.openai nếu cũng trống)."""
    update_ebook(deps.WORKSPACE_PATH, slug, {"ai": {}}, replace_ai=True)
    logger.info("[config][RESET/AI] slug=%s xoá ai riêng — về config chung", slug)
    return RedirectResponse(url=f"/ebooks/{slug}/settings", status_code=303)


def _global_ai_payload(*, include_secret: bool = False) -> dict:
    from novel2epub.db import get_thread_connection

    conn = get_thread_connection(Path(deps.DB_PATH).resolve())
    row = conn.execute(
        "SELECT global_ai_json, translate_json, ai_json FROM settings WHERE id = 1"
    ).fetchone()
    stored = json.loads(row["global_ai_json"] or "{}") if row else {}
    translate = json.loads(row["translate_json"] or "{}") if row else {}
    assistant = json.loads(row["ai_json"] or "{}") if row else {}
    translate_openai = translate.get("openai") if isinstance(translate.get("openai"), dict) else {}
    assistant_openai = assistant.get("openai") if isinstance(assistant.get("openai"), dict) else {}
    api_key = str(stored.get("api_key") or translate_openai.get("api_key") or assistant_openai.get("api_key") or "")
    payload = {
        "base_url": str(stored.get("base_url") or translate_openai.get("base_url") or assistant_openai.get("base_url") or "http://localhost:20128/v1"),
        "api_key": api_key if include_secret else "",
        "api_key_configured": bool(api_key),
        "translation_model": str(stored.get("translation_model") or translate_openai.get("model") or "free-stack"),
        "assistant_model": str(stored.get("assistant_model") or assistant_openai.get("model") or "free-stack"),
        "timeout_seconds": int(stored.get("timeout_seconds") or translate_openai.get("timeout_seconds") or assistant_openai.get("timeout_seconds") or 120000),
        "temperature": float(stored.get("temperature", translate_openai.get("temperature", assistant_openai.get("temperature", 0.7)))),
    }
    return payload


def save_global_ai_settings(payload: dict) -> dict:
    current = _global_ai_payload(include_secret=True)
    api_key = str(payload.get("api_key") or "").strip()
    if payload.get("clear_api_key"):
        api_key = ""
    elif not api_key:
        api_key = current["api_key"]
    global_ai = {
        "base_url": str(payload.get("base_url", current["base_url"])).strip().rstrip("/"),
        "api_key": api_key,
        "translation_model": str(payload.get("translation_model", current["translation_model"])).strip(),
        "assistant_model": str(payload.get("assistant_model", current["assistant_model"])).strip(),
        "timeout_seconds": max(1, int(payload.get("timeout_seconds", current["timeout_seconds"]))),
        "temperature": float(payload.get("temperature", current["temperature"])),
    }
    if not global_ai["base_url"]:
        raise ValueError("base_url không được để trống.")
    if not 0 <= global_ai["temperature"] <= 2:
        raise ValueError("temperature phải nằm trong khoảng 0 đến 2.")
    update_defaults(deps.WORKSPACE_PATH, {"global_ai": global_ai})
    return {**global_ai, "api_key": "", "api_key_configured": bool(api_key)}


@router.post("/settings/ai/models")
def list_ai_models(payload: dict):
    """Proxy model discovery; credential chỉ nhận trong request body."""
    base_url = str(payload.get("base_url") or "").strip()
    api_key = str(payload.get("api_key") or "").strip()
    if not api_key and payload.get("use_saved_api_key", True):
        api_key = _global_ai_payload(include_secret=True)["api_key"]
    timeout_seconds = max(1, int(payload.get("timeout_seconds", 30)))
    if not base_url:
        return JSONResponse({"models": [], "error": "Thiếu base_url."})
    try:
        models = openai_client.list_models(base_url, api_key, timeout_seconds)
        return JSONResponse({"models": models})
    except Exception as e:
        return JSONResponse({"models": [], "error": str(e)})


def _test_ai_provider(base_url: str, api_key: str, timeout_seconds: int) -> JSONResponse:
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
    data = resp.json()
    items = data.get("data", data) if isinstance(data, dict) else data
    model_count = len(items) if isinstance(items, list) else 0
    headers_obj = resp.headers if hasattr(resp.headers, "get") else SimpleNamespace(get=lambda k, d=None: d)
    result: dict = {"ok": True, "latency_ms": latency_ms, "model_count": model_count}
    omniroute_version = headers_obj.get("X-OmniRoute-Version")
    if omniroute_version:
        result["omniroute_version"] = omniroute_version
    return JSONResponse(result, status_code=200)


@router.post("/settings/ai/test")
def test_global_ai_connection(payload: dict):
    current = _global_ai_payload(include_secret=True)
    base_url = str(payload.get("base_url") or current["base_url"]).strip()
    api_key = str(payload.get("api_key") or current["api_key"]).strip()
    timeout_seconds = max(1, int(payload.get("timeout_seconds", 15)))
    return _test_ai_provider(base_url, api_key, timeout_seconds)


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


@router.get("/settings/translate/default-prompts")
def get_default_prompts(source_language: str = ""):
    """Trả prompt_template + title_prompt_template mặc định theo ngôn ngữ nguồn.
    Dùng cho nút 'Nạp prompt mẫu theo ngôn ngữ nguồn' trong UI."""
    from novel2epub.config import DEFAULT_PROMPT, EN_DEFAULT_PROMPT, EN_TITLE_PROMPT, TITLE_PROMPT

    if source_language == "en":
        return JSONResponse({"prompt_template": EN_DEFAULT_PROMPT, "title_prompt_template": EN_TITLE_PROMPT})
    return JSONResponse({"prompt_template": DEFAULT_PROMPT, "title_prompt_template": TITLE_PROMPT})


@router.post("/ebooks/{slug}/settings/translate")
def save_translate(
    slug: str,
    type: str = Form("openai"),
    preset: str = Form(""),
    profile: str = Form("traditional_cn_novel"),
    base_url: str = Form("http://localhost:20128/v1"),
    api_key: str = Form(""),
    model: str = Form("free-stack"),
    timeout_seconds: int = Form(120000),
    temperature: float = Form(0.7),
    prompt_template: str = Form(""),
    title_prompt_template: str = Form(""),
    genre: str = Form("auto"),
    tone: str = Form(""),
    pronoun_policy: str = Form(""),
    title_mode: str = Form(""),
    han_viet_level: str = Form(""),
    keep_paragraphs: bool = Form(False),
    delay_seconds: float = Form(0.5),
    max_workers: int = Form(1),
    source_language: str = Form(""),
    target_language: str = Form("vi"),
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
    batch_size: int = Form(1),
    prompt_max_chars: int = Form(20000),
    auto_glossary: bool = Form(True),
    use_idioms: bool = Form(True),
    ai_glossary_analysis: bool = Form(False),
    auto_cleanup_han: bool = Form(False),
    cleanup_han_engine: str = Form("local_mt"),
    cleanup_han_max_chars: int = Form(18000),
    cleanup_han_retries: int = Form(1),
):
    openai_cfg: dict = {
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "timeout_seconds": timeout_seconds,
        "temperature": temperature,
    }
    # Luôn ghi cả khi rỗng: rỗng nghĩa là "bỏ ghi đè, dùng lại Dịch chung" — merge
    # đè (không xoá được key vắng mặt), nên phải ghi rỗng tường minh mới xoá được
    # ghi đè cũ. Xem load_config: chuỗi rỗng bị bỏ qua, không áp dụng làm override.
    openai_cfg["prompt_template"] = clean_prompt_text(prompt_template)
    openai_cfg["title_prompt_template"] = clean_prompt_text(title_prompt_template)

    preset_model_key = (LOCAL_MT_MODEL_PRESETS.get(local_model) or {}).get("model_key")
    hachimimt_cfg: dict = {
        "model_key": preset_model_key or hachimimt_model_key,
        "backend": "ctranslate2",
        "beam_size": hachimimt_beam_size,
        "chunk_mode": hachimimt_chunk_mode,
    }

    translate: dict = {
        "type": type,
        "preset": preset,
        "profile": profile,
        "source_language": source_language,
        "target_language": target_language,
        "model": local_model,
        "genre": genre,
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
        "batch_size": max(1, batch_size),
        "prompt_max_chars": max(0, prompt_max_chars),
        "auto_glossary": auto_glossary,
        "use_idioms": use_idioms,
        "ai_glossary_analysis": ai_glossary_analysis,
        "auto_cleanup_han": auto_cleanup_han,
        "cleanup_han": {
            "engine": "openai" if cleanup_han_engine == "openai" else "local_mt",
            "max_chars": max(0, cleanup_han_max_chars),
            "retries": max(0, cleanup_han_retries),
        },
    }
    path = deps.ebook_config_path(slug)
    logger.info(
        "[config][AI/DỊCH] slug=%s lưu riêng cho ebook (DB %s): type=%s source_lang=%s local_model=%s genre=%s base_url=%r model=%r "
        "hachimimt=%s timeout=%ss temperature=%s tone=%r pronoun=%s title_mode=%s han_viet=%s "
        "keep_paragraphs=%s retry=%s chunk_max_chars=%s delay=%ss "
        "batch_size=%s prompt_max_chars=%s auto_cleanup_han=%s cleanup_han=%s/%s",
        slug, path, type, source_language, local_model, genre, base_url, model,
        hachimimt_model_key, timeout_seconds, temperature, tone,
        pronoun_policy, title_mode, han_viet_level, keep_paragraphs, retry_attempts,
        chunk_max_chars, delay_seconds,
        batch_size, prompt_max_chars, auto_cleanup_han,
        cleanup_han_max_chars, cleanup_han_retries,
    )
    # Cấu hình AI dịch RIÊNG của ebook này — defaults (config chung) không đổi.
    update_ebook(deps.WORKSPACE_PATH, slug, {"translate": translate})
    return RedirectResponse(url=f"/ebooks/{slug}/settings", status_code=303)


@router.post("/ebooks/{slug}/settings/ai")
def save_ai(
    slug: str,
    base_url: str = Form("http://localhost:20128/v1"),
    api_key: str = Form(""),
    timeout_seconds: int = Form(120000),
    temperature: float = Form(0.7),
    api_key_configured: bool = Form(False),
):
    """Lưu provider AI biên tập (`ai.openai`) RIÊNG cho từng ebook — ghi đè Global AI.

    Dùng cho: glossary suggest/rewrite/evaluate. Per-book override bao gồm cả
    base_url, api_key, timeout, temperature (khác với model — translation_model
    và assistant_model lưu riêng qua endpoint `model-overrides`). API key để
    trống khi lưu sẽ GIỮ NGUYÊN secret hiện tại của truyện này (không ghi đè
    bằng rỗng). `api_key_configured` chỉ để khớp hợp đồng trường với GET.
    """
    from novel2epub.db import get_thread_connection

    conn = get_thread_connection(Path(deps.DB_PATH).resolve())
    row = conn.execute(
        "SELECT ai_overrides_json FROM ebooks WHERE slug = ?", (slug,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Không có ebook {slug!r}.")
    existing = json.loads(row["ai_overrides_json"] or "{}")
    current_key = str((existing.get("openai") or {}).get("api_key") or "")

    incoming = (api_key or "").strip()
    stored_key = incoming if incoming else current_key

    ai_openai_cfg: dict = {
        "base_url": base_url,
        "api_key": stored_key,
        "timeout_seconds": timeout_seconds,
        "temperature": temperature,
    }
    path = deps.ebook_config_path(slug)
    logger.info(
        "[config][AI/BIÊN TẬP] slug=%s lưu riêng cho ebook (DB %s): base_url=%r timeout=%ss temperature=%s key_changed=%s",
        slug, path, base_url, timeout_seconds, temperature, bool(incoming),
    )
    update_ebook(deps.WORKSPACE_PATH, slug, {"ai": {"openai": ai_openai_cfg}})
    return {"saved": True, "api_key_configured": bool(stored_key)}


@router.post("/ebooks/{slug}/settings/reader")
def save_reader(
    slug: str,
    url: str = Form(""),
    service_key: str = Form(""),
    timeout_seconds: int = Form(60),
    batch_size: int = Form(50),
    push_anchors: str = Form(""),
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
        # Checkbox không tick thì trình duyệt KHÔNG gửi field — rỗng = tắt.
        "push_anchors": bool(push_anchors),
    }})
    update_ebook(deps.WORKSPACE_PATH, slug, {"reader": {
        "slug": reader_slug,
        "free_chapters": free_chapters,
        "published": published,
    }})
    return RedirectResponse(url=f"/ebooks/{slug}/settings", status_code=303)


@router.post("/settings/api")
def settings_api_save(
    token: str = Form(""),
    cors_origins: str = Form(""),
    auto_build: str = Form(""),
):
    origins = [line.strip() for line in cors_origins.splitlines() if line.strip()]
    update_defaults(
        deps.WORKSPACE_PATH,
        {
            "api": {
                "token": token.strip(),
                "cors_origins": origins,
                # Checkbox không tick thì trình duyệt KHÔNG gửi field — chuỗi
                # rỗng nghĩa là tắt.
                "auto_build": bool(auto_build),
            }
        },
    )
    return RedirectResponse(url="/settings/api", status_code=303)


@router.post("/settings/api/token")
def settings_api_new_token():
    """Sinh token ngẫu nhiên mới. Token cũ mất hiệu lực ngay — mọi thiết bị
    đã cấu hình phải nhập lại."""
    import secrets

    update_defaults(
        deps.WORKSPACE_PATH, {"api": {"token": secrets.token_urlsafe(32)}}
    )
    return RedirectResponse(url="/settings/api", status_code=303)


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
        # translate per-ebook — max_workers ghi vào override riêng như tab Dịch.
        "translate": {"max_workers": max(1, translate_max_workers)},
    })
    return RedirectResponse(url=f"/ebooks/{slug}/settings", status_code=303)


# ── Local MT CHUNG: danh mục model + cài đặt/cập nhật + config mặc định ────
#
# Trang quản lý tập trung cho toàn hệ thống: xem model nào đã tải về máy,
# tải model mới / cập nhật lại (job nền vì tải hàng trăm MB), và đặt model
# mặc định. Danh sách model đọc trực tiếp từ `hachimimt.translator.MODELS`
# nên khi bổ sung Local MT mới chỉ cần thêm entry ở đó — trang tự hiển thị.

@router.get("/api/ui/settings/local-mt")
def local_mt_overview():
    from novel2epub.hachimimt.models import (
        MODELS,
        MODELS_DIR,
        is_model_downloaded,
    )

    cfg = deps.cfg()
    tr = cfg.translate
    models = []
    for key, m in MODELS.items():
        models.append({
            "key": key,
            "label": m.label,
            "model_id": m.model_id,
            "ct2_model_id": m.ct2_model_id or m.model_id,
            "size_mb": m.ct2_size_mb,
            "default_beam": m.default_beam,
            "downloaded": is_model_downloaded(key, "ct2"),
        })
    return {
        # Thiết kế cho việc bổ sung Local MT khác sau này: mỗi engine một nhóm
        # model; hiện tại chỉ có "hachimimt".
        "engines": [
            {
                "id": "hachimimt",
                "label": "Local MT (NMT cục bộ)",
                "models": models,
            }
        ],
        "models_dir": str(MODELS_DIR),
        "config": {
            "model_key": tr.hachimimt.model_key,
            "backend": tr.hachimimt.backend,
            "beam_size": tr.hachimimt.beam_size,
            "chunk_mode": tr.hachimimt.chunk_mode,
        },
    }


@router.post("/api/ui/settings/local-mt/config")
def local_mt_config_save(payload: dict):
    """Lưu model/beam/chunk mode MẶC ĐỊNH dùng chung (`defaults.translate`)."""
    from novel2epub.hachimimt.models import MODELS

    current = deps.cfg().translate
    model_key = str(payload.get("model_key") or "").strip()
    if model_key and model_key not in MODELS:
        raise HTTPException(status_code=400, detail=f"Không biết model: {model_key}")
    chunk_mode = str(payload.get("chunk_mode") or current.hachimimt.chunk_mode).strip()
    if chunk_mode not in ("sentence", "paragraph"):
        raise HTTPException(status_code=400, detail="chunk_mode phải là 'sentence' hoặc 'paragraph'.")
    hachimimt = {
        "model_key": model_key or current.hachimimt.model_key,
        "beam_size": max(1, int(payload.get("beam_size", current.hachimimt.beam_size))),
        "chunk_mode": chunk_mode,
    }
    update_defaults(deps.WORKSPACE_PATH, {"translate": {"hachimimt": hachimimt}})
    logger.info(
        "[config][LOCAL-MT] defaults lưu: model_key=%s beam=%s chunk_mode=%s",
        hachimimt["model_key"], hachimimt["beam_size"], hachimimt["chunk_mode"],
    )
    return {"saved": True, "config": {**hachimimt, "backend": "ctranslate2"}}


@router.post("/api/ui/settings/local-mt/install")
def local_mt_install(request: Request, payload: dict):
    """Tải về / cập nhật model Local MT qua job nền.

    `ensure_model_files` idempotent: file đủ rồi trả ngay không tải gì; thiếu
    thì snapshot_download bổ sung đúng pattern còn thiếu (cập nhật cũng là gọi
    lại hàm này). Job dùng pool `automation` riêng, không chặn worker khác.
    """
    import threading

    from novel2epub.hachimimt.models import Backend, MODELS
    from novel2epub.hachimimt.translator import ensure_model_files

    model_key = str(payload.get("model_key") or "").strip()
    if model_key not in MODELS:
        raise HTTPException(status_code=400, detail=f"Không biết model: {model_key}")
    label = MODELS[model_key].label
    cancel_event = threading.Event()

    def _target(log, _key=model_key, _ev=cancel_event):
        log(f"[local-mt] Bắt đầu tải/cập nhật {MODELS[_key].model_id} …")
        path = ensure_model_files(MODELS[_key], Backend.CT2)
        log(f"[local-mt] Xong: {path}")

    started = request.app.state.job.start_custom(
        f"local-mt-install-{model_key}",
        _target,
        category="automation",
        cancel_event=cancel_event,
        label=job_label("local-mt-install", title=label),
    )
    if not started:
        raise HTTPException(status_code=409, detail="Đang có job khác chạy, vui lòng đợi.")
    return {"started": True, "model_key": model_key}


@router.get("/api/ui/settings/translate-defaults")
def translate_defaults_get():
    """Cấu hình DỊCH CHUNG (defaults.translate) hiển thị trên trang quản lý.

    Không chứa credential AI (Global AI lo) và phần Local MT (trang riêng)."""
    tr = deps.cfg().translate
    return {
        "type": tr.type,
        "source_language": tr.source_language,
        "target_language": tr.target_language,
        "genre": tr.genre,
        "tone": tr.style.tone,
        "pronoun_policy": tr.style.pronoun_policy,
        "title_mode": tr.style.title_mode,
        "han_viet_level": tr.style.han_viet_level,
        "keep_paragraphs": tr.style.keep_paragraphs,
        "delay_seconds": tr.delay_seconds,
        "max_workers": tr.max_workers,
        "batch_size": tr.batch_size,
        "prompt_max_chars": tr.prompt_max_chars,
        "retry_attempts": tr.retry.attempts,
        "retry_delay_seconds": tr.retry.delay_seconds,
        "chunk_max_chars": tr.chunk.max_chars,
        "chunk_overlap_paragraphs": tr.chunk.overlap_paragraphs,
        "auto_glossary": tr.auto_glossary,
        "use_idioms": tr.use_idioms,
        "ai_glossary_analysis": tr.ai_glossary_analysis,
        "auto_cleanup_han": tr.auto_cleanup_han,
        "cleanup_han_engine": tr.cleanup_han.engine,
        "cleanup_han_max_chars": tr.cleanup_han.max_chars,
        "cleanup_han_retries": tr.cleanup_han.retries,
        "prompt_template": tr.openai.prompt_template,
        "title_prompt_template": tr.openai.title_prompt_template,
        # Cho combobox Thể loại trên trang quản lý (giống tab Dịch của ebook).
        "genres": [{"value": k, "label": v.label or k} for k, v in GENRE_PRESETS.items()],
    }


@router.post("/api/ui/settings/translate-defaults")
def translate_defaults_save(payload: dict):
    """Ghi cấu hình DỊCH CHUNG vào defaults.translate (deep-merge).

    Prompt ghi qua `openai` để merge không đè mất credential đang có; các
    trường khác ghi phẳng/nested tương ứng cấu trúc dataclass."""
    genre = str(payload.get("genre") or "auto").strip()
    translate: dict = {
        "source_language": str(payload.get("source_language") or "").strip(),
        "target_language": str(payload.get("target_language") or "vi").strip() or "vi",
        "genre": genre,
        "style": {
            "tone": str(payload.get("tone") or ""),
            "pronoun_policy": str(payload.get("pronoun_policy") or ""),
            "title_mode": str(payload.get("title_mode") or ""),
            "han_viet_level": str(payload.get("han_viet_level") or ""),
            "keep_paragraphs": bool(payload.get("keep_paragraphs", True)),
        },
        "delay_seconds": max(0.0, float(payload.get("delay_seconds", 0.5))),
        "max_workers": max(1, int(payload.get("max_workers", 1))),
        "batch_size": max(1, int(payload.get("batch_size", 1))),
        "prompt_max_chars": max(0, int(payload.get("prompt_max_chars", 20000))),
        "retry": {
            "attempts": max(1, int(payload.get("retry_attempts", 1))),
            "delay_seconds": max(0.0, float(payload.get("retry_delay_seconds", 0.0))),
        },
        "chunk": {
            "max_chars": max(0, int(payload.get("chunk_max_chars", 0))),
            "overlap_paragraphs": max(0, int(payload.get("chunk_overlap_paragraphs", 0))),
        },
        "auto_glossary": bool(payload.get("auto_glossary", False)),
        "use_idioms": bool(payload.get("use_idioms", True)),
        "ai_glossary_analysis": bool(payload.get("ai_glossary_analysis", False)),
        "auto_cleanup_han": bool(payload.get("auto_cleanup_han", False)),
        "cleanup_han": {
            "engine": "openai" if payload.get("cleanup_han_engine") == "openai" else "local_mt",
            "max_chars": max(0, int(payload.get("cleanup_han_max_chars", 18000))),
            "retries": max(0, int(payload.get("cleanup_han_retries", 1))),
        },
    }
    prompt_template = str(payload.get("prompt_template") or "")
    title_prompt_template = str(payload.get("title_prompt_template") or "")
    openai_update: dict = {}
    if prompt_template.strip():
        openai_update["prompt_template"] = clean_prompt_text(prompt_template)
    if title_prompt_template.strip():
        openai_update["title_prompt_template"] = clean_prompt_text(title_prompt_template)
    if openai_update:
        translate["openai"] = openai_update
    update_defaults(deps.WORKSPACE_PATH, {"translate": translate})
    logger.info(
        "[config][DỊCH-CHUNG] defaults lưu: genre=%s tone=%r workers=%s batch=%s "
        "prompt_max_chars=%s chunk=%s cleanup_han=%s/%s prompt=%s",
        translate["genre"], translate["style"]["tone"], translate["max_workers"],
        translate["batch_size"], translate["prompt_max_chars"],
        translate["chunk"], translate["cleanup_han"]["engine"],
        translate["cleanup_han"]["retries"], bool(openai_update),
    )
    return {"saved": True}
