"""CRUD automation + chạy ngay (xem spec automation-scheduling / cron-schedule)."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from novel2epub.automation import (
    STEPS,
    add_automation,
    load_automations,
    remove_automation,
    update_automation,
    validate_schedule,
)

from .. import deps
from ..scheduler import next_run_at

router = APIRouter()


def _require_valid_schedule(schedule: str) -> None:
    if not validate_schedule(schedule):
        raise HTTPException(
            status_code=400,
            detail=f"Lịch không hợp lệ: {schedule!r} — dùng 'manual' hoặc cron 5 trường, ví dụ '*/30 * * * *'.",
        )


def _ebook_options() -> list[dict[str, str]]:
    library = deps.library()
    if not library.ebooks:
        return [{"slug": "default", "title": "default"}]
    options = []
    for slug, entry in library.ebooks.items():
        cfg = deps.resolved_cfg(slug)
        options.append({"slug": slug, "title": entry.name or cfg.novel.title or slug})
    return sorted(options, key=lambda ebook: ebook["title"].casefold())


@router.get("/api/automation/validate-schedule")
def automation_validate_schedule(schedule: str):
    return {"valid": validate_schedule(schedule.strip())}


@router.post("/automation")
def automation_create(
    ebook: str = Form(...),
    steps: Annotated[list[str], Form()] = [],
    schedule: str = Form("manual"),
    crawl_workers: int = Form(4, ge=1),
    translate_workers: int = Form(4, ge=1),
):
    _require_valid_schedule(schedule)
    steps = [s for s in steps if s in STEPS] or ["build"]
    add_automation(
        deps.AUTOMATIONS_PATH, ebook, steps, schedule,
        crawl_workers=crawl_workers, translate_workers=translate_workers,
    )
    return RedirectResponse(url="/automation", status_code=303)


@router.post("/automation/{automation_id}/update")
def automation_update(
    automation_id: str,
    steps: Annotated[list[str], Form()] = [],
    schedule: str = Form("manual"),
    enabled: bool = Form(False),
):
    _require_valid_schedule(schedule)
    steps = [s for s in steps if s in STEPS] or ["build"]
    try:
        update_automation(deps.AUTOMATIONS_PATH, automation_id, {
            "steps": steps, "schedule": schedule, "enabled": enabled,
        })
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return RedirectResponse(url="/automation", status_code=303)


@router.post("/automation/{automation_id}/delete")
def automation_delete(automation_id: str):
    remove_automation(deps.AUTOMATIONS_PATH, automation_id)
    return RedirectResponse(url="/automation", status_code=303)


@router.post("/automation/{automation_id}/run-now")
def automation_run_now(request: Request, automation_id: str):
    job_id = request.app.state.scheduler.run_now(automation_id)
    if job_id is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy automation.")
    return RedirectResponse(url="/automation", status_code=303)
