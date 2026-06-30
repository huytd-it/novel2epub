"""Xem & sửa tay 1 chương (raw + bản dịch)."""
from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

import html

from novel2epub import bulk_transfer, footnotes
from novel2epub.pipeline import (
    step_crawl_selected,
    step_delete_translation_selected,
    step_retranslate_title,
    step_review_chapter,
    step_rewrite_preview,
    step_suggest_chapter,
    step_translate_selected,
)
from novel2epub.storage import Storage
from novel2epub.toc import count_words

from novel2epub.openai_client import run_chat as openai_run_chat

from .. import deps
from .glossary import _append_glossary_entry

_AI_STEPS = {
    "review": step_review_chapter,
    "suggest": step_suggest_chapter,
    "rewrite": step_rewrite_preview,
}

router = APIRouter()


def _chapter_glossary(storage: Storage, raw: str, translated: str) -> list[dict[str, str | bool | int]]:
    """Return glossary rows with entries used in this chapter first.

    raw_count/translated_count đếm số lần xuất hiện literal trong chương, dùng
    để soi vị trí (jump-to) và phát hiện thiếu thống nhất (vd có trong raw mà
    không thấy trong bản dịch).
    """
    haystack = f"{raw}\n{translated}".lower()
    notes = storage.read_glossary_notes()
    rows: list[dict[str, str | bool | int]] = []
    for filename, label in (("names.txt", "Tên riêng"), ("vietphrase.txt", "Thuật ngữ")):
        for source, suggested in storage.read_glossary_file(filename).items():
            source_hit = source.lower() in haystack if source else False
            suggested_hit = suggested.lower() in haystack if suggested else False
            raw_count = raw.count(source) if source else 0
            translated_count = translated.count(suggested) if suggested else 0
            rows.append({
                "source": source,
                "suggested": suggested,
                "note": notes.get(suggested, ""),
                "file": filename,
                "type": label,
                "relevant": source_hit or suggested_hit,
                "raw_count": raw_count,
                "translated_count": translated_count,
                "mismatch": raw_count > 0 and translated_count == 0,
            })
    return sorted(rows, key=lambda row: (not row["relevant"], str(row["type"]), str(row["source"])))


# Nhãn tiếng Việt cho category của AI review, gắn với mục III docs/rule.md.
_CATEGORY_LABELS = {
    "glossary": "Glossary",
    "consistency": "Nhất quán",
    "mistranslation": "Sai nghĩa",
    "hanviet": "Hán Việt",
    "fluency": "Văn phong",
    "other": "Khác",
}


def _render_translated_preview(storage: Storage, translated: str) -> tuple[str, list[dict]]:
    """Đánh dấu footnote trong bản dịch để hiện preview kèm chú thích trên web.

    Chỉ dùng để hiển thị (textarea sửa tay vẫn giữ text thuần, không có marker).
    """
    notes = storage.read_glossary_notes()
    marked, footnote_list = footnotes.annotate(translated, notes)
    escaped = "\n".join(
        f"<p>{footnotes.markers_to_html(html.escape(line))}</p>" if line.strip() else ""
        for line in marked.splitlines()
    )
    return escaped, footnote_list


def _chapter_context(storage: Storage, ch, raw: str, translated: str, slug: str, meta: dict | None = None) -> dict:
    glossary_rows = _chapter_glossary(storage, raw, translated)
    translated_preview_html, footnote_list = _render_translated_preview(storage, translated)
    # Cột "VI" (bản dịch máy) trong editor 3 cột: snapshot bản máy nếu có; chương
    # cũ chưa có snapshot thì degrade an toàn về bản dịch hiện hành (read-only).
    translated_mt = storage.read_translated_mt(ch) if storage.has_translated_mt(ch) else translated
    # Chuẩn bị dữ liệu paragraph để render table so sánh (raw || MT || biên tập)
    raw_paras = raw.split("\n") if raw else [""]
    mt_paras = translated_mt.split("\n") if translated_mt else [""]
    edit_paras = translated.split("\n") if translated else [""]
    num_paras = max(len(raw_paras), len(mt_paras), len(edit_paras))
    raw_paras += [""] * (num_paras - len(raw_paras))
    mt_paras += [""] * (num_paras - len(mt_paras))
    edit_paras += [""] * (num_paras - len(edit_paras))
    # Loại bỏ các row có raw trống (blank line, trailing newline)
    filtered = [(r, m, e) for r, m, e in zip(raw_paras, mt_paras, edit_paras) if r.strip()]
    if not filtered:
        filtered = [("", "", "")]
    raw_paras = [f[0] for f in filtered]
    mt_paras = [f[1] for f in filtered]
    edit_paras = [f[2] for f in filtered]
    num_paras = len(raw_paras)
    return {
        "ch": ch,
        "raw": raw,
        "translated": translated,
        "translated_mt": translated_mt,
        "translated_preview_html": translated_preview_html,
        "footnote_list": footnote_list,
        "footnotes_html": footnotes.render_footnotes_html(footnote_list),
        "raw_char_count": len(raw),
        "translated_word_count": count_words(translated),
        "slug": slug,
        "meta": meta or {},
        "glossary_rows": glossary_rows,
        "glossary_relevant_count": sum(1 for row in glossary_rows if row["relevant"]),
        "CATEGORY_LABELS": _CATEGORY_LABELS,
        "raw_paras": raw_paras,
        "mt_paras": mt_paras,
        "edit_paras": edit_paras,
        "num_paras": num_paras,
    }


@router.get("/chapters/{index}")
def chapter_detail(request: Request, index: int):
    cfg = deps.cfg()
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")
    ch = next((c for c in manifest.chapters if c.index == index), None)
    if ch is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy chương.")

    raw = storage.read_raw(ch) if storage.has_raw(ch) else ""
    translated = storage.read_translated(ch) if storage.has_translated(ch) else ""
    meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
    return deps.templates.TemplateResponse(
        request,
        "chapter.html",
        _chapter_context(storage, ch, raw, translated, cfg.novel.slug, meta),
    )


@router.get("/ebooks/{slug}/chapters/{index}")
def ebook_chapter_detail(request: Request, slug: str, index: int):
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")
    ch = next((c for c in manifest.chapters if c.index == index), None)
    if ch is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy chương.")

    raw = storage.read_raw(ch) if storage.has_raw(ch) else ""
    translated = storage.read_translated(ch) if storage.has_translated(ch) else ""
    meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
    return deps.templates.TemplateResponse(
        request,
        "chapter.html",
        _chapter_context(storage, ch, raw, translated, slug, meta),
    )


@router.post("/chapters/{index}")
def chapter_save(index: int, translated: str = Form(...)):
    """Lưu bản dịch sửa tay — chính là khâu 'edit' cuối cùng trước khi build."""
    cfg = deps.cfg()
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")
    ch = next((c for c in manifest.chapters if c.index == index), None)
    if ch is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy chương.")

    storage.write_translated(ch, translated)
    return RedirectResponse(url=f"/chapters/{index}", status_code=303)


@router.post("/ebooks/{slug}/chapters/{index}")
def ebook_chapter_save(slug: str, index: int, translated: str = Form(...)):
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")
    ch = next((c for c in manifest.chapters if c.index == index), None)
    if ch is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy chương.")

    storage.write_translated(ch, translated)
    return RedirectResponse(url=f"/ebooks/{slug}/chapters/{index}", status_code=303)


@router.post("/ebooks/{slug}/chapters/{index}/action")
def ebook_chapter_action(request: Request, slug: str, index: int, action: str = Form(...), override: bool = Form(False), translate_backend: str = Form("hachimimt")):
    cfg = deps.resolved_cfg(slug)
    if action == "translate" and translate_backend:
        cfg.translate.type = translate_backend

    def _target(log):
        if action == "crawl":
            step_crawl_selected(cfg, log, force=override, selected_indexes=[index])
        elif action == "translate":
            step_translate_selected(cfg, log, force=override, selected_indexes=[index])
        else:
            raise ValueError(f"action không hợp lệ: {action!r}")

    started = request.app.state.job.start_custom(f"chapter-{action}", _target, category=action)
    if not started:
        raise HTTPException(status_code=409, detail="Đang có job khác chạy, vui lòng đợi.")
    return RedirectResponse(url=f"/ebooks/{slug}/chapters/{index}", status_code=303)


@router.post("/ebooks/{slug}/chapters/{index}/delete-translation")
def ebook_chapter_delete_translation(request: Request, slug: str, index: int):
    cfg = deps.resolved_cfg(slug)

    def _target(log):
        step_delete_translation_selected(cfg, log, selected_indexes=[index])

    started = request.app.state.job.start_custom(f"delete-translation-{index}", _target, category="translate")
    if not started:
        raise HTTPException(status_code=409, detail="Đang có job khác chạy, vui lòng đợi.")
    return RedirectResponse(url=f"/ebooks/{slug}/chapters/{index}", status_code=303)


@router.post("/api/ebooks/{slug}/chapters/{index}/retranslate-title")
async def api_ebook_chapter_retranslate_title(
    request: Request,
    slug: str,
    index: int,
    engine: str = Form(None),
    model: str = Form(None),
    custom_prompt: str = Form(None),
    generate_description: bool = Form(True),
):
    """Dịch lại tiêu đề chương dùng nội dung đã dịch làm ngữ cảnh.

    Yêu cầu chương đã có bản dịch.
    Trả JSON {title_vi, title_note, title_zh, title_description}.
    """
    cfg = deps.resolved_cfg(slug)
    try:
        result = step_retranslate_title(
            cfg,
            slug=slug,
            index=index,
            engine=engine,
            model=model,
            custom_prompt=custom_prompt,
            generate_description=generate_description,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse(result)


# --- AI hỗ trợ ngay trong editor: review / rewrite-preview / suggest glossary ---


def _load_chapter_or_404(cfg, index: int):
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")
    ch = next((c for c in manifest.chapters if c.index == index), None)
    if ch is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy chương.")
    return storage, ch


@router.post("/ebooks/{slug}/chapters/{index}/ai/rewrite/apply")
def ebook_chapter_ai_rewrite_apply(slug: str, index: int):
    """Người review chấp nhận bản nháp AI: chuyển bản dịch hiện tại sang
    before_rewrite (để khôi phục), ghi bản nháp thành bản dịch, xóa preview."""
    cfg = deps.resolved_cfg(slug)
    storage, ch = _load_chapter_or_404(cfg, index)
    meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
    preview = (meta.get("ai_rewrite") or {}).get("text", "")
    if not preview.strip():
        raise HTTPException(status_code=400, detail="Không có bản nháp AI để áp dụng.")
    current = storage.read_translated(ch) if storage.has_translated(ch) else ""
    meta["before_rewrite"] = current
    meta.pop("ai_rewrite", None)
    storage.write_translated(ch, preview)
    storage.write_meta(ch, meta)
    return RedirectResponse(url=f"/ebooks/{slug}/chapters/{index}", status_code=303)


@router.post("/ebooks/{slug}/chapters/{index}/ai/rewrite/discard")
def ebook_chapter_ai_rewrite_discard(slug: str, index: int):
    cfg = deps.resolved_cfg(slug)
    storage, ch = _load_chapter_or_404(cfg, index)
    meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
    if meta.pop("ai_rewrite", None) is not None:
        storage.write_meta(ch, meta)
    return RedirectResponse(url=f"/ebooks/{slug}/chapters/{index}", status_code=303)


@router.post("/ebooks/{slug}/chapters/{index}/ai/review/dismiss")
def ebook_chapter_ai_review_dismiss(slug: str, index: int):
    cfg = deps.resolved_cfg(slug)
    storage, ch = _load_chapter_or_404(cfg, index)
    meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
    if meta.pop("ai_review", None) is not None:
        storage.write_meta(ch, meta)
    return RedirectResponse(url=f"/ebooks/{slug}/chapters/{index}", status_code=303)


@router.post("/ebooks/{slug}/chapters/{index}/ai/suggest/apply")
async def ebook_chapter_ai_suggest_apply(slug: str, index: int, request: Request):
    """Thêm các đề xuất glossary được tick vào names/vietphrase rồi xóa khỏi meta."""
    cfg = deps.resolved_cfg(slug)
    storage, ch = _load_chapter_or_404(cfg, index)
    form = await request.form()
    i = 0
    while f"source_{i}" in form:
        if f"selected_{i}" in form:
            _append_glossary_entry(
                storage,
                form.get(f"target_file_{i}", ""),
                form.get(f"source_{i}", ""),
                form.get(f"suggested_{i}", ""),
            )
        i += 1
    meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
    if meta.pop("ai_suggestions", None) is not None:
        storage.write_meta(ch, meta)
    return RedirectResponse(url=f"/ebooks/{slug}/chapters/{index}", status_code=303)


@router.post("/ebooks/{slug}/chapters/{index}/ai/{op}")
def ebook_chapter_ai(request: Request, slug: str, index: int, op: str):
    """Chạy AI review / rewrite-preview / suggest cho ĐÚNG chương này (job nền)."""
    cfg = deps.resolved_cfg(slug)
    step = _AI_STEPS.get(op)
    if step is None:
        raise HTTPException(status_code=400, detail=f"Thao tác AI không hợp lệ: {op!r}")

    def _target(log):
        step(cfg, log, index=index)

    started = request.app.state.job.start_custom(f"ai-{op}-{index}", _target, category="translate")
    if not started:
        raise HTTPException(status_code=409, detail="Đang có job khác chạy, vui lòng đợi.")
    return RedirectResponse(url=f"/ebooks/{slug}/chapters/{index}", status_code=303)


# --- API JSON cho UI poll trong khi job dịch đang chạy ---


def _chapter_translated_payload(storage: Storage, ch) -> dict:
    """Trả payload {text, complete, mtime, char_count} cho endpoint JSON.

    `mtime` = 0 nếu file chưa tồn tại (chapters chưa được dịch); `complete`
    = False khi meta thiếu hoặc `complete != True` (partial do job crash).
    Xem spec `translate-chunk-streaming` requirement: web-api.
    """
    p = storage.translated_path(ch)
    if p.exists():
        text = p.read_text(encoding="utf-8")
        mtime = p.stat().st_mtime
    else:
        text = ""
        mtime = 0.0
    meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
    complete = bool(meta.get("complete", False))
    return {
        "text": text,
        "complete": complete,
        "mtime": mtime,
        "char_count": len(text),
    }


@router.get("/api/ebooks/{slug}/chapters/{index}/translated")
def api_ebook_chapter_translated(slug: str, index: int):
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")
    ch = next((c for c in manifest.chapters if c.index == index), None)
    if ch is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy chương.")
    return JSONResponse(_chapter_translated_payload(storage, ch))


_POLISH_PROMPT = """Bạn là biên tập viên truyện dịch Trung → Việt.
Hãy BIÊN TẬP LẠI bản dịch Việt sau cho mượt mà, dễ hiểu, tự nhiên hơn.
Tham khảo bản gốc Trung để hiểu đúng ngữ cảnh và nghĩa.

Nguyên tắc:
- Giữ nguyên nội dung, KHÔNG thêm bớt hay giải thích
- Đối chiếu với bản gốc để đảm bảo nghĩa không bị sai lệch
- Chỉ trả về đoạn văn đã biên tập, không kèm lời dẫn hay code fence

--- Bản gốc (Trung) ---
{text_zh}

--- Bản dịch cần biên tập ---
{text}"""

_EXPLAIN_PROMPT = """Bạn là trợ lý dịch thuật Trung → Việt.
Hãy GIẢI THÍCH đoạn văn dịch sau: các từ Hán Việt khó, thành ngữ, điển tích,
hoặc cách hiểu câu văn. Trả lời ngắn gọn bằng tiếng Việt, phù hợp với người
đang review bản dịch.

Đoạn văn:
{text}"""

_EXPLAIN_TERMS_PROMPT = """Bạn là trợ lý dịch thuật Trung → Việt.
Hãy liệt kê và giải thích ngắn gọn các từ ngữ QUAN TRỌNG trong đoạn văn sau:

1. **Tên riêng Hán-Việt**: nhân vật, địa danh, môn phái, chức danh
2. **Thành ngữ/điển tích**: các cụm từ có nghĩa ẩn dụ
3. **Thuật ngữ đặc thù**: từ liên quan đến martial arts, võ công, tôn giáo...

Định dạng mỗi mục:
**Từ gốc** (Hán): giải thích ngắn gọn

KHÔNG tóm tắt nội dung đoạn văn. Chỉ liệt kê và giải thích từ ngữ.

Đoạn văn:
{text}"""


def _call_openai(cfg, prompt: str) -> str:
    result = openai_run_chat(cfg.translate.openai, prompt).strip()
    lines = result.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


@router.post("/api/ebooks/{slug}/chapters/{index}/parapolish")
def api_ebook_chapter_parapolish(slug: str, index: int, text: str = Form(...), text_zh: str = Form("")):
    """Biên tập 1 đoạn văn bằng AI — mượt/dễ hiểu hơn, không thay đổi nội dung.
    
    text: bản dịch Việt cần biên tập
    text_zh: bản gốc Trung (để AI tham khảo ngữ cảnh)
    """
    cfg = deps.resolved_cfg(slug)
    if not cfg.translate.openai.api_key and not cfg.translate.openai.base_url:
        raise HTTPException(status_code=400, detail="Chưa cấu hình OpenAI.")
    try:
        polished = _call_openai(cfg, _POLISH_PROMPT.format(text=text, text_zh=text_zh or "(không có)"))
        return JSONResponse({"polished": polished})
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/api/ebooks/{slug}/chapters/{index}/paraexplain")
def api_ebook_chapter_paraexplain(
    slug: str,
    index: int,
    text: str = Form(...),
    type: str = Form("terms"),  # "terms" | "full"
):
    """Giải thích từ ngữ tập trung vào tên riêng, thành ngữ — hỗ trợ review bản dịch.
    
    type: "terms" = giải thích tập trung (mặc định), "full" = giải thích toàn bộ (cũ)
    """
    cfg = deps.resolved_cfg(slug)
    if not cfg.translate.openai.api_key and not cfg.translate.openai.base_url:
        raise HTTPException(status_code=400, detail="Chưa cấu hình OpenAI.")
    try:
        prompt = _EXPLAIN_TERMS_PROMPT if type == "terms" else _EXPLAIN_PROMPT
        explanation = _call_openai(cfg, prompt.format(text=text))
        return JSONResponse({"explanation": explanation, "type": type})
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/api/chapters/{index}/translated")
def api_chapter_translated(index: int):
    """Back-compat: route không slug dùng config mặc định (ebook đang active)."""
    cfg = deps.cfg()
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")
    ch = next((c for c in manifest.chapters if c.index == index), None)
    if ch is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy chương.")
    return JSONResponse(_chapter_translated_payload(storage, ch))


# --- Batch Operations ---


@router.post("/api/ebooks/{slug}/batch/translate-titles")
async def api_batch_translate_titles(
    request: Request,
    slug: str,
    indexes: str = Form(...),  # Comma-separated list of indexes
    engine: str = Form(None),
    model: str = Form(None),
    custom_prompt: str = Form(None),
):
    """Batch translate titles for multiple chapters."""
    cfg = deps.resolved_cfg(slug)
    index_list = [int(i.strip()) for i in indexes.split(",") if i.strip()]

    def _target(log):
        for idx in index_list:
            try:
                step_retranslate_title(
                    cfg,
                    log,
                    slug=slug,
                    index=idx,
                    engine=engine,
                    model=model,
                    custom_prompt=custom_prompt,
                )
            except RuntimeError as e:
                log(f"[batch-tiêu-đề] Lỗi chương {idx}: {e}")

    started = request.app.state.job.start_custom(
        f"batch-translate-titles-{len(index_list)}", _target, category="translate"
    )
    if not started:
        raise HTTPException(status_code=409, detail="Đang có job khác chạy, vui lòng đợi.")
    return JSONResponse({"started": True, "total": len(index_list)})


@router.post("/api/ebooks/{slug}/batch/suggest-glossary")
async def api_batch_suggest_glossary(
    request: Request,
    slug: str,
    indexes: str = Form(...),  # Comma-separated list of indexes
):
    """Batch suggest glossary for multiple chapters."""
    cfg = deps.resolved_cfg(slug)
    index_list = [int(i.strip()) for i in indexes.split(",") if i.strip()]

    def _target(log):
        for idx in index_list:
            try:
                step_suggest_chapter(cfg, log, index=idx)
            except RuntimeError as e:
                log(f"[batch-glossary] Lỗi chương {idx}: {e}")

    started = request.app.state.job.start_custom(
        f"batch-suggest-glossary-{len(index_list)}", _target, category="translate"
    )
    if not started:
        raise HTTPException(status_code=409, detail="Đang có job khác chạy, vui lòng đợi.")
    return JSONResponse({"started": True, "total": len(index_list)})


_EXPORT_PROMPTS = {"translated": bulk_transfer.EDIT_PROMPT, "raw": bulk_transfer.TRANSLATE_PROMPT}


@router.post("/api/ebooks/{slug}/batch/export")
async def api_batch_export(slug: str, indexes: str = Form(""), source: str = Form("translated")):
    """Xuất chương đã chọn thành một khối text (prompt + glossary + chương có
    marker) để dán lên web chat AI. `source=translated` (mặc định) xuất bản
    dịch hiện hành để AI BIÊN TẬP; `source=raw` xuất bản gốc tiếng Trung
    (chương chưa dịch hoặc muốn dịch lại) để AI DỊCH."""
    if source not in _EXPORT_PROMPTS:
        raise HTTPException(status_code=400, detail=f"source không hợp lệ: {source!r}")
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")

    index_list = [int(i.strip()) for i in indexes.split(",") if i.strip()]
    if not index_list:
        raise HTTPException(status_code=400, detail="Chưa chọn chương nào. Hãy tick checkbox trước.")

    by_index = {c.index: c for c in manifest.chapters}
    items: list[tuple[int, str, str]] = []
    skipped: list[int] = []
    for idx in index_list:
        ch = by_index.get(idx)
        if source == "raw":
            ok = ch is not None and storage.has_raw(ch)
        else:
            ok = ch is not None and storage.has_translated(ch)
        if not ok:
            skipped.append(idx)
            continue
        if source == "raw":
            items.append((idx, ch.title_zh, storage.read_raw(ch)))
        else:
            items.append((idx, ch.title_vi or ch.title_zh, storage.read_translated(ch)))

    if not items:
        detail = "Không có chương nào đã crawl raw trong số đã chọn." if source == "raw" \
            else "Không có chương đã dịch nào trong số đã chọn."
        raise HTTPException(status_code=400, detail=detail)

    text = bulk_transfer.build_export(
        items,
        names=storage.read_glossary_file("names.txt"),
        vietphrase=storage.read_glossary_file("vietphrase.txt"),
        prompt=_EXPORT_PROMPTS[source],
    )
    return JSONResponse({"text": text, "skipped": skipped, "total": len(items), "source": source})


@router.post("/api/ebooks/{slug}/batch/import")
async def api_batch_import(
    slug: str,
    text: str = Form(...),
    indexes: str = Form(""),
    mode: str = Form("preview"),  # "preview" | "confirm"
):
    """Nhập văn bản đã biên tập: parse theo marker, preview diff theo chương +
    glossary; mode `confirm` mới ghi đè `translated/` và merge glossary."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")

    parsed = bulk_transfer.parse_import(text)
    if not parsed:
        raise HTTPException(
            status_code=400,
            detail="Không tìm thấy marker chương nào (========== CHƯƠNG N ==========).",
        )

    expected = [int(i.strip()) for i in indexes.split(",") if i.strip()]
    by_index = {c.index: c for c in manifest.chapters}
    content_by_index = dict(parsed)
    report = bulk_transfer.validate_import(
        list(content_by_index.keys()), expected, list(by_index.keys())
    )
    glossary = bulk_transfer.parse_glossary(text)

    # Mục glossary thực sự mới (chưa có hoặc khác giá trị) — để preview/báo cáo.
    existing_names = storage.read_glossary_file("names.txt")
    existing_vp = storage.read_glossary_file("vietphrase.txt")
    new_names = {s: t for s, t in glossary["names"].items() if existing_names.get(s) != t}
    new_vp = {s: t for s, t in glossary["vietphrase"].items() if existing_vp.get(s) != t}

    chapters_info = []
    for idx in report["matched"]:
        ch = by_index[idx]
        old = storage.read_translated(ch) if storage.has_translated(ch) else ""
        new = content_by_index[idx]
        chapters_info.append({
            "index": idx,
            "changed": new.strip() != old.strip(),
            "old_len": len(old),
            "new_len": len(new),
        })

    if mode != "confirm":
        return JSONResponse({
            "mode": "preview",
            "chapters": chapters_info,
            "missing": report["missing"],
            "unknown": report["unknown"],
            "extra": report["extra"],
            "glossary_names": new_names,
            "glossary_vietphrase": new_vp,
        })

    # confirm: ghi đè translated/ + merge glossary. translated_mt/ (snapshot
    # bản máy) chỉ được ghi nếu chương CHƯA có — coi đây là lần dịch đầu (vd
    # luồng "xuất raw để dịch") thì backfill snapshot; nếu đã có (đang biên
    # tập/dịch lại) thì giữ nguyên để còn so sánh trong editor 3 cột.
    written: list[int] = []
    for idx in report["matched"]:
        ch = by_index[idx]
        if not storage.has_translated_mt(ch):
            storage.write_translated_mt(ch, content_by_index[idx])
        storage.write_translated(ch, content_by_index[idx])
        written.append(idx)

    glossary_added = 0
    for source, target in glossary["names"].items():
        if _append_glossary_entry(storage, "names.txt", source, target):
            glossary_added += 1
    for source, target in glossary["vietphrase"].items():
        if _append_glossary_entry(storage, "vietphrase.txt", source, target):
            glossary_added += 1

    return JSONResponse({
        "mode": "confirm",
        "written": written,
        "glossary_added": glossary_added,
        "missing": report["missing"],
        "unknown": report["unknown"],
    })


@router.patch("/api/ebooks/{slug}/meta")
async def api_patch_meta(request: Request, slug: str):
    """Update manifest metadata fields (title_vi, author_vi, description_vi)."""
    body = await request.json()
    allowed = {"title_vi", "author_vi", "description_vi"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update.")
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.data_dir, slug)
    manifest = storage.load_manifest()
    if not manifest:
        raise HTTPException(status_code=404, detail="Manifest not found.")
    for k, v in updates.items():
        setattr(manifest, k, v)
    storage.save_manifest(manifest)
    return JSONResponse({"ok": True, "updated": list(updates.keys())})
