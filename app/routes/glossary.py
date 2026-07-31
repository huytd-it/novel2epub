"""Trang quản lý glossary: data table (CRUD inline), xuất/nhập cho AI dọn lại,
và match-count + propagate (lan truyền) thay đổi vào các bản dịch cũ."""
from __future__ import annotations

import re

from fastapi import APIRouter, Body, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from novel2epub import bulk_transfer, glossary_review
from novel2epub.pipeline import _chapter_range, step_find_replace
from novel2epub.storage import Storage, normalize_glossary_pending

from .. import deps

router = APIRouter()


def _read_pending(storage) -> list[dict]:
    """Hàng chờ duyệt thay đổi auto-glossary (extra json `glossary_pending`),
    đã migrate schema replacement + normalize."""
    storage.migrate_glossary_queue()
    return normalize_glossary_pending(storage.read_extra_json("glossary_pending"))


def _normalize_pending(raw) -> list[dict]:
    """Normalize a queue snapshot without performing another database read."""
    return normalize_glossary_pending(raw)


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
    storage.migrate_glossary_queue()
    # Trang tải dữ liệu theo trang qua ajax (/glossary/list) — không nhúng toàn
    # bộ mục vào HTML nữa.
    return deps.templates.TemplateResponse(
        request,
        "glossary.html",
        {
            "slug": slug,
            "job": request.app.state.job.status(),
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
    """Danh sách đề xuất thay đổi glossary đang chờ duyệt (hàng chờ replacement)."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    entries = _read_pending(storage)
    return JSONResponse({"entries": entries, "count": len(entries)})


@router.get("/api/ebooks/{slug}/glossary/replace/preview")
def ebook_glossary_replace_preview(slug: str):
    """Preview: đếm số lần khớp từng đề xuất trong bản dịch cũ + meta + ebook
    (xem `Storage.replacement_counts`) — dữ liệu cho nút "Duyệt" xác nhận,
    kể cả khi count = 0 (chỉ upsert glossary, không cần lan truyền)."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    entries = _read_pending(storage)
    pairs = [
        (p["existing_target"], p["target"])
        for p in entries
        if p["existing_target"] and p["existing_target"] != p["target"]
    ]
    counts = storage.replacement_counts(pairs)
    by_old = {c["old"]: c for c in counts["pairs"]}
    for p in entries:
        info = by_old.get(p["existing_target"]) if p["existing_target"] else None
        p["count"] = info["count"] if info else 0
        p["chapters"] = info["chapters"] if info else 0
    return JSONResponse({"entries": entries, "count": len(entries), "total_matches": counts["total"]})


def glossary_approve_job_factory(params: dict):
    """Tái tạo job duyệt glossary từ spec đã lưu (xem JobQueue.register_kind)
    — để enqueue lại job còn dang dở sau khi app restart.

    Job thực hiện: upsert glossary + gỡ hàng chờ (MỘT transaction) rồi lan
    truyền các thay đổi `existing_target → target` vào bản dịch cũ. Idempotent:
    nếu chạy lại, các source đã duyệt không còn trong hàng chờ nên bị bỏ qua
    (stale)."""
    slug = params["slug"]
    requested = params["entries"]

    def _target(log: Callable[[str], None]) -> None:
        cfg = deps.resolved_cfg(slug)
        storage = Storage(cfg.output.data_dir, cfg.novel.slug)
        result = storage.approve_glossary_rows(requested)
        approved = result["approved"]
        log(f"[glossary-duyệt] Đã duyệt {len(approved)}/{len(requested)} mục, còn {len(result['remaining'])} chờ.")
        for a in approved:
            log(
                f"[glossary-duyệt]   + {a['source']}: "
                f"'{a.get('existing_target') or '—'}' → '{a['target']}'"
            )
        pairs = [
            (a["existing_target"], a["target"])
            for a in approved
            if a.get("existing_target") and a["existing_target"] != a["target"]
        ]
        stats: dict = {"total": 0, "chapters": 0, "ebook": False}
        if pairs:
            log(f"[glossary-duyệt] Lan truyền {len(pairs)} thay đổi vào bản dịch cũ…")
            stats = storage.apply_replacements(pairs)
            log(f"[glossary-duyệt] Hoàn tất: {stats['total']} lần thay trên {stats['chapters']} chương.")
        else:
            log("[glossary-duyệt] Không có thay đổi nào để lan truyền (mục mới / giữ nguyên).")
        return {
            "requested": len(requested),
            "approved": approved,
            "remaining": len(result["remaining"]),
            "replacements": stats,
        }

    return _target


@router.post("/api/ebooks/{slug}/glossary/replace/approve")
def ebook_glossary_replace_approve(request: Request, slug: str, payload: dict = Body(...)):
    """Duyệt (hàng loạt) đề xuất thay thế: enqueue MỘT job duyệt
    (category=translate, lock ebook) — KHÔNG thay đổi dữ liệu ngay ở đây. Job
    thực hiện upsert glossary + gỡ hàng chờ + lan truyền vào bản dịch (xem
    `glossary_approve_job_factory`), kết quả nằm trong outcome/log của job.

    Body JSON `{"entries": [{source, target, note}, ...]}` — giá trị lấy từ
    input trên UI nên có thể đã được sửa tay (note giữ nguyên nếu để trống)."""
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
            }
        )
    if not entries:
        raise HTTPException(status_code=400, detail="Chưa chọn đề xuất nào để duyệt.")
    cfg = deps.resolved_cfg(slug)
    spec = {"kind": "glossary-approve", "params": {"slug": slug, "entries": entries}}
    started = request.app.state.job.start_custom(
        "glossary-approve",
        glossary_approve_job_factory(spec["params"]),
        category="translate",
        ebook=slug,
        spec=spec,
    )
    if not started:
        raise HTTPException(status_code=409, detail="Đang có job khác chạy, vui lòng đợi.")
    return JSONResponse({"started": True, "requested": len(entries)})


@router.get("/api/ebooks/{slug}/glossary/approve/status")
def ebook_glossary_approve_status(request: Request, slug: str):
    """Trạng thái + outcome của job duyệt glossary gần nhất cho ebook này."""
    queue = getattr(request.app.state.job, "queue", None)
    if queue is None:
        return JSONResponse({"running": False, "state": "", "step": "", "job_id": "", "outcome": None, "error": ""})
    recent = None
    running = False
    for j in queue.snapshot()["history"]:
        if j.get("ebook") == slug and j.get("step") == "glossary-approve":
            recent = j
            break
    for j in queue.snapshot()["running"]:
        if j.get("ebook") == slug and j.get("step") == "glossary-approve":
            running = True
            recent = j
            break
    if recent is None:
        return JSONResponse({"running": False, "state": "", "step": "", "job_id": "", "outcome": None, "error": ""})
    return JSONResponse(
        {
            "running": running,
            "state": recent.get("state", ""),
            "step": recent.get("step", ""),
            "job_id": recent.get("id", ""),
            "outcome": recent.get("outcome"),
            "error": recent.get("error", ""),
        }
    )


@router.post("/api/ebooks/{slug}/glossary/pending/clear")
def ebook_glossary_pending_clear(slug: str, payload: dict = Body(...)):
    """Bỏ đề xuất khỏi hàng chờ KHÔNG đưa vào glossary. Body JSON
    `{"sources": [...]}` hoặc `{"all": true}` (bỏ toàn bộ)."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    storage.migrate_glossary_queue()
    if payload.get("all"):
        previous_count = 0
        def _clear_all(raw):
            nonlocal previous_count
            previous_count = len(_normalize_pending(raw))
            return []
        storage.update_extra_json("glossary_pending", _clear_all)
        return JSONResponse({"cleared": previous_count})
    sources = {str(s).strip() for s in payload.get("sources", []) if str(s).strip()}
    if not sources:
        raise HTTPException(status_code=400, detail="Chưa chọn đề xuất nào để bỏ.")
    cleared = 0
    def _clear_selected(raw):
        nonlocal cleared
        pending = _normalize_pending(raw)
        remaining = [p for p in pending if p["source"] not in sources]
        cleared = len(pending) - len(remaining)
        return remaining
    storage.update_extra_json("glossary_pending", _clear_selected)
    return JSONResponse({"cleared": cleared})


@router.get("/api/ebooks/{slug}/glossary/suspects")
def ebook_glossary_suspects(slug: str):
    """Tab "Nghi vấn": nhóm mục trùng target / source lồng nhau. Conflicts từ
    lần dịch nay nằm trong hàng chờ duyệt (replacement) nên không còn nhóm
    riêng ở đây. Consolidate legacy trước để chỉ quét names.txt."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    storage.consolidate_glossary()
    storage.migrate_glossary_queue()
    data = glossary_review.find_suspects(
        storage.read_glossary_entries("names.txt"),
        None,
    )
    data["count"] = (
        len(data["same_target"]) + len(data["nested_source"]) + len(data["conflicts"])
    )
    return JSONResponse(data)


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
