"""Trang đọc chương — giao diện sách, tách biệt khỏi editor."""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

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
