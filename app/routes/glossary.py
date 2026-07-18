"""Trang quản lý glossary: data table (CRUD inline), xuất/nhập cho AI dọn lại,
và sửa tên riêng rồi áp dụng lại vào các bản dịch cũ (có preview)."""
from __future__ import annotations

from fastapi import APIRouter, Body, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from novel2epub import bulk_transfer
from novel2epub.pipeline import _chapter_range, step_find_replace
from novel2epub.storage import Storage

from .. import deps

router = APIRouter()

def _conflicts_count(storage) -> int:
    data = storage.read_extra_json("glossary_conflicts")
    return len(data) if isinstance(data, list) else 0


def _append_glossary_entry(
    storage: Storage, source: str, suggested: str, note: str = ""
) -> bool:
    """Thêm 1 dòng `source = suggested [| note]` vào glossary (list chuẩn duy
    nhất names.txt — đã bỏ phân loại), bỏ qua nếu thiếu dữ liệu hoặc mục đã
    tồn tại với đúng giá trị đó. Trả True nếu có ghi thật."""
    source, suggested, note = source.strip(), suggested.strip(), note.strip()
    if not source or not suggested:
        return False
    existing = {s: t for s, t, _n in storage.read_glossary_entries_merged()}
    if existing.get(source) == suggested and not note:
        return False

    line = f"{source} = {suggested}" + (f" | {note}" if note else "")
    storage.append_glossary_line("names.txt", line)
    return True


@router.get("/ebooks/{slug}/glossary")
def ebook_glossary(request: Request, slug: str):
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    # Trang tải dữ liệu theo trang qua ajax (/glossary/list) — không nhúng toàn
    # bộ mục vào HTML nữa.
    return deps.templates.TemplateResponse(
        request,
        "glossary.html",
        {
            "slug": slug,
            "job": request.app.state.job.status(),
            "conflicts_count": _conflicts_count(storage),
        },
    )


@router.get("/api/ebooks/{slug}/glossary/list")
def ebook_glossary_list(
    slug: str,
    page: int = 1,
    per_page: int = 50,
    q: str = "",
    sort: str = "",
    dir: str = "asc",
):
    """Một trang glossary (server-side pagination + search + sort). Consolidate
    vietphrase legacy vào names.txt trước để chỉ cần quét 1 list."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    storage.consolidate_glossary()

    per_page = max(1, min(int(per_page), 500))
    total = storage.count_glossary_entries("names.txt", q)
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(int(page), pages))
    offset = (page - 1) * per_page
    rows = storage.read_glossary_page("names.txt", offset, per_page, q, sort, dir)
    return JSONResponse(
        {
            "entries": [{"source": s, "target": t, "note": n} for s, t, n in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": pages,
        }
    )


@router.post("/api/ebooks/{slug}/glossary/entry")
def ebook_glossary_upsert_entry(
    slug: str,
    source: str = Form(...),
    target: str = Form(...),
    note: str = Form(""),
    original_source: str = Form(""),
):
    """Autosave MỘT mục (thêm hoặc sửa). Nếu `original_source` khác `source`
    (đổi tên Hán) thì xoá mục cũ trước rồi upsert mục mới."""
    source, target = source.strip(), target.strip()
    if not source or not target:
        raise HTTPException(status_code=400, detail="Cần cả Hán và Việt.")
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    orig = original_source.strip()
    if orig and orig != source:
        storage.delete_glossary_entry(orig)
    storage.upsert_glossary_entry(source, target, note)
    return JSONResponse({"ok": True})


@router.post("/api/ebooks/{slug}/glossary/entry/delete")
def ebook_glossary_delete_entry(slug: str, source: str = Form(...)):
    """Xoá MỘT mục glossary khỏi DB ngay (persist), dùng bởi nút Xoá trên bảng."""
    source = source.strip()
    if not source:
        raise HTTPException(status_code=400, detail="Thiếu mục cần xoá.")
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    storage.delete_glossary_entry(source)
    return JSONResponse({"ok": True})


@router.post("/api/ebooks/{slug}/glossary/clean")
def ebook_glossary_clean(slug: str):
    """Dọn dữ liệu toàn glossary (trim, bỏ mục thiếu, dedup theo source) trên
    server. Trả `{before, after, removed}`."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    before, after = storage.clean_glossary()
    return JSONResponse({"before": before, "after": after, "removed": before - after})


@router.post("/ebooks/{slug}/glossary")
async def ebook_glossary_save(slug: str, payload: dict = Body(...)):
    """Lưu toàn bộ glossary từ data table. Payload JSON:
    `{"entries": [{source, target, note}, ...]}`.
    Ghi tất cả vào names.txt (list chuẩn duy nhất) và dọn sạch vietphrase.txt
    — lazy consolidation dữ liệu cũ sau lần lưu đầu tiên."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)

    def _to_tuples(rows) -> list[tuple[str, str, str]]:
        out: list[tuple[str, str, str]] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            out.append(
                (
                    str(row.get("source", "")),
                    str(row.get("target", "")),
                    str(row.get("note", "")),
                )
            )
        return out

    storage.write_glossary_entries("names.txt", _to_tuples(payload.get("entries")))
    storage.write_glossary_entries("vietphrase.txt", [])
    return JSONResponse({"ok": True})


@router.post("/ebooks/{slug}/glossary/quick-add")
def ebook_glossary_quick_add(
    slug: str,
    chapter_index: int = Form(...),
    source: str = Form(""),
    suggested: str = Form(""),
    note: str = Form(""),
):
    """Thêm nhanh 1 mục glossary ngay từ trang chương — dùng khi đang đọc bản
    dịch và phát hiện thuật ngữ/tên riêng cần thống nhất, không cần qua trang
    Glossary riêng."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    _append_glossary_entry(storage, source, suggested, note)
    return RedirectResponse(url=f"/ebooks/{slug}/chapters/{chapter_index}", status_code=303)


@router.post("/api/ebooks/{slug}/glossary/export")
def ebook_glossary_export(slug: str):
    """Xuất glossary hiện tại kèm prompt nhờ web chat AI dọn lại (dedup, sửa
    Hán-Việt, gộp mâu thuẫn). Trả `{text}` để dán/tải `.md`."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    glossary = {s: t for s, t, _n in storage.read_glossary_entries_merged()}
    text = bulk_transfer.build_glossary_export(glossary)
    return JSONResponse({"text": text, "count": len(glossary)})


@router.post("/api/ebooks/{slug}/glossary/import")
def ebook_glossary_import(slug: str, text: str = Form(...)):
    """Nhập glossary AI trả về: parse các dòng `Hán = Việt` trong khối
    `## GLOSSARY` rồi MERGE vào glossary hiện tại (source trùng → giá trị mới
    thắng, giữ ghi chú cũ). Ghi tất cả vào names.txt + dọn vietphrase.txt
    (consolidation). Trả thống kê `{added, updated, total}`."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    parsed = bulk_transfer.parse_glossary(text)
    if not parsed:
        raise HTTPException(
            status_code=400,
            detail="Không tìm thấy mục glossary nào (cần khối ## GLOSSARY với các dòng `Hán = Việt`).",
        )

    current = storage.read_glossary_entries_merged()
    note_by_source = {s: n for s, _t, n in current}
    merged = {s: t for s, t, _n in current}
    added = updated = 0
    for source, target in parsed.items():
        if source not in merged:
            added += 1
        elif merged[source] != target:
            updated += 1
        else:
            continue
        merged[source] = target
    storage.write_glossary_entries(
        "names.txt", [(s, t, note_by_source.get(s, "")) for s, t in merged.items()]
    )
    storage.write_glossary_entries("vietphrase.txt", [])

    return JSONResponse({"added": added, "updated": updated, "total": added + updated})


def _reapply_chapters(storage: Storage, manifest, find: str, start, end):
    """Chương đã dịch trong phạm vi có chứa `find` (dùng cho preview + apply)."""
    for ch in _chapter_range(manifest.chapters, None, start, end):
        if storage.has_translated(ch):
            content = storage.read_translated(ch)
            count = content.count(find)
            if count:
                yield ch, content, count


def _snippet(content: str, find: str, width: int = 60) -> str:
    """Trích một đoạn quanh lần khớp đầu tiên để hiển thị trong preview."""
    pos = content.find(find)
    if pos < 0:
        return ""
    start = max(0, pos - width)
    end = min(len(content), pos + len(find) + width)
    text = content[start:end].replace("\n", " ").strip()
    return ("…" if start > 0 else "") + text + ("…" if end < len(content) else "")


@router.post("/api/ebooks/{slug}/glossary/reapply-preview")
def ebook_glossary_reapply_preview(
    slug: str,
    find: str = Form(...),
    replace: str = Form(""),
    chapter_from: int = Form(0),
    chapter_to: int = Form(0),
):
    """Xem trước 'sửa tên & áp dụng lại': quét `translated/` trong phạm vi, trả
    danh sách chương bị ảnh hưởng + số chỗ khớp + snippet. KHÔNG ghi gì."""
    find = find.strip()
    if not find:
        raise HTTPException(status_code=400, detail="Chuỗi cần tìm đang rỗng.")
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")

    start = chapter_from or None
    end = chapter_to or None
    chapters = []
    total = 0
    for ch, content, count in _reapply_chapters(storage, manifest, find, start, end):
        total += count
        chapters.append(
            {
                "index": ch.index,
                "title": ch.title,
                "count": count,
                "snippet": _snippet(content, find),
            }
        )
    return JSONResponse(
        {"find": find, "replace": replace, "total": total, "chapters": chapters}
    )


@router.post("/ebooks/{slug}/glossary/reapply")
def ebook_glossary_reapply(
    request: Request,
    slug: str,
    find: str = Form(...),
    replace: str = Form(...),
    chapter_from: int = Form(0),
    chapter_to: int = Form(0),
    source: str = Form(""),
):
    """Áp dụng lại: thay `find`→`replace` literal trên các chương ĐÃ DỊCH (chạy
    nền qua job). Nếu có `source`, cập nhật luôn mục glossary tương ứng (đổi
    target sang `replace`) trước khi chạy — quét CẢ 2 list vì DB cũ có thể
    chưa consolidate."""
    find, replace = find.strip(), replace.strip()
    if not find or not replace:
        raise HTTPException(status_code=400, detail="Cần cả chuỗi tìm và chuỗi thay.")
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)

    if source.strip():
        for list_name in ("names.txt", "vietphrase.txt"):
            entries = storage.read_glossary_entries(list_name)
            if not any(s == source.strip() for s, _t, _n in entries):
                continue
            updated = [
                (s, replace if s == source.strip() else t, n) for s, t, n in entries
            ]
            storage.write_glossary_entries(list_name, updated)

    start = chapter_from or None
    end = chapter_to or None

    def _target(log):
        step_find_replace(
            cfg, log, find=find, replace=replace, start=start, end=end, also_raw=False
        )

    started = request.app.state.job.start_custom(
        "reapply", _target, category="translate", ebook=cfg.novel.slug
    )
    if not started:
        raise HTTPException(status_code=409, detail="Đang có job khác chạy, vui lòng đợi.")
    return JSONResponse({"ok": True})
