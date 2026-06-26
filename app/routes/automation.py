"""CRUD automation + chạy ngay (xem spec automation-scheduling)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from novel2epub.automation import STEPS, add_automation, load_automations, remove_automation, update_automation

from .. import deps

router = APIRouter()


def _ebook_slugs() -> list[str]:
    library = deps.library()
    return list(library.ebooks.keys()) if library.ebooks else ["default"]


@router.get("/automation")
def automation_page(request: Request):
    automations = load_automations(deps.AUTOMATIONS_PATH)
    return deps.templates.TemplateResponse(
        request,
        "automation.html",
        {"automations": automations.values(), "ebooks": _ebook_slugs(), "steps": STEPS},
    )


@router.post("/automation")
def automation_create(
    ebook: str = Form(...),
    steps: Annotated[list[str], Form()] = [],
    schedule: str = Form("manual"),
):
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
