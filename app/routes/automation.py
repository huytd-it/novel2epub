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


def _ebook_slugs() -> list[str]:
    library = deps.library()
    return list(library.ebooks.keys()) if library.ebooks else ["default"]


@router.get("/automation")
def automation_page(request: Request):
    automations = load_automations(deps.AUTOMATIONS_PATH)
    now = datetime.now()
    next_runs = {}
    for a in automations.values():
        nxt = next_run_at(a, now)
        next_runs[a.id] = nxt.strftime("%Y-%m-%d %H:%M") if nxt else ""
    return deps.templates.TemplateResponse(
        request,
        "automation.html",
        {"automations": automations.values(), "ebooks": _ebook_slugs(),
         "steps": STEPS, "next_runs": next_runs},
    )


@router.post("/automation")
def automation_create(
    ebook: str = Form(...),
    steps: Annotated[list[str], Form()] = [],
    schedule: str = Form("manual"),
):
    _require_valid_schedule(schedule)
    steps = [s for s in steps if s in STEPS] or ["build"]
    add_automation(deps.AUTOMATIONS_PATH, ebook, steps, schedule)
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
