"""Trang đọc chương — giao diện sách, tách biệt khỏi editor."""
from __future__ import annotations

import re
import threading

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from novel2epub.notes import split_paras
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
def reader_search(slug: str, q: str, regex: bool = False, case: bool = False):
    """Tìm toàn văn xuyên chương trong các bản dịch (chỉ đọc). `regex=True` coi
    `q` là biểu thức chính quy; `case=True` phân biệt hoa/thường (mặc định
    không). Trả list `{chapter_index, title, count, snippets}` theo thứ tự
    chương, bỏ qua chương chưa có bản dịch."""
    q = q.strip()
    if not q:
        raise HTTPException(status_code=400, detail="Chuỗi tìm kiếm đang rỗng.")
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

    results = []
    for ch in manifest.chapters:
        if not storage.has_translated(ch):
            continue
        text = storage.read_translated(ch)
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


@router.get("/ebooks/{slug}/read")
def reader_root(request: Request, slug: str):
    """Redirect tới chương đầu tiên (hoặc bookmark gần nhất)."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None or not manifest.chapters:
        raise HTTPException(status_code=404, detail="Chưa có chương nào.")
    # Tìm chương đầu tiên có bản dịch
    for ch in manifest.chapters:
        if storage.has_translated(ch):
            return RedirectResponse(url=f"/ebooks/{slug}/read/{ch.index}", status_code=302)
    # Không có bản dịch nào → redirect chương đầu
    return RedirectResponse(url=f"/ebooks/{slug}/read/{manifest.chapters[0].index}", status_code=302)


@router.get("/ebooks/{slug}/read/{index}")
def reader_chapter(request: Request, slug: str, index: int):
    """Trang đọc chương với giao diện sách."""
    cfg, storage, manifest, ch = _load_chapter_or_404(slug, index)

    has_translated = storage.has_translated(ch)
    translated = storage.read_translated(ch) if has_translated else ""
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
            "has_translated": storage.has_translated(c),
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

    return deps.templates.TemplateResponse(
        request,
        "reader.html",
        {
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
        },
    )


_QUICK_MT_MAX_CHARS = 2000
_quick_mt_lock = threading.Lock()
_quick_mt_cache: dict[str, object] = {}


def _quick_mt_translator(slug: str):
    """Translator NMT cục bộ dùng chung cho dịch nhanh trên trang đọc.

    Model CT2 nặng nên giữ một instance cho mỗi model_key — mọi ebook dùng
    cùng model sẽ chia sẻ, glossary lấy theo ebook đầu tiên nạp model đó.
    """
    from novel2epub.translator import HachimiMTTranslator

    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    key = cfg.translate.hachimimt.model_key
    with _quick_mt_lock:
        translator = _quick_mt_cache.get(key)
        if translator is None:
            translator = HachimiMTTranslator(cfg.translate, storage=storage)
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
