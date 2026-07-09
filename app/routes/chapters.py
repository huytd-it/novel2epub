"""Xem & sửa tay 1 chương (raw + bản dịch)."""
from __future__ import annotations

import dataclasses
import threading
from typing import Callable

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

import html

from novel2epub import bulk_transfer, footnotes
from novel2epub.pipeline import (
    step_cleanup_han_selected,
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
from novel2epub.translator import _filter_glossary

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

    category_map = {"crawl": "crawl", "translate": "translate", "cleanup-han": "translate"}
    category = category_map.get(action, "translate")
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    ch = next((c for c in manifest.chapters if c.index == index), None) if manifest else None
    ebook_title = cfg.novel.title or slug
    ch_label = ch.title if ch and ch.title else f"Ch.{index}"
    cancel_event = threading.Event()

    def _target(log, _cfg=cfg, _act=action, _idx=index, _ev=cancel_event):
        if _act == "crawl":
            step_crawl_selected(_cfg, log, force=override, selected_indexes=[_idx], should_cancel=_ev.is_set)
        elif _act == "translate":
            step_translate_selected(_cfg, log, force=override, selected_indexes=[_idx], should_cancel=_ev.is_set)
        elif _act == "cleanup-han":
            step_cleanup_han_selected(_cfg, log, force=override, selected_indexes=[_idx], should_cancel=_ev.is_set)
        else:
            raise ValueError(f"action không hợp lệ: {_act!r}")

    step_label = {"crawl": "Crawl", "translate": "Dịch", "cleanup-han": "Cleanup Hán"}.get(action, action)
    request.app.state.job.queue.enqueue(
        category, f"chapter-{action}", _target,
        label=f"{step_label} · {ebook_title} · {ch_label}",
        ebook=slug, lock_ebook=False, chapter_indexes=[index],
        cancel_event=cancel_event,
    )
    return RedirectResponse(url=f"/ebooks/{slug}/chapters/{index}", status_code=303)


@router.post("/ebooks/{slug}/chapters/{index}/delete-translation")
def ebook_chapter_delete_translation(request: Request, slug: str, index: int):
    cfg = deps.resolved_cfg(slug)

    cancel_event = threading.Event()

    def _target(log, _cfg=cfg, _idx=index, _ev=cancel_event):
        step_delete_translation_selected(_cfg, log, selected_indexes=[_idx])

    request.app.state.job.queue.enqueue(
        "translate", f"delete-translation-{index}", _target,
        label=f"Xóa bản dịch · {cfg.novel.title or slug} · Ch.{index}",
        ebook=slug, lock_ebook=False, chapter_indexes=[index],
        cancel_event=cancel_event,
    )
    return RedirectResponse(url=f"/ebooks/{slug}/chapters/{index}", status_code=303)


@router.post("/api/ebooks/{slug}/chapters/{index}/retranslate-title")
def api_ebook_chapter_retranslate_title(
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
    Trả JSON {title_vi, title_note, title, title_description}.
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

    cancel_event = threading.Event()

    def _target(log, _step=step, _cfg=cfg, _idx=index):
        _step(_cfg, log, index=_idx)

    request.app.state.job.queue.enqueue(
        "translate", f"ai-{op}-{index}", _target,
        label=f"AI {op} · {cfg.novel.title or slug} · Ch.{index}",
        ebook=slug, lock_ebook=False, chapter_indexes=[index],
        cancel_event=cancel_event,
    )
    return RedirectResponse(url=f"/ebooks/{slug}/chapters/{index}", status_code=303)


# --- API JSON cho UI poll trong khi job dịch đang chạy ---


def _chapter_translated_payload(storage: Storage, ch) -> dict:
    """Trả payload {text, complete, mtime, char_count} cho endpoint JSON.

    `mtime` = 0 nếu file chưa tồn tại (chapters chưa được dịch); `complete`
    = False khi meta thiếu hoặc `complete != True` (partial do job crash).
    Xem spec `translate-chunk-streaming` requirement: web-api.
    """
    text = storage.read_translated(ch)
    mtime = storage.translated_updated_at(ch)
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


@router.get("/api/ebooks/{slug}/chapters/{index}/translated-mt")
def api_ebook_chapter_translated_mt(slug: str, index: int):
    """Snapshot bản dịch máy cho chế độ so sánh của trang đọc.

    `has_mt_snapshot=False` nghĩa là `read_translated_mt` đang fallback về
    `translated` (chương dịch trước khi có snapshot) — UI báo "hai bản giống
    nhau" thay vì hiển thị diff rỗng khó hiểu.
    """
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")
    ch = next((c for c in manifest.chapters if c.index == index), None)
    if ch is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy chương.")
    return JSONResponse({
        "text": storage.read_translated_mt(ch),
        "has_mt_snapshot": storage.has_translated_mt(ch),
    })


def _load_chapter_json_or_404(slug: str, index: int):
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")
    ch = next((c for c in manifest.chapters if c.index == index), None)
    if ch is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy chương.")
    return storage, manifest, ch


@router.post("/api/ebooks/{slug}/chapters/{index}/revert-edits")
def api_ebook_chapter_revert_edits(slug: str, index: int):
    """Xóa bản biên tập: khôi phục `translated/` về snapshot bản dịch máy.

    Chỉ hoạt động khi chương có snapshot MT thật (không dùng bản fallback —
    ghi đè translated bằng chính nó là vô nghĩa và gây hiểu lầm đã khôi phục).
    """
    storage, _manifest, ch = _load_chapter_json_or_404(slug, index)
    if not storage.has_translated_mt(ch):
        raise HTTPException(
            status_code=400,
            detail="Chương không có snapshot bản dịch máy để khôi phục.",
        )
    storage.write_translated(ch, storage.read_translated_mt(ch))
    return JSONResponse({"reverted": True})


@router.post("/api/ebooks/{slug}/chapters/{index}/delete-translation")
def api_ebook_chapter_delete_translation(slug: str, index: int):
    """Xóa toàn bộ bản dịch của 1 chương (translated + snapshot MT + meta).

    Bản sync cho trang đọc — khác route form `/ebooks/.../delete-translation`
    (job nền + redirect về editor): xóa vài file là thao tác tức thời, không
    cần queue.
    """
    storage, manifest, ch = _load_chapter_json_or_404(slug, index)
    storage.delete_translated(ch)
    if ch.last_action_status:
        ch.last_action_status = ""
        storage.save_chapter(ch)
    return JSONResponse({"deleted": True})


@router.post("/api/ebooks/{slug}/chapters/{index}/toggle-skip")
def api_ebook_chapter_toggle_skip(slug: str, index: int):
    """Bật/tắt trạng thái skipped của 1 chương. Skipped chapters bị ẩn khỏi
    table mặc định, không bị xoá dữ liệu. Có filter_skipped=yes để xem lại."""
    storage, manifest, ch = _load_chapter_json_or_404(slug, index)
    ch.skipped = not ch.skipped
    storage.save_chapter(ch)
    return JSONResponse({"skipped": ch.skipped})


@router.post("/api/ebooks/{slug}/batch/clean-raw")
async def api_batch_clean_raw(slug: str, indexes: str = Form(...)):
    """Xóa hàng loạt file raw cho các chương đã chọn. Không đụng translated/
    translated_mt/meta — chỉ xóa raw/*.md để có thể crawl lại."""
    from pathlib import Path as _Path
    cfg = deps.resolved_cfg(slug)
    index_list = [int(i.strip()) for i in indexes.split(",") if i.strip()]
    if not index_list:
        raise HTTPException(status_code=400, detail="Chưa chọn chương nào.")
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")
    deleted = 0
    for ch in manifest.chapters:
        if ch.index not in index_list:
            continue
        if storage.has_raw(ch):
            storage.write_raw(ch, "")
            deleted += 1
    return JSONResponse({"deleted": deleted})


@router.post("/api/ebooks/{slug}/batch/update-skip")
async def api_batch_update_skip(slug: str, indexes: str = Form(...), skip: bool = Form(True)):
    """Bật (skip=True) hoặc tắt (skip=False) skipped cho hàng loạt chương."""
    cfg = deps.resolved_cfg(slug)
    index_list = [int(i.strip()) for i in indexes.split(",") if i.strip()]
    if not index_list:
        raise HTTPException(status_code=400, detail="Chưa chọn chương nào.")
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")
    updated = 0
    for ch in manifest.chapters:
        if ch.index in index_list and ch.skipped != skip:
            ch.skipped = skip
            updated += 1
    if updated:
        for ch in manifest.chapters:
            if ch.index in index_list:
                storage.save_chapter(ch)
    return JSONResponse({"updated": updated, "skip": skip})


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


@router.post("/api/ebooks/{slug}/batch/delete-translation")
async def api_batch_delete_translation(request: Request, slug: str, indexes: str = Form(...)):
    """Xóa hàng loạt bản dịch (translated + snapshot MT + meta) cho các chương đã chọn.

    Thao tác phá huỷ — UI phải xác nhận trước khi gọi. Raw KHÔNG bị xoá, có thể
    dịch lại. Job category=translate để dùng chung khoá với các batch dịch khác.
    """
    cfg = deps.resolved_cfg(slug)
    index_list = [int(i.strip()) for i in indexes.split(",") if i.strip()]
    if not index_list:
        raise HTTPException(status_code=400, detail="Chưa chọn chương nào. Hãy tick checkbox trước.")

    def _target(log):
        step_delete_translation_selected(cfg, log, selected_indexes=index_list)

    started = request.app.state.job.start_custom(
        f"batch-delete-translation-{len(index_list)}", _target, category="translate"
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


@router.post("/api/ebooks/{slug}/batch/ai-rewrite")
async def api_batch_ai_rewrite(
    request: Request,
    slug: str,
    indexes: str = Form(...),
    backend: str = Form("openai"),
):
    """Batch "Biên tập đã chọn" — backend chọn qua form field `backend`.

    - backend="openai" (mặc định): gọi `step_rewrite_preview` cho từng chương.
      LUÔN xoá bản nháp cũ (nếu có) rồi tạo lại bản nháp mới trong
      meta['ai_rewrite']. KHÔNG ghi đè bản dịch hiện hành — user vào từng
      chương để xem diff rồi áp dụng/bỏ (giống flow per-chapter /ai/rewrite).

    - backend="hachimimt": dịch lại bằng Local NMT, ghi đè bản dịch hiện
      hành (force=True). Hữu ích khi muốn thử lại bằng model NMT khác.
    """
    cfg = deps.resolved_cfg(slug)
    index_list = [int(i.strip()) for i in indexes.split(",") if i.strip()]
    if not index_list:
        raise HTTPException(status_code=400, detail="Chưa chọn chương nào.")
    backend = (backend or "openai").lower()
    if backend not in ("openai", "hachimimt"):
        raise HTTPException(status_code=400, detail=f"backend không hợp lệ: {backend!r}")

    if backend == "hachimimt":
        # Local NMT: dịch lại từ raw, ghi đè bản dịch cũ.
        mod_cfg = dataclasses.replace(
            cfg,
            translate=dataclasses.replace(cfg.translate, type="hachimimt"),
        )

        def _target(log):
            try:
                step_translate_selected(
                    mod_cfg, log, force=True, selected_indexes=index_list
                )
            except Exception as e:  # noqa: BLE001
                log(f"[batch-rewrite-local-nmt] Lỗi: {e}")

        started = request.app.state.job.start_custom(
            f"batch-rewrite-local-nmt-{len(index_list)}", _target, category="translate"
        )
    else:
        def _target(log):
            from novel2epub.storage import Storage
            storage = Storage(cfg.output.data_dir, cfg.novel.slug)
            manifest = storage.load_manifest()
            if manifest:
                idx_set = set(index_list)
                cleared = 0
                for ch in manifest.chapters:
                    if ch.index in idx_set and storage.has_meta(ch):
                        meta = storage.read_meta(ch)
                        if "ai_rewrite" in meta:
                            meta.pop("ai_rewrite", None)
                            storage.write_meta(ch, meta)
                            cleared += 1
                if cleared:
                    log(f"[batch-rewrite] Đã xoá {cleared} bản nháp cũ, tạo lại.")
            for idx in index_list:
                try:
                    step_rewrite_preview(cfg, log, index=idx)
                except RuntimeError as e:
                    log(f"[batch-rewrite] Lỗi chương {idx}: {e}")

        started = request.app.state.job.start_custom(
            f"batch-ai-rewrite-{len(index_list)}", _target, category="translate"
        )
    if not started:
        raise HTTPException(status_code=409, detail="Đang có job khác chạy, vui lòng đợi.")
    return JSONResponse({"started": True, "total": len(index_list), "backend": backend})


_EXPORT_PROMPTS = {"translated": bulk_transfer.EDIT_PROMPT, "raw": bulk_transfer.TRANSLATE_PROMPT}


def _filter_glossary_for_batch(
    names: dict[str, str],
    vietphrase: dict[str, str],
    items: list[tuple[int, str, str]],
) -> tuple[dict[str, str], dict[str, str]]:
    """Rút gọn glossary về đúng các mục xuất hiện trong batch (translate.glossary_filter).

    Khối glossary nhét vào export dùng chung cho cả nguồn raw (ZH) lẫn translated
    (VI), nên so khớp key Hán VÀ value Việt với toàn bộ text (title + content)."""
    combined = "\n".join(f"{title}\n{content}" for _, title, content in items)
    return (
        _filter_glossary(names, zh_text=combined, vi_text=combined),
        _filter_glossary(vietphrase, zh_text=combined, vi_text=combined),
    )


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
            items.append((idx, ch.title, storage.read_raw(ch)))
        else:
            items.append((idx, ch.title, storage.read_translated(ch)))

    if not items:
        detail = "Không có chương nào đã crawl raw trong số đã chọn." if source == "raw" \
            else "Không có chương đã dịch nào trong số đã chọn."
        raise HTTPException(status_code=400, detail=detail)

    names = storage.read_glossary_file("names.txt")
    vietphrase = storage.read_glossary_file("vietphrase.txt")
    if cfg.translate.glossary_filter:
        names, vietphrase = _filter_glossary_for_batch(names, vietphrase, items)
    text = bulk_transfer.build_export(
        items,
        names=names,
        vietphrase=vietphrase,
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
    content_by_index = {idx: content for idx, _title, content in parsed}
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


def _ai_call_with_retry(
    openai_cfg,
    prompt: str,
    log: Callable[[str], None],
    label: str,
):
    """Gọi AI qua `run_chat_with_meta` với retry 1 lần. Trả `(content, meta)`
    nếu thành công, hoặc `None` nếu CẢ 2 lần đều lỗi — caller tự quyết định
    skip batch hay raise.

    Lý do retry 1 lần: API có round-robin — gọi lại ngay thường đổi sang
    model/node khác và pass khi lần 1 bị timeout/5xx. Nếu lần 2 vẫn fail
    (provider tạch hẳn, hoặc lỗi logic) thì skip để job vẫn chạy tiếp
    các batch sau thay vì chết cả job.
    """
    from novel2epub.openai_client import run_chat_with_meta

    for attempt in (1, 2):
        try:
            return run_chat_with_meta(openai_cfg, prompt)
        except Exception as e:
            if attempt == 1:
                log(f"[batch-dịch] {label}: AI lỗi lần 1, thử lại: {e}")
            else:
                log(f"[batch-dịch] {label}: AI lỗi lần 2: {e}")
    log(f"[batch-dịch] {label}: ⚠ Cả 2 lần đều lỗi, bỏ qua batch này, tiếp tục batch kế tiếp.")
    return None


def _run_batch_translate(slug: str, index_list: list[int], log: Callable[[str], None]) -> None:
    """Target chạy trong job queue cho POST batch/translate (xem route bên
    dưới). `index_list` là danh sách GỐC chưa lọc — việc lọc "đã dịch rồi"/
    "chưa có raw" xảy ra ở ĐÂY (lúc job thực sự chạy), không phải lúc enqueue,
    nên job này idempotent: enqueue lại y hệt spec cũ sau khi app restart
    (xem JobQueue.load_pending) là an toàn, chỉ dịch phần còn thiếu.
    """
    from novel2epub.pipeline import _clean_title

    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        log(f"[batch-dịch] Lỗi: ebook {slug!r} chưa có manifest.")
        return

    by_index = {c.index: c for c in manifest.chapters}
    items: list[tuple[int, str, str]] = []
    skipped: list[int] = []
    already_translated: list[int] = []
    for idx in index_list:
        ch = by_index.get(idx)
        if ch is None or not storage.has_raw(ch):
            skipped.append(idx)
            continue
        if storage.has_translated(ch):
            already_translated.append(idx)
            continue
        items.append((idx, ch.title, storage.read_raw(ch)))

    if already_translated:
        log(f"[batch-dịch] Bỏ qua {len(already_translated)} chương đã dịch: {already_translated}")
    if skipped:
        log(f"[batch-dịch] Bỏ qua {len(skipped)} chương chưa có raw: {skipped}")
    if not items:
        log("[batch-dịch] Không có chương nào cần dịch.")
        return

    # Glossary chung — đọc 1 lần, merge dần qua các batch
    names_glossary = dict(storage.read_glossary_file("names.txt"))
    vietphrase_glossary = dict(storage.read_glossary_file("vietphrase.txt"))

    # Chia items thành các batch: tối đa translate.batch_size chương/batch,
    # VÀ khối export (prompt + glossary + chương) không vượt
    # translate.prompt_max_chars — batch bị cắt sớm khi chạm giới hạn.
    # Chương đơn lẻ đã vượt giới hạn vẫn đi 1 mình (không chia nhỏ được).
    def _export_len(batch: list[tuple[int, str, str]]) -> int:
        bn, bv = names_glossary, vietphrase_glossary
        if cfg.translate.glossary_filter:
            bn, bv = _filter_glossary_for_batch(names_glossary, vietphrase_glossary, batch)
        return len(bulk_transfer.build_export(
            batch, names=bn, vietphrase=bv, prompt=bulk_transfer.TRANSLATE_PROMPT,
        ))

    batch_size = max(1, cfg.translate.batch_size)
    budget = cfg.translate.prompt_max_chars
    batches: list[list[tuple[int, str, str]]] = []
    cur: list[tuple[int, str, str]] = []
    for item in items:
        cand = cur + [item]
        if cur and (len(cand) > batch_size or (budget > 0 and _export_len(cand) > budget)):
            batches.append(cur)
            cur = [item]
        else:
            cur = cand
    if cur:
        batches.append(cur)
    total_batches = len(batches)
    log(f"[batch-dịch] Dịch {len(items)} chương, chia {total_batches} batch "
        f"(batch_size={batch_size}, prompt_max_chars={budget or 'tắt'}).")
    if budget > 0:
        for b in batches:
            if len(b) == 1 and _export_len(b) > budget:
                log(f"[batch-dịch] ⚠ Chương {b[0][0]} một mình đã vượt prompt_max_chars "
                    f"({_export_len(b)} > {budget} ký tự) — vẫn gửi nguyên chương.")

    all_written: list[int] = []
    all_missing: list[int] = []
    all_unknown: list[int] = []
    all_skipped: list[int] = []  # chương thuộc batch fail cả 2 lần gọi AI
    titles_updated: list[int] = []
    glossary_added = 0
    batch_metas: list[dict] = []

    for batch_idx, batch_items in enumerate(batches, 1):
        label = f"Batch {batch_idx}/{total_batches}"

        # 1. Build export cho batch này (dùng glossary đã merge từ các batch trước).
        # glossary_filter: chỉ nhét mục glossary xuất hiện trong batch (giữ nguyên
        # names_glossary/vietphrase_glossary đầy đủ cho các batch sau).
        batch_names, batch_vietphrase = names_glossary, vietphrase_glossary
        if cfg.translate.glossary_filter:
            batch_names, batch_vietphrase = _filter_glossary_for_batch(
                names_glossary, vietphrase_glossary, batch_items
            )
        export_text = bulk_transfer.build_export(
            batch_items,
            names=batch_names,
            vietphrase=batch_vietphrase,
            prompt=bulk_transfer.TRANSLATE_PROMPT,
        )

        # 2. Gọi AI (retry 1 lần — fail cả 2 lần → skip batch này, tiếp tục batch kế tiếp)
        result = _ai_call_with_retry(
            cfg.translate.openai, export_text, log, label,
        )
        if result is None:
            all_skipped.extend(i for i, _, _ in batch_items)
            continue

        response_text, meta = result
        batch_metas.append(meta or {})

        # 3. Parse response
        parsed = bulk_transfer.parse_import(response_text)
        if not parsed:
            log(f"[batch-dịch] {label}: raw response (200 ký tự đầu): {response_text[:200]!r}")
            raise RuntimeError(
                f"Batch {batch_idx}/{total_batches}: AI trả về nhưng không có "
                "marker chương nào (## Chương N). "
                "Xem log để debug — raw response đã được ghi ở trên."
            )

        content_by_index = {idx: content for idx, _title, content in parsed}
        title_by_index = {idx: title for idx, title, _content in parsed if title.strip()}
        expected = [i for i, _, _ in batch_items]
        report = bulk_transfer.validate_import(
            list(content_by_index.keys()), expected, list(by_index.keys())
        )
        glossary = bulk_transfer.parse_glossary(response_text)

        # 4. Ghi translated/ — giữ snapshot MT trước khi ghi bản AI. Tiêu đề AI
        # dịch trong heading ghi đè manifest title (match theo index của marker,
        # KHÔNG theo số chương trong tiêu đề — hai số này có thể lệch nhau).
        batch_titles_changed = False
        for idx in report["matched"]:
            ch = by_index[idx]
            if not storage.has_translated_mt(ch):
                storage.write_translated_mt(ch, content_by_index[idx])
            storage.write_translated(ch, content_by_index[idx])
            all_written.append(idx)

            new_title = _clean_title(title_by_index.get(idx, ""))
            if new_title:
                # Ép lại số chương THẬT (第M章 trong tiêu đề gốc) — AI hay dịch
                # "gọn" làm rơi số, hoặc echo nhầm index vị trí vào tiêu đề.
                new_title = bulk_transfer.ensure_title_number(
                    ch.title_zh or ch.title, new_title
                )
            if new_title and new_title != ch.title:
                if not ch.title_zh:
                    ch.title_zh = ch.title
                ch.title = new_title
                ch.title_note = ""
                titles_updated.append(idx)
                batch_titles_changed = True
            storage.save_chapter(ch)

        # 5. Merge glossary mới vào dict chung (cho batch kế tiếp dùng tham khảo)
        for source, target in glossary["names"].items():
            if source not in names_glossary:
                names_glossary[source] = target
                if _append_glossary_entry(storage, "names.txt", source, target):
                    glossary_added += 1
        for source, target in glossary["vietphrase"].items():
            if source not in vietphrase_glossary:
                vietphrase_glossary[source] = target
                if _append_glossary_entry(storage, "vietphrase.txt", source, target):
                    glossary_added += 1

        all_missing.extend(report["missing"])
        all_unknown.extend(report["unknown"])
        log(f"[batch-dịch] Batch {batch_idx}/{total_batches}: ghi {len(report['matched'])} chương.")

    # Tổng hợp ai_meta từ tất cả batch
    cost = sum(m.get("cost_usd", 0) for m in batch_metas)
    tokens = sum((m.get("tokens_in", 0) + m.get("tokens_out", 0)) for m in batch_metas)
    summary = (
        f"[batch-dịch] Hoàn tất: {len(all_written)}/{len(items)} chương"
        f" · {len(titles_updated)} tiêu đề cập nhật · {glossary_added} mục glossary mới"
    )
    if cost:
        summary += f" · {cost:.4f} USD"
    if tokens:
        summary += f" · {tokens} tokens"
    log(summary)
    if all_missing:
        log(f"[batch-dịch] ⚠ AI bỏ sót: {all_missing}")
    if all_unknown:
        log(f"[batch-dịch] ⚠ Index lạ (bỏ qua): {all_unknown}")
    if all_skipped:
        log(f"[batch-dịch] ⚠ Bỏ qua do AI lỗi 2 lần liên tiếp: {all_skipped}")


def batch_translate_job_factory(params: dict) -> Callable[[Callable[[str], None]], object]:
    """Tái tạo `target(log)` từ spec đã lưu (xem JobQueue.register_kind) —
    dùng để enqueue lại job batch/translate còn dang dở sau khi app restart."""
    slug = params["slug"]
    index_list = params["indexes"]

    def _target(log: Callable[[str], None]) -> None:
        _run_batch_translate(slug, index_list, log)

    return _target


@router.post("/api/ebooks/{slug}/batch/translate")
async def api_batch_translate(request: Request, slug: str, indexes: str = Form("")):
    """Enqueue dịch hàng loạt theo luồng "Xuất RAW" → gọi AI → "Nhập" — chạy
    NỀN qua job queue (category=translate), KHÔNG block request. Chia nhỏ
    thành các batch để tránh gửi quá nhiều chương 1 lần cho AI.

    Config: `translate.batch_size` (mặc định 10) — tối đa số chương / lần gọi AI.

    Chương đã có bản dịch (`storage.has_translated`) tự động bị BỎ QUA — muốn
    dịch lại thì xoá bản dịch cũ trước (nút "Xóa bản dịch selected"). Việc lọc
    xảy ra lúc job THỰC SỰ chạy (xem `_run_batch_translate`), không phải lúc
    enqueue, nên job idempotent — an toàn khi được enqueue lại tự động sau khi
    app restart trong lúc job còn pending/đang chạy (xem `JobQueue.load_pending`,
    đăng ký kind ở `app/main.py`).

    Tiêu đề AI dịch trong heading `## Chương N: <title>` được ghi đè vào
    `manifest.chapters[].title` (backfill `title_zh` nếu đang rỗng) — xem chi
    tiết trong `_run_batch_translate`.

    Trả `{started, total, pending, skip_hint}` NGAY (không đợi dịch xong) — kết
    quả chi tiết (written/glossary/ai_meta) nằm trong log của job, xem trang
    /queue hoặc /logs, hoặc GET /api/queue/{job_id}/log.
    """
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")

    index_list = [int(i.strip()) for i in indexes.split(",") if i.strip()]
    if not index_list:
        raise HTTPException(status_code=400, detail="Chưa chọn chương nào.")

    by_index = {c.index: c for c in manifest.chapters}
    pending = sum(
        1
        for idx in index_list
        if (ch := by_index.get(idx)) is not None and storage.has_raw(ch) and not storage.has_translated(ch)
    )
    if pending == 0:
        raise HTTPException(
            status_code=400,
            detail="Không có chương nào cần dịch (đã dịch hết hoặc chưa có raw).",
        )

    spec = {"kind": "batch-translate", "params": {"slug": slug, "indexes": index_list}}
    request.app.state.job.start_custom(
        f"batch-translate-{len(index_list)}",
        batch_translate_job_factory(spec["params"]),
        category="translate",
        ebook=slug,
        spec=spec,
    )
    return JSONResponse({"started": True, "total": len(index_list), "pending": pending})


@router.patch("/api/ebooks/{slug}/meta")
async def api_patch_meta(request: Request, slug: str):
    """Update manifest metadata fields (title, author, description)."""
    body = await request.json()
    allowed = {"title", "author", "description"}
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
