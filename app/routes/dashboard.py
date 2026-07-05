"""Dashboard tổng hợp nhiều ebook: tiến độ cào/dịch, lỗi automation, chi phí
dịch, dung lượng đĩa — dùng cho tính năng automation liên tục (bulk import)."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from novel2epub.automation import load_automations
from novel2epub.progress import chapter_progress, han_fixed_total
from novel2epub.storage import Storage
from novel2epub.toc import crawl_problem_indexes

from .. import deps
from ..cost_summary import read_cost_summary
from ..storage_report import ebook_storage_report

router = APIRouter()


def _ebook_slugs() -> list[str]:
    library = deps.library()
    return list(library.ebooks.keys()) if library.ebooks else []


def _build_dashboard_data(request: Request) -> dict:
    automations = load_automations(deps.AUTOMATIONS_PATH)
    rows = []
    total_raw = total_translated = total_chapters = 0
    error_count = 0

    for slug in _ebook_slugs():
        cfg = deps.resolved_cfg(slug)
        storage = Storage(cfg.output.data_dir, cfg.novel.slug)
        manifest = storage.load_manifest()
        progress = chapter_progress(storage, manifest)
        crawl_problems = crawl_problem_indexes(manifest.chapters, storage) if manifest else []
        han_fixed = han_fixed_total(storage, manifest)
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
            "name": cfg.novel.title or slug,
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

    queue_snapshot = request.app.state.job.queue.snapshot()
    summary = {
        "ebook_count": len(rows),
        "raw_count": total_raw,
        "translated_count": total_translated,
        "raw_pct": round(total_raw / total_chapters * 100) if total_chapters else 0,
        "translated_pct": round(total_translated / total_chapters * 100) if total_chapters else 0,
        "total_chapters": total_chapters,
        "error_count": error_count,
        "running_jobs": len(queue_snapshot["running"]),
    }
    return {"rows": rows, "summary": summary}


@router.get("/dashboard")
def dashboard_page(request: Request):
    data = _build_dashboard_data(request)
    return deps.templates.TemplateResponse(request, "dashboard.html", data)


@router.get("/api/dashboard")
def dashboard_api(request: Request):
    return JSONResponse(_build_dashboard_data(request))
