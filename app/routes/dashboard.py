"""Dashboard tổng hợp nhiều ebook: tiến độ cào/dịch, lỗi automation, chi phí
dịch, dung lượng đĩa — dùng cho tính năng automation liên tục (bulk import)."""
from __future__ import annotations

import threading
import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from novel2epub.automation import load_automations
from novel2epub.db import resolve_db_path
from novel2epub.progress import chapter_progress, han_fixed_total
from novel2epub.storage import Storage
from novel2epub.toc import crawl_problem_indexes

from .. import deps
from ..cost_summary import read_cost_summary
from ..storage_report import ebook_storage_report

router = APIRouter()

# Trang tự poll mỗi 4s nhưng phần nặng (quét cả bảng chapters của mọi ebook)
# chỉ đổi khi có ghi vào DB — nên cache lại và bỏ cache khi file DB đổi.
# TTL chỉ là lưới an toàn cho thay đổi mà chữ ký file không bắt được (ví dụ
# ghi vào WAL không đổi kích thước trong cùng 1 nấc mtime), không phải cơ chế
# chính. Xem `_db_signature`.
_CACHE_MAX_TTL = 30.0
_cache_lock = threading.Lock()
_cache: tuple | None = None  # (signature, built_at_monotonic, payload)


def _ebook_slugs() -> list[str]:
    library = deps.library()
    return list(library.ebooks.keys()) if library.ebooks else []


def _ebook_cfgs() -> list[tuple[str, object]]:
    """(slug, cfg) cho mọi ebook. Rẻ (~10ms/5 ebook) nên chạy cả khi cache hit
    — chữ ký cache PHẢI suy ra từ chính cfg này, xem `_db_signature`."""
    return [(slug, deps.resolved_cfg(slug)) for slug in _ebook_slugs()]


def _db_signature(cfgs: list[tuple[str, object]]) -> tuple:
    """Chữ ký (đường dẫn, mtime, size) của các file DB mà rows được dựng từ đó.

    Phải derive từ `cfg.output.data_dir` chứ KHÔNG phải `deps.DB_PATH`: test
    monkeypatch `deps.resolved_cfg` sang DB tạm nhưng không đụng `DB_PATH`, nên
    key theo `DB_PATH` sẽ đứng yên giữa 2 DB khác nhau và trả nhầm dữ liệu ebook
    này cho ebook kia. Key theo nguồn thật thì cache luôn đi theo dữ liệu thật.

    Kèm cả file `-wal`: DB chạy journal_mode=WAL nên ghi mới nằm ở WAL, file
    `.db` chính có thể chưa đổi cho tới lúc checkpoint.
    """
    sig: list = [tuple(slug for slug, _ in cfgs)]
    seen: set[str] = set()
    for _, cfg in cfgs:
        db = resolve_db_path(cfg.output.data_dir)
        for path in (db, Path(str(db) + "-wal")):
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            try:
                st = path.stat()
                sig.append((key, st.st_mtime_ns, st.st_size))
            except OSError:
                sig.append((key, None, None))
    return tuple(sig)


def _build_ebook_rows(cfgs: list[tuple[str, object]]) -> tuple[list[dict], dict]:
    """Phần nặng: mỗi ebook 1 lượt quét bảng chapters. Tách khỏi phần "live"
    (queue snapshot) để cache được mà không làm đơ ô "Job đang chạy"."""
    automations = load_automations(deps.AUTOMATIONS_PATH)
    rows = []
    total_raw = total_translated = total_chapters = 0
    error_count = 0

    for slug, cfg in cfgs:
        storage = Storage(cfg.output.data_dir, cfg.novel.slug)
        manifest = storage.load_manifest()
        # 1 query/ebook cho cả 3 số liệu dưới đây; không có nó thì mỗi hàm tự
        # chạy 1 query/chương và kéo về nguyên văn raw/translated của cả bộ.
        stats_map = storage.bulk_chapter_stats()
        progress = chapter_progress(storage, manifest, stats_map=stats_map)
        crawl_problems = (
            crawl_problem_indexes(manifest.chapters, storage, stats_map=stats_map)
            if manifest
            else []
        )
        han_fixed = han_fixed_total(storage, manifest, stats_map=stats_map)
        disk_report = ebook_storage_report(storage, cfg.epub_path)
        cost_summary = read_cost_summary(storage)
        ebook_automations = [a for a in automations.values() if a.ebook == slug]
        if any(a.last_run_error for a in ebook_automations):
            error_count += 1

        total_raw += progress["raw_count"]
        total_translated += progress["translated_count"]
        total_chapters += progress["total"]

        rows.append({
            "slug": slug,
            "title": cfg.novel.title or slug,
            "progress": progress,
            "crawl_problems": len(crawl_problems),
            "han_fixed": han_fixed,
            "disk_total": disk_report["total"],
            "cost_summary": cost_summary,
            "automations": [
                {
                    "id": a.id,
                    "steps": a.steps,
                    "schedule": a.schedule,
                    "enabled": a.enabled,
                    "last_run_at": a.last_run_at,
                    "last_run_outcome": a.last_run_outcome,
                    "last_run_error": a.last_run_error,
                    "last_run_stats": a.last_run_stats,
                }
                for a in ebook_automations
            ],
        })

    totals = {
        "raw_count": total_raw,
        "translated_count": total_translated,
        "total_chapters": total_chapters,
        "error_count": error_count,
    }
    return rows, totals


def _ebook_rows_cached() -> tuple[list[dict], dict]:
    global _cache
    cfgs = _ebook_cfgs()
    sig = _db_signature(cfgs)
    now = time.monotonic()

    with _cache_lock:
        if _cache is not None:
            cached_sig, built_at, payload = _cache
            if cached_sig == sig and now - built_at < _CACHE_MAX_TTL:
                return payload

    # Dựng NGOÀI lock: chỉ đọc, và giữ lock suốt ~600ms sẽ xếp hàng mọi request
    # khác. Hai request cùng lúc có thể cùng dựng — chấp nhận được. `sig` chụp
    # TRƯỚC khi dựng nên nếu DB đổi giữa chừng thì lần poll sau lệch chữ ký và
    # dựng lại, không bao giờ kẹt ở dữ liệu cũ.
    payload = _build_ebook_rows(cfgs)
    with _cache_lock:
        _cache = (sig, now, payload)
    return payload


def _build_dashboard_data(request: Request) -> dict:
    rows, totals = _ebook_rows_cached()
    total_chapters = totals["total_chapters"]
    queue_snapshot = request.app.state.job.queue.snapshot()
    summary = {
        "ebook_count": len(rows),
        "raw_count": totals["raw_count"],
        "translated_count": totals["translated_count"],
        "raw_pct": round(totals["raw_count"] / total_chapters * 100) if total_chapters else 0,
        "translated_pct": (
            round(totals["translated_count"] / total_chapters * 100) if total_chapters else 0
        ),
        "total_chapters": total_chapters,
        "error_count": totals["error_count"],
        # Không cache: job bắt đầu/kết thúc phải hiện ngay, không đợi chữ ký DB.
        "running_jobs": len(queue_snapshot["running"]),
    }
    return {"rows": rows, "summary": summary}


@router.get("/api/dashboard")
def dashboard_api(request: Request):
    return JSONResponse(_build_dashboard_data(request))
