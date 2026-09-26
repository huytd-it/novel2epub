"""AI Harness scan and review API. All endpoints use the app's API auth gate."""
from __future__ import annotations

from pathlib import Path
import hashlib
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from novel2epub import ai_harness as workflow
from novel2epub.db import get_thread_connection
from novel2epub.storage import Storage

from .. import deps

router = APIRouter()


def _conn():
    return get_thread_connection(Path(deps.DB_PATH).resolve())


def _storage(slug: str):
    try:
        cfg = deps.resolved_cfg(slug)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy truyện") from exc
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=400, detail="Truyện chưa có mục lục")
    return cfg, storage, manifest


def scan_job_factory(params: dict):
    slug, run_id = params["slug"], int(params["run_id"])

    def target(log):
        conn = _conn()
        with conn:
            conn.execute("UPDATE ai_harness_runs SET status='running' WHERE id=?", (run_id,))
        try:
            cfg, storage, manifest = _storage(slug)
            chapters = {ch.index: ch for ch in manifest.chapters}
            pending = conn.execute(
                "SELECT chapter_index FROM ai_harness_chapters WHERE run_id=? AND status='queued' ORDER BY chapter_index",
                (run_id,),
            ).fetchall()
            for item in pending:
                index = item["chapter_index"]
                ch = chapters.get(index)
                try:
                    if ch is None:
                        raise ValueError("Chương đã bị xóa")
                    issues = workflow.scan_chapter(cfg, storage, ch)
                    workflow.save_chapter_result(conn, run_id, index, issues)
                    log(f"[ai-harness] Chương {index}: {len(issues)} đề xuất")
                except Exception as exc:
                    # API/provider exceptions may contain request details; never persist secrets.
                    error = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                    workflow.save_chapter_result(conn, run_id, index, None, error)
                    log(f"[ai-harness] Chương {index} thất bại: {error}")
        except Exception:
            with conn:
                conn.execute("UPDATE ai_harness_runs SET status='failed' WHERE id=?", (run_id,))
            raise
        workflow.finish_run(conn, run_id)

    return target


@router.get("/api/ui/ebooks/{slug}/ai-harness/runs")
def list_runs(slug: str):
    return {"runs": workflow.list_runs(_conn(), slug)}


@router.post("/api/ui/ebooks/{slug}/ai-harness/runs")
def start_run(request: Request, slug: str):
    _cfg, storage, manifest = _storage(slug)
    indexes = [ch.index for ch in manifest.chapters if storage.has_active_branch_text(ch)]
    if not indexes:
        raise HTTPException(status_code=400, detail="Truyện chưa có chương đã dịch")
    conn = _conn()
    active = conn.execute(
        "SELECT id FROM ai_harness_runs WHERE ebook_slug=? AND status IN ('queued','running') LIMIT 1", (slug,)
    ).fetchone()
    if active:
        raise HTTPException(status_code=409, detail="Truyện đang có lượt rà soát chưa xong")
    run_id = workflow.create_run(conn, slug, indexes)
    spec = {"kind": "ai-harness-scan", "params": {"slug": slug, "run_id": run_id}}
    started = request.app.state.job.start_custom(
        "ai-harness-scan", scan_job_factory(spec["params"]), category="translate",
        ebook=slug, spec=spec, chapter_indexes=indexes, label=f"AI Harness: {slug}",
    )
    if not started:
        with conn:
            conn.execute("UPDATE ai_harness_runs SET status='failed', finished_at=datetime('now') WHERE id=?", (run_id,))
        raise HTTPException(status_code=409, detail="Không thể xếp job rà soát")
    return {"run_id": run_id, "queue_url": "/queue"}


def _run(slug: str, run_id: int):
    run = workflow.get_run(_conn(), slug, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy lượt rà soát")
    return run


@router.get("/api/ui/ebooks/{slug}/ai-harness/runs/{run_id}")
def get_run(slug: str, run_id: int):
    return _run(slug, run_id)


@router.get("/api/ui/ebooks/{slug}/ai-harness/runs/{run_id}/report.md")
def report_markdown(slug: str, run_id: int):
    return PlainTextResponse(
        workflow.export_markdown(_run(slug, run_id)),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="ai-harness-{slug}-{run_id}.md"'},
    )


class Selection(BaseModel):
    ids: list[int]


class Approval(Selection):
    token: str


def _preview_token(ids: list[int], preview: dict) -> str:
    payload = json.dumps({"ids": sorted(ids), "preview": preview}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _selected(slug: str, run_id: int, ids: list[int], *, allow_blocked: bool = False):
    _run(slug, run_id)
    try:
        return workflow.selected_issues(_conn(), slug, run_id, ids, allow_blocked=allow_blocked)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/ui/ebooks/{slug}/ai-harness/runs/{run_id}/preview")
def preview(slug: str, run_id: int, body: Selection):
    _cfg, storage, manifest = _storage(slug)
    rows = _selected(slug, run_id, body.ids)
    try:
        result = workflow.preview_selected(storage, manifest, rows)
        return {**result, "token": _preview_token(body.ids, result)}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/ui/ebooks/{slug}/ai-harness/runs/{run_id}/apply")
def apply(slug: str, run_id: int, body: Approval):
    _cfg, storage, manifest = _storage(slug)
    rows = _selected(slug, run_id, body.ids)
    try:
        current = workflow.preview_selected(storage, manifest, rows)
        if body.token != _preview_token(body.ids, current):
            raise ValueError("Preview đã cũ; xem trước lại trước khi áp dụng")
        return workflow.apply_selected(_conn(), storage, manifest, rows)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/ui/ebooks/{slug}/ai-harness/runs/{run_id}/dismiss")
def dismiss(slug: str, run_id: int, body: Selection):
    rows = _selected(slug, run_id, body.ids, allow_blocked=True)
    with _conn() as conn:
        conn.executemany("UPDATE ai_harness_issues SET status='dismissed' WHERE id=?", [(row["id"],) for row in rows])
    return {"dismissed": len(rows)}
