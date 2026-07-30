"""Trang quản lý glossary: data table (CRUD inline), xuất/nhập cho AI dọn lại,
và match-count + propagate (lan truyền) thay đổi vào các bản dịch cũ."""
from __future__ import annotations

import re

from fastapi import APIRouter, Body, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from novel2epub import bulk_transfer, glossary_review
from novel2epub.pipeline import _chapter_range, step_find_replace
from novel2epub.storage import Storage

from .. import deps

router = APIRouter()

def _conflicts_count(storage) -> int:
    data = storage.read_extra_json("glossary_conflicts")
    return len(data) if isinstance(data, list) else 0


def _read_pending(storage) -> list[dict]:
    """Hàng chờ duyệt đề xuất auto-glossary (extra json `glossary_pending`),
    đã normalize — bỏ row hỏng, ép kiểu chapter_index."""
    raw = storage.read_extra_json("glossary_pending")
    out: list[dict] = []
    for p in raw if isinstance(raw, list) else []:
        if not isinstance(p, dict):
            continue
        source = str(p.get("source", "")).strip()
        target = str(p.get("target", "")).strip()
        if not source or not target:
            continue
        try:
            chapter_index = int(p.get("chapter_index", 0))
        except (TypeError, ValueError):
            chapter_index = 0
        out.append({"source": source, "target": target, "chapter_index": chapter_index})
    return out


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
            "pending_count": len(_read_pending(storage)),
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


@router.post("/api/ebooks/{slug}/glossary/entries/delete")
def ebook_glossary_delete_entries(slug: str, payload: dict = Body(...)):
    """Xoá NHIỀU mục một lần (multi-select trên bảng). Body JSON
    `{"sources": [...]}`. Source không tồn tại được bỏ qua, không lỗi."""
    sources = [str(s).strip() for s in payload.get("sources", []) if str(s).strip()]
    if not sources:
        raise HTTPException(status_code=400, detail="Chưa chọn mục nào để xoá.")
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    deleted = sum(1 for s in sources if storage.delete_glossary_entry(s))
    return JSONResponse({"deleted": deleted})


@router.post("/api/ebooks/{slug}/glossary/clean")
def ebook_glossary_clean(slug: str):
    """Dọn dữ liệu toàn glossary (trim, bỏ mục thiếu, dedup theo source) trên
    server. Trả `{before, after, removed}`."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    before, after = storage.clean_glossary()
    return JSONResponse({"before": before, "after": after, "removed": before - after})


@router.get("/api/ebooks/{slug}/glossary/pending")
def ebook_glossary_pending(slug: str):
    """Danh sách đề xuất auto-glossary đang chờ duyệt (tab "Đề xuất AI")."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    entries = _read_pending(storage)
    return JSONResponse({"entries": entries, "count": len(entries)})


@router.post("/api/ebooks/{slug}/glossary/pending/approve")
def ebook_glossary_pending_approve(slug: str, payload: dict = Body(...)):
    """Duyệt (hàng loạt) đề xuất chờ: upsert vào names.txt rồi gỡ khỏi hàng chờ.
    Body JSON `{"entries": [{source, target, note, original_source}, ...]}` —
    giá trị lấy từ input trên UI nên có thể đã được sửa tay trước khi duyệt;
    `original_source` là source lúc AI đề xuất, dùng làm khóa gỡ khỏi hàng chờ."""
    entries = []
    for row in payload.get("entries", []) if isinstance(payload.get("entries"), list) else []:
        if not isinstance(row, dict):
            continue
        source = str(row.get("source", "")).strip()
        target = str(row.get("target", "")).strip()
        if not source or not target:
            continue
        entries.append(
            {
                "source": source,
                "target": target,
                "note": str(row.get("note", "")).strip(),
                "original_source": str(row.get("original_source", "")).strip() or source,
            }
        )
    if not entries:
        raise HTTPException(status_code=400, detail="Chưa chọn đề xuất nào để duyệt.")
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    for e in entries:
        storage.upsert_glossary_entry(e["source"], e["target"], e["note"])
    approved_keys = {e["original_source"] for e in entries}
    remaining = [p for p in _read_pending(storage) if p["source"] not in approved_keys]
    storage.write_extra_json("glossary_pending", remaining)
    return JSONResponse({"approved": len(entries), "remaining": len(remaining)})


@router.post("/api/ebooks/{slug}/glossary/pending/clear")
def ebook_glossary_pending_clear(slug: str, payload: dict = Body(...)):
    """Bỏ đề xuất khỏi hàng chờ KHÔNG đưa vào glossary. Body JSON
    `{"sources": [...]}` hoặc `{"all": true}` (bỏ toàn bộ)."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    pending = _read_pending(storage)
    if payload.get("all"):
        storage.write_extra_json("glossary_pending", [])
        return JSONResponse({"cleared": len(pending)})
    sources = {str(s).strip() for s in payload.get("sources", []) if str(s).strip()}
    if not sources:
        raise HTTPException(status_code=400, detail="Chưa chọn đề xuất nào để bỏ.")
    remaining = [p for p in pending if p["source"] not in sources]
    storage.write_extra_json("glossary_pending", remaining)
    return JSONResponse({"cleared": len(pending) - len(remaining)})


@router.get("/api/ebooks/{slug}/glossary/suspects")
def ebook_glossary_suspects(slug: str):
    """Tab "Nghi vấn": nhóm mục trùng target / source lồng nhau / conflicts
    từ lần dịch. Consolidate legacy trước để chỉ quét names.txt."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    storage.consolidate_glossary()
    data = glossary_review.find_suspects(
        storage.read_glossary_entries("names.txt"),
        storage.read_extra_json("glossary_conflicts"),
    )
    data["count"] = (
        len(data["same_target"]) + len(data["nested_source"]) + len(data["conflicts"])
    )
    return JSONResponse(data)


@router.post("/api/ebooks/{slug}/glossary/conflicts/resolve")
def ebook_glossary_conflict_resolve(
    slug: str, source: str = Form(...), new: str = Form(...)
):
    """Gỡ 1 conflict đã xử lý (Giữ cũ / Lấy mới đều gọi) theo khóa dedup
    `(source, new)` — trùng key pipeline dùng khi ghi — để không hiện lại."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    raw = storage.read_extra_json("glossary_conflicts")
    if not isinstance(raw, list):
        raw = []
    remaining = [
        c
        for c in raw
        if not (isinstance(c, dict) and c.get("source") == source and c.get("new") == new)
    ]
    storage.write_extra_json("glossary_conflicts", remaining)
    return JSONResponse({"removed": len(raw) - len(remaining)})


@router.post("/api/ebooks/{slug}/glossary/conflicts/bulk-resolve")
def ebook_glossary_conflicts_bulk_resolve(slug: str, payload: dict = Body(...)):
    action = payload.get("action")
    if action not in {"take", "keep"}:
        raise HTTPException(status_code=400, detail="Thao tác conflict không hợp lệ.")

    requested: dict[tuple[str, str], dict[str, str]] = {}
    rows = payload.get("entries")
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        source = str(row.get("source", "")).strip()
        original_new = str(row.get("original_new", "")).strip()
        target = str(row.get("target", "")).strip()
        if not source or not original_new or (action == "take" and not target):
            continue
        requested[(source, original_new)] = {
            "target": target,
            "note": str(row.get("note", "")).strip(),
        }
    if not requested:
        raise HTTPException(status_code=400, detail="Chưa chọn conflict hợp lệ.")

    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    raw = storage.read_extra_json("glossary_conflicts")
    conflicts = raw if isinstance(raw, list) else []
    remaining = []
    resolved = 0
    for conflict in conflicts:
        if not isinstance(conflict, dict):
            remaining.append(conflict)
            continue
        key = (
            str(conflict.get("source", "")).strip(),
            str(conflict.get("new", "")).strip(),
        )
        request_row = requested.get(key)
        if request_row is None:
            remaining.append(conflict)
            continue
        if action == "take":
            storage.upsert_glossary_entry(
                key[0], request_row["target"], request_row["note"]
            )
        resolved += 1

    storage.write_extra_json("glossary_conflicts", remaining)
    return JSONResponse({"resolved": resolved, "remaining": len(remaining)})


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


def _compile_find(find: str, regex: bool):
    """Biên dịch chuỗi tìm kiếm thành pattern. `regex=False` coi `find` là chuỗi
    literal (escape). Ném HTTPException(400) khi regex không hợp lệ."""
    try:
        return re.compile(find if regex else re.escape(find))
    except re.error as e:
        raise HTTPException(status_code=400, detail=f"Regex không hợp lệ: {e}")


def _matching_chapters(storage: Storage, manifest, pattern, start, end):
    """Chương đã dịch trong phạm vi có chứa `pattern` (dùng cho match-count)."""
    for ch in _chapter_range(manifest.chapters, None, start, end):
        if storage.has_translated(ch):
            content = storage.read_translated(ch)
            count = len(pattern.findall(content))
            if count:
                yield ch, content, count


@router.get("/api/ebooks/{slug}/glossary/match-count")
def ebook_glossary_match_count(
    slug: str, find: str, chapter_index: int = 0, regex: bool = False
):
    """Đếm số chỗ khớp `find` trong bản dịch: theo 1 chương (nếu truyền
    chapter_index) + toàn bộ. `regex=True` coi `find` là biểu thức chính quy.
    Số đếm này chính là preview của propagate — không có bước xem trước riêng."""
    find = find.strip()
    if not find:
        raise HTTPException(status_code=400, detail="Chuỗi cần tìm đang rỗng.")
    pattern = _compile_find(find, regex)
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")

    chapter_count = total = chapter_total = 0
    for ch, _content, count in _matching_chapters(storage, manifest, pattern, None, None):
        total += count
        chapter_total += 1
        if chapter_index and ch.index == chapter_index:
            chapter_count = count
    return JSONResponse(
        {
            "find": find,
            "chapter_count": chapter_count,
            "total_count": total,
            "chapter_total": chapter_total,
        }
    )


@router.post("/api/ebooks/{slug}/glossary/propagate")
def ebook_glossary_propagate(
    request: Request,
    slug: str,
    find: str = Form(...),
    replace: str = Form(...),
    scope: str = Form(...),
    chapter_index: int = Form(0),
    regex: bool = Form(False),
):
    """Lan truyền thay đổi glossary vào bản dịch: `scope=chapter` thay đồng bộ
    NGAY trong 1 chương (backup vào meta như step_find_replace), `scope=all`
    enqueue job step_find_replace toàn bộ. `regex=True` coi `find` là biểu thức
    chính quy (backreference `\\1` dùng được trong `replace`). Không tự sửa mục
    glossary — client đã upsert qua /glossary/entry trước."""
    find, replace = find.strip(), replace.strip()
    if not find or not replace:
        raise HTTPException(status_code=400, detail="Cần cả chuỗi tìm và chuỗi thay.")
    if scope not in ("chapter", "all"):
        raise HTTPException(status_code=400, detail="scope phải là 'chapter' hoặc 'all'.")
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)

    if scope == "chapter":
        if not chapter_index:
            raise HTTPException(status_code=400, detail="Thiếu chapter_index.")
        pattern = _compile_find(find, regex)
        manifest = storage.load_manifest()
        if manifest is None:
            raise HTTPException(status_code=404, detail="Chưa có manifest.")
        ch = next((c for c in manifest.chapters if c.index == chapter_index), None)
        if ch is None or not storage.has_translated(ch):
            raise HTTPException(status_code=404, detail="Chương chưa có bản dịch.")
        content = storage.read_translated(ch)
        new_content, count = pattern.subn(replace, content)
        if count:
            meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
            meta["before_find_replace"] = content
            storage.write_meta(ch, meta)
            storage.write_translated(ch, new_content)
        return JSONResponse({"replaced": count})

    # scope == "all": validate regex sớm để trả 400 trước khi enqueue job.
    if regex:
        _compile_find(find, regex)

    def _target(log):
        step_find_replace(
            cfg, log, find=find, replace=replace, start=None, end=None,
            also_raw=False, regex=regex,
        )

    started = request.app.state.job.start_custom(
        "propagate", _target, category="translate", ebook=cfg.novel.slug
    )
    if not started:
        raise HTTPException(status_code=409, detail="Đang có job khác chạy, vui lòng đợi.")
    return JSONResponse({"ok": True})
