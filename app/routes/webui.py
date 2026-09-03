"""JSON API riêng cho SPA (`/`).

Tách khỏi các router cũ có chủ đích: route hiện tại vẫn phải chạy
nguyên vẹn trong lúc SPA được port dần từng trang, nên phần này chỉ ĐỌC lại
cùng domain logic (`Storage`, `chapter_progress`) và không đụng vào chúng.

Endpoint đều nằm dưới `/api/ui/` để phân biệt với `/api/v1/` (hợp đồng công
khai cho readest, có CORS) và `/api/` (các endpoint nội bộ đã có).
"""
from __future__ import annotations

import dataclasses
import json
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Body, File, Form, HTTPException, Request, UploadFile

from novel2epub import revisions
from novel2epub import wireguard as wg
from novel2epub.automation import STEPS as AUTOMATION_STEPS
from novel2epub.automation import (
    add_automation,
    load_automations,
    remove_automation,
    update_automation,
    validate_schedule,
)
from novel2epub.progress import chapter_progress
from novel2epub.queue_labels import batch_job_label, chapter_job_label
from novel2epub.sources import SourcePreset, delete_preset, save_preset
from novel2epub.storage import Storage
from novel2epub.toc import apply_chapter_query, chapter_rows, count_words
from novel2epub.wireguard import WireGuardProfileError

from .. import deps
from ..chapter_compare import align_paragraphs, align_sources
from ..cost_summary import read_cost_summary
from ..ebook_deletion import (
    ConfirmationMismatch,
    EbookBusy,
    EbookNotFound,
    EpubDeleteFailed,
    delete_ebook as delete_ebook_data,
)
from ..library_state import archived_slugs
from ..scheduler import next_run_at
from ..storage_report import ebook_storage_report, purge_raw, purge_translated_mt, remove_epub
from . import settings as settings_routes
from . import library as library_routes
from .sources import _load_validation, _preset_usage

router = APIRouter(prefix="/api/ui")

# Mã trạng thái 1 ký tự dùng trong chuỗi RLE của dải chương.
_NONE = "n"
_RAW = "r"
_MT = "m"
_EDITED = "e"
_SKIP = "s"


def _chapter_state(chapter, stats: dict) -> str:
    if getattr(chapter, "skipped", False):
        return _SKIP
    if not stats.get("has_translated"):
        return _RAW if stats.get("has_raw") else _NONE
    return _EDITED if stats.get("edit_state") in ("edited_ai", "edited_local_mt") else _MT


def _encode_strip(states: list[str]) -> str:
    """Nén dải chương thành run-length: 'e120,m40,n1500'.

    Trạng thái chương gần như luôn liên tục theo lô (crawl/dịch chạy theo
    khoảng), nên RLE giữ nguyên độ chính xác từng chương mà payload vẫn nhỏ
    hơn hai bậc so với gửi cả mảng — quan trọng vì trang Thư viện tải dải của
    mọi ebook cùng lúc.
    """
    if not states:
        return ""
    parts: list[str] = []
    current = states[0]
    count = 1
    for state in states[1:]:
        if state == current:
            count += 1
        else:
            parts.append(f"{current}{count}")
            current = state
            count = 1
    parts.append(f"{current}{count}")
    return ",".join(parts)


def _ebook_summary(
    slug: str,
    cfg,
    *,
    archived: bool,
    in_library: bool,
    created_at: str = "",
    updated_at: str = "",
) -> dict:
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    stats_map = storage.bulk_chapter_stats()
    progress = chapter_progress(storage, manifest, stats_map=stats_map)

    chapters = manifest.chapters if manifest else []
    states = [_chapter_state(ch, stats_map.get(ch.index, {})) for ch in chapters]
    counts = {code: states.count(code) for code in (_NONE, _RAW, _MT, _EDITED, _SKIP)}

    epub_path = Path(cfg.epub_path)
    return {
        "slug": slug,
        "title": cfg.novel.title,
        "author": cfg.novel.author,
        "archived": archived,
        "in_library": in_library,
        "toc_url": cfg.crawl.toc_url,
        "translate_type": cfg.translate.type,
        "created_at": created_at,
        "updated_at": updated_at,
        "total": progress["total"],
        "raw_count": progress["raw_count"],
        "translated_count": progress["translated_count"],
        "strip": _encode_strip(states),
        "counts": counts,
        "epub_exists": epub_path.exists(),
        "epub_size": epub_path.stat().st_size if epub_path.exists() else 0,
    }


def _entries():
    library = deps.library()
    if library.ebooks:
        return list(library.ebooks.items())
    return [("default", None)]


def _log_filter(q: str = "", levels: str = "", source: str = "", older_than_days: float | None = None) -> "LogFilter":
    """Ghép tham số query của SPA thành LogFilter dùng chung cho đọc/xoá/export."""
    from novel2epub.logstore import LogFilter

    # "cũ hơn N ngày" = chỉ giữ dòng có ts > mốc — xoá theo `until`.
    until = None
    if older_than_days is not None:
        until = time.time() - max(0.0, float(older_than_days)) * 86400
    return LogFilter(
        q=q,
        levels=[lv for lv in levels.split(",") if lv],
        loggers=[source] if source else (),
        until=until,
    )


@router.get("/logs")
def logs_tail(
    q: str = "",
    levels: str = "",
    source: str = "",
    limit: int = 300,
    before_id: int | None = None,
):
    """Trang log MỚI NHẤT từ bảng `app_logs` trong `.db`.

    Lọc server-side theo mức/nguồn (logger)/nội dung để UI không phải tải cả
    kho log rồi tự cắt. `before_id` là con trỏ phân trang: trả các hàng cũ hơn
    hàng đó — ổn định dù log mới cứ ghi thêm giữa hai lần tải.
    """
    from novel2epub.db import get_thread_connection
    from novel2epub.logstore import query_logs

    conn = get_thread_connection(deps.DB_PATH)
    return query_logs(conn, _log_filter(q, levels, source), limit=limit, before_id=before_id)


@router.get("/logs/stats")
def logs_stats():
    """Tổng quan nhật ký: tổng số dòng, đếm theo mức, biên thời gian."""
    from novel2epub.db import get_thread_connection
    from novel2epub.logstore import log_stats

    return log_stats(get_thread_connection(deps.DB_PATH))


@router.get("/logs/sources")
def log_sources():
    """Các logger đã ghi log (kèm số dòng) — dropdown 'nguồn' của trang Nhật ký."""
    from novel2epub.db import get_thread_connection
    from novel2epub.logstore import log_sources

    return {"sources": log_sources(get_thread_connection(deps.DB_PATH))}


@router.delete("/logs")
def logs_clear(
    q: str = "",
    levels: str = "",
    source: str = "",
    older_than_days: float | None = None,
):
    """Xoá nhật ký khớp bộ lọc (bỏ trống hết = xoá toàn bộ).

    `older_than_days` giữ lại log mới hơn số ngày chỉ định — dùng cho dọn
    định kỳ mà không mất lịch sử gần. Trả số dòng đã xoá.
    """
    from novel2epub.db import get_thread_connection
    from novel2epub.logstore import clear_logs

    deleted = clear_logs(
        get_thread_connection(deps.DB_PATH),
        _log_filter(q, levels, source, older_than_days=older_than_days),
    )
    return {"ok": True, "deleted": deleted}


@router.get("/logs/export")
def logs_export(
    q: str = "",
    levels: str = "",
    source: str = "",
    limit: int = 50000,
):
    """Tải nhật ký khớp bộ lọc dưới dạng file text (định dạng như app.log cũ)."""
    from fastapi.responses import Response

    from novel2epub.db import get_thread_connection
    from novel2epub.logstore import format_entry, query_logs

    conn = get_thread_connection(deps.DB_PATH)
    data = query_logs(conn, _log_filter(q, levels, source), limit=limit, order="asc")
    body = "\n".join(format_entry(e) for e in data["entries"])
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return Response(
        content=body,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="novel2epub-logs-{stamp}.txt"'},
    )


# Route ĐỘNG `{entry_id}` phải đăng ký SAU CÙNG nhóm /logs/*: FastAPI khớp theo
# thứ tự đăng ký và path param không tự loại trừ "export"/"stats" — đặt trước
# sẽ nuốt các route tĩnh kia thành lỗi 422.
@router.get("/logs/{entry_id}")
def logs_entry(entry_id: int):
    """Chi tiết đầy đủ 1 dòng log — UI rút gọn dòng lỗi, bấm vào mới tải đây."""
    from novel2epub.db import get_thread_connection
    from novel2epub.logstore import get_log_by_id

    entry = get_log_by_id(get_thread_connection(deps.DB_PATH), entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Dòng log không tồn tại.")
    return entry


@router.delete("/logs/{entry_id}")
def logs_delete_entry(entry_id: int):
    """Xoá đúng 1 dòng log (nút Xoá trên từng dòng của trang Nhật ký)."""
    from novel2epub.db import get_thread_connection
    from novel2epub.logstore import delete_log_by_id

    if not delete_log_by_id(get_thread_connection(deps.DB_PATH), entry_id):
        raise HTTPException(status_code=404, detail="Dòng log không tồn tại.")
    return {"ok": True}


@router.get("/library")
def library_list(
    show_archived: bool = False,
    q: str = "",
    sort: str = "title",
    page: int = 0,
    limit: int = 24,
    current_slug: str = "",
):
    """Trang hoá thư viện trước khi dựng các summary tốn chi phí."""
    page = max(page, 0)
    limit = max(1, min(limit, 100))
    q = q.strip()
    if sort not in {
        "title", "title_desc", "created_at", "created_at_asc",
        "updated_at", "updated_at_asc", "recent",
    }:
        raise HTTPException(status_code=400, detail="Kiểu sắp xếp thư viện không hợp lệ.")

    from novel2epub.db import get_thread_connection

    conn = get_thread_connection(deps.DB_PATH)
    where: list[str] = []
    params: list[object] = []
    if not show_archived:
        where.append("archived = 0")
    if q:
        pattern = f"%{q}%"
        where.append(
            "(title LIKE ? COLLATE NOCASE OR author LIKE ? COLLATE NOCASE OR slug LIKE ? COLLATE NOCASE)"
        )
        params.extend([pattern, pattern, pattern])
    where_sql = f" WHERE {' AND '.join(where)}" if where else ""
    order_sql = {
        "title": "title COLLATE NOCASE ASC, slug ASC",
        "title_desc": "title COLLATE NOCASE DESC, slug DESC",
        "created_at": "created_at DESC, title COLLATE NOCASE ASC, slug ASC",
        "created_at_asc": "created_at ASC, title COLLATE NOCASE ASC, slug ASC",
        "updated_at": "updated_at DESC, title COLLATE NOCASE ASC, slug ASC",
        "updated_at_asc": "updated_at ASC, title COLLATE NOCASE ASC, slug ASC",
        # Alias cũ của SPA.
        "recent": "date_added DESC, title COLLATE NOCASE ASC, slug ASC",
    }[sort]
    total = conn.execute(f"SELECT COUNT(*) FROM ebooks{where_sql}", params).fetchone()[0]
    archived_count = conn.execute("SELECT COUNT(*) FROM ebooks WHERE archived = 1").fetchone()[0]
    rows = conn.execute(
        f"SELECT slug, archived, created_at, updated_at FROM ebooks{where_sql} "
        f"ORDER BY {order_sql} LIMIT ? OFFSET ?",
        [*params, limit, page * limit],
    ).fetchall()

    def summary(row):
        slug = row["slug"]
        return _ebook_summary(
            slug,
            deps.resolved_cfg(slug),
            archived=bool(row["archived"]),
            in_library=True,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # Giữ chế độ một ebook mặc định cho cài đặt mới chưa có entry library.
    if total == 0 and not q and not show_archived:
        return {
            "ebooks": [_ebook_summary("default", deps.cfg(), archived=False, in_library=False)],
            "archived_count": archived_count,
            "total": 1,
            "page": 0,
            "limit": limit,
            "current": None,
        }

    current = None
    if current_slug:
        current_row = conn.execute(
            "SELECT slug, archived, created_at, updated_at FROM ebooks WHERE slug = ?",
            (current_slug,),
        ).fetchone()
        if current_row is not None:
            current = summary(current_row)

    return {
        "ebooks": [summary(row) for row in rows],
        "archived_count": archived_count,
        "total": total,
        "page": page,
        "limit": limit,
        "current": current,
    }


def _required_toc_url(payload: dict) -> str:
    toc_url = str(payload.get("toc_url") or "").strip()
    if not toc_url:
        raise HTTPException(status_code=400, detail="Thiếu URL mục lục.")
    return toc_url


@router.post("/library/ebooks/preview")
def library_ebook_preview(payload: dict = Body(...)):
    toc_url = _required_toc_url(payload)
    mode = str(payload.get("scrapling_mode") or "").strip()
    source = str(payload.get("source") or "").strip()
    try:
        data = library_routes._fetch_meta(toc_url, mode, source)
        crawl_cfg, actual_source = library_routes._build_meta_crawl_cfg(toc_url, mode, source)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    data["source"] = actual_source
    data["crawl_preview"] = library_routes._crawl_preview(crawl_cfg)
    return data


@router.post("/library/ebooks")
def library_ebook_create(request: Request, payload: dict = Body(...)):
    toc_url = _required_toc_url(payload)
    source = str(payload.get("source") or "").strip()
    mode = str(payload.get("scrapling_mode") or "").strip()
    title = str(payload.get("title") or "").strip()
    author = str(payload.get("author") or "").strip()
    slug = str(payload.get("slug") or "").strip()
    description = str(payload.get("description") or "")
    cover_url = str(payload.get("cover_url") or "")

    if not title:
        try:
            fetched = library_routes._fetch_meta(toc_url, mode, source)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        title = str(fetched.get("title") or "")
        author = author or str(fetched.get("author") or "")
        slug = slug or str(fetched.get("slug") or "")
        description = description or str(fetched.get("description") or "")
        cover_url = cover_url or str(fetched.get("cover_url") or "")

    created = library_routes._write_new_ebook(
        toc_url, slug, title, author, scrapling_mode=mode, source_name=source,
    )
    library_routes._save_ebook_metadata(created["slug"], description, cover_url)
    if bool(payload.get("fetch_toc")):
        toc_job = library_routes._enqueue_fetch_toc(request, created["slug"])
    else:
        request.app.state.job.queue.restore_ebook(created["slug"])
        toc_job = None
    return {"status": "created", **created, "toc_job": toc_job}


def _bulk_urls(payload: dict) -> list[str]:
    """Chuẩn hoá `toc_urls` từ payload (list hoặc chuỗi nhiều dòng) + giới hạn."""
    raw_urls = payload.get("toc_urls", [])
    if isinstance(raw_urls, str):
        urls = [url.strip() for url in raw_urls.splitlines() if url.strip()]
    elif isinstance(raw_urls, list):
        urls = [str(url).strip() for url in raw_urls if str(url).strip()]
    else:
        raise HTTPException(status_code=400, detail="toc_urls phải là danh sách hoặc chuỗi nhiều dòng.")
    if not urls:
        raise HTTPException(status_code=400, detail="Thiếu URL mục lục.")
    if len(urls) > library_routes.MAX_BULK_URLS:
        raise HTTPException(
            status_code=400,
            detail=f"Tối đa {library_routes.MAX_BULK_URLS} URL mỗi lần nhập.",
        )
    return urls


def _bulk_items(payload: dict) -> dict[str, dict]:
    """Metadata đã duyệt/ sửa từ bước preview, map theo URL. URL không có entry
    (hoặc entry thiếu title) sẽ được fetch tự động như trước."""
    raw_items = payload.get("items")
    if raw_items is None:
        return {}
    if not isinstance(raw_items, list):
        raise HTTPException(status_code=400, detail="items phải là danh sách.")
    items_by_url: dict[str, dict] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if url:
            items_by_url[url] = item
    return items_by_url


@router.post("/library/ebooks/translate-metadata")
def library_ebooks_translate_metadata(payload: dict = Body(...)):
    """JSON API cho SPA: dịch metadata preview (title/author/description).

    Engine mặc định localmt; AI có thể override model từ Dịch chung.
    Trả bản nháp tiếng Việt để duyệt, không lưu gì."""
    engine = str(payload.get("engine") or "localmt").strip().lower()
    model = str(payload.get("model") or "").strip()
    try:
        return library_routes.translate_ebook_metadata(
            deps.cfg(),
            title=str(payload.get("title") or ""),
            author=str(payload.get("author") or ""),
            description=str(payload.get("description") or ""),
            engine=engine,
            model=model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        label = "Local MT" if engine == "localmt" else "AI"
        raise HTTPException(status_code=503, detail=f"{label} dịch metadata lỗi: {exc}") from exc


@router.post("/library/ebooks/bulk-preview")
def library_ebooks_bulk_preview(payload: dict = Body(...)):
    """Preview hàng loạt: fetch metadata từng URL độc lập — 1 URL lỗi không chặn
    các URL còn lại. Cho SPA duyệt/sửa metadata (kèm crawl_preview) trước khi tạo."""
    urls = _bulk_urls(payload)
    results = []
    for url in urls:
        try:
            data = library_routes._fetch_meta(url)
            crawl_cfg, actual_source = library_routes._build_meta_crawl_cfg(url)
            data["source"] = actual_source
            data["crawl_preview"] = library_routes._crawl_preview(crawl_cfg)
            results.append({"url": url, "status": "ok", **data})
        except HTTPException as exc:
            results.append({"url": url, "status": "failed", "reason": str(exc.detail)})
        except Exception as exc:
            results.append({"url": url, "status": "failed", "reason": str(exc)})
    return {"results": results}


@router.post("/library/ebooks/bulk")
def library_ebooks_bulk(request: Request, payload: dict = Body(...)):
    urls = _bulk_urls(payload)
    items_by_url = _bulk_items(payload)
    fetch_toc = bool(payload.get("fetch_toc"))
    results = []
    for url in urls:
        item = items_by_url.get(url)
        try:
            if item and str(item.get("title") or "").strip():
                # Bước preview đã duyệt/sửa/dịch metadata — dùng luôn, không re-fetch.
                fetched = {
                    "slug": str(item.get("slug") or ""),
                    "title": str(item.get("title") or "").strip(),
                    "author": str(item.get("author") or "").strip(),
                    "description": str(item.get("description") or ""),
                    "cover_url": str(item.get("cover_url") or ""),
                }
                source = str(item.get("source") or "").strip()
                mode = str(item.get("scrapling_mode") or "").strip()
            else:
                fetched = library_routes._fetch_meta(url)
                source = ""
                mode = ""
            write_kwargs = {}
            if mode:
                write_kwargs["scrapling_mode"] = mode
            if source:
                write_kwargs["source_name"] = source
            created = library_routes._write_new_ebook(
                url,
                str(fetched.get("slug") or ""),
                str(fetched.get("title") or ""),
                str(fetched.get("author") or ""),
                **write_kwargs,
            )
            library_routes._save_ebook_metadata(
                created["slug"],
                str(fetched.get("description") or ""),
                str(fetched.get("cover_url") or ""),
            )
            if fetch_toc:
                toc_job = library_routes._enqueue_fetch_toc(request, created["slug"])
            else:
                request.app.state.job.queue.restore_ebook(created["slug"])
                toc_job = None
            results.append({"url": url, "status": "created", **created, "toc_job": toc_job})
        except HTTPException as exc:
            status = "skipped-duplicate" if exc.status_code == 409 else "failed"
            results.append({"url": url, "status": status, "reason": str(exc.detail)})
        except Exception as exc:
            results.append({"url": url, "status": "failed", "reason": str(exc)})
    return {"results": results}


@router.post("/library/ebooks/{slug}/delete")
def library_ebook_delete(request: Request, slug: str, confirm_slug: str = Form(...)):
    """Xóa vĩnh viễn ebook: EPUB + mọi dữ liệu trong DB (cascade). Đồng bộ với
    route Jinja2 cùng tên, nhưng trả JSON thay vì redirect."""
    try:
        delete_ebook_data(
            deps.DB_PATH,
            slug,
            confirm_slug,
            lambda: deps.resolved_cfg(slug).epub_path,
            request.app.state.job.queue,
        )
    except ConfirmationMismatch as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EbookNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EbookBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except EpubDeleteFailed as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True}


# ── Upload file (TXT/EPUB) ────────────────────────────────────────────────


@router.post("/library/ebooks/upload/preview")
async def upload_preview(file: UploadFile = File(...)):
    """Parse file upload và trả metadata gợi ý — KHÔNG ghi DB."""
    from novel2epub.upload_parser import ParseError, parse_upload_file, suggest_slug

    if not file.filename:
        raise HTTPException(status_code=400, detail="Thiếu tên file.")
    name_lower = file.filename.lower()
    if not name_lower.endswith(".txt") and not name_lower.endswith(".epub"):
        raise HTTPException(status_code=400, detail="Chỉ chấp nhận file .txt và .epub.")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="File trống.")

    try:
        parsed = parse_upload_file(file.filename, file_bytes)
    except ParseError as e:
        raise HTTPException(status_code=400, detail=str(e))

    slug = suggest_slug(parsed.title, file.filename)
    return {
        "title": parsed.title,
        "author": parsed.author,
        "slug": slug,
        "chapter_count": len(parsed.chapters),
        "chapters_preview": [ch.title for ch in parsed.chapters[:20]],
        "has_cover": parsed.cover_bytes is not None,
        "filename": file.filename,
    }


@router.post("/library/ebooks/upload")
async def upload_create_ebook(
    request: Request,
    file: UploadFile = File(...),
    slug: str = Form(""),
    title: str = Form(""),
    author: str = Form(""),
    description: str = Form(""),
):
    """Tạo ebook mới từ file upload (TXT/EPUB). Tạo chapter raw trong DB."""
    from novel2epub.config_writer import add_ebook
    from novel2epub.storage import Chapter, Manifest
    from novel2epub.upload_parser import ParseError, parse_upload_file, suggest_slug

    if not file.filename:
        raise HTTPException(status_code=400, detail="Thiếu tên file.")
    name_lower = file.filename.lower()
    if not name_lower.endswith(".txt") and not name_lower.endswith(".epub"):
        raise HTTPException(status_code=400, detail="Chỉ chấp nhận file .txt và .epub.")
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="File trống.")

    try:
        parsed = parse_upload_file(file.filename, file_bytes)
    except ParseError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Resolve slug
    if not slug:
        slug = suggest_slug(parsed.title, file.filename)
    if not slug:
        slug = library_routes.vn_slugify(title.strip() or parsed.title or file.filename)
    if not slug or not library_routes._has_latin(slug):
        raise HTTPException(status_code=400, detail="Slug không hợp lệ: cần ít nhất 1 ký tự latin.")
    lib = deps.library()
    if slug in lib.ebooks:
        raise HTTPException(status_code=409, detail=f"Ebook '{slug}' đã tồn tại.")

    # Dùng title từ form nếu có, fallback parsed
    final_title = title.strip() or parsed.title
    final_author = author.strip() or parsed.author

    # Ghi ebook vào config — toc_url rỗng vì từ upload
    add_ebook(
        deps.WORKSPACE_PATH,
        slug,
        title=final_title,
        author=final_author,
        toc_url="",
    )
    library_routes._save_ebook_metadata(slug, description=description.strip())

    # Ghi raw chapters + cover vào Storage
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    storage.ensure_dirs()

    manifest = storage.load_manifest()
    if manifest is None:
        manifest = Manifest(
            slug=slug,
            source_url="",
            title=final_title,
            author=final_author,
        )

    # Ghi cover nếu có
    if parsed.cover_bytes and parsed.cover_ext:
        cover_file = storage.write_cover(parsed.cover_bytes, parsed.cover_ext)
        manifest.cover_file = cover_file

    # Ghi chapters — assign index tuần tự nếu index None
    next_idx = 1
    chapters_list = list(manifest.chapters) if manifest.chapters else []
    existing_indexes = {ch.index for ch in chapters_list}

    for ch_parsed in parsed.chapters:
        idx = ch_parsed.index
        if idx is None:
            while next_idx in existing_indexes:
                next_idx += 1
            idx = next_idx
            next_idx += 1
        elif idx in existing_indexes:
            # Index đã tồn tại → skip
            while next_idx in existing_indexes:
                next_idx += 1
            next_idx = max(next_idx, idx + 1)
            continue
        else:
            next_idx = max(next_idx, idx + 1)

        ch = Chapter(index=idx, url="", title=ch_parsed.title)
        storage.write_raw(ch, ch_parsed.content)
        chapters_list.append(ch)
        existing_indexes.add(idx)

    # Sort chapters theo index
    chapters_list.sort(key=lambda c: c.index)
    manifest.chapters = chapters_list

    # Save manifest (full list, KHÔNG xóa chapter cũ)
    storage.save_manifest(manifest)

    # Restore ebook vào queue
    request.app.state.job.queue.restore_ebook(slug)

    return {"slug": slug, "title": final_title, "chapter_count": len(chapters_list)}


@router.post("/ebooks/{slug}/chapters/upload")
async def upload_append_chapters(slug: str, file: UploadFile = File(...)):
    """Bổ sung chương từ file TXT/EPUB vào ebook đã có.

    Đối chiếu theo index rút từ tiêu đề: index đã có raw → bỏ qua (không
    ghi đè); chưa có → ghi vào đúng index đó. Không rút được số → gán
    max_existing+1, +2... Luôn save_manifest với FULL chapter list để không
    xóa nhầm chương cũ.
    """
    from novel2epub.storage import Chapter
    from novel2epub.upload_parser import ParseError, parse_upload_file

    lib = deps.library()
    if slug not in lib.ebooks:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy ebook '{slug}'.")
    if not file.filename:
        raise HTTPException(status_code=400, detail="Thiếu tên file.")
    name_lower = file.filename.lower()
    if not name_lower.endswith(".txt") and not name_lower.endswith(".epub"):
        raise HTTPException(status_code=400, detail="Chỉ chấp nhận file .txt và .epub.")
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="File trống.")

    try:
        parsed = parse_upload_file(file.filename, file_bytes)
    except ParseError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not parsed.chapters:
        raise HTTPException(status_code=400, detail="File không chứa chương nào.")

    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có mục lục.")

    raw_indexes = {ch.index for ch in manifest.chapters if storage.has_raw(ch)}
    used_indexes = {ch.index for ch in manifest.chapters}
    next_idx = max(used_indexes) + 1 if used_indexes else 1

    added = 0
    skipped = 0
    added_indexes: list[int] = []
    skipped_titles: list[str] = []
    new_chapters = list(manifest.chapters)

    for ch_parsed in parsed.chapters:
        target = ch_parsed.index
        if target is None:
            while next_idx in used_indexes:
                next_idx += 1
            target = next_idx
            next_idx += 1
        elif target in raw_indexes:
            # Index đã có raw (cũ hoặc vừa thêm từ chính file này) → bỏ qua,
            # không ghi đè.
            skipped += 1
            skipped_titles.append(ch_parsed.title)
            continue
        elif target in used_indexes:
            # Index tồn tại trong manifest nhưng chưa có raw (lỗ hổng crawl) →
            # lấp đúng index đó.
            pass
        else:
            if target >= next_idx:
                next_idx = target + 1

        existing = next((c for c in new_chapters if c.index == target), None)
        if existing is not None:
            # Lấp lỗ hổng: giữ nguyên row, chỉ cập nhật tiêu đề nếu trống
            if not existing.title:
                existing.title = ch_parsed.title
        else:
            new_chapters.append(Chapter(index=target, url="", title=ch_parsed.title))
        storage.write_raw(Chapter(index=target, url="", title=ch_parsed.title),
                           ch_parsed.content)
        used_indexes.add(target)
        raw_indexes.add(target)
        added += 1
        added_indexes.append(target)

    # EPUB kèm bìa mà ebook chưa có → giữ bìa
    if parsed.cover_bytes and parsed.cover_ext and not manifest.cover_file:
        manifest.cover_file = storage.write_cover(parsed.cover_bytes, parsed.cover_ext)

    new_chapters.sort(key=lambda c: c.index)
    manifest.chapters = new_chapters
    storage.save_manifest(manifest)

    return {
        "added": added,
        "skipped": skipped,
        "total": len(new_chapters),
        "added_indexes": added_indexes,
        "skipped_titles": skipped_titles[:20],
    }


@router.get("/ebooks/{slug}")
def ebook_detail(request: Request, slug: str):
    """Tổng quan một truyện: tiến độ, EPUB, chi phí, chương có vấn đề.

    KHÔNG kèm danh sách chương — bảng chương phân trang riêng qua
    `/chapters` để trang không phải tải lại vài nghìn dòng mỗi lần đổi bộ lọc.
    """
    from novel2epub.toc import crawl_problem_indexes

    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    stats_map = storage.bulk_chapter_stats()
    progress = chapter_progress(storage, manifest, stats_map=stats_map)

    chapters = manifest.chapters if manifest else []
    states = [_chapter_state(ch, stats_map.get(ch.index, {})) for ch in chapters]
    epub_path = Path(cfg.epub_path)

    return {
        "slug": slug,
        "title": cfg.novel.title,
        "author": cfg.novel.author,
        "language": cfg.novel.language,
        "series": cfg.novel.series,
        "toc_url": cfg.crawl.toc_url,
        "crawl_mode": cfg.crawl.scrapling.mode,
        "translate_type": cfg.translate.type,
        "translate_model": cfg.translate.model or cfg.translate.openai.model,
        "has_manifest": manifest is not None,
        "total": progress["total"],
        "raw_count": progress["raw_count"],
        "translated_count": progress["translated_count"],
        "strip": _encode_strip(states),
        "counts": {code: states.count(code) for code in (_NONE, _RAW, _MT, _EDITED, _SKIP)},
        "crawl_problems": crawl_problem_indexes(chapters, storage, stats_map=stats_map)
        if manifest
        else [],
        "epub_exists": epub_path.exists(),
        "epub_path": str(epub_path),
        "epub_size": epub_path.stat().st_size if epub_path.exists() else 0,
        "cost_summary": read_cost_summary(storage),
        "reader_configured": cfg.reader.configured,
        "active_jobs": [
            job
            for job in request.app.state.job.queue.snapshot()["running"]
            if job.get("ebook") == slug
        ],
    }


@router.get("/ebooks/{slug}/chapters")
def ebook_chapters(
    slug: str,
    sort: str = "source",
    direction: str = "asc",
    search: str = "",
    filter_raw: str = "any",
    filter_translated: str = "any",
    filter_missing: str = "any",
    filter_skipped: str = "no",
    filter_local_mt: str = "any",
    filter_ai: str = "any",
    filter_title_error: str = "any",
    offset: int = 0,
    limit: int = 100,
):
    """Bảng chương đã lọc/sắp xếp, phân trang phía server.

    Lọc và sắp xếp uỷ quyền cho `apply_chapter_query` — cùng hàm mà trang
    Jinja2 và các thao tác hàng loạt dùng, nên "chọn tất cả kết quả đang lọc"
    ở giao diện mới trỏ đúng tập chương mà backend sẽ xử lý.
    """
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        return {"rows": [], "total": 0, "matched": 0, "indexes": []}

    stats_map = storage.bulk_chapter_stats()
    rows = apply_chapter_query(
        chapter_rows(manifest.chapters, storage, stats_map=stats_map),
        sort=sort,
        direction=direction,
        search=search,
        filter_raw=filter_raw,
        filter_translated=filter_translated,
        filter_missing=filter_missing,
        filter_skipped=filter_skipped,
        filter_local_mt=filter_local_mt,
        filter_ai=filter_ai,
        filter_title_error=filter_title_error,
    )

    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    page = rows[offset : offset + limit]

    return {
        "rows": [dataclasses.asdict(row) for row in page],
        "total": len(manifest.chapters),
        "matched": len(rows),
        # Toàn bộ index khớp bộ lọc, để nút "chọn tất cả" không phải tải hết
        # dữ liệu từng dòng chỉ để biết mình đang chọn những chương nào.
        "indexes": [row.index for row in rows],
    }


@router.get("/ebooks/{slug}/chapters/{index}")
def ebook_chapter_compare(slug: str, index: int):
    """Toàn bộ dữ liệu một chương cho trang Chương của SPA.

    Gộp cả ba thứ trang đó cần để chỉ tốn MỘT request: nội dung đọc/sửa
    (`translated_paras`), khung đối chiếu 3 cột (`paragraphs`), và trạng thái
    nhánh + bản nháp AI.

    Cả `translated_paras` lẫn `paragraphs` đều chia theo TỪNG DÒNG không rỗng
    (`notes.split_paras` / `novel2epub.blocks.split_paragraphs`) nên chỉ số hàng
    của khung đối chiếu trùng đúng chỉ số đoạn mà `para/save` và ghi chú dùng
    (xem docs/architecture.md).
    """
    from novel2epub.notes import split_paras
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có mục lục.")

    chapter = next((c for c in manifest.chapters if c.index == index), None)
    if chapter is None:
        raise HTTPException(status_code=404, detail=f"Không có chương {index}.")

    raw = storage.read_raw(chapter) if storage.has_raw(chapter) else ""
    active = storage.active_branch(chapter)
    translated = storage.read_branch_text(chapter, active) if storage.has_branch_text(chapter, active) else ""
    # Snapshot và workspace phải thuộc cùng nhánh active; nếu dữ liệu legacy
    # chưa có snapshot thì degrade về workspace hiện tại.
    translated_mt = storage.read_branch_mt_snapshot(chapter, active) or translated
    meta = storage.read_meta(chapter) if storage.has_meta(chapter) else {}
    storage.expire_stale_revisions(chapter)

    indexes = [c.index for c in manifest.chapters]
    position = indexes.index(index)

    ai_revisions = storage.list_ai_revisions(chapter)
    # Candidate (pending) mang nội dung có thể áp; report/suggestion mang JSON.
    for item in ai_revisions:
        if item["status"] == "pending":
            item["payload_preview"] = (item.get("payload_json") or "")[:2000]

    branches = {
        branch: {
            "label": revisions.branch_label(branch),
            "has_text": storage.has_branch_text(chapter, branch),
            "revision": storage.read_branch_revision(chapter, branch),
            "title": storage.read_branch_title(chapter, branch) or chapter.title,
            "active": branch == active,
        }
        for branch in revisions.BRANCHES
    }

    # ── Bốn nguồn của khung đối chiếu 4 cột (additive với các field legacy) ──
    # `ai_edit` là nhánh `local_mt` sau AI biên tập; `local_mt` là baseline dịch
    # máy (snapshot nếu có, fallback bản hiện tại) để so phần AI đã sửa.
    local_mt_text = storage.read_branch_text(chapter, revisions.BRANCH_LOCAL_MT)
    local_mt_has = storage.has_branch_text(chapter, revisions.BRANCH_LOCAL_MT)
    local_mt_baseline = storage.read_branch_mt_snapshot(chapter, revisions.BRANCH_LOCAL_MT) or local_mt_text
    ai_text = storage.read_branch_text(chapter, revisions.BRANCH_AI)
    ai_has = storage.has_branch_text(chapter, revisions.BRANCH_AI)
    ai_baseline = storage.read_branch_mt_snapshot(chapter, revisions.BRANCH_AI) or ai_text
    local_mt_ai_edited = meta.get("local_mt_ai_edited") or None

    def _source_status(has_text: bool, baseline: str) -> str:
        if has_text:
            return "ready"
        return "partial" if baseline.strip() else "missing"

    sources = {
        "raw": {
            "status": "ready" if raw.strip() else "missing",
            "text": raw,
            "title": None,
            "revision": None,
            "character_count": len(raw),
            "edited": None,
            "engine": None,
            "model": None,
            "updated_at": None,
        },
        "local_mt": {
            "status": _source_status(local_mt_has, local_mt_baseline),
            "text": local_mt_baseline,
            "title": storage.read_branch_title(chapter, revisions.BRANCH_LOCAL_MT) or chapter.title,
            "revision": storage.read_branch_revision(chapter, revisions.BRANCH_LOCAL_MT),
            "character_count": len(local_mt_text),
            "edited": None,
            "engine": None,
            "model": None,
            "updated_at": None,
        },
        "ai": {
            "status": _source_status(ai_has, ai_baseline),
            "text": ai_text,
            "title": storage.read_branch_title(chapter, revisions.BRANCH_AI) or chapter.title,
            "revision": storage.read_branch_revision(chapter, revisions.BRANCH_AI),
            "character_count": len(ai_text),
            "edited": meta.get("before_rewrite") or None,
            "engine": None,
            "model": None,
            "updated_at": None,
        },
        "ai_edit": {
            "status": "ready" if (local_mt_has and local_mt_ai_edited) else "missing",
            "text": local_mt_text,
            "title": storage.read_branch_title(chapter, revisions.BRANCH_LOCAL_MT) or chapter.title,
            "revision": storage.read_branch_revision(chapter, revisions.BRANCH_LOCAL_MT),
            "character_count": len(local_mt_text),
            "edited": local_mt_ai_edited,
            "engine": (local_mt_ai_edited or {}).get("engine") if local_mt_ai_edited else None,
            "model": (local_mt_ai_edited or {}).get("model") if local_mt_ai_edited else None,
            "updated_at": (local_mt_ai_edited or {}).get("generated_at") if local_mt_ai_edited else None,
        },
    }

    return {
        "index": chapter.index,
        "title": storage.read_active_branch_title(chapter),
        "title_zh": storage.read_branch_title_zh(chapter, active) or getattr(chapter, "title_zh", "") or "",
        "url": chapter.url,
        "skipped": bool(getattr(chapter, "skipped", False)),
        "has_raw": bool(raw),
        "has_translated": bool(translated),
        "has_mt_snapshot": bool(storage.read_branch_mt_snapshot(chapter, active)),
        "revision": storage.read_branch_revision(chapter, active),
        "active_branch": active,
        "branches": branches,
        "ai_revisions": ai_revisions,
        "raw": raw,
        "translated": translated,
        "translated_mt": translated_mt,
        "sources": sources,
        # Chia theo DÒNG — khớp `para/save` và ghi chú.
        "translated_paras": split_paras(translated) if translated else [],
        # Chia theo KHỐI — chỉ để gióng các cột đối chiếu. Hàng giữ cả 4 nguồn
        # mới (`raw`/`local_mt`/`ai`/`ai_edit`) lẫn 2 field legacy (`mt`/`edited`
        # = baseline dịch máy và bản hiện tại của nhánh `local_mt`).
        "paragraphs": [
            {"raw": r, "local_mt": m, "ai": a, "ai_edit": e, "mt": m, "edited": e}
            for r, m, a, e in align_sources(raw, local_mt_baseline, ai_text, local_mt_text)
        ],
        "raw_char_count": len(raw),
        "word_count": count_words(translated),
        "meta": meta,
        "prev_index": indexes[position - 1] if position > 0 else None,
        "next_index": indexes[position + 1] if position + 1 < len(indexes) else None,
        "position": position + 1,
        "chapter_total": len(indexes),
    }


@router.post("/ebooks/{slug}/chapters/{index}/translated")
def ebook_chapter_save(slug: str, index: int, payload: dict = Body(...)):
    """Ghi TOÀN VĂN bản dịch, giữ nguyên từng ký tự xuống dòng.

    Cố ý không nhận chỉ số đoạn: khung so sánh 3 cột chia theo DÒNG TRỐNG và
    gộp các dòng trong một khối lại, còn `notes.split_paras` — thứ mà
    `para/save` đánh số theo — chia theo TỪNG DÒNG. Một khối "lời dẫn + lời
    thoại" là 1 hàng ở khung so sánh nhưng là 2 đoạn với `para/save`, nên lấy
    chỉ số hàng gọi sang đó sẽ ghi đè nhầm dòng mà không báo lỗi. Sửa theo
    từng đoạn phải đi qua Reader, nơi dùng đúng cách đánh số ấy.
    """
    translated = payload.get("translated")
    if not isinstance(translated, str):
        raise HTTPException(status_code=400, detail="Thiếu trường 'translated'.")

    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có mục lục.")

    chapter = next((c for c in manifest.chapters if c.index == index), None)
    if chapter is None:
        raise HTTPException(status_code=404, detail=f"Không có chương {index}.")

    # Optimistic lock: nếu client gửi `expected_rev` (bản dịch nó đang xem), chỉ
    # ghi khi chưa ai sửa; lệch → 409, không ghi đè mù. Không gửi = ghi thẳng
    # (luồng cũ, không ai xung đột khi editor đang offline).
    branch = storage.active_branch(chapter)
    expected_rev = payload.get("expected_rev")
    if isinstance(expected_rev, int):
        if not storage.compare_and_swap_branch(
            chapter, branch, expected_rev=expected_rev, new_text=translated
        ):
            raise HTTPException(
                status_code=409,
                detail="Bản dịch đã thay đổi sau khi mở trang — tải lại trước khi ghi.",
            )
    else:
        storage.write_branch_text(chapter, branch, translated)
    return {
        "saved": True,
        "branch": branch,
        "word_count": count_words(translated),
        "revision": storage.read_branch_revision(chapter, branch),
    }


@router.post("/ebooks/{slug}/chapters/{index}/raw")
def ebook_chapter_save_raw(slug: str, index: int, payload: dict = Body(...)):
    """Ghi TOÀN VĂN bản gốc của một chương.

    Nhận JSON `{raw: string, expected_raw?: string}`. Khi client gửi
    `expected_raw` (bản gốc lúc mở trang), chỉ ghi khi bản gốc hiện tại
    vẫn khớp — lệch → 409, chống ghi đè do crawl lại hay sửa ở tab khác.
    Không gửi `expected_raw` thì ghi thẳng (tương thích luồng cũ).
    """
    raw = payload.get("raw")
    if not isinstance(raw, str):
        raise HTTPException(status_code=400, detail="Thiếu trường 'raw'.")

    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có mục lục.")
    chapter = next((c for c in manifest.chapters if c.index == index), None)
    if chapter is None:
        raise HTTPException(status_code=404, detail=f"Không có chương {index}.")

    expected_raw = payload.get("expected_raw")
    if isinstance(expected_raw, str):
        current = storage.read_raw(chapter) if storage.has_raw(chapter) else ""
        if current.replace("\r\n", "\n") != expected_raw.replace("\r\n", "\n"):
            raise HTTPException(status_code=409, detail="Bản gốc đã thay đổi — tải lại trang trước khi ghi.")
        # Chương chưa từng crawl: raw_text IS NULL nên write_raw_conditional
        # (WHERE raw_text IS NOT NULL) sẽ luôn fail — ghi thẳng trong trường hợp
        # expected rỗng này để cho phép tạo bản gốc thủ công.
        if not storage.has_raw(chapter) and expected_raw.strip() == "":
            storage.write_raw(chapter, raw)
        elif not storage.write_raw_conditional(chapter, expected_raw, raw):
            raise HTTPException(status_code=409, detail="Bản gốc đã thay đổi — tải lại trang trước khi ghi.")
    else:
        storage.write_raw(chapter, raw)
    return {"saved": True, "raw_char_count": len(raw)}


@router.post("/ebooks/{slug}/chapters/{index}/compare/block")
def ebook_chapter_compare_block(slug: str, index: int, payload: dict = Body(...)):
    """Sửa/xóa ĐOẠN trong khung đối chiếu 3 cột (bản gốc | dịch máy | bản hiện tại).

    `block` là chỉ số ĐOẠN = TỪNG DÒNG không rỗng (`align_paragraphs` /
    `novel2epub.blocks.split_paragraphs`), trùng với chỉ số của chế độ Đọc và
    `para/save` — không còn là chỉ số khối cách dòng trống.

    Body JSON:
    - `op`:
      - `"edit_raw"` — sửa cột Bản gốc. `raw_expected` = nội dung đoạn raw lúc
        preview (raw không revision nên đây là khóa chống stale), `new_text`.
      - `"edit_translated"` — sửa cột Bản hiện tại. `block_expected` = nội dung
        đoạn hiện tại, `new_text`, `revision` = revision nhánh active (CAS).
      - `"delete"` — xóa đoạn raw + đoạn MT + đoạn bản dịch active ĐỒNG BỘ
        trong MỘT transaction (xem `Storage.delete_aligned_paragraph`). Cần
        `raw_expected` + `revision`.
    - `block`: index đoạn trong khung đối chiếu (`align_paragraphs`).

    `edit_raw`/`edit_translated` không đụng nhánh/khối khác: sửa raw chỉ sửa raw,
    sửa bản hiện tại chỉ sửa bản dịch của nhánh active (MT snapshot giữ nguyên).
    Dịch máy chỉ đọc — không có op nào sửa trực tiếp cột MT.

    Trả `{"saved"/"deleted", "revision", "reason"}` — `reason` rỗng khi thành
    công; 409 khi stale/conflict (không ghi gì).
    """
    from novel2epub.blocks import replace_paragraph, split_paragraphs

    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có mục lục.")
    chapter = next((c for c in manifest.chapters if c.index == index), None)
    if chapter is None:
        raise HTTPException(status_code=404, detail=f"Không có chương {index}.")

    op = payload.get("op")
    block = payload.get("block")
    if op not in ("edit_raw", "edit_translated", "delete"):
        raise HTTPException(status_code=400, detail="op phải là edit_raw/edit_translated/delete.")
    if not isinstance(block, int) or block < 0:
        raise HTTPException(status_code=400, detail="block phải là số nguyên ≥ 0.")

    branch = payload.get("branch", storage.active_branch(chapter))
    if branch not in revisions.BRANCHES:
        raise HTTPException(status_code=400, detail="branch phải là ai hoặc local_mt.")
    revision = payload.get("revision")
    if not isinstance(revision, int):
        raise HTTPException(status_code=400, detail="Thiếu 'revision' (revision nhánh đang hoạt động).")

    if op == "delete":
        raw_expected = payload.get("raw_expected")
        if not isinstance(raw_expected, str):
            raise HTTPException(status_code=400, detail="Thiếu 'raw_expected' cho thao tác xóa.")
        result = storage.delete_aligned_paragraph(
            chapter,
            branch=branch,
            raw_expected=raw_expected,
            block_index=block,
            expected_rev=revision,
        )
        if not result["deleted"]:
            raise HTTPException(status_code=409, detail=result["reason"])
        return {
            "deleted": True,
            "revision": result["revision"],
            "reason": "",
            "blocks_removed": ["raw", "mt", "translated"],
        }

    new_text = payload.get("new_text")
    if not isinstance(new_text, str):
        raise HTTPException(status_code=400, detail="Thiếu 'new_text'.")

    if op == "edit_raw":
        raw_expected = payload.get("raw_expected")
        if not isinstance(raw_expected, str):
            raise HTTPException(status_code=400, detail="Thiếu 'raw_expected'.")
        if not storage.has_raw(chapter):
            raise HTTPException(status_code=404, detail="Chương chưa có bản gốc.")
        current_raw = storage.read_raw(chapter)
        new_raw, reason = replace_paragraph(current_raw, block, raw_expected, new_text)
        if reason:
            raise HTTPException(status_code=409, detail=reason)
        if not storage.write_raw_conditional(chapter, current_raw, new_raw):
            raise HTTPException(
                status_code=409, detail="Bản gốc đã thay đổi — tải lại trang."
            )
        return {"saved": True, "revision": revision, "reason": ""}

    # op == "edit_translated"
    block_expected = payload.get("block_expected")
    if not isinstance(block_expected, str):
        raise HTTPException(status_code=400, detail="Thiếu 'block_expected'.")
    if not storage.has_branch_text(chapter, branch):
        raise HTTPException(status_code=404, detail="Chương chưa có bản dịch.")
    current = storage.read_branch_text(chapter, branch)
    new_block, reason = replace_paragraph(current, block, block_expected, new_text)
    if reason:
        # Xóa một đoạn làm cột dịch ngắn hơn cột gốc, nên chỉ số hàng đối chiếu
        # của các đoạn phía sau không còn là chỉ số trong riêng nhánh dịch. Khi
        # nội dung mong đợi là duy nhất, dùng chính khóa stale đó để tìm lại đúng
        # đoạn; nội dung trùng vẫn bị từ chối để không sửa nhầm.
        translated_paras = split_paragraphs(current)
        matches = [
            i for i, paragraph in enumerate(translated_paras)
            if paragraph.strip() == block_expected.strip()
        ]
        if len(matches) == 1:
            new_block, reason = replace_paragraph(
                current, matches[0], block_expected, new_text
            )
    if reason:
        raise HTTPException(status_code=409, detail=reason)
    if not storage.compare_and_swap_branch(
        chapter, branch, expected_rev=revision, new_text=new_block
    ):
        raise HTTPException(
            status_code=409,
            detail="Bản dịch đã thay đổi — tải lại trang.",
        )
    return {"saved": True, "revision": storage.read_branch_revision(chapter, branch), "reason": ""}


@router.post("/ebooks/{slug}/chapters/{index}/ai/rewrite/confirm")
def webui_ai_rewrite_confirm(slug: str, index: int, payload: dict = Body(...)):
    """Chấp nhận một candidate (bản nháp AI) — optimistic lock, JSON.

    Bản nháp không bao giờ tự active: chỉ đây mới đưa nó vào bản dịch hoạt
    động. Snapshot lệch/hết hạn → 409 kèm lý do, không ghi đè."""
    from novel2epub.pipeline import step_apply_ai_revision

    revision_id = payload.get("revision_id")
    if not isinstance(revision_id, int):
        raise HTTPException(status_code=400, detail="Thiếu 'revision_id'.")
    cfg = deps.resolved_cfg(slug)
    try:
        step_apply_ai_revision(cfg, lambda m: None, revision_id=revision_id)
    except revisions.RevisionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    chapter = next((c for c in storage.load_manifest().chapters if c.index == index), None)
    return {
        "applied": True,
        "revision": storage.read_revision(chapter) if chapter else None,
        "revision_id": revision_id,
    }


@router.post("/ebooks/{slug}/chapters/{index}/ai/rewrite/discard")
def webui_ai_rewrite_discard(slug: str, index: int, payload: dict = Body(...)):
    """Bỏ một candidate — không đụng bản dịch hoạt động."""
    from novel2epub.pipeline import step_discard_ai_revision

    revision_id = payload.get("revision_id")
    if not isinstance(revision_id, int):
        raise HTTPException(status_code=400, detail="Thiếu 'revision_id'.")
    cfg = deps.resolved_cfg(slug)
    ok = step_discard_ai_revision(cfg, lambda m: None, revision_id=revision_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản nháp.")
    return {"discarded": True, "revision_id": revision_id}


@router.get("/ebooks/{slug}/settings")
def ebook_settings(slug: str):
    """Cấu hình hiệu lực của một truyện, phẳng theo ĐÚNG tên trường của form.

    Khoá ở đây khớp 1-1 với tham số `Form(...)` của các endpoint lưu trong
    `app/routes/settings.py` (`save_novel`, `save_source`, ...). Cố ý không
    đặt tên riêng cho API: giao diện mới POST thẳng vào các endpoint cũ, nên
    lệch tên là mất dữ liệu lúc lưu mà không có lỗi nào báo.
    """
    from novel2epub.sources import detect_preset, load_presets

    from .settings import GENRE_PRESETS, _read_crawl_overrides

    cfg = deps.resolved_cfg(slug)
    crawl, sc, tr, oa, ai, rd = (
        cfg.crawl,
        cfg.crawl.scrapling,
        cfg.translate,
        cfg.translate.openai,
        cfg.ai.openai,
        cfg.reader,
    )

    presets = load_presets(deps.SOURCES_PATH)
    source_name = getattr(cfg, "source", "") or ""
    source_detected = False
    if not source_name and crawl.toc_url:
        source_name = detect_preset(crawl.toc_url, presets) or ""
        source_detected = bool(source_name)

    return {
        "slug": slug,
        "novel": {
            "title": cfg.novel.title,
            "author": cfg.novel.author,
            "description": cfg.novel.description,
            "language": cfg.novel.language,
            "publisher": cfg.novel.publisher,
            "pubdate": cfg.novel.pubdate,
            "subjects": "\n".join(cfg.novel.subjects),
            "series": cfg.novel.series,
            "series_index": cfg.novel.series_index,
            "identifier": cfg.novel.identifier,
            "cover_url": cfg.novel.cover_url,
        },
        "source": {
            "toc_url": crawl.toc_url,
            "chapter_link_pattern": crawl.chapter_link_pattern,
            "cover_url_pattern": crawl.cover_url_pattern,
            "max_chapters": crawl.max_chapters,
            "delay_seconds": crawl.delay_seconds,
            "max_workers": crawl.max_workers,
            "concurrency_cap": crawl.concurrency_cap,
            "content_selector": crawl.content_selector,
            "scrapling_mode": sc.mode,
            "solve_cloudflare": sc.solve_cloudflare,
            "network_idle": sc.network_idle,
            "impersonate": sc.impersonate,
            "proxy": sc.proxy,
            "dns_over_https": sc.dns_over_https,
            "next_page_selector": crawl.next_page_selector,
            "next_page_url_pattern": crawl.next_page_url_pattern,
            "max_pages_per_chapter": crawl.max_pages_per_chapter,
            "toc_next_page_selector": crawl.toc_next_page_selector,
            "toc_max_pages": crawl.toc_max_pages,
            "retry_attempts": crawl.retry.attempts,
            "retry_delay_seconds": crawl.retry.delay_seconds,
            "retry_backoff": crawl.retry.backoff,
            "retry_max_delay_seconds": crawl.retry.max_delay_seconds,
            "retry_respect_retry_after": crawl.retry.respect_retry_after,
            "headless": crawl.headless,
            "strip_patterns": "\n".join(crawl.strip_patterns),
        },
        "translate": {
            "type": tr.type,
            "preset": tr.preset,
            "profile": tr.profile,
            "base_url": oa.base_url,
            "api_key": "",
            "model": oa.model,
            "timeout_seconds": oa.timeout_seconds,
            "temperature": oa.temperature,
            "prompt_template": oa.prompt_template,
            "title_prompt_template": oa.title_prompt_template,
            "genre": tr.genre,
            "tone": tr.style.tone,
            "pronoun_policy": tr.style.pronoun_policy,
            "title_mode": tr.style.title_mode,
            "han_viet_level": tr.style.han_viet_level,
            "keep_paragraphs": tr.style.keep_paragraphs,
            "delay_seconds": tr.delay_seconds,
            "max_workers": tr.max_workers,
            "source_language": tr.source_language,
            "target_language": tr.target_language,
            "local_model": tr.model,
            "retry_attempts": tr.retry.attempts,
            "retry_delay_seconds": tr.retry.delay_seconds,
            "chunk_max_chars": tr.chunk.max_chars,
            "chunk_overlap_paragraphs": tr.chunk.overlap_paragraphs,
            "hachimimt_model_key": tr.hachimimt.model_key,
            "hachimimt_backend": tr.hachimimt.backend,
            "hachimimt_beam_size": tr.hachimimt.beam_size,
            "hachimimt_chunk_mode": tr.hachimimt.chunk_mode,
            "batch_size": tr.batch_size,
            "prompt_max_chars": tr.prompt_max_chars,
            "auto_glossary": tr.auto_glossary,
            "use_idioms": tr.use_idioms,
            "ai_glossary_analysis": tr.ai_glossary_analysis,
            "auto_cleanup_han": tr.auto_cleanup_han,
            "cleanup_han_engine": tr.cleanup_han.engine,
            "cleanup_han_max_chars": tr.cleanup_han.max_chars,
            "cleanup_han_retries": tr.cleanup_han.retries,
        },
        "ai": {
            "base_url": ai.base_url,
            "api_key": "",
            "api_key_configured": bool(ai.api_key),
            "timeout_seconds": ai.timeout_seconds,
            "temperature": ai.temperature,
        },
        "global_ai": settings_routes._global_ai_payload(),
        "opds": {
            "token": "",
            "token_configured": bool(cfg.api.token),
            "cors_origins": "\n".join(cfg.api.cors_origins),
            "auto_build": cfg.api.auto_build,
        },
        "reader": {
            "url": rd.url,
            "service_key": rd.service_key,
            "timeout_seconds": rd.timeout_seconds,
            "batch_size": rd.batch_size,
            "push_anchors": rd.push_anchors,
            "reader_slug": rd.slug,
            "free_chapters": rd.free_chapters,
            "published": rd.published,
        },
        "output": {
            "data_dir": cfg.output.data_dir,
            "epub_path": cfg.output.epub_path,
            "crawl_max_workers": cfg.queue.crawl_workers,
            "translate_max_workers": cfg.queue.translate_workers,
        },
        "meta": {
            "source_name": source_name,
            "source_detected": source_detected,
            "source_presets": sorted(presets),
            # Trường ebook đã ghi đè lên preset — giao diện đánh dấu để người
            # dùng biết cái nào đang lệch khỏi nguồn chung.
            "overridden_fields": sorted(_read_crawl_overrides(deps.DB_PATH, slug))
            if source_name
            else [],
            "genres": [{"value": k, "label": v.label or k} for k, v in GENRE_PRESETS.items()],
        },
    }


def _ebook_model_overrides(slug: str) -> dict:
    from novel2epub.db import get_thread_connection

    conn = get_thread_connection(Path(deps.DB_PATH).resolve())
    row = conn.execute(
        "SELECT translate_overrides_json, ai_overrides_json FROM ebooks WHERE slug = ?",
        (slug,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Không có ebook {slug!r}.")
    translate = json.loads(row["translate_overrides_json"] or "{}")
    assistant = json.loads(row["ai_overrides_json"] or "{}")
    return {
        "translation_model": str(translate.get("translation_model") or ""),
        "assistant_model": str(assistant.get("assistant_model") or ""),
    }


@router.get("/ebooks/{slug}/settings/model-overrides")
def ebook_model_overrides(slug: str):
    return _ebook_model_overrides(slug)


@router.post("/ebooks/{slug}/settings/model-overrides")
def ebook_model_overrides_save(slug: str, payload: dict = Body(...)):
    from novel2epub.db import get_thread_connection

    translation_model = str(payload.get("translation_model") or "").strip()
    assistant_model = str(payload.get("assistant_model") or "").strip()
    conn = get_thread_connection(Path(deps.DB_PATH).resolve())
    row = conn.execute(
        "SELECT translate_overrides_json, ai_overrides_json FROM ebooks WHERE slug = ?",
        (slug,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Không có ebook {slug!r}.")
    translate = json.loads(row["translate_overrides_json"] or "{}")
    assistant = json.loads(row["ai_overrides_json"] or "{}")
    if translation_model:
        translate["translation_model"] = translation_model
    else:
        translate.pop("translation_model", None)
    if assistant_model:
        assistant["assistant_model"] = assistant_model
    else:
        assistant.pop("assistant_model", None)
    with conn:
        conn.execute(
            "UPDATE ebooks SET translate_overrides_json = ?, ai_overrides_json = ?, "
            "updated_at = datetime('now') WHERE slug = ?",
            (json.dumps(translate, ensure_ascii=False), json.dumps(assistant, ensure_ascii=False), slug),
        )
    return {"saved": True, "model_overrides": _ebook_model_overrides(slug)}


@router.get("/settings/global-ai")
def global_ai_settings():
    return settings_routes._global_ai_payload()


@router.post("/settings/global-ai")
def global_ai_settings_save(payload: dict = Body(...)):
    try:
        saved = settings_routes.save_global_ai_settings(payload)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"saved": True, "global_ai": saved}


def _opds_settings_payload() -> dict:
    api = deps.cfg().api
    return {
        "token": "",
        "token_configured": bool(api.token),
        "cors_origins": "\n".join(api.cors_origins),
        "auto_build": api.auto_build,
    }


@router.post("/settings/opds")
def opds_settings_save(payload: dict = Body(...)):
    from novel2epub.config import update_defaults

    current = deps.cfg().api
    token = str(payload.get("token") or "").strip() or current.token
    origins = [line.strip() for line in str(payload.get("cors_origins") or "").splitlines() if line.strip()]
    update_defaults(deps.WORKSPACE_PATH, {"api": {
        "token": token,
        "cors_origins": origins,
        "auto_build": bool(payload.get("auto_build")),
    }})
    return {"saved": True, "opds": _opds_settings_payload()}


_SETTINGS_SAVERS = {
    "novel": settings_routes.save_novel,
    "source": settings_routes.save_source,
    "translate": settings_routes.save_translate,
    "ai": settings_routes.save_ai,
    "reader": settings_routes.save_reader,
    "output": settings_routes.save_output,
}


@router.post("/ebooks/{slug}/settings/{section}")
def ebook_settings_save(slug: str, section: str, payload: dict = Body(...)):
    """Lưu một khối cấu hình, gọi THẲNG hàm xử lý form cũ trong `settings.py`.

    Không HTTP round-trip sang endpoint `Form(...)` cũ: những endpoint đó trả
    `RedirectResponse` 303 sang trang Jinja2, mà `fetch` mặc định đi theo
    redirect rồi tải về cả trang HTML chỉ để vứt đi — tốn băng thông, và nếu
    SPA chạy khác origin (Vercel) thì trang đích nằm ngoài `_CORS_PREFIXES`
    nên sẽ bị trình duyệt chặn bởi CORS.

    Gọi hàm Python trực tiếp né được cả hai: `save_novel` v.v. là hàm sync
    thường, `Form(...)` chỉ là giá trị mặc định lúc FastAPI parse HTTP — gọi
    trực tiếp với keyword argument bỏ qua lớp đó hoàn toàn. `payload` phải
    đúng bộ khoá mà hàm nhận (khoá JSON = tên tham số Form), xem
    `tests/test_ui_settings_contract.py`.
    """
    fn = _SETTINGS_SAVERS.get(section)
    if fn is None:
        raise HTTPException(status_code=404, detail=f"Không có mục cài đặt '{section}'.")

    try:
        fn(slug=slug, **payload)
    except TypeError as exc:
        raise HTTPException(status_code=400, detail=f"Payload không hợp lệ: {exc}") from exc

    return {"saved": True}


@router.get("/library/{slug}")
def library_detail(slug: str):
    archived = archived_slugs(deps.LIBRARY_STATE_PATH)
    library = deps.library()
    entry = library.ebooks.get(slug) if library.ebooks else None
    if library.ebooks and entry is None:
        raise HTTPException(status_code=404, detail=f"Không có ebook {slug!r}.")
    cfg = deps.resolved_cfg(slug)
    return _ebook_summary(
        slug, cfg, archived=slug in archived, in_library=entry is not None
    )


# ── Cấu hình hiệu lực (đã che bí mật) + readiness/build ──────────────────


@router.get("/ebooks/{slug}/config/effective")
def ebook_effective_config(slug: str):
    """Cấu hình HIỆU LỰC của ebook (defaults -> preset -> override), đã che
    bí mật (api_key/service_key...). `redacted_fields` liệt kê field đã che."""
    from novel2epub.redaction import redact_cfg

    cfg = deps.resolved_cfg(slug)
    return redact_cfg(cfg)


@router.get("/ebooks/{slug}/readiness")
def ebook_readiness(slug: str):
    """Sẵn sàng build/dịch: có manifest chưa, mỗi nhánh dịch được bao nhiêu
    chương, build đang stale không, có job/artefact lock đang chạy không."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        return {
            "has_manifest": False,
            "total": 0,
            "branches": {},
            "build": storage.read_build(),
            "build_stale": False,
        }
    chapters = manifest.chapters
    total = len(chapters)
    branches: dict[str, dict] = {}
    for branch in revisions.BRANCHES:
        count = sum(1 for ch in chapters if storage.has_branch_text(ch, branch))
        branches[branch] = {
            "count": count,
            "label": revisions.branch_label(branch),
        }
    build = storage.read_build()
    return {
        "has_manifest": True,
        "total": total,
        "translated": branches.get("ai", {}).get("count", 0),
        "local_mt": branches.get("local_mt", {}).get("count", 0),
        "branches": branches,
        "build": build,
        "build_stale": storage.build_stale(),
        "build_blockers": storage.build_blockers(chapters),
        "legacy_report": storage.legacy_ai_rewrite_report(),
    }


@router.get("/ebooks/{slug}/build")
def ebook_build_status(slug: str):
    """Trạng thái build artifact hiện tại (lock owner, status, stale?)."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    build = storage.read_build()
    manifest = storage.load_manifest()
    blockers = storage.build_blockers(manifest.chapters) if manifest is not None else []
    return {"build": build, "build_stale": storage.build_stale(), "build_blockers": blockers}


@router.get("/ebooks/{slug}/build/preview")
def ebook_build_preview(slug: str):
    """Preview đầy đủ cho trang Build: stats, validation, metadata, EPUB preview.

    Không gọi model, chỉ đọc DB/manifest. Dùng cho trang /ebooks/:slug/build mới:
    hiển thị thống kê, validate chính tả/mã hóa/dấu lạ, preview nội dung sẽ đóng gói.
    """
    from novel2epub.build_validation import build_preview_payload

    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    return build_preview_payload(cfg, storage)


@router.post("/ebooks/{slug}/build/confirm")
def ebook_build_confirm(request: Request, slug: str, payload: dict = Body(default={})):
    """Xác nhận build sau khi đã xem preview/validation.

    Body: {force?: bool} — khi force=true, bỏ qua validate mềm (vẫn chặn nếu không có gì để build).
    Enqueue job build nền (category build), trả job_id để UI poll queue.
    """
    from novel2epub.pipeline import step_build_selected
    from novel2epub.queue_labels import job_label

    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=400, detail="Chưa có manifest — hãy crawl trước.")

    force = bool(payload.get("force"))
    if not force:
        blockers = storage.build_blockers(manifest.chapters)
        if blockers:
            detail = "; ".join(f"Chương {b['index']}: {b['reason']}" for b in blockers[:5])
            raise HTTPException(
                status_code=409,
                detail=f"Không build được — còn {len(blockers)} chương chưa có bản dịch hoàn chỉnh: {detail}",
            )

    # chặn duplicate build đang chạy — kiểm tra artifact status
    build = storage.read_build()
    if build.get("status") == "building":
        raise HTTPException(status_code=409, detail="Đang có build khác chạy cho ebook này — chờ xong rồi thử lại.")

    def _target(log):
        step_build_selected(cfg, log)

    job = request.app.state.job.queue.enqueue(
        "build",
        "build",
        _target,
        label=job_label("build", title=cfg.novel.title, slug=slug),
        ebook=slug,
    )
    return {"ok": True, "job_id": job.id, "ebook": slug}


@router.get("/ebooks/{slug}/chapters/{index}/validation")
def ebook_chapter_validation(slug: str, index: int):
    """Chi tiết lỗi per-para cho 1 chương — dùng cho tab Lỗi của ChapterPage.

    Trả validation chi tiết (paraIndex, start, end) để highlight và scroll. Highlight hoạt động ở cả
    chế độ đọc và sửa; edit mode dùng paraIndex để cuộn textarea.
    """
    from novel2epub.build_validation import validate_chapter_detailed

    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có mục lục.")
    ch = next((c for c in manifest.chapters if c.index == index), None)
    if ch is None:
        raise HTTPException(status_code=404, detail=f"Không có chương {index}.")
    # Dùng bản sẽ xuất bản (publication_version) nếu có, fallback active_branch
    pv = storage.publication_version(ch)
    if pv is not None:
        text = pv.text
        title = pv.title
    else:
        text = storage.read_branch_text(ch, storage.active_branch(ch))
        title = storage.read_branch_title(ch, storage.active_branch(ch)) or ch.title
    # Nếu vẫn rỗng, thử fallback raw? Không highlight raw
    result = validate_chapter_detailed(text, title)
    # Thêm context chương
    result["index"] = ch.index
    result["title"] = title
    # Title issues riêng đã có paraIndex -1
    return result


@router.post("/ebooks/{slug}/build")
def ebook_build_start(request: Request, slug: str, payload: dict = Body(...)):
    """Build là bulk action và bắt buộc đi qua preview + confirm."""
    raise HTTPException(
        status_code=409,
        detail={
            "reason": "Build phải preview readiness và tập chương trước khi xác nhận.",
            "preview_url": f"/api/ui/ebooks/{slug}/build/preview",
            "confirm_url": f"/api/ui/ebooks/{slug}/build/confirm",
            "action": "build",
        },
    )


# ── nhánh bản dịch (ai_translation vs local_mt) ──────────────────────────


@router.get("/ebooks/{slug}/chapters/{index}/branches")
def ebook_chapter_branches(slug: str, index: int):
    """Trạng thái 2 nhánh của một chương: text, revision, title, active."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có mục lục.")
    chapter = next((c for c in manifest.chapters if c.index == index), None)
    if chapter is None:
        raise HTTPException(status_code=404, detail=f"Không có chương {index}.")
    active = storage.active_branch(chapter)
    branches = {}
    for branch in revisions.BRANCHES:
        has_text = storage.has_branch_text(chapter, branch)
        branches[branch] = {
            "label": revisions.branch_label(branch),
            "has_text": has_text,
            "revision": storage.read_branch_revision(chapter, branch),
            "title": storage.read_branch_title(chapter, branch) or chapter.title,
            "active": branch == active,
        }
    return {
        "index": index,
        "active": active,
        "branches": branches,
        "legacy_report": storage.legacy_ai_rewrite_report(),
    }


@router.post("/ebooks/{slug}/chapters/{index}/branches")
def ebook_chapter_set_branch(slug: str, index: int, payload: dict = Body(...)):
    """Đổi nhánh ĐANG HOẠT ĐỘNG của chương (bản đi vào EPUB/Reader)."""
    from novel2epub import revisions as _rev

    branch = payload.get("branch")
    if branch not in _rev.BRANCHES:
        raise HTTPException(status_code=400, detail=f"branch không hợp lệ: {branch!r}")
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có mục lục.")
    chapter = next((c for c in manifest.chapters if c.index == index), None)
    if chapter is None:
        raise HTTPException(status_code=404, detail=f"Không có chương {index}.")
    storage.set_active_branch(chapter, branch)
    return {"index": index, "active": branch}


@router.post("/ebooks/{slug}/translate")
def ebook_translate_branch(request: Request, slug: str, payload: dict = Body(...)):
    """Endpoint bulk dịch cũ đã đóng; dùng bulk-preview + bulk-confirm."""
    raise HTTPException(
        status_code=409,
        detail={
            "reason": "Dịch hàng loạt phải preview tập chương/config trước.",
            "preview_url": f"/api/ui/ebooks/{slug}/chapters/bulk-preview",
            "actions": ["translate", "local-mt"],
        },
    )


@router.get("/genres")
def list_genres():
    """Thể loại dùng cho prompt dịch và prompt biên tập (xem `novel2epub/genre.py`)."""
    from novel2epub.genre import GENRE_PRESETS

    return {
        "genres": [
            {"value": key, "label": preset.label or key} for key, preset in GENRE_PRESETS.items()
        ]
    }


@router.post("/ebooks/{slug}/rewrite")
def ebook_rewrite_selected(request: Request, slug: str, payload: dict = Body(...)):
    """Endpoint bulk AI edit cũ đã đóng; draft bắt buộc preview + confirm."""
    raise HTTPException(
        status_code=409,
        detail={
            "reason": "AI edit hàng loạt phải preview eligibility Local MT trước.",
            "preview_url": f"/api/ui/ebooks/{slug}/chapters/bulk-preview",
            "action": "ai-edit-draft",
        },
    )


# ── preview token chính xác + bulk preview/confirm ────────────────────────


@router.post("/ebooks/{slug}/chapters/{index}/preview-token")
def ebook_issue_preview_token(slug: str, index: int, payload: dict = Body(...)):
    """Cấp token duyệt bản nháp — snapshot chính xác nhánh tại thời điểm cấp.
    Token một lần, có hạn; UI phải gửi kèm khi confirm để chắc chắn bản đang
    duyệt vẫn là bản sẽ áp."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có mục lục.")
    chapter = next((c for c in manifest.chapters if c.index == index), None)
    if chapter is None:
        raise HTTPException(status_code=404, detail=f"Không có chương {index}.")
    revision_id = payload.get("revision_id")
    if not isinstance(revision_id, int):
        raise HTTPException(status_code=400, detail="Thiếu 'revision_id'.")
    branch = revisions.normalize_branch(payload.get("branch", revisions.BRANCH_AI))
    cand = storage.read_ai_revision(chapter, revision_id)
    if cand is None or cand.status != revisions.STATUS_PENDING:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản nháp đang chờ duyệt.")
    if revisions.normalize_branch(cand.branch) != branch:
        raise HTTPException(status_code=400, detail="Bản nháp không thuộc nhánh này.")
    token = storage.issue_preview_token(chapter, branch=branch, revision_id=revision_id)
    return {
        "token": token,
        "idx": index,
        "branch": branch,
        "revision_id": revision_id,
        "base_rev": storage.read_branch_revision(chapter, branch),
    }


@router.post("/ebooks/{slug}/chapters/{index}/ai/rewrite/confirm-token")
def webui_ai_rewrite_confirm_token(slug: str, index: int, payload: dict = Body(...)):
    """Chấp nhận candidate kèm preview token (exact snapshot). Token lệch/hết
    hạn → 409. Atomic: xác thực token rồi mới áp (snapshot lại trong lúc áp)."""
    from novel2epub import preview as preview_mod
    from novel2epub.pipeline import step_apply_ai_revision

    revision_id = payload.get("revision_id")
    token = payload.get("token")
    if not isinstance(revision_id, int) or not isinstance(token, str) or not token:
        raise HTTPException(status_code=400, detail="Thiếu 'revision_id'/'token'.")
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có mục lục.")
    chapter = next((c for c in manifest.chapters if c.index == index), None)
    if chapter is None:
        raise HTTPException(status_code=404, detail=f"Không có chương {index}.")
    cand = storage.read_ai_revision(chapter, revision_id)
    if cand is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản nháp.")
    branch = revisions.normalize_branch(cand.branch)
    try:
        storage.consume_preview_token(token, branch=branch, revision_id=revision_id)
    except preview_mod.PreviewTokenError as e:
        raise HTTPException(status_code=409, detail=str(e))
    try:
        step_apply_ai_revision(cfg, lambda m: None, revision_id=revision_id)
    except revisions.RevisionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {
        "applied": True,
        "revision": storage.read_branch_revision(chapter, branch),
        "revision_id": revision_id,
        "branch": branch,
    }


@router.post("/ebooks/{slug}/chapters/ai/preview")
def ebook_ai_preview_bulk(request: Request, slug: str, payload: dict = Body(...)):
    """Endpoint bulk draft cũ đã đóng; preview mới không được gọi model."""
    raise HTTPException(
        status_code=409,
        detail={
            "reason": "Hãy preview eligibility trước; model chỉ chạy sau confirm.",
            "preview_url": f"/api/ui/ebooks/{slug}/chapters/bulk-preview",
            "action": "ai-edit-draft",
        },
    )


@router.post("/ebooks/{slug}/chapters/ai/confirm")
def ebook_ai_confirm_bulk(slug: str, payload: dict = Body(...)):
    """Không auto-approve candidate hàng loạt; accept từng draft bằng token."""
    raise HTTPException(
        status_code=409,
        detail={
            "reason": "AI edit draft phải được review và accept chọn lọc từng bản.",
            "chapter_confirm_url": f"/api/ui/ebooks/{slug}/chapters/{{index}}/ai/rewrite/confirm-token",
        },
    )


# ── legacy migration (non-destructive) ───────────────────────────────────


@router.post("/ebooks/{slug}/legacy-migrate")
def ebook_legacy_migrate(slug: str, payload: dict = Body(...)):
    """Nâng bản nháp legacy (meta['ai_rewrite'] chưa có revision_id) thành
    candidate trong `ai_revisions`. KHÔNG xoá dữ liệu gốc; idempotent."""
    from novel2epub.pipeline import step_migrate_legacy_revisions

    indexes = payload.get("indexes")
    selected_indexes: list[int] | None = None
    if isinstance(indexes, list) and indexes:
        selected_indexes = [int(i) for i in indexes]
    cfg = deps.resolved_cfg(slug)
    report = step_migrate_legacy_revisions(cfg, lambda m: None, selected_indexes=selected_indexes)
    return {"migrated": report}


# ── từ điển entity (global + override theo ebook) ────────────────────────


@router.get("/entities")
def entity_list(query: str = "", offset: int = 0, limit: int = 100, sort_field: str = "", sort_dir: str = "asc"):
    """Entity TOÀN CỤC (phân trang)."""
    cfg = deps.cfg()
    storage = Storage(cfg.output.data_dir, "default")
    limit = max(1, min(limit, 500))
    rows = storage.read_entities_page(offset, limit, query, sort_field or None, sort_dir)
    return {
        "rows": [{"source": s, "target": t, "protect": bool(p)} for s, t, p in rows],
        "total": storage.count_entities(query),
    }


@router.post("/entities")
def entity_upsert_global(payload: dict = Body(...)):
    """Thêm/cập nhật entity TOÀN CỤC."""
    cfg = deps.cfg()
    storage = Storage(cfg.output.data_dir, "default")
    ok = storage.upsert_entity(
        payload.get("source", ""), payload.get("target", ""), bool(payload.get("protect", False))
    )
    if not ok:
        raise HTTPException(status_code=400, detail="Thiếu source/target.")
    return {"saved": True}


@router.delete("/entities")
def entity_delete_global(payload: dict = Body(...)):
    """Xoá entity TOÀN CỤC."""
    cfg = deps.cfg()
    storage = Storage(cfg.output.data_dir, "default")
    if not storage.delete_entity(payload.get("source", "")):
        raise HTTPException(status_code=404, detail="Không tìm thấy entity.")
    return {"deleted": True}


@router.get("/ebooks/{slug}/entities")
def ebook_entity_list(slug: str, query: str = "", offset: int = 0, limit: int = 100, sort_field: str = "", sort_dir: str = "asc"):
    """Entity của ebook: override riêng + đếm tổng global. Phân trang override."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    limit = max(1, min(limit, 500))
    rows = storage.read_entity_overrides_page(offset, limit, query, sort_field or None, sort_dir)
    return {
        "rows": [{"source": s, "target": t, "protect": bool(p)} for s, t, p in rows],
        "total": storage.count_entity_overrides(query),
        "global_total": storage.count_entities(),
        "merged": [{"source": e.source, "target": e.target, "protect": e.protect} for e in storage.read_merged_entities()],
    }


@router.post("/ebooks/{slug}/entities")
def ebook_entity_upsert(slug: str, payload: dict = Body(...)):
    """Thêm/cập nhật override entity RIÊNG cho ebook (thắng mục global)."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    ok = storage.upsert_entity_override(
        payload.get("source", ""), payload.get("target", ""), bool(payload.get("protect", False))
    )
    if not ok:
        raise HTTPException(status_code=400, detail="Thiếu source/target.")
    return {"saved": True}


@router.delete("/ebooks/{slug}/entities")
def ebook_entity_delete(slug: str, payload: dict = Body(...)):
    """Xoá override entity riêng của ebook."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    if not storage.delete_entity_override(payload.get("source", "")):
        raise HTTPException(status_code=404, detail="Không tìm thấy entity override.")
    return {"deleted": True}


# ═══════════════════════════ Lưu trữ (Storage) ══════════════════════════


def _storage_ebook_slugs() -> list[str]:
    library = deps.library()
    return list(library.ebooks.keys()) if library.ebooks else []


@router.get("/storage")
def storage_overview():
    rows = []
    grand_total = 0
    for slug in _storage_ebook_slugs() or ["default"]:
        cfg = deps.resolved_cfg(slug)
        storage = Storage(cfg.output.data_dir, cfg.novel.slug)
        report = ebook_storage_report(storage, cfg.epub_path)
        grand_total += report["total"]
        counts = storage.content_counts()
        report["raw_chapters"] = counts["raw"]
        report["translated_chapters"] = counts["translated"]
        report["glossary_entries"] = counts["glossary"]
        rows.append({"slug": slug, "title": cfg.novel.title or slug, "report": report})
    return {"rows": rows, "grand_total": grand_total}


@router.post("/storage/{slug}/purge-raw")
def storage_purge_raw_api(slug: str):
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    removed = purge_raw(storage)
    return {"removed": removed}


@router.post("/storage/{slug}/purge-mt")
def storage_purge_mt_api(slug: str):
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    removed = purge_translated_mt(storage)
    return {"removed": removed}


@router.post("/storage/{slug}/remove-epub")
def storage_remove_epub_api(slug: str):
    cfg = deps.resolved_cfg(slug)
    removed = remove_epub(cfg.epub_path)
    return {"removed": removed}


# ═══════════════════════════ Tự động hóa (Automation) ═══════════════════


def _automation_ebook_options() -> list[dict[str, str]]:
    library = deps.library()
    if not library.ebooks:
        return [{"slug": "default", "title": "default"}]
    options = []
    for slug in library.ebooks:
        cfg = deps.resolved_cfg(slug)
        options.append({"slug": slug, "title": cfg.novel.title or slug})
    return sorted(options, key=lambda ebook: ebook["title"].casefold())


def _automation_dict(a) -> dict:
    d = asdict(a)
    d["next_run"] = None
    return d


@router.get("/automation")
def automation_overview():
    automations = load_automations(deps.AUTOMATIONS_PATH)
    now = datetime.now()
    items = []
    for a in automations.values():
        d = asdict(a)
        nxt = next_run_at(a, now)
        d["next_run"] = nxt.strftime("%Y-%m-%d %H:%M") if nxt else ""
        items.append(d)
    return {
        "automations": items,
        "ebooks": _automation_ebook_options(),
        "steps": list(AUTOMATION_STEPS),
    }


def _require_valid_schedule(schedule: str) -> None:
    if not validate_schedule(schedule):
        raise HTTPException(
            status_code=400,
            detail=f"Lịch không hợp lệ: {schedule!r} — dùng 'manual' hoặc cron 5 trường, ví dụ '*/30 * * * *'.",
        )


@router.post("/automation")
def automation_create_api(payload: dict = Body(...)):
    ebook = str(payload.get("ebook", "")).strip()
    if not ebook:
        raise HTTPException(status_code=400, detail="Thiếu ebook.")
    schedule = str(payload.get("schedule", "manual")).strip() or "manual"
    _require_valid_schedule(schedule)
    steps = [s for s in payload.get("steps", []) if s in AUTOMATION_STEPS] or ["build"]

    def _thr(key: str) -> int:
        try:
            v = int(payload.get(key, 0) or 0)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"{key} phải là số nguyên 0–10000.")
        if not 0 <= v <= 10000:
            raise HTTPException(status_code=400, detail=f"{key} phải trong khoảng 0–10000.")
        return v

    automation = add_automation(
        deps.AUTOMATIONS_PATH,
        ebook,
        steps,
        schedule,
        crawl_workers=max(1, min(64, int(payload.get("crawl_workers", 4) or 4))),
        translate_workers=max(1, min(64, int(payload.get("translate_workers", 4) or 4))),
        translate_threshold=_thr("translate_threshold"),
        cleanup_threshold=_thr("cleanup_threshold"),
        publish_threshold=_thr("publish_threshold"),
        build_threshold=_thr("build_threshold"),
    )
    return asdict(automation)


@router.post("/automation/{automation_id}/update")
def automation_update_api(automation_id: str, payload: dict = Body(...)):
    schedule = str(payload.get("schedule", "manual")).strip() or "manual"
    _require_valid_schedule(schedule)
    steps = [s for s in payload.get("steps", []) if s in AUTOMATION_STEPS] or ["build"]

    def _thr(key: str) -> int:
        try:
            v = int(payload.get(key, 0) or 0)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"{key} phải là số nguyên 0–10000.")
        if not 0 <= v <= 10000:
            raise HTTPException(status_code=400, detail=f"{key} phải trong khoảng 0–10000.")
        return v

    try:
        update_automation(
            deps.AUTOMATIONS_PATH,
            automation_id,
            {
                "steps": steps,
                "schedule": schedule,
                "enabled": bool(payload.get("enabled", True)),
                "crawl_workers": max(1, min(64, int(payload.get("crawl_workers", 4) or 4))),
                "translate_workers": max(1, min(64, int(payload.get("translate_workers", 4) or 4))),
                "translate_threshold": _thr("translate_threshold"),
                "cleanup_threshold": _thr("cleanup_threshold"),
                "publish_threshold": _thr("publish_threshold"),
                "build_threshold": _thr("build_threshold"),
            },
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"ok": True}


@router.post("/automation/{automation_id}/delete")
def automation_delete_api(automation_id: str):
    remove_automation(deps.AUTOMATIONS_PATH, automation_id)
    return {"ok": True}


@router.post("/automation/{automation_id}/run-now")
def automation_run_now_api(request: Request, automation_id: str):
    job_id = request.app.state.scheduler.run_now(automation_id)
    if job_id is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy automation.")
    return {"ok": True, "job_id": job_id}


# ═══════════════════════════ WireGuard ═══════════════════════════════════

_WG_MAX_UPLOAD_BYTES = 1_000_000


def _wg_db() -> str:
    return str(deps.DB_PATH)


def _wg_ui_config(cfg) -> dict:
    """KHÔNG kèm `wgcf.argv` — có thể chứa token/secret, xem `app/routes/wireguard.py`."""
    argv = list(cfg.wgcf.argv or [])
    return {
        "enabled": cfg.enabled,
        "profiles_dir": cfg.profiles_dir,
        "wg_exe": cfg.wg_exe,
        "manage_service": cfg.manage_service,
        "service_timeout_seconds": cfg.service_timeout_seconds,
        "lock_timeout_seconds": cfg.lock_timeout_seconds,
        "wgcf_enabled": cfg.wgcf.enabled,
        "wgcf_executable": cfg.wgcf.executable,
        "wgcf_output": cfg.wgcf.output,
        "wgcf_timeout_seconds": cfg.wgcf.timeout_seconds,
        "wgcf_argv_configured": bool(argv),
        "wgcf_argv_count": len(argv),
    }


def _wg_profile_or_404(profile_id: str) -> dict:
    prof = wg.get_profile(_wg_db(), profile_id)
    if prof is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy profile.")
    return prof


@router.get("/wireguard")
def wireguard_overview():
    cfg = deps.cfg().wireguard
    return {"config": _wg_ui_config(cfg), "profiles": wg.list_profiles(_wg_db())}


@router.post("/wireguard/settings")
def wireguard_save_settings_api(payload: dict = Body(...)):
    if bool(payload.get("replace_wgcf_argv")):
        argv = [line.strip() for line in str(payload.get("wgcf_argv", "")).splitlines() if line.strip()]
    else:
        current = deps.cfg().wireguard.wgcf.argv
        argv = list(current) if isinstance(current, (list, tuple)) else []
    try:
        wg.write_config(_wg_db(), {
            "enabled": bool(payload.get("enabled")),
            "profiles_dir": str(payload.get("profiles_dir", "")).strip(),
            "wg_exe": str(payload.get("wg_exe", "")).strip(),
            "manage_service": bool(payload.get("manage_service")),
            "service_timeout_seconds": float(payload.get("service_timeout_seconds", 60.0)),
            "lock_timeout_seconds": float(payload.get("lock_timeout_seconds", 30.0)),
            "wgcf": {
                "enabled": bool(payload.get("wgcf_enabled")),
                "executable": str(payload.get("wgcf_executable", "")).strip(),
                "argv": argv,
                "output": str(payload.get("wgcf_output", "wgcf-profile.conf")).strip(),
                "timeout_seconds": float(payload.get("wgcf_timeout_seconds", 120.0)),
            },
        })
    except WireGuardProfileError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True}


@router.post("/wireguard/import")
def wireguard_import_api(file: UploadFile = File(...), name: str = Form("")):
    parts: list[bytes] = []
    total = 0
    while True:
        chunk = file.file.read(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > _WG_MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"File cấu hình quá lớn (giới hạn {_WG_MAX_UPLOAD_BYTES // 1024} KB).",
            )
        parts.append(chunk)
    if total == 0:
        raise HTTPException(status_code=400, detail="File cấu hình rỗng.")

    import os
    import tempfile

    cfg = deps.cfg().wireguard
    label = (name or "").strip() or (file.filename or "")
    fd, tmppath = tempfile.mkstemp(suffix=".conf", prefix="n2e-wg-import-")
    os.close(fd)
    try:
        Path(tmppath).write_bytes(b"".join(parts))
        wg.import_profile(_wg_db(), cfg.profiles_dir, tmppath, source="manual", name=label or None)
    except WireGuardProfileError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        try:
            Path(tmppath).unlink(missing_ok=True)
        except OSError:
            pass
    return {"ok": True}


@router.post("/wireguard/discover")
def wireguard_discover_api():
    cfg = deps.cfg().wireguard
    try:
        added = wg.discover_profiles(_wg_db(), cfg.profiles_dir)
    except WireGuardProfileError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"added": len(added)}


@router.post("/wireguard/provision")
def wireguard_provision_api(payload: dict = Body(default={})):
    cfg = deps.cfg().wireguard
    try:
        wg.provision_wgcf_profile(_wg_db(), cfg, label=str(payload.get("label", "")).strip())
    except WireGuardProfileError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True}


@router.post("/wireguard/{profile_id}/enable")
def wireguard_enable_api(profile_id: str):
    prof = _wg_profile_or_404(profile_id)
    wg.set_enabled(_wg_db(), prof["id"], True)
    return {"ok": True}


@router.post("/wireguard/{profile_id}/disable")
def wireguard_disable_api(profile_id: str):
    prof = _wg_profile_or_404(profile_id)
    wg.set_enabled(_wg_db(), prof["id"], False)
    return {"ok": True}


@router.post("/wireguard/{profile_id}/position")
def wireguard_position_api(profile_id: str, payload: dict = Body(...)):
    prof = _wg_profile_or_404(profile_id)
    wg.set_order(_wg_db(), prof["id"], int(payload.get("position", 0)))
    return {"ok": True}


@router.post("/wireguard/{profile_id}/activate")
def wireguard_activate_api(profile_id: str):
    prof = _wg_profile_or_404(profile_id)
    cfg = deps.cfg().wireguard
    try:
        wg.activate_profile(_wg_db(), cfg, prof["id"])
    except WireGuardProfileError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True}


@router.post("/wireguard/rotate")
def wireguard_rotate_api():
    cfg = deps.cfg().wireguard
    try:
        wg.rotate_profile(_wg_db(), cfg)
    except WireGuardProfileError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True}


@router.post("/wireguard/{profile_id}/delete")
def wireguard_delete_api(profile_id: str):
    prof = _wg_profile_or_404(profile_id)
    if prof["status"] == "active" or wg.get_active_id(_wg_db()) == prof["id"]:
        raise HTTPException(status_code=409, detail="Không thể xóa profile đang active — hủy active trước.")
    cfg = deps.cfg().wireguard
    try:
        removed = wg.remove_profile(_wg_db(), cfg.profiles_dir, prof["id"])
    except WireGuardProfileError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not removed:
        raise HTTPException(status_code=404, detail="Không tìm thấy profile.")
    return {"ok": True}


# ═══════════════════════════ Nguồn (Sources) ═════════════════════════════

# Đúng bộ trường mà form preset (cũ) chỉnh được — cố ý KHÔNG kèm search_* và
# toc_next_page_selector/toc_max_pages: form legacy cũng không sửa các trường
# đó, chỉ AI-detect/import mới điền được. Giữ đồng bộ nếu form được mở rộng.
_SOURCE_EDITABLE_FIELDS = {
    "engine", "url", "domains", "chapter_link_pattern", "content_selector",
    "toc_selector", "chapter_title_selector", "title_selector", "author_selector",
    "desc_selector", "cover_selector", "cover_url_pattern", "encoding", "user_agent", "headless",
    "magic", "js_code", "delay_seconds", "next_page_selector", "next_page_url_pattern",
    "max_pages_per_chapter", "scrapling_mode", "solve_cloudflare", "network_idle",
    "impersonate", "proxy", "dns_over_https", "concurrency_cap", "strip_patterns",
    "toc_next_page_selector", "toc_max_pages", "retry_attempts", "retry_delay_seconds",
    "retry_backoff", "retry_max_delay_seconds", "retry_respect_retry_after",
}


@router.get("/sources")
def sources_overview():
    presets = deps.presets()
    validation = _load_validation()
    usage = _preset_usage(presets, deps.library())
    return {
        "presets": [asdict(p) for p in presets.values()],
        "usage": usage,
        "validation": validation,
    }


@router.post("/sources")
def sources_save_api(payload: dict = Body(...)):
    name = str(payload.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="Thiếu tên nguồn.")
    kwargs = {k: v for k, v in payload.items() if k in _SOURCE_EDITABLE_FIELDS}
    if isinstance(kwargs.get("strip_patterns"), str):
        kwargs["strip_patterns"] = [
            line.strip() for line in kwargs["strip_patterns"].splitlines() if line.strip()
        ]
    kwargs["name"] = name
    preset = SourcePreset(**kwargs)
    save_preset(deps.DB_PATH, preset)
    return asdict(preset)


@router.post("/sources/{name}/delete")
def sources_delete_api(name: str):
    presets = deps.presets()
    usage = _preset_usage(presets, deps.library())
    if usage.get(name):
        raise HTTPException(
            status_code=409,
            detail=f"Nguồn '{name}' đang dùng bởi: {', '.join(usage[name])}. Hãy đổi nguồn cho các ebook đó trước.",
        )
    delete_preset(deps.DB_PATH, name)
    return {"ok": True}


@router.post("/sources/{name}/clone")
def sources_clone_api(name: str, payload: dict = Body(default={})):
    presets = deps.presets()
    src = presets.get(name)
    if src is None:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy nguồn '{name}'.")
    new_name = str(payload.get("new_name", "")).strip() or f"{name}-copy"
    suffix = 2
    base_name = new_name
    while new_name in presets:
        new_name = f"{base_name}-{suffix}"
        suffix += 1
    data = asdict(src)
    data["name"] = new_name
    clone = SourcePreset(**data)
    save_preset(deps.DB_PATH, clone)
    return asdict(clone)


@router.post("/sources/{name}/test")
def sources_test_api(request: Request, name: str, payload: dict = Body(...)):
    """Dry-run: fetch_toc + 1 fetch_chapter, chạy nền, không ghi gì xuống đĩa.
    Kết quả lưu vào `source_validation.json`, đọc lại qua `GET /api/ui/sources`."""
    from novel2epub.crawler import ScraplingCrawler

    from .sources import _record_validation

    toc_url = str(payload.get("toc_url", "")).strip()
    if not toc_url:
        raise HTTPException(status_code=400, detail="Thiếu URL mục lục để test.")
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
        except Exception as e:  # noqa: BLE001
            _record_validation(name, False, str(e))
            log(f"[test nguồn] {name}: lỗi — {e}")
        finally:
            if crawler is not None:
                crawler.close()

    request.app.state.job.start_custom(f"test-source-{name}", _target, category="crawl")
    return {"started": True}


@router.post("/sources/inspect")
def sources_inspect_api(payload: dict = Body(...)):
    """Fetch 1 URL bằng Scrapling để lấy DOM snapshot — phục vụ picker và
    kiểm tra selectorwrapper/regex ngay trong modal mà không cần đoán bằng AI.

    Body: {url: str, scrapling_mode?: str, max_chars?: int}
    Trả: {ok, url, html, truncated, hrefs[], sample_links[]}
    Lưu trữ DOM ở client (state), backend chỉ fetch và trả HTML."""
    from novel2epub.config import CrawlConfig, ScraplingConfig
    from novel2epub.crawler import ScraplingCrawler
    from novel2epub.selector_ai import collect_sample_links

    url = str(payload.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="Thiếu URL.")
    mode = str(payload.get("scrapling_mode") or "stealthy").strip().lower()
    if mode not in ("fetcher", "stealthy", "dynamic"):
        mode = "stealthy"
    max_chars = int(payload.get("max_chars") or 200_000)
    max_chars = max(5_000, min(max_chars, 500_000))
    crawl_cfg = CrawlConfig(toc_url=url)
    crawl_cfg.scrapling = ScraplingConfig(mode=mode)
    try:
        crawler = ScraplingCrawler(crawl_cfg)
    except ImportError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    try:
        try:
            page = crawler._fetch_page(url)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Không tải được trang: {e}") from e
        raw_html = crawler._last_response_html or ""
        truncated = len(raw_html) > max_chars
        html = raw_html[:max_chars]
        # hrefs cho preview regex
        hrefs: list[str] = []
        try:
            links = page.css("a[href]")
            if links:
                for a in links:
                    href = a.attrib.get("href", "") if hasattr(a, "attrib") else ""
                    if href:
                        hrefs.append(str(href).strip())
                        if len(hrefs) >= 80:
                            break
        except Exception:
            hrefs = []
        # sample tuyệt đối cùng host có số — dùng cho regex hint
        try:
            sample_links = collect_sample_links(url, hrefs if hrefs else [], limit=40)
        except Exception:
            sample_links = []
    finally:
        try:
            crawler.close()
        except Exception:
            pass
    return {
        "ok": True,
        "url": url,
        "html": html,
        "truncated": truncated,
        "html_length": len(raw_html),
        "hrefs": hrefs[:80],
        "sample_links": sample_links,
        "mode": mode,
    }


@router.post("/sources/validate-selectors")
def sources_validate_selectors_api(payload: dict = Body(...)):
    """Đếm số phần tử khớp từng selector trên 1 HTML snapshot.

    Body: {html: str, url?: str, selectors: {field: selector}, patterns?: {field: regex}}
    Trả: {counts: {field: int (-1=lỗi cú pháp)}, pattern_hits: {field: {ok, matched, total}}, warnings: []}
    Dùng để hiển thị cảnh báo 'khớp N phần tử' ngay khi user gõ selector/regex."""
    import re

    from novel2epub.selector_ai import validate_pattern

    html = str(payload.get("html") or "")
    url = str(payload.get("url") or "").strip()
    selectors = payload.get("selectors") or {}
    patterns = payload.get("patterns") or {}
    sample_links = payload.get("sample_links") or []
    if not isinstance(selectors, dict):
        selectors = {}
    if not isinstance(patterns, dict):
        patterns = {}
    if not html or not html.strip():
        raise HTTPException(status_code=400, detail="Thiếu HTML để kiểm tra selector.")
    # Chọn parser: ưu tiên scrapling Selector (khớp engine crawl thật), fallback bs4
    page = None
    use_scrapling = False
    try:
        from scrapling.parser import Selector as ScraplingSelector

        try:
            page = ScraplingSelector(content=html.encode("utf-8", errors="ignore"), url=url or "http://example.com", encoding="utf-8")
            use_scrapling = True
        except Exception:
            page = None
    except ImportError:
        page = None
    # Fallback soup
    soup = None
    if page is None:
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
        except ImportError:
            raise HTTPException(status_code=500, detail="Thiếu parser (cần scrapling hoặc beautifulsoup4).")

    counts: dict[str, int] = {}
    for field, sel in selectors.items():
        sel = str(sel or "").strip()
        if not sel:
            counts[field] = 0
            continue
        try:
            if use_scrapling and page is not None:
                res = page.css(sel)
                if res is None:
                    counts[field] = 0
                else:
                    try:
                        counts[field] = len(res)
                    except TypeError:
                        counts[field] = 1 if res else 0
            else:
                assert soup is not None
                counts[field] = len(soup.select(sel))
        except Exception:
            counts[field] = -1
    # pattern validation
    pattern_hits: dict[str, dict] = {}
    # nếu không có sample_links, thử rút từ html (a[href])
    if not sample_links and html:
        try:
            if soup is None and page is not None:
                pass
            else:
                if soup is None:
                    from bs4 import BeautifulSoup

                    soup = BeautifulSoup(html, "html.parser")
                sample_links = [a.get("href", "") for a in soup.select("a[href]")][:40]
        except Exception:
            sample_links = []
    total = len(sample_links) if isinstance(sample_links, list) else 0
    for field, pat in patterns.items():
        pat = str(pat or "").strip()
        if not pat:
            pattern_hits[field] = {"ok": True, "matched": 0, "total": total}
            continue
        try:
            re.compile(pat)
        except re.error as e:
            pattern_hits[field] = {"ok": False, "error": str(e), "matched": 0, "total": total}
            continue
        ok, matched = validate_pattern(pat, sample_links if isinstance(sample_links, list) else [])
        pattern_hits[field] = {"ok": ok, "matched": matched, "total": total}
    warnings: list[str] = []
    for field, cnt in counts.items():
        if cnt == -1:
            warnings.append(f"{field}: selector lỗi cú pháp.")
        elif cnt == 0:
            warnings.append(f"{field}: không khớp phần tử nào.")
        elif cnt > 10:
            warnings.append(f"{field}: khớp {cnt} phần tử — quá rộng, nên thu hẹp wrapper hoặc thêm :nth-child.")
        elif cnt > 1 and field in ("content_selector", "next_page_selector", "toc_next_page_selector"):
            # các wrapper đơn trị nên 1
            warnings.append(f"{field}: khớp {cnt} phần tử — dự kiến 0-1, thêm positional helper (đầu/cuối) nếu cần.")
        elif cnt > 5 and field in ("title_selector", "author_selector", "cover_selector", "desc_selector", "chapter_title_selector"):
            warnings.append(f"{field}: khớp {cnt} phần tử — nên 1.")
    for field, pat in patterns.items():
        # cover_url_pattern khớp URL ảnh chứ không phải link chương —
        # sample_links là link chương nên bỏ qua cảnh báo matched=0.
        if field == "cover_url_pattern":
            pat_s = str(pat or "").strip()
            if pat_s:
                try:
                    re.compile(pat_s)
                except re.error as e:
                    warnings.append(f"{field}: regex lỗi — {e}")
            continue
    for field, info in pattern_hits.items():
        if field == "cover_url_pattern":
            continue  # đã kiểm riêng ở trên (chỉ kiểm cú pháp, không đối chiếu link chương)
        if not info.get("ok"):
            warnings.append(f"{field}: regex lỗi — {info.get('error','')}")
        elif info.get("total") and info.get("matched") == info.get("total") and info.get("total", 0) > 5:
            warnings.append(f"{field}: regex khớp toàn bộ {info['total']} link mẫu (.*) — sẽ crawl cả menu, hãy thu hẹp (vd /chuong-\\d+\\.html$).")
        elif info.get("total") and info.get("matched") == 0:
            warnings.append(f"{field}: regex không khớp link mẫu nào.")
    return {"counts": counts, "pattern_hits": pattern_hits, "warnings": warnings, "total_links": total}


@router.post("/sources/suggest")
def sources_suggest_selectors_api(payload: dict = Body(...)):
    """AI gợi ý selector cho preset từ HTML snapshot đã lưu ở client.

    Không tự fetch — `SourcesPage` đã tải DOM bằng `sources/inspect` thành công
    mới gọi endpoint này. Body: {html_toc, html_chapter, toc_url, chapter_url,
    sample_links?} (chấp nhận alias {html, chapter_html, url}). Trả:
    {ok, fields: {selector field → selector}, diagnostics: {field: count},
    pattern_ok, pattern_hits, toc_digest, chapter_digest}.
    """
    from novel2epub import selector_ai
    from novel2epub.selector_ai import validate_pattern

    html_toc = str(payload.get("html_toc") or payload.get("html") or "")
    html_chapter = str(payload.get("html_chapter") or payload.get("chapter_html") or "")
    if not html_toc and not html_chapter:
        raise HTTPException(status_code=400, detail="Trả HTML snapshot ở 'html_toc'/'html_chapter' (hoặc 'html').")
    toc_url = str(payload.get("toc_url") or payload.get("url") or "").strip()
    chapter_url = str(payload.get("chapter_url") or "").strip()
    # chapter_url fallback: đoán từ link TOC, giống route cũ
    sample_links = payload.get("sample_links")
    if not isinstance(sample_links, list):
        sample_links = None
    hrefs: list[str] = []
    if sample_links is None or len(sample_links) == 0:
        try:
            from bs4 import BeautifulSoup

            soups = [BeautifulSoup(html_toc or html_chapter, "html.parser")]
            for soup in soups:
                for a in soup.select("a[href]"):
                    href = a.get("href", "")
                    if href:
                        hrefs.append(str(href).strip())
            sample_links = selector_ai.collect_sample_links(toc_url or "http://example.com", hrefs)
        except Exception:
            sample_links = []
    if not chapter_url and hrefs:
        guessed = selector_ai.guess_chapter_url(toc_url or "http://example.com", hrefs)
        if guessed:
            chapter_url = guessed
    # Khử kính: đừng cho AI "thấy" HTML thô — chỉ cho digest.
    try:
        ai_cfg = deps.cfg().ai.openai
    except HTTPException:
        raise
    if not ai_cfg.base_url or not ai_cfg.model:
        raise HTTPException(status_code=400, detail="Chưa cấu hình AI (base_url/model) ở Settings › AI biên tập.")
    from novel2epub import openai_client

    toc_digest, toc_map = selector_ai.build_dom_digest(html_toc or html_chapter, selector_ai.TOC_FIELD_SPECS)
    chapter_digest, chapter_map = selector_ai.build_dom_digest(html_chapter or html_toc, selector_ai.CHAPTER_FIELD_SPECS)
    label_map = {**toc_map, **chapter_map}
    if not label_map and not sample_links:
        raise HTTPException(status_code=422, detail="Không trích được ứng viên DOM nào — thử tải DOM ở tab 'Mục lục' và 'Chương mẫu' trước.")
    prompt = selector_ai.build_suggest_prompt(toc_url, chapter_url, toc_digest, chapter_digest, sample_links or [])
    try:
        raw = openai_client.run_chat(ai_cfg, prompt)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Gọi AI thất bại: {e}") from e
    try:
        fields = selector_ai.parse_suggestion(raw, label_map)
    except ValueError as e:
        raise HTTPException(status_code=502, detail=f"AI trả về không đọc được: {e}") from e

    chapter_html_fields = {"content_selector", "chapter_title_selector", "next_page_selector"}
    diagnostics: dict[str, int] = {}
    for field, sel in fields.items():
        if field == "chapter_link_pattern" or not sel:
            continue
        html = html_chapter if field in chapter_html_fields else html_toc or html_chapter
        diagnostics[field] = selector_ai.count_matches(html, sel) if html else 0
    pattern_ok, pattern_hits = validate_pattern(fields.get("chapter_link_pattern", ""), sample_links or [])
    return {
        "ok": True,
        "fields": fields,
        "diagnostics": diagnostics,
        "chapter_url": chapter_url,
        "sample_count": len(sample_links or []),
        "pattern_ok": pattern_ok,
        "pattern_hits": pattern_hits,
        "toc_digest": toc_digest,
        "chapter_digest": chapter_digest,
    }


# ═══════════════════════════ Workflow / Blockers / Queue ═════════════════


@router.get("/ebooks/{slug}/blockers")
def ebook_blockers(slug: str):
    """Blockers ngăn build: chương không skip nhưng thiếu active-branch workspace.
    Build bị chặn hoàn toàn nếu `build_blocked=True`."""
    from novel2epub.pipeline import readiness_blockers
    cfg = deps.resolved_cfg(slug)
    return readiness_blockers(cfg)


@router.get("/ebooks/{slug}/chapters/{index}/workflow")
def ebook_chapter_workflow(slug: str, index: int):
    """Trạng thái workflow đầy đủ của một chương: branches, candidates, build readiness."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có mục lục.")
    chapter = next((c for c in manifest.chapters if c.index == index), None)
    if chapter is None:
        raise HTTPException(status_code=404, detail=f"Không có chương {index}.")
    storage.expire_stale_revisions(chapter)
    active = storage.active_branch(chapter)
    branches = {}
    for branch in revisions.BRANCHES:
        has_text = storage.has_branch_text(chapter, branch)
        branches[branch] = {
            "label": revisions.branch_label(branch),
            "has_text": has_text,
            "revision": storage.read_branch_revision(chapter, branch),
            "title": storage.read_branch_title(chapter, branch) or chapter.title,
            "active": branch == active,
        }
    ai_revisions = storage.list_ai_revisions(chapter)
    for item in ai_revisions:
        if item["status"] == "pending":
            item["payload_preview"] = (item.get("payload_json") or "")[:1000]
    active_branch_has_text = branches.get(active, {}).get("has_text", False)
    return {
        "index": index,
        "title": chapter.title,
        "skipped": bool(getattr(chapter, "skipped", False)),
        "active_branch": active,
        "branches": branches,
        "ai_revisions": ai_revisions,
        "pending_candidates": sum(1 for r in ai_revisions if r["status"] == "pending"),
        "build_ready": active_branch_has_text,
        "build_blocker": None if (chapter.skipped or active_branch_has_text) else f"Nhánh '{active}' chưa có bản dịch.",
        "has_raw": storage.has_raw(chapter),
    }


@router.get("/ebooks/{slug}/chapters/{index}/revisions")
def ebook_chapter_revisions(slug: str, index: int, status: str = ""):
    """Lịch sử candidate AI của một chương (mới nhất trước). Lọc theo `status` nếu cần."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có mục lục.")
    chapter = next((c for c in manifest.chapters if c.index == index), None)
    if chapter is None:
        raise HTTPException(status_code=404, detail=f"Không có chương {index}.")
    storage.expire_stale_revisions(chapter)
    items = storage.list_ai_revisions(chapter, status=status or None)
    for item in items:
        raw_payload = item.get("payload_json") or ""
        item["payload_preview"] = raw_payload[:2000]
        item.pop("payload_json", None)
    return {"index": index, "revisions": items, "total": len(items)}


@router.post("/ebooks/{slug}/chapters/bulk")
def ebook_chapters_bulk(request: Request, slug: str, payload: dict = Body(...)):
    """Endpoint bulk cũ đã đóng: mọi bulk action bắt buộc preview + confirm."""
    raise HTTPException(
        status_code=409,
        detail={
            "reason": "Mọi hành động hàng loạt phải preview trước khi xác nhận.",
            "preview_url": f"/api/ui/ebooks/{slug}/chapters/bulk-preview",
            "confirm_url": f"/api/ui/ebooks/{slug}/chapters/bulk-confirm",
        },
    )


@router.post("/ebooks/{slug}/chapters/bulk-preview")
def ebook_chapters_bulk_preview(request: Request, slug: str, payload: dict = Body(...)):
    """Preview hành động hàng loạt — KHÔNG đổi trạng thái, không gọi model.

    Trả token có hạn (snapshot đánh giá + vân tay config/workspace từng chương)
    để UI hiển thị rồi mới gọi `/bulk-confirm`. Xem `novel2epub/bulk_contract.py`.
    """
    from novel2epub import bulk_contract

    cfg = deps.resolved_cfg(slug)
    action = str(payload.get("action", "")).strip()
    if action == "set-branch":
        action = "switch-branch"
    if action not in bulk_contract.BULK_ACTIONS:
        raise HTTPException(status_code=400, detail=f"action không hợp lệ: {action!r}")
    indexes = payload.get("indexes")
    if not isinstance(indexes, list) or not indexes:
        raise HTTPException(status_code=400, detail="Thiếu 'indexes'.")
    try:
        index_list = [int(i) for i in indexes]
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="'indexes' phải là list số.")
    branch = str(payload.get("branch") or revisions.BRANCH_AI).strip()
    force = bool(payload.get("force", False))

    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có mục lục.")
    plan = bulk_contract.preview_plan(
        storage, manifest, action=action, indexes=index_list, branch=branch, force=force,
    )
    if plan["total"] == 0:
        raise HTTPException(status_code=400, detail="Không có chương nào khớp danh sách.")

    config_hash = bulk_contract.config_fingerprint(cfg)
    principal = getattr(request.state, "principal", None)
    actor = {
        "issuer": str(getattr(principal, "issuer", "") or ""),
        "subject": str(getattr(principal, "subject", "") or ""),
        "role": str(getattr(principal, "role", "") or ""),
    }
    token = storage.issue_bulk_token(
        action=action,
        options={
            "branch": branch, "force": force, "indexes": index_list,
            "actor": actor,
        },
        config_hash=config_hash,
        chapters=plan["chapters"],
        eligibility={"eligible": plan["eligible"], "blocked": plan["blocked"]},
        estimates=plan["estimates"],
    )
    return {
        "token": token,
        "action": action,
        "branch": branch,
        "force": force,
        "config_hash": config_hash,
        "total": plan["total"],
        "eligible": plan["eligible"],
        "blocked": plan["blocked"],
        "chapters": plan["chapters"],
        "estimates": plan["estimates"],
        "expires_at": time.time() + bulk_contract.BULK_TOKEN_TTL_SECONDS,
    }


@router.post("/ebooks/{slug}/chapters/bulk-confirm")
def ebook_chapters_bulk_confirm(request: Request, slug: str, payload: dict = Body(...)):
    """Xác nhận hành động đã preview — xác thực token rồi mới thực thi.

    Token hết hạn/đã dùng/config đổi/workspace chương đổi giữa chừng → 409,
    phải `/bulk-preview` lại. Action dài đẩy job nền, action nhanh chạy ngay."""
    from novel2epub import bulk_contract
    from novel2epub.pipeline import step_bulk_confirm

    cfg = deps.resolved_cfg(slug)
    token = str(payload.get("token", "")).strip()
    if not token:
        raise HTTPException(status_code=400, detail="Thiếu 'token'.")

    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    row = storage.read_bulk_token(token)
    if row is None:
        raise HTTPException(status_code=400, detail="Token không tồn tại.")
    ok, reason, options = storage.validate_bulk_token(
        token, config_hash=bulk_contract.config_fingerprint(cfg),
    )
    if not ok:
        raise HTTPException(status_code=409, detail=reason)
    action = row["action"]

    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có mục lục.")
    try:
        plan_chapters = json.loads(row["chapters_json"] or "[]")
    except json.JSONDecodeError:
        plan_chapters = []
    plan = {"action": action, "branch": options.get("branch", ""), "chapters": plan_chapters}
    changed = bulk_contract.verify_fingerprints(plan, storage, manifest)
    if changed:
        raise HTTPException(
            status_code=409,
            detail={"reason": "Dữ liệu đã thay đổi kể từ khi preview — hãy preview lại.",
                    "changed_indexes": changed},
        )

    eligible_indexes = [int(i["index"]) for i in plan_chapters if i.get("ok")]
    if not eligible_indexes:
        raise HTTPException(status_code=409, detail="Preview không có chương đủ điều kiện để thực thi.")

    def _dispatch(name, category, fn):
        action_label = {
            "translate": "translate",
            "local-mt": "local-mt",
            "ai-edit": "ai-rewrite",
            "ai-edit-draft": "ai-rewrite",
            "build": "build",
            "delete-translation": "delete-translation",
        }.get(action, action)
        if len(eligible_indexes) == 1:
            ch_idx = eligible_indexes[0]
            ch = storage.get_chapter(ch_idx) if manifest else None
            ch_title = ch.title if ch else ""
            job_lbl = chapter_job_label(
                action_label, title=cfg.novel.title, slug=slug, index=ch_idx, chapter_title=ch_title
            )
        else:
            job_lbl = batch_job_label(
                action_label, title=cfg.novel.title, slug=slug, count=len(eligible_indexes)
            )
        return request.app.state.job.start_custom(
            name, fn, category=category, ebook=slug,
            chapter_indexes=eligible_indexes,
            label=job_lbl,
        )

    try:
        result = step_bulk_confirm(
            cfg, lambda m: None, action=action, indexes=eligible_indexes,
            branch=options.get("branch", ""), force=bool(options.get("force", False)),
            dispatch=_dispatch,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    # Consume chỉ sau khi thao tác nhanh thành công hoặc job đã được enqueue.
    storage.consume_bulk_token(token)
    storage.invalidate_bulk_tokens(action=action)
    return {**result, "token": token, "consumed": True, "exact_indexes": eligible_indexes}


def _ai_edit_eligible(storage, manifest, payload: dict) -> tuple[list[int], list[dict]]:
    """Đọc `indexes`, lọc chương đủ điều kiện biên tập AI (đã có bản dịch
    Local MT — đọc file, không gọi model). Trả `(eligible, blocked)`."""
    from novel2epub import bulk_contract

    indexes = payload.get("indexes")
    if not isinstance(indexes, list) or not indexes:
        raise HTTPException(status_code=400, detail="Thiếu 'indexes'.")
    try:
        index_list = [int(i) for i in indexes]
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="'indexes' phải là list số.")

    wanted = set(index_list)
    eligible: list[int] = []
    blocked: list[dict] = []
    for ch in manifest.chapters:
        if ch.index not in wanted:
            continue
        ok, reason = bulk_contract.chapter_eligibility(storage, ch, action="ai-edit")
        if ok:
            eligible.append(ch.index)
        else:
            blocked.append({"index": ch.index, "reason": reason})
    return eligible, blocked


def _enqueue_ai_edit_job(job, cfg, storage, slug: str, eligible: list[int], blocked: list[dict]) -> dict:
    """Xếp job biên tập AI ghi TRỰC TIẾP vào nhánh `local_mt` cho `eligible`
    (CAS mỗi chương lúc thực thi — chương đổi giữa chừng bị bỏ qua có log)."""
    from novel2epub.pipeline import step_ai_edit_local_mt_bulk

    if not eligible:
        raise HTTPException(
            status_code=409,
            detail="Không có chương nào đủ điều kiện — cần bản dịch Local MT trước.",
        )

    if len(eligible) == 1:
        ch = storage.get_chapter(eligible[0])
        label = chapter_job_label(
            "ai-rewrite", title=cfg.novel.title, slug=slug,
            index=eligible[0], chapter_title=getattr(ch, "title", "") if ch else "",
        )
    else:
        label = batch_job_label(
            "ai-rewrite", title=cfg.novel.title, slug=slug, count=len(eligible),
        )

    def _target(log, _cfg=cfg, _idx=list(eligible)):
        step_ai_edit_local_mt_bulk(_cfg, log, selected_indexes=_idx)

    queued = job.queue.enqueue(
        "ai-edit", f"ai-edit-{slug}", _target,
        label=label, ebook=slug, chapter_indexes=list(eligible),
    )
    return {
        "status": "queued",
        "job_id": queued.id,
        "queued": len(eligible),
        "skipped": len(blocked),
        "indexes": eligible,
        "blocked": blocked,
    }


@router.post("/ebooks/{slug}/chapters/ai-edit")
def ebook_chapters_ai_edit(request: Request, slug: str, payload: dict = Body(...)):
    """AI biên tập GHI TRỰC TIẾP vào nhánh `local_mt` (canonical).

    Đây là hành động GHI ĐÈ bản dịch nên bắt buộc xác nhận: gửi `confirm: true`.
    UI nên đi qua hợp đồng bulk-preview/confirm (action `ai-edit`) để xem trước
    số chương đủ điều kiện; endpoint này dành cho luồng CLI/API/test muốn một
    cú gọi trực tiếp có cờ xác nhận rõ ràng."""
    if not payload.get("confirm"):
        raise HTTPException(
            status_code=400,
            detail="AI biên tập ghi đè bản dịch Local MT — cần xác nhận (confirm: true).",
        )
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có mục lục.")

    eligible, blocked = _ai_edit_eligible(storage, manifest, payload)
    return _enqueue_ai_edit_job(request.app.state.job, cfg, storage, slug, eligible, blocked)


@router.post("/ebooks/{slug}/chapters/ai-edit-draft")
def ebook_chapters_ai_edit_draft(request: Request, slug: str, payload: dict = Body(...)):
    """Alias cũ của `/ai-edit` — request shape giữ nguyên nhưng semantics đã
    đổi sang GHI TRỰC TIẾP (không còn sinh bản nháp chờ duyệt): bấm là ghi đè
    bản dịch Local MT bằng kết quả AI. Có ghi đè thật nên luồng UI mới đi qua
    hợp đồng bulk-preview/confirm (action `ai-edit`); endpoint này chỉ còn cho
    CLI/API cũ gọi."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có mục lục.")

    eligible, blocked = _ai_edit_eligible(storage, manifest, payload)
    return _enqueue_ai_edit_job(request.app.state.job, cfg, storage, slug, eligible, blocked)

@router.get("/queue")
def queue_status(request: Request):
    """Trạng thái queue theo category: running / pending / workers / history gần nhất."""
    snap = request.app.state.job.queue.snapshot()
    pending_by_cat: dict[str, list] = snap.get("pending", {}) or {}
    by_cat: dict[str, dict] = {}
    for cat in ("crawl", "local-mt", "ai-translate", "ai-edit", "build"):
        pending_for_cat = pending_by_cat.get(cat, [])
        running_for_cat = [j for j in snap.get("running", []) if j.get("category") == cat]
        by_cat[cat] = {
            "running": running_for_cat,
            "pending_count": len(pending_for_cat),
            "pending": pending_for_cat[:20],
        }
    return {
        "categories": snap.get("categories", []),
        "running": snap.get("running", []),
        "pending": snap.get("pending", {}),
        "history": snap.get("history", [])[:50],
        "by_category": by_cat,
    }


# ── Import / Export entity (global + override) ───────────────────────────


@router.get("/entities/export")
def entity_export_global():
    """Xuất toàn bộ entity global dạng JSON."""
    cfg = deps.cfg()
    storage = Storage(cfg.output.data_dir, "default")
    return {"entities": storage.export_entities(), "total": storage.count_entities()}


@router.post("/entities/import")
def entity_import_global(payload: dict = Body(...)):
    """Import entity global. `merge=true` upsert (giữ mục cũ); mặc định thay thế."""
    cfg = deps.cfg()
    storage = Storage(cfg.output.data_dir, "default")
    rows = payload.get("entities")
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="Thiếu trường 'entities' (list).")
    merge = bool(payload.get("merge", False))
    result = storage.import_entities(rows, merge=merge)
    return result


@router.get("/ebooks/{slug}/entities/export")
def ebook_entity_export(slug: str):
    """Xuất override entity của ebook dạng JSON."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    return {
        "entities": storage.export_entity_overrides(),
        "total": storage.count_entity_overrides(),
    }


@router.post("/ebooks/{slug}/entities/import")
def ebook_entity_import(slug: str, payload: dict = Body(...)):
    """Import override entity cho ebook. `merge=true` upsert; mặc định thay thế."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    rows = payload.get("entities")
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="Thiếu trường 'entities' (list).")
    merge = bool(payload.get("merge", False))
    result = storage.import_entity_overrides(rows, merge=merge)
    return result
