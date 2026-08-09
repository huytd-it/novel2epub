"""Trang đọc chương — giao diện sách, tách biệt khỏi editor."""
from __future__ import annotations

import re
import threading

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from novel2epub import han_cleanup
from novel2epub.notes import split_paras
from novel2epub.pipeline import step_cleanup_han_local_mt_selected
from novel2epub.storage import Storage
from novel2epub.toc import count_words

from .. import deps

router = APIRouter()


def _load_chapter_or_404(slug: str, index: int):
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")
    ch = next((c for c in manifest.chapters if c.index == index), None)
    if ch is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy chương.")
    return cfg, storage, manifest, ch


def _reader_paras(text: str) -> list[str]:
    """Split chapter text into display paragraphs for reader compare mode."""
    if not text:
        return []
    blocks = re.split(r"\n\s*\n", text.strip())
    return [" ".join(block.splitlines()) for block in blocks if block.strip()]


def _pad_paras(left: list[str], right: list[str]) -> tuple[list[str], list[str]]:
    total = max(len(left), len(right))
    return left + [""] * (total - len(left)), right + [""] * (total - len(right))


_SEARCH_SNIPPET_RADIUS = 50  # ký tự mỗi bên quanh chỗ khớp (~100 ký tự)
_SEARCH_MAX_SNIPPETS = 3


def _search_snippet(text: str, match: re.Match) -> str:
    """Đoạn ~100 ký tự quanh chỗ khớp, gộp xuống dòng, thêm dấu … khi bị cắt."""
    start = max(0, match.start() - _SEARCH_SNIPPET_RADIUS)
    end = min(len(text), match.end() + _SEARCH_SNIPPET_RADIUS)
    snippet = " ".join(text[start:end].split())
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet


@router.get("/api/ebooks/{slug}/search")
def reader_search(slug: str, q: str, regex: bool = False, case: bool = False, source: str = "translated"):
    """Tìm toàn văn xuyên chương trong bản dịch (mặc định) hoặc bản gốc.

    `regex=True` coi `q` là biểu thức chính quy; `case=True` phân biệt
    hoa/thường (mặc định không). `source=translated` chỉ quét các chương có bản
    dịch (bản hiện tại của nhánh active); `source=raw` quét bản gốc đã crawl —
    GỒM cả chương chưa dịch. Trả list `{chapter_index, title, count, snippets}`
    theo thứ tự chương.
    """
    q = q.strip()
    if not q:
        raise HTTPException(status_code=400, detail="Chuỗi tìm kiếm đang rỗng.")
    if source not in ("translated", "raw"):
        raise HTTPException(status_code=400, detail="source phải là 'translated' hoặc 'raw'.")
    flags = 0 if case else re.IGNORECASE
    try:
        pattern = re.compile(q if regex else re.escape(q), flags)
    except re.error as e:
        raise HTTPException(status_code=400, detail=f"Regex không hợp lệ: {e}")

    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")

    def _text(ch) -> str | None:
        if source == "raw":
            return storage.read_raw(ch) if storage.has_raw(ch) else None
        return storage.read_active_branch_text(ch) if storage.has_active_branch_text(ch) else None

    results = []
    for ch in manifest.chapters:
        text = _text(ch)
        if not text:
            continue
        matches = list(pattern.finditer(text))
        if not matches:
            continue
        results.append(
            {
                "chapter_index": ch.index,
                "title": ch.title or f"Chương {ch.index}",
                "count": len(matches),
                "snippets": [
                    _search_snippet(text, m) for m in matches[:_SEARCH_MAX_SNIPPETS]
                ],
            }
        )
    return JSONResponse(results)


def _first_reading_index(slug: str) -> int:
    """Chương đầu tiên có bản dịch, hoặc chương đầu mục lục nếu chưa dịch gì."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None or not manifest.chapters:
        raise HTTPException(status_code=404, detail="Chưa có chương nào.")
    for ch in manifest.chapters:
        if storage.has_active_branch_text(ch):
            return ch.index
    return manifest.chapters[0].index


@router.get("/ebooks/{slug}/read")
def reader_root(request: Request, slug: str):
    """Redirect tới chương đầu tiên có bản dịch (bookmark là client-side)."""
    return RedirectResponse(
        url=f"/ebooks/{slug}/read/{_first_reading_index(slug)}", status_code=302
    )


@router.get("/api/ebooks/{slug}/read/first-index")
def reader_first_index(slug: str):
    """Bản JSON của `reader_root`, cho SPA tự điều hướng — bookmark (client-side,
    localStorage) vẫn được ưu tiên hơn giá trị này khi có."""
    return JSONResponse({"index": _first_reading_index(slug)})


def _chapter_context(slug: str, index: int) -> dict:
    """Dữ liệu render đầy đủ cho 1 chương — dùng chung cho trang HTML và API
    AJAX (`/read/{index}/data`) để trang đọc có thể chuyển chương không cần
    tải lại toàn trang khi đang biên tập."""
    cfg, storage, manifest, ch = _load_chapter_or_404(slug, index)

    has_translated = storage.has_active_branch_text(ch)
    translated = storage.read_active_branch_text(ch) if has_translated else ""
    translated_paras = split_paras(translated) if translated else []
    has_raw = storage.has_raw(ch)
    raw = storage.read_raw(ch) if has_raw else ""
    raw_paras = _reader_paras(raw)
    edit_paras = _reader_paras(translated) if translated else []
    raw_paras, edit_paras = _pad_paras(raw_paras, edit_paras)

    # Danh sách chương cho navigation
    chapters_info = []
    for c in manifest.chapters:
        chapters_info.append({
            "index": c.index,
            "title": c.title or f"Chương {c.index}",
            "has_translated": storage.has_active_branch_text(c),
        })

    prev_ch = None
    next_ch = None
    for i, c in enumerate(manifest.chapters):
        if c.index == index:
            if i > 0:
                prev_ch = manifest.chapters[i - 1]
            if i < len(manifest.chapters) - 1:
                next_ch = manifest.chapters[i + 1]
            break

    return {
        "slug": slug,
        "ch": ch,
        "has_translated": has_translated,
        "has_raw": has_raw,
        "raw": raw,
        "raw_paras": raw_paras,
        "edit_paras": edit_paras,
        "raw_char_count": len(raw),
        "translated_paras": translated_paras,
        "translated_word_count": count_words(translated) if translated else 0,
        "chapters_info": chapters_info,
        "prev_ch": prev_ch,
        "next_ch": next_ch,
        "notes": storage.read_notes(),
        "has_mt_snapshot": storage.has_translated_mt(ch),
    }


@router.get("/api/ebooks/{slug}/read/{index}/data")
def reader_chapter_data(slug: str, index: int):
    """Dữ liệu JSON của 1 chương cho điều hướng AJAX trên trang đọc.

    Chỉ dùng cho chuyển chương nhanh khi đang biên tập: client tự fallback về
    điều hướng tải lại trang bình thường khi `has_translated=false` (khi đó
    khung HTML rỗng/hành động khác quá nhiều để dựng lại an toàn bằng JS).
    """
    ctx = _chapter_context(slug, index)
    ch = ctx["ch"]
    return JSONResponse({
        "index": ch.index,
        "title": ch.title or f"Chương {ch.index}",
        "title_zh": getattr(ch, "title_zh", "") or "",
        "skipped": bool(getattr(ch, "skipped", False)),
        "has_translated": ctx["has_translated"],
        "has_raw": ctx["has_raw"],
        "has_mt_snapshot": ctx["has_mt_snapshot"],
        "translated_paras": ctx["translated_paras"],
        "raw_paras": ctx["raw_paras"],
        "edit_paras": ctx["edit_paras"],
        "raw_char_count": ctx["raw_char_count"],
        "word_count": ctx["translated_word_count"],
        "prev_index": ctx["prev_ch"].index if ctx["prev_ch"] else None,
        "next_index": ctx["next_ch"].index if ctx["next_ch"] else None,
        "notes": ctx["notes"],
    })


_QUICK_MT_MAX_CHARS = 2000
_quick_mt_lock = threading.Lock()
_quick_mt_cache: dict[str, object] = {}


def _quick_mt_translator(slug: str):
    """Translator NMT cục bộ dùng chung cho dịch nhanh trên trang đọc.

    Model CT2 nặng nên cache theo model và ebook; glossary/storage là dữ liệu
    riêng từng ebook nên không được dùng nhầm instance giữa các sách.
    """
    from novel2epub.translator import LocalMTTranslator

    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    key = f"{cfg.translate.hachimimt.model_key}:{cfg.novel.slug}"
    with _quick_mt_lock:
        translator = _quick_mt_cache.get(key)
        if translator is None:
            translator = LocalMTTranslator(cfg.translate, storage=storage)
            _quick_mt_cache[key] = translator
        return translator


@router.post("/api/ebooks/{slug}/quick-translate")
def reader_quick_translate(slug: str, text: str = Form(...)):
    """Dịch nhanh một đoạn được bôi đen bằng NMT cục bộ (HachimiMT/MoxhiMT)."""
    text = text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Chưa có nội dung để dịch.")
    if len(text) > _QUICK_MT_MAX_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"Đoạn quá dài ({len(text)} ký tự, tối đa {_QUICK_MT_MAX_CHARS}).",
        )
    translator = _quick_mt_translator(slug)
    with _quick_mt_lock:
        try:
            translated = translator.translate(text)
        except Exception as e:  # model chưa tải được / thiếu ctranslate2
            raise HTTPException(status_code=503, detail=f"MT cục bộ lỗi: {e}")
    return JSONResponse({"text": translated})


@router.post("/api/ebooks/{slug}/cleanup-han-local-mt")
def reader_cleanup_han_local_mt(
    request: Request,
    slug: str,
    scope: str = Form(...),
    chapter_index: int = Form(0),
):
    """Clear vùng chữ Hán bằng Local MT trong chương hoặc xếp job toàn sách."""
    if scope not in {"chapter", "all"}:
        raise HTTPException(status_code=400, detail="scope phải là 'chapter' hoặc 'all'.")
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)

    if scope == "chapter":
        if not chapter_index:
            raise HTTPException(status_code=400, detail="Thiếu chapter_index.")
        _cfg, storage, _manifest, ch = _load_chapter_or_404(slug, chapter_index)
        if not storage.has_translated(ch):
            raise HTTPException(status_code=404, detail="Chương chưa có bản dịch.")
        before = storage.read_translated(ch)
        translator = _quick_mt_translator(slug)
        with _quick_mt_lock:
            try:
                after, fixed, warnings = han_cleanup.cleanup_han_with_local_mt(
                    before, translator.translate,
                )
            except Exception as exc:
                raise HTTPException(status_code=503, detail=f"MT cục bộ lỗi: {exc}")
        if after != before:
            meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
            meta["before_local_mt_cleanup"] = before
            storage.write_meta(ch, meta)
            storage.write_translated(ch, after)
        return JSONResponse({
            "fixed": fixed,
            "han_before": han_cleanup.count_han(before),
            "han_after": han_cleanup.count_han(after),
            "warnings": warnings,
        })

    def _target(log):
        step_cleanup_han_local_mt_selected(cfg, log)

    started = request.app.state.job.start_custom(
        "cleanup-han-local-mt", _target, category="translate", ebook=cfg.novel.slug,
    )
    if not started:
        raise HTTPException(status_code=409, detail="Đang có job khác chạy, vui lòng đợi.")
    return JSONResponse({"ok": True})


_TTS_MAX_CHARS = 3000
_TTS_VOICE_RE = re.compile(r"^[a-zA-Z]{2}-[a-zA-Z]{2,4}-[A-Za-z0-9]+Neural$")
_TTS_RATE_RE = re.compile(r"^[+-]\d{1,3}%$")


@router.post("/api/tts")
async def reader_tts(
    text: str = Form(...),
    voice: str = Form("vi-VN-HoaiMyNeural"),
    rate: str = Form("+0%"),
):
    """Tổng hợp giọng đọc bằng Edge TTS, trả về một file mp3 trọn đoạn."""
    text = text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Chưa có nội dung để đọc.")
    if len(text) > _TTS_MAX_CHARS:
        text = text[:_TTS_MAX_CHARS]
    if not _TTS_VOICE_RE.match(voice):
        raise HTTPException(status_code=400, detail="Giọng đọc không hợp lệ.")
    if not _TTS_RATE_RE.match(rate):
        raise HTTPException(status_code=400, detail="Tốc độ đọc không hợp lệ.")

    try:
        import edge_tts
    except ImportError:
        raise HTTPException(
            status_code=503, detail="Chưa cài edge-tts (pip install edge-tts)."
        )

    # Dịch vụ Edge thỉnh thoảng đóng stream mà không gửi audio — thử lại vài lần.
    last_error = "Edge TTS không trả về âm thanh."
    for _ in range(3):
        audio = bytearray()
        try:
            async for chunk in edge_tts.Communicate(text, voice, rate=rate).stream():
                if chunk["type"] == "audio":
                    audio.extend(chunk["data"])
        except Exception as e:
            last_error = str(e)
            continue
        if audio:
            return Response(bytes(audio), media_type="audio/mpeg")
    raise HTTPException(status_code=502, detail=f"Edge TTS lỗi: {last_error}")
