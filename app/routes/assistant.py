"""Assistant Panel — runtime chat cho SPA /app (Phase 0).

Route mỏng: CRUD thread + gọi LLM qua `openai_client.run_chat`. Mọi logic DB
và resolve config nằm trong `novel2epub/assistant.py`.

Nằm dưới `/api/...` nên tự hưởng `api_token_gate` + CORS hiện tại trong
`app/main.py` — không thêm auth/CORS riêng.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from novel2epub import assistant as assistant_mod
from novel2epub import openai_client
from novel2epub.db import get_thread_connection

from .. import deps

router = APIRouter()

QUEUE_URL = "/queue"


def _conn():
    return get_thread_connection(Path(deps.DB_PATH).resolve())


def _require_ebook(slug: str):
    try:
        return deps.resolved_cfg(slug)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


def _get_thread_or_404(thread_id: int, slug: str) -> dict:
    try:
        thread = assistant_mod.get_thread(_conn(), thread_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    if thread["ebook_slug"] != slug:
        raise HTTPException(status_code=404, detail="Thread không thuộc ebook này.")
    return thread


class ThreadCreateBody(BaseModel):
    provider_base_url: str = ""
    model: str = ""


class ThreadPatchBody(BaseModel):
    provider_base_url: str | None = None
    model: str | None = None


class ChatBody(BaseModel):
    content: str = ""
    chapter_index: int | None = None
    selection: str = ""
    stream: bool = False
    use_tools: bool = True


@router.get("/api/ui/ebooks/{slug}/assistant/defaults")
def assistant_defaults(slug: str):
    """Mặc định LLM từ `ai.openai` của ebook đang mở (fallback global đã merge
    trong `load_config`). Không bao giờ trả api_key."""
    cfg = _require_ebook(slug)
    defaults = assistant_mod.default_provider_for_ebook(cfg)
    return {
        **defaults,
        "api_key_configured": bool(cfg.ai.openai.api_key),
        "timeout_seconds": cfg.ai.openai.timeout_seconds,
    }


@router.get("/api/ui/ebooks/{slug}/assistant/threads")
def assistant_list_threads(slug: str):
    _require_ebook(slug)
    return {"threads": assistant_mod.list_threads(_conn(), slug)}


@router.post("/api/ui/ebooks/{slug}/assistant/threads")
def assistant_create_thread(slug: str, body: ThreadCreateBody):
    cfg = _require_ebook(slug)
    defaults = assistant_mod.default_provider_for_ebook(cfg)
    thread = assistant_mod.create_thread(
        _conn(),
        slug,
        provider_base_url=body.provider_base_url.strip() or defaults["provider_base_url"],
        model=body.model.strip() or defaults["model"],
    )
    return {"thread": thread}


@router.get("/api/ui/ebooks/{slug}/assistant/threads/{thread_id}")
def assistant_get_thread(slug: str, thread_id: int):
    thread = _get_thread_or_404(thread_id, slug)
    messages = assistant_mod.list_messages(_conn(), thread_id)
    return {"thread": thread, "messages": messages}


@router.patch("/api/ui/ebooks/{slug}/assistant/threads/{thread_id}")
def assistant_patch_thread(slug: str, thread_id: int, body: ThreadPatchBody):
    _get_thread_or_404(thread_id, slug)
    thread = assistant_mod.update_thread_provider(
        _conn(), thread_id, body.provider_base_url, body.model
    )
    return {"thread": thread}


@router.delete("/api/ui/ebooks/{slug}/assistant/threads/{thread_id}")
def assistant_delete_thread(slug: str, thread_id: int):
    _get_thread_or_404(thread_id, slug)
    assistant_mod.delete_thread(_conn(), thread_id)
    return {"ok": True}


def _storage_for(slug: str):
    from novel2epub.storage import Storage

    cfg = _require_ebook(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")
    return cfg, storage, manifest


def _run_llm(cfg_base_url_model, prompt: str) -> str:
    try:
        return openai_client.run_chat(cfg_base_url_model, prompt)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


def _run_agent(
    chat_cfg, storage, manifest, prompt: str, history: list[dict], enqueue_job=None
) -> tuple[str, list[dict], list[dict]]:
    try:
        return assistant_mod.run_agent_turn(
            chat_cfg, storage, manifest, prompt, history, enqueue_job=enqueue_job
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


# ── Tools đọc trực tiếp (panel/tools gọi, không qua LLM) ────────────────

@router.get("/api/ui/ebooks/{slug}/assistant/search")
def assistant_search(
    slug: str,
    q: str = "",
    regex: bool = False,
    source: str = "translated",
    scope: str = "all",
    chapter_index: int = 0,
    limit: int = 300,
):
    _require_ebook(slug)
    _, storage, manifest = _storage_for(slug)
    try:
        return assistant_mod.search_ebook(
            storage, manifest, q, regex, source, scope, chapter_index, limit
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/api/ui/ebooks/{slug}/assistant/chapters/{index}")
def assistant_get_chapter(
    slug: str, index: int, include_raw: bool = False, include_translated: bool = True
):
    _require_ebook(slug)
    _, storage, manifest = _storage_for(slug)
    try:
        return assistant_mod.get_chapter(
            storage, manifest, index, include_raw, include_translated
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/api/ui/ebooks/{slug}/assistant/glossary")
def assistant_glossary(slug: str, q: str = "", limit: int = 300):
    _require_ebook(slug)
    _, storage, _manifest = _storage_for(slug)
    return assistant_mod.get_glossary(storage, q, limit)


@router.get("/api/ui/ebooks/{slug}/assistant/characters")
def assistant_characters(slug: str, q: str = "", limit: int = 100):
    _require_ebook(slug)
    _, storage, _manifest = _storage_for(slug)
    return assistant_mod.get_characters(storage, q, limit)


@router.get("/api/ui/ebooks/{slug}/assistant/idioms")
def assistant_idioms(slug: str, q: str = "", limit: int = 100):
    _require_ebook(slug)
    _, storage, _manifest = _storage_for(slug)
    return assistant_mod.get_idioms(storage, q, limit)


def _sse_chunks(text: str, size: int = 200):
    for i in range(0, len(text), size):
        chunk = text[i : i + size]
        yield f"data: {json.dumps({'delta': chunk}, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


@router.post("/api/ui/ebooks/{slug}/assistant/threads/{thread_id}/chat")
def assistant_chat(request: Request, slug: str, thread_id: int, body: ChatBody):
    cfg = _require_ebook(slug)
    thread = _get_thread_or_404(thread_id, slug)
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Nội dung chat trống.")
    prompt = assistant_mod.build_chat_prompt(
        content,
        {"ebook_slug": slug, "chapter_index": body.chapter_index, "selection": body.selection},
    )
    chat_cfg = assistant_mod.resolve_chat_config(cfg, thread)
    if not chat_cfg.base_url or not chat_cfg.model:
        raise HTTPException(status_code=400, detail="Chưa cấu hình provider/model cho thread.")

    conn = _conn()
    assistant_mod.add_message(conn, thread_id, "user", content)
    past = assistant_mod.list_messages(conn, thread_id, limit=20)
    history = [
        {"role": m["role"], "content": m["content"]}
        for m in past
        if m["role"] in ("user", "assistant")
    ]

    def _enqueue_fill(params: dict) -> dict:
        spec = {
            "kind": "assistant-fill-context",
            "params": {
                "slug": slug,
                "chapter_indexes": params.get("chapter_indexes") or [],
                "min_frequency": 2,
                "max_candidates": 100,
                "with_retranslate": params.get("with_retranslate", True),
                "with_characters": params.get("with_characters", True),
                "model_override": thread.get("model") or "",
            },
        }
        started = request.app.state.job.start_custom(
            "assistant-fill-context",
            assistant_fill_context_job_factory(spec["params"]),
            category="translate",
            ebook=slug,
            spec=spec,
            label=f"Assistant fill-context: {slug}",
        )
        if not started:
            raise ValueError("Đang có job khác chạy, vui lòng đợi.")
        return {"queued": True, "queue_url": QUEUE_URL}

    trace: list[dict] = []
    previews: list[dict] = []
    if body.use_tools:
        try:
            _, storage, manifest = _storage_for(slug)
        except HTTPException as e:
            # Ebook chưa có manifest (mới tạo): chat thường, không tool.
            if e.status_code != 404:
                raise
            storage = manifest = None  # type: ignore[assignment]
        if storage is not None:
            reply, trace, previews = _run_agent(
                chat_cfg, storage, manifest, prompt, history[:-1], _enqueue_fill
            )
        else:
            reply = _run_llm(chat_cfg, prompt)
    else:
        reply = _run_llm(chat_cfg, prompt)
    saved = assistant_mod.add_message(conn, thread_id, "assistant", reply)

    if body.stream:
        return StreamingResponse(
            _sse_chunks(reply),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return {
        "thread_id": thread_id, "message_id": saved["id"], "reply": reply,
        "tool_calls": trace, "previews": previews,
    }


class ParaEditPreviewBody(BaseModel):
    index: int = 0
    para_index: int = 0
    new_text: str = ""


class ParaEditApplyBody(BaseModel):
    index: int = 0
    para_index: int = 0
    expected: str = ""
    new_text: str = ""


class GlossaryEditsBody(BaseModel):
    edits: list[dict] = []


class FindReplaceApplyBody(BaseModel):
    find: str = ""
    replace: str = ""
    regex: bool = False
    selections: list[dict] = []
    source: str = "translated"
    all_matches: bool = False


@router.post("/api/ui/ebooks/{slug}/assistant/edits/preview")
def assistant_edits_preview(slug: str, body: ParaEditPreviewBody):
    """Diff 1 đoạn trước khi ghi (read-only) — thẻ preview cho tick chọn."""
    _require_ebook(slug)
    _, storage, manifest = _storage_for(slug)
    try:
        return assistant_mod.preview_paragraph_edit(
            storage, manifest, body.index, body.para_index, body.new_text
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/api/ui/ebooks/{slug}/assistant/edits/apply")
def assistant_edits_apply(slug: str, body: ParaEditApplyBody):
    """Ghi 1 đoạn đã preview: `expected` lệch → 409 (bản dịch đã đổi)."""
    _require_ebook(slug)
    _, storage, manifest = _storage_for(slug)
    try:
        return assistant_mod.apply_paragraph_edit(
            storage, manifest, body.index, body.para_index, body.expected, body.new_text
        )
    except ValueError as e:
        status = 409 if "thay đổi" in str(e) or "Không ghi được" in str(e) else 400
        raise HTTPException(status_code=status, detail=str(e)) from e


@router.post("/api/ui/ebooks/{slug}/assistant/glossary/preview")
def assistant_glossary_preview(slug: str, body: GlossaryEditsBody):
    _require_ebook(slug)
    _, storage, _manifest = _storage_for(slug)
    try:
        return assistant_mod.preview_glossary_edits(storage, body.edits)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/api/ui/ebooks/{slug}/assistant/glossary/apply")
def assistant_glossary_apply(slug: str, body: GlossaryEditsBody):
    _require_ebook(slug)
    _, storage, _manifest = _storage_for(slug)
    try:
        return assistant_mod.apply_glossary_edits(storage, body.edits)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/api/ui/ebooks/{slug}/assistant/find-replace/apply")
def assistant_find_replace_apply(slug: str, body: FindReplaceApplyBody):
    """Áp dụng thay thế cho các đoạn đã chọn từ find-preview (tái dùng cùng
    semantics apply-selected: stale protection + backup meta)."""
    _require_ebook(slug)
    _, storage, manifest = _storage_for(slug)
    try:
        return assistant_mod.apply_selected_replacements(
            storage, manifest, body.find, body.replace, body.regex,
            body.selections, body.source, body.all_matches,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class FindReplacePreviewBatchBody(BaseModel):
    replacements: list[dict] = []
    source: str = "translated"
    scope: str = "all"
    chapter_index: int = 0
    limit: int = 300


class FindReplaceApplyBatchBody(BaseModel):
    groups: list[dict] = []
    source: str = "translated"
    all_matches: bool = False


@router.post("/api/ui/ebooks/{slug}/assistant/find-replace/preview-batch")
def assistant_find_replace_preview_batch(slug: str, body: FindReplacePreviewBatchBody):
    """Preview GỘP nhiều cặp tìm-thay trong một lần gọi (read-only, tối đa 300
    đoạn) — nguồn cho tick chọn theo đoạn của tìm-thay thông minh."""
    _require_ebook(slug)
    _, storage, manifest = _storage_for(slug)
    try:
        return assistant_mod.preview_find_replace_batch(
            storage, manifest, body.replacements, body.source,
            body.scope, body.chapter_index, body.limit,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/api/ui/ebooks/{slug}/assistant/find-replace/apply-batch")
def assistant_find_replace_apply_batch(slug: str, body: FindReplaceApplyBatchBody):
    """Áp dụng nhiều nhóm đã tick chọn: mỗi nhóm một lượt apply-selected,
    cộng dồn replaced/chapters/stale."""
    _require_ebook(slug)
    _, storage, manifest = _storage_for(slug)
    try:
        return assistant_mod.apply_find_replace_batch(
            storage, manifest, body.groups, body.source, body.all_matches
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class FillContextBody(BaseModel):
    chapter_indexes: list[int] = []
    min_frequency: int = 2
    max_candidates: int = 100
    with_retranslate: bool = True
    with_characters: bool = True
    model_override: str = ""


def assistant_fill_context_job_factory(params: dict):
    """Tái tạo job fill ngữ cảnh từ spec đã lưu — sống sót qua restart.

    Job làm 3 việc, kết quả vào hàng chờ duyệt (KHÔNG ghi thẳng glossary hay
    nhân vật, KHÔNG lấp raw/bản dịch):
    1. Dò tên riêng từ raw → `glossary_pending` (thuần CPU).
    2. AI dịch lại hàng loạt mục chưa có Việt (`retranslate_terms` tự chia lô
       theo `prompt_max_chars`) → `glossary_pending`.
    3. AI trích nhân vật/quan hệ (`characters_ai`, gom nhóm theo ngân sách
       prompt) → `characters_pending`.
    """
    from novel2epub import characters_ai, glossary_ai, proper_names

    slug = params["slug"]
    chapter_indexes = [int(i) for i in params.get("chapter_indexes") or []]
    min_frequency = max(1, int(params.get("min_frequency") or 2))
    max_candidates = max(1, int(params.get("max_candidates") or 100))
    with_retranslate = bool(params.get("with_retranslate", True))
    with_characters = bool(params.get("with_characters", True))
    model_override = str(params.get("model_override") or "").strip()

    def _target(log: Callable[[str], None]) -> dict:
        from novel2epub.storage import Storage

        cfg = deps.resolved_cfg(slug)
        ai_cfg = cfg.ai.openai
        if model_override:
            import dataclasses

            ai_cfg = dataclasses.replace(ai_cfg, model=model_override)
        storage = Storage(cfg.output.data_dir, cfg.novel.slug)
        manifest = storage.load_manifest()
        if manifest is None:
            raise RuntimeError("Chưa có manifest.")
        selected = set(chapter_indexes)
        outcome: dict = {}

        # 1. Tên riêng từ raw.
        texts = [
            (ch.index, storage.read_raw(ch))
            for ch in manifest.chapters
            if (not selected or ch.index in selected) and storage.has_raw(ch)
        ]
        if texts:
            candidates = proper_names.extract_proper_name_candidates(
                texts, min_frequency=min_frequency, max_candidates=max_candidates
            )
            queued = proper_names.queue_proper_name_candidates(storage, candidates)
            log(f"[fill-context] Quét {len(texts)} chương raw: {queued['detected']} ứng viên,"
                f" {queued['queued']} vào hàng chờ duyệt.")
            outcome["extract"] = {"scanned_chapters": len(texts), **queued}
        else:
            log("[fill-context] Không có chương raw nào để quét.")
            outcome["extract"] = {"scanned_chapters": 0}

        # 2. AI dịch lại các mục chưa có Việt (chia lô theo prompt_max_chars).
        if with_retranslate:
            from .glossary import _normalize_pending, _read_pending

            pending = {p["source"]: p for p in _read_pending(storage)}
            current = {s: (t, n) for s, t, n in storage.read_glossary_entries_merged()}
            base: dict[str, tuple[str, str]] = dict(current)
            for src, prow in pending.items():
                base[src] = (prow["target"], prow.get("note", ""))
            entries = [
                {"source": s, "target": t, "note": n}
                for s, (t, n) in base.items()
                if not t.strip() or t.strip() == s.strip()
            ]
            if not entries:
                log("[fill-context] Không còn mục nào thiếu Việt để dịch lại.")
                outcome["retranslate"] = {"requested": 0, "queued": 0}
            else:
                story = {"title": cfg.novel.title, "author": cfg.novel.author,
                         "description": cfg.novel.description}
                log(f"[fill-context] Nhờ AI dịch lại {len(entries)} mục"
                    f" (lô theo prompt_max_chars={cfg.translate.prompt_max_chars or 20000})…")
                results = glossary_ai.retranslate_terms(
                    ai_cfg, entries, story=story,
                    context=cfg.translate.context_note,
                    genre=cfg.translate.genre,
                    max_chars=cfg.translate.prompt_max_chars or 20000,
                    log=log,
                )
                additions = [
                    {"source": r["source"], "target": r["target"],
                     "existing_target": current.get(r["source"], ("", ""))[0],
                     "chapter_index": 0, "note": r.get("reason") or base[r["source"]][1]}
                    for r in results if r["target"] != base.get(r["source"], ("", ""))[0]
                ]

                def _merge(raw):
                    fresh = {row["source"] for row in additions}
                    kept = [row for row in _normalize_pending(raw) if row["source"] not in fresh]
                    return kept + additions

                merged = storage.update_extra_json("glossary_pending", _merge)
                log(f"[fill-context] {len(additions)} mục vào hàng chờ (tổng {len(merged)}).")
                outcome["retranslate"] = {"requested": len(entries), "queued": len(additions)}

        # 3. Trích nhân vật/quan hệ.
        if with_characters:
            chapters = []
            for ch in manifest.chapters:
                if selected and ch.index not in selected:
                    continue
                raw = storage.read_raw(ch)
                if not raw.strip():
                    continue
                translated = (
                    storage.read_active_branch_text(ch)
                    if storage.has_active_branch_text(ch) else ""
                )
                chapters.append((ch.index, raw, translated))
            if not chapters:
                log("[fill-context] Không có chương raw nào để trích nhân vật.")
                outcome["characters"] = {"characters": 0, "relations": 0}
            else:
                existing = {r[0]: r[1] for r in storage.read_character_entries()}
                glossary = {s: t for s, t, _n in storage.read_glossary_entries_merged()}
                result = characters_ai.extract_characters(
                    ai_cfg, chapters, existing, glossary,
                    genre=cfg.translate.genre,
                    max_chars=cfg.translate.prompt_max_chars or 20000,
                    log=log,
                )
                storage.write_extra_json("characters_pending", result)
                log(f"[fill-context] {len(result['characters'])} nhân vật,"
                    f" {len(result['relations'])} quan hệ vào hàng chờ duyệt.")
                outcome["characters"] = {
                    "characters": len(result["characters"]),
                    "relations": len(result["relations"]),
                }
        return outcome

    return _target


@router.post("/api/ui/ebooks/{slug}/assistant/fill-context")
def assistant_fill_context(request: Request, slug: str, body: FillContextBody):
    """Enqueue MỘT job fill ngữ cảnh (category=translate, khoá ebook).

    Task lâu (AI dịch hàng loạt + trích nhân vật mất hàng phút) không chạy
    trong request — tiến độ xem ở `/queue`, kết quả vào hàng chờ duyệt.
    """
    _require_ebook(slug)
    spec = {
        "kind": "assistant-fill-context",
        "params": {
            "slug": slug,
            "chapter_indexes": [int(i) for i in body.chapter_indexes],
            "min_frequency": body.min_frequency,
            "max_candidates": body.max_candidates,
            "with_retranslate": body.with_retranslate,
            "with_characters": body.with_characters,
            "model_override": body.model_override.strip(),
        },
    }
    started = request.app.state.job.start_custom(
        "assistant-fill-context",
        assistant_fill_context_job_factory(spec["params"]),
        category="translate",
        ebook=slug,
        spec=spec,
        chapter_indexes=spec["params"]["chapter_indexes"] or None,
        label=f"Assistant fill-context: {slug}",
    )
    if not started:
        raise HTTPException(status_code=409, detail="Đang có job khác chạy, vui lòng đợi.")
    return {"started": True, "queue_url": QUEUE_URL}


class GenericChatBody(BaseModel):
    ebook_slug: str = ""
    thread_id: int = 0
    content: str = ""
    chapter_index: int | None = None
    selection: str = ""
    stream: bool = False
    use_tools: bool = True


@router.post("/api/ui/assistant/chat")
def assistant_chat_generic(request: Request, body: GenericChatBody):
    """Alias đúng tên trong kế hoạch (`/api/ui/assistant/chat`) — đọc
    provider/model của thread rồi gọi cùng path với route theo ebook."""
    slug = (body.ebook_slug or "").strip()
    if not slug or not body.thread_id:
        raise HTTPException(status_code=400, detail="Cần ebook_slug và thread_id.")
    return assistant_chat(
        request,
        slug,
        body.thread_id,
        ChatBody(
            content=body.content,
            chapter_index=body.chapter_index,
            selection=body.selection,
            stream=body.stream,
            use_tools=body.use_tools,
        ),
    )



