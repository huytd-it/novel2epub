"""JSON API riêng cho SPA (`/app`).

Tách khỏi các router cũ có chủ đích: route Jinja2 hiện tại vẫn phải chạy
nguyên vẹn trong lúc SPA được port dần từng trang, nên phần này chỉ ĐỌC lại
cùng domain logic (`Storage`, `chapter_progress`) và không đụng vào chúng.

Endpoint đều nằm dưới `/api/ui/` để phân biệt với `/api/v1/` (hợp đồng công
khai cho readest, có CORS) và `/api/` (các endpoint nội bộ đã có).
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Request

from novel2epub.progress import chapter_progress
from novel2epub.storage import Storage
from novel2epub.toc import apply_chapter_query, chapter_rows, count_words

from .. import deps
from ..chapter_compare import align_paragraphs
from ..cost_summary import read_cost_summary
from ..library_state import archived_slugs

router = APIRouter(prefix="/api/ui")

# Mã trạng thái 1 ký tự dùng trong chuỗi RLE của dải chương.
_NONE = "n"
_RAW = "r"
_MT = "m"
_EDITED = "e"
_SKIP = "s"


def _chapter_state(chapter, stats: dict) -> str:
    if getattr(chapter, "skipped", False):
        return _SKIP
    if not stats.get("has_translated"):
        return _RAW if stats.get("has_raw") else _NONE
    try:
        meta = json.loads(stats.get("meta_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        meta = {}
    return _EDITED if meta.get("before_rewrite") else _MT


def _encode_strip(states: list[str]) -> str:
    """Nén dải chương thành run-length: 'e120,m40,n1500'.

    Trạng thái chương gần như luôn liên tục theo lô (crawl/dịch chạy theo
    khoảng), nên RLE giữ nguyên độ chính xác từng chương mà payload vẫn nhỏ
    hơn hai bậc so với gửi cả mảng — quan trọng vì trang Thư viện tải dải của
    mọi ebook cùng lúc.
    """
    if not states:
        return ""
    parts: list[str] = []
    current = states[0]
    count = 1
    for state in states[1:]:
        if state == current:
            count += 1
        else:
            parts.append(f"{current}{count}")
            current = state
            count = 1
    parts.append(f"{current}{count}")
    return ",".join(parts)


def _ebook_summary(slug: str, name: str, cfg, *, archived: bool, in_library: bool) -> dict:
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    stats_map = storage.bulk_chapter_stats()
    progress = chapter_progress(storage, manifest, stats_map=stats_map)

    chapters = manifest.chapters if manifest else []
    states = [_chapter_state(ch, stats_map.get(ch.index, {})) for ch in chapters]
    counts = {code: states.count(code) for code in (_NONE, _RAW, _MT, _EDITED, _SKIP)}

    epub_path = Path(cfg.epub_path)
    return {
        "slug": slug,
        "name": name,
        "title": cfg.novel.title,
        "author": cfg.novel.author,
        "archived": archived,
        "in_library": in_library,
        "toc_url": cfg.crawl.toc_url,
        "translate_type": cfg.translate.type,
        "total": progress["total"],
        "raw_count": progress["raw_count"],
        "translated_count": progress["translated_count"],
        "strip": _encode_strip(states),
        "counts": counts,
        "epub_exists": epub_path.exists(),
        "epub_size": epub_path.stat().st_size if epub_path.exists() else 0,
    }


def _entries():
    library = deps.library()
    if library.ebooks:
        return list(library.ebooks.items())
    return [("default", None)]


@router.get("/logs")
def logs_tail(source: str = "app", limit: int = 400):
    """Đọc phần CUỐI file log.

    `/api/logs/{source}` chỉ cắt từ đầu file nên trang theo dõi phải đoán
    offset qua hai lần gọi. Job đang chạy chỉ quan tâm dòng mới nhất, nên
    endpoint này trả thẳng đuôi file.
    """
    from ..logging_config import LOG_DIR

    path = LOG_DIR / f"{source}.log"
    if ".." in source or "/" in source or "\\" in source:
        raise HTTPException(status_code=400, detail="Tên nguồn log không hợp lệ.")
    if not path.exists():
        return {"source": source, "lines": [], "total": 0}

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    limit = max(1, min(limit, 5000))
    return {"source": source, "lines": lines[-limit:], "total": len(lines)}


@router.get("/logs/sources")
def log_sources():
    from ..logging_config import LOG_DIR

    if not LOG_DIR.exists():
        return {"sources": []}
    names = sorted(p.stem for p in LOG_DIR.glob("*.log"))
    return {"sources": names}


@router.get("/library")
def library_list(show_archived: bool = False):
    archived = archived_slugs(deps.LIBRARY_STATE_PATH)
    items = []
    for slug, entry in _entries():
        is_archived = slug in archived
        if is_archived and not show_archived:
            continue
        if entry is None:
            cfg = deps.cfg()
            name = cfg.novel.title or cfg.novel.slug
        else:
            cfg = deps.resolved_cfg(slug)
            name = entry.name or cfg.novel.title or slug
        items.append(
            _ebook_summary(slug, name, cfg, archived=is_archived, in_library=entry is not None)
        )
    return {"ebooks": items, "archived_count": len(archived)}


@router.get("/ebooks/{slug}")
def ebook_detail(request: Request, slug: str):
    """Tổng quan một truyện: tiến độ, EPUB, chi phí, chương có vấn đề.

    KHÔNG kèm danh sách chương — bảng chương phân trang riêng qua
    `/chapters` để trang không phải tải lại vài nghìn dòng mỗi lần đổi bộ lọc.
    """
    from novel2epub.toc import crawl_problem_indexes

    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    stats_map = storage.bulk_chapter_stats()
    progress = chapter_progress(storage, manifest, stats_map=stats_map)

    chapters = manifest.chapters if manifest else []
    states = [_chapter_state(ch, stats_map.get(ch.index, {})) for ch in chapters]
    epub_path = Path(cfg.epub_path)

    return {
        "slug": slug,
        "title": cfg.novel.title,
        "author": cfg.novel.author,
        "language": cfg.novel.language,
        "series": cfg.novel.series,
        "toc_url": cfg.crawl.toc_url,
        "crawl_mode": cfg.crawl.scrapling.mode,
        "translate_type": cfg.translate.type,
        "translate_model": cfg.translate.model or cfg.translate.openai.model,
        "has_manifest": manifest is not None,
        "total": progress["total"],
        "raw_count": progress["raw_count"],
        "translated_count": progress["translated_count"],
        "strip": _encode_strip(states),
        "counts": {code: states.count(code) for code in (_NONE, _RAW, _MT, _EDITED, _SKIP)},
        "crawl_problems": crawl_problem_indexes(chapters, storage, stats_map=stats_map)
        if manifest
        else [],
        "epub_exists": epub_path.exists(),
        "epub_path": str(epub_path),
        "epub_size": epub_path.stat().st_size if epub_path.exists() else 0,
        "cost_summary": read_cost_summary(storage),
        "reader_configured": cfg.reader.configured,
        "active_jobs": [
            job
            for job in request.app.state.job.queue.snapshot()["running"]
            if job.get("ebook") == slug
        ],
    }


@router.get("/ebooks/{slug}/chapters")
def ebook_chapters(
    slug: str,
    sort: str = "source",
    direction: str = "asc",
    search: str = "",
    filter_raw: str = "any",
    filter_translated: str = "any",
    filter_missing: str = "any",
    filter_skipped: str = "no",
    offset: int = 0,
    limit: int = 100,
):
    """Bảng chương đã lọc/sắp xếp, phân trang phía server.

    Lọc và sắp xếp uỷ quyền cho `apply_chapter_query` — cùng hàm mà trang
    Jinja2 và các thao tác hàng loạt dùng, nên "chọn tất cả kết quả đang lọc"
    ở giao diện mới trỏ đúng tập chương mà backend sẽ xử lý.
    """
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        return {"rows": [], "total": 0, "matched": 0, "indexes": []}

    stats_map = storage.bulk_chapter_stats()
    rows = apply_chapter_query(
        chapter_rows(manifest.chapters, storage, stats_map=stats_map),
        sort=sort,
        direction=direction,
        search=search,
        filter_raw=filter_raw,
        filter_translated=filter_translated,
        filter_missing=filter_missing,
        filter_skipped=filter_skipped,
    )

    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    page = rows[offset : offset + limit]

    return {
        "rows": [dataclasses.asdict(row) for row in page],
        "total": len(manifest.chapters),
        "matched": len(rows),
        # Toàn bộ index khớp bộ lọc, để nút "chọn tất cả" không phải tải hết
        # dữ liệu từng dòng chỉ để biết mình đang chọn những chương nào.
        "indexes": [row.index for row in rows],
    }


@router.get("/ebooks/{slug}/chapters/{index}")
def ebook_chapter_compare(slug: str, index: int):
    """Dữ liệu khung so sánh 3 cột của một chương."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có mục lục.")

    chapter = next((c for c in manifest.chapters if c.index == index), None)
    if chapter is None:
        raise HTTPException(status_code=404, detail=f"Không có chương {index}.")

    raw = storage.read_raw(chapter) if storage.has_raw(chapter) else ""
    translated = storage.read_translated(chapter) if storage.has_translated(chapter) else ""
    # Chương cũ chưa có snapshot bản máy thì degrade về bản hiện hành: cột giữa
    # hiển thị đúng thứ đang có, chỉ là không còn đối chiếu được với bản sửa.
    translated_mt = (
        storage.read_translated_mt(chapter)
        if storage.has_translated_mt(chapter)
        else translated
    )
    meta = storage.read_meta(chapter) if storage.has_meta(chapter) else {}

    indexes = [c.index for c in manifest.chapters]
    position = indexes.index(index)

    return {
        "index": chapter.index,
        "title": chapter.title,
        "title_zh": getattr(chapter, "title_zh", "") or "",
        "url": chapter.url,
        "skipped": bool(getattr(chapter, "skipped", False)),
        "has_raw": bool(raw),
        "has_translated": bool(translated),
        "has_mt_snapshot": storage.has_translated_mt(chapter),
        "raw": raw,
        "translated": translated,
        "translated_mt": translated_mt,
        "paragraphs": [
            {"raw": r, "mt": m, "edited": e}
            for r, m, e in align_paragraphs(raw, translated_mt, translated)
        ],
        "raw_char_count": len(raw),
        "word_count": count_words(translated),
        "meta": meta,
        "prev_index": indexes[position - 1] if position > 0 else None,
        "next_index": indexes[position + 1] if position + 1 < len(indexes) else None,
        "position": position + 1,
        "chapter_total": len(indexes),
    }


@router.post("/ebooks/{slug}/chapters/{index}/translated")
def ebook_chapter_save(slug: str, index: int, payload: dict = Body(...)):
    """Ghi TOÀN VĂN bản dịch, giữ nguyên từng ký tự xuống dòng.

    Cố ý không nhận chỉ số đoạn: khung so sánh 3 cột chia theo DÒNG TRỐNG và
    gộp các dòng trong một khối lại, còn `notes.split_paras` — thứ mà
    `para/save` đánh số theo — chia theo TỪNG DÒNG. Một khối "lời dẫn + lời
    thoại" là 1 hàng ở khung so sánh nhưng là 2 đoạn với `para/save`, nên lấy
    chỉ số hàng gọi sang đó sẽ ghi đè nhầm dòng mà không báo lỗi. Sửa theo
    từng đoạn phải đi qua Reader, nơi dùng đúng cách đánh số ấy.
    """
    translated = payload.get("translated")
    if not isinstance(translated, str):
        raise HTTPException(status_code=400, detail="Thiếu trường 'translated'.")

    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có mục lục.")

    chapter = next((c for c in manifest.chapters if c.index == index), None)
    if chapter is None:
        raise HTTPException(status_code=404, detail=f"Không có chương {index}.")

    storage.write_translated(chapter, translated)
    return {"saved": True, "word_count": count_words(translated)}


@router.get("/library/{slug}")
def library_detail(slug: str):
    archived = archived_slugs(deps.LIBRARY_STATE_PATH)
    library = deps.library()
    entry = library.ebooks.get(slug) if library.ebooks else None
    if library.ebooks and entry is None:
        raise HTTPException(status_code=404, detail=f"Không có ebook {slug!r}.")
    cfg = deps.resolved_cfg(slug)
    name = (entry.name if entry else "") or cfg.novel.title or slug
    return _ebook_summary(
        slug, name, cfg, archived=slug in archived, in_library=entry is not None
    )
