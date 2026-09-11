"""Trang quản lý glossary: data table (CRUD inline), xuất/nhập cho AI dọn lại,
và match-count + propagate (lan truyền) thay đổi vào các bản dịch cũ."""
from __future__ import annotations

import json
import re
from collections import Counter

from fastapi import APIRouter, Body, Form, HTTPException, Request
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse, RedirectResponse

from novel2epub import bulk_transfer, glossary_ai, glossary_review
from novel2epub.han_cleanup import count_han
from novel2epub.notes import split_paras
from novel2epub.pipeline import _chapter_range, step_find_replace
from novel2epub.storage import Storage, normalize_glossary_pending

from app.chapter_compare import split_blocks

from .. import deps

router = APIRouter()

# Một nguồn duy nhất cho thông báo: planner thuần dữ liệu cũng dùng chuỗi này.
INVALID_SOURCE_DETAIL = glossary_review.INVALID_SOURCE_DETAIL


class ProperNameExtractRequest(BaseModel):
    """Yêu cầu dò tên riêng trong raw và đưa ứng viên vào hàng chờ glossary."""

    chapter_indexes: list[int] | None = Field(default=None, description="Giới hạn chương; bỏ trống để quét toàn sách.")
    min_frequency: int = Field(default=2, ge=1, le=100)
    max_candidates: int = Field(default=100, ge=1, le=500)
    translate: bool = Field(default=True, description="Dịch ứng viên bằng Local MT trước khi xếp hàng.")


_SURNAME = set("赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴宋茅庞熊纪舒屈项祝董梁杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍虞万支柯管卢莫经房裘缪干解应宗丁宣邓郁单杭洪包诸左石崔吉龚程邢裴陆荣翁荀羊於惠甄曲封芮储靳汲邴糜松井段富巫乌焦巴弓牧隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭厉戎祖武符刘景詹束龙叶幸司韶郜黎蓟薄印宿白怀蒲台从鄂索咸籍赖卓蔺屠蒙池乔阴胥能苍双闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍却璩桑桂濮牛寿通边扈燕冀郏浦尚农温别庄晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘匡国文寇广禄阙东欧殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶空曾毋沙乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公")
_NAME_CONTEXT = re.compile(r"(?:说道|问道|笑道|喝道|叫道|看着|望向|对|向|与|跟|被|将|让)([\u3400-\u9fff]{2,4})")
_HAN_TOKEN = re.compile(r"[\u3400-\u9fff]{2,4}")
_NAME_STOP = {"什么", "怎么", "这个", "那个", "自己", "他们", "我们", "你们", "现在", "时候", "因为", "所以", "但是", "如果", "没有", "一个", "已经", "可以", "知道", "说道", "问道", "看着", "起来", "出来", "进去", "这里", "那里"}


def extract_proper_name_candidates(texts: list[tuple[int, str]], *, min_frequency: int = 2, max_candidates: int = 100) -> list[dict]:
    """Dò ứng viên tên người từ raw bằng surname + ngữ cảnh hội thoại.

    Đây là recognizer bảo thủ, không khẳng định entity: kết quả luôn phải qua
    hàng chờ duyệt trước khi thành glossary.
    """
    counts: Counter[str] = Counter()
    contexts: dict[str, str] = {}
    chapters: dict[str, int] = {}
    contextual: Counter[str] = Counter()
    for chapter_index, text in texts:
        for match in _HAN_TOKEN.finditer(text):
            token = match.group(0)
            if token in _NAME_STOP or token[0] not in _SURNAME:
                continue
            counts[token] += 1
            chapters.setdefault(token, chapter_index)
            contexts.setdefault(token, text[max(0, match.start() - 18): match.end() + 18].replace("\n", " "))
        for token in _NAME_CONTEXT.findall(text):
            if token not in _NAME_STOP:
                contextual[token] += 1
                counts[token] += 1
                chapters.setdefault(token, chapter_index)
    rows = []
    for source, frequency in counts.most_common():
        if frequency < min_frequency:
            continue
        context_hits = contextual[source]
        confidence = min(0.98, 0.45 + min(frequency, 10) * 0.035 + min(context_hits, 3) * 0.1)
        rows.append({
            "source": source,
            "frequency": frequency,
            "confidence": round(confidence, 2),
            "chapter_index": chapters[source],
            "context": contexts.get(source, ""),
        })
        if len(rows) >= max_candidates:
            break
    return rows


def _validate_glossary_source(source: str) -> None:
    if count_han(source) == 0:
        raise HTTPException(status_code=400, detail=INVALID_SOURCE_DETAIL)


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
    _validate_glossary_source(source)
    existing = {s: t for s, t, _n in storage.read_glossary_entries_merged()}
    if existing.get(source) == suggested and not note:
        return False

    line = f"{source} = {suggested}" + (f" | {note}" if note else "")
    storage.append_glossary_line("names.txt", line)
    return True


def _sorted_entries(rows: list[tuple[str, str, str]], sort: str, dir: str) -> list[tuple[str, str, str]]:
    """Sắp xếp trong Python cho nhánh có lọc cờ — cùng quy tắc với SQL
    (`COLLATE NOCASE`, cột lạ thì giữ nguyên thứ tự position)."""
    col = {"source": 0, "target": 1, "note": 2}.get(sort or "")
    if col is None:
        return rows
    return sorted(rows, key=lambda r: r[col].lower(), reverse=str(dir).lower() == "desc")


@router.get("/api/ebooks/{slug}/glossary/list")
def ebook_glossary_list(
    slug: str,
    page: int = 1,
    per_page: int = 50,
    q: str = "",
    sort: str = "",
    dir: str = "asc",
    filter: str = "",
):
    """Một trang glossary (server-side pagination + search + sort). Consolidate
    vietphrase legacy vào names.txt trước để chỉ cần quét 1 list.

    `filter` là danh sách cờ "giá trị đáng ngờ" ngăn cách bởi dấu phẩy (xem
    `glossary_review.GLOSSARY_FLAGS`). Cờ là vị từ chuỗi (có chữ Hán trong cột
    Việt, chữ Latin trong cột Hán...) nên SQLite không lọc được — nhánh này đọc
    cả list rồi lọc/sắp/phân trang trong Python. Vài nghìn mục nên vẫn tức thì,
    và nhánh không lọc giữ nguyên đường SQL cũ.
    """
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    storage.consolidate_glossary()

    per_page = max(1, min(int(per_page), 500))
    flags = glossary_review.parse_flags(filter)

    if flags:
        rows_all = storage.read_glossary_entries("names.txt")
        needle = (q or "").strip().lower()
        if needle:
            rows_all = [r for r in rows_all if needle in (r[0] + r[1] + r[2]).lower()]
        rows_all = glossary_review.filter_by_flags(rows_all, flags)
        total = len(rows_all)
        pages = max(1, (total + per_page - 1) // per_page)
        page = max(1, min(int(page), pages))
        offset = (page - 1) * per_page
        rows = _sorted_entries(rows_all, sort, dir)[offset : offset + per_page]
    else:
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


@router.get("/api/ebooks/{slug}/glossary/flags")
def ebook_glossary_flags(slug: str):
    """Số mục dính từng cờ "giá trị đáng ngờ" — dữ liệu cho các chip Lọc.

    Dùng chung `entry_flags` với route list nên con số trên chip luôn khớp số
    dòng bấm vào lọc ra."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    entries = storage.read_glossary_entries("names.txt")
    counts = glossary_review.count_entry_flags(entries)
    return JSONResponse(
        {
            "flags": [
                {"key": key, "label": label, "hint": hint, "count": counts[key]}
                for key, (label, hint) in glossary_review.GLOSSARY_FLAGS.items()
            ],
            "total": len(entries),
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
    """Autosave MỘT mục (thêm hoặc sửa).

    Nếu đổi source thì xoá mục cũ; nếu đổi target thì lan truyền giá trị cũ
    sang nội dung đã dịch bằng cùng quy tắc với luồng duyệt glossary.
    """
    source, target = source.strip(), target.strip()
    if not source or not target:
        raise HTTPException(status_code=400, detail="Cần cả Hán và Việt.")
    _validate_glossary_source(source)
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    orig = original_source.strip()
    lookup_source = orig or source
    old_target = next(
        (
            existing_target
            for existing_source, existing_target, _note in storage.read_glossary_entries_merged()
            if existing_source == lookup_source
        ),
        None,
    )
    if orig and orig != source:
        storage.delete_glossary_entry(orig)
    storage.upsert_glossary_entry(source, target, note)
    if old_target and old_target != target:
        storage.apply_replacements([(old_target, target)])
    return JSONResponse({"ok": True})


class GlossaryEditIn(BaseModel):
    """Một dòng bảng glossary người dùng đã sửa nhưng CHƯA ghi."""

    source: str = ""
    target: str = ""
    note: str = ""
    original_source: str = Field(default="", description="Khoá cũ; bỏ trống nghĩa là thêm mới.")


class GlossaryEditsIn(BaseModel):
    edits: list[GlossaryEditIn] = Field(default_factory=list)


def _plan_edits(storage, payload: GlossaryEditsIn) -> list[dict]:
    return glossary_review.plan_glossary_edits(
        storage.read_glossary_entries_merged(),
        [edit.model_dump() for edit in payload.edits],
    )


@router.post("/api/ebooks/{slug}/glossary/entries/preview")
def ebook_glossary_edits_preview(slug: str, payload: GlossaryEditsIn):
    """Xem trước CẢ ĐỢT sửa trước khi ghi: mỗi dòng kèm giá trị cũ, loại thay
    đổi, lỗi (nếu có) và số chỗ trong bản dịch cũ sẽ bị lan truyền theo.

    Chỉ đọc — không đụng glossary lẫn nội dung chương."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    planned = _plan_edits(storage, payload)
    counts = storage.replacement_counts(glossary_review.replacement_pairs(planned))
    by_old = {c["old"]: c for c in counts["pairs"]}
    for row in planned:
        info = by_old.get(row["existing_target"]) if row["existing_target"] else None
        applies = info is not None and not row["error"] and row["kind"] != "unchanged"
        row["count"] = info["count"] if applies else 0
        row["chapters"] = info["chapters"] if applies else 0
    return JSONResponse(
        {
            "entries": planned,
            "writes": sum(1 for r in planned if not r["error"] and r["kind"] != "unchanged"),
            "errors": sum(1 for r in planned if r["error"]),
            "total_matches": counts["total"],
        }
    )


@router.post("/api/ebooks/{slug}/glossary/entries")
def ebook_glossary_upsert_entries(slug: str, payload: GlossaryEditsIn):
    """Ghi CẢ ĐỢT sửa sau khi người dùng xác nhận ở modal xem trước.

    Từ chối toàn bộ nếu còn dòng lỗi (all-or-nothing ở mức xác thực) để kết quả
    khớp với thứ đã xem trước. Đổi Hán thì xoá khoá cũ; đổi Việt thì lan truyền
    sang bản dịch đã có — gộp MỘT lượt quét cho cả đợt thay vì mỗi dòng một lần.
    """
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    planned = _plan_edits(storage, payload)

    failed = [r for r in planned if r["error"]]
    if failed:
        first = failed[0]
        raise HTTPException(
            status_code=400,
            detail=f"{first['source'] or first['original_source'] or '(trống)'}: {first['error']}"
            + (f" (+{len(failed) - 1} dòng lỗi khác)" if len(failed) > 1 else ""),
        )

    writes = [r for r in planned if r["kind"] != "unchanged"]
    pairs = glossary_review.replacement_pairs(planned)
    for row in writes:
        if row["kind"] == "rename":
            storage.delete_glossary_entry(row["original_source"])
        storage.upsert_glossary_entry(row["source"], row["target"], row["note"])

    stats = storage.apply_replacements(pairs) if pairs else {"total": 0, "chapters": 0, "ebook": False}
    return JSONResponse(
        {
            "applied": len(writes),
            "added": sum(1 for r in writes if r["kind"] == "new"),
            "renamed": sum(1 for r in writes if r["kind"] == "rename"),
            "skipped": len(planned) - len(writes),
            "replacements": stats,
        }
    )


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


@router.post(
    "/api/ebooks/{slug}/glossary/proper-names/extract",
    tags=["Glossary"],
    summary="Trích xuất tên riêng từ raw",
)
def ebook_glossary_extract_proper_names(slug: str, payload: ProperNameExtractRequest):
    """Dò tên người từ raw, tùy chọn dịch Local MT, rồi xếp hàng chờ duyệt.

    Entry glossary đã tồn tại và source đã có trong pending đều được bỏ qua;
    endpoint không bao giờ ghi trực tiếp vào glossary chuẩn.
    """
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có mục lục.")
    selected = set(payload.chapter_indexes or [])
    texts = [
        (chapter.index, storage.read_raw(chapter))
        for chapter in manifest.chapters
        if (not selected or chapter.index in selected) and storage.has_raw(chapter)
    ]
    candidates = extract_proper_name_candidates(
        texts, min_frequency=payload.min_frequency, max_candidates=payload.max_candidates
    )
    existing = {source for source, _target, _note in storage.read_glossary_entries_merged()}
    pending_before = _read_pending(storage)
    pending_sources = {row["source"] for row in pending_before}
    translator = None
    if payload.translate and candidates:
        try:
            from .reader import _quick_mt_lock, _quick_mt_translator
            translator = _quick_mt_translator(slug)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Không tải được Local MT: {exc}")

    additions: list[dict] = []
    skipped_existing = 0
    for row in candidates:
        source = row["source"]
        if source in existing or source in pending_sources:
            skipped_existing += 1
            continue
        target = source
        if translator is not None:
            try:
                with _quick_mt_lock:
                    target = translator.translate(source).strip()
            except Exception as exc:
                raise HTTPException(status_code=503, detail=f"Local MT lỗi khi dịch '{source}': {exc}")
        if not target:
            continue
        additions.append({
            "source": source,
            "existing_target": "",
            "target": target,
            "chapter_index": row["chapter_index"],
            "note": f"Raw NER · tần suất {row['frequency']} · tin cậy {row['confidence']:.0%} · {row['context']}",
        })

    def _merge(current):
        pending = _normalize_pending(current)
        seen = {row["source"] for row in pending}
        return pending + [row for row in additions if row["source"] not in seen and row["source"] not in existing]

    merged = storage.update_extra_json("glossary_pending", _merge)
    return {
        "scanned_chapters": len(texts),
        "detected": len(candidates),
        "queued": len(merged) - len(pending_before),
        "skipped_existing": skipped_existing,
        "candidates": candidates,
    }


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
        _validate_glossary_source(source)
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


class GlossaryAiRequest(BaseModel):
    """Yêu cầu Trợ lý AI dịch lại các mục đã tick trên bảng."""

    sources: list[str] = Field(default_factory=list)
    instruction: str = Field(default="", description="Yêu cầu thêm cho riêng lần chạy này.")


def glossary_ai_job_factory(params: dict):
    """Tái tạo job Trợ lý AI glossary từ spec đã lưu (xem JobQueue.register_kind).

    Job KHÔNG ghi thẳng vào glossary: kết quả vào hàng chờ duyệt
    (`glossary_pending`) để người dùng xem "cũ → mới" kèm số chỗ ảnh hưởng rồi
    mới duyệt — cùng đường đi với đề xuất auto-glossary lúc dịch.
    """
    slug = params["slug"]
    sources = params["sources"]
    instruction = str(params.get("instruction", "") or "")

    def _target(log: Callable[[str], None]) -> None:
        cfg = deps.resolved_cfg(slug)
        storage = Storage(cfg.output.data_dir, cfg.novel.slug)
        current = {s: (t, n) for s, t, n in storage.read_glossary_entries_merged()}
        # Trợ lý AI chỉ sửa cột Việt — cột Hán là khoá của hàng chờ duyệt, không
        # đổi được. Mục có cột Hán không phải chữ Trung (thường là Hán/Việt bị
        # đảo) sẽ tạo ra đề xuất mà bước Duyệt từ chối, nên loại từ đây và chỉ
        # cho người dùng đường đi đúng.
        selected = [s for s in sources if s in current]
        invalid = [s for s in selected if count_han(s) == 0]
        entries = [
            {"source": s, "target": current[s][0], "note": current[s][1]}
            for s in selected
            if s not in invalid
        ]
        if invalid:
            log(
                f"[glossary-ai] Bỏ qua {len(invalid)} mục có cột Hán không phải chữ Trung "
                f"(vd {invalid[0]!r}) — AI không sửa được cột Hán, hãy sửa tay trong bảng rồi bấm Áp dụng."
            )
        if not entries:
            log("[glossary-ai] Không còn mục nào xử lý được. Dừng.")
            return {"requested": len(sources), "queued": 0, "unchanged": 0, "skipped": len(invalid)}

        parts = [x.strip() for x in (cfg.translate.context_note, instruction) if x.strip()]
        context = "\n\n".join(parts)
        # Metadata truyện đi kèm prompt: tên + giới thiệu đủ để AI biết thể
        # loại và hệ thống xưng hô trước khi phiên âm tên riêng.
        story = {
            "title": cfg.novel.title,
            "author": cfg.novel.author,
            "description": cfg.novel.description,
        }
        log(f"[glossary-ai] Nhờ AI rà soát {len(entries)} mục" + (" (có mô tả bối cảnh)." if context else "."))
        results = glossary_ai.retranslate_terms(
            cfg.ai.openai,
            entries,
            story=story,
            context=context,
            genre=cfg.translate.genre,
            max_chars=cfg.translate.prompt_max_chars or 20000,
            log=log,
        )

        changed = [r for r in results if r["target"] != current.get(r["source"], ("", ""))[0]]
        unchanged = len(results) - len(changed)
        for r in changed:
            log(f"[glossary-ai]   ~ {r['source']}: '{current[r['source']][0]}' → '{r['target']}'"
                + (f" ({r['reason']})" if r["reason"] else ""))

        additions = [
            {
                "source": r["source"],
                "target": r["target"],
                "existing_target": current[r["source"]][0],
                "chapter_index": 0,
                "note": r["reason"] or current[r["source"]][1],
            }
            for r in changed
        ]

        def _merge(raw):
            # Đề xuất mới cho cùng một source THAY đề xuất cũ đang chờ: hàng chờ
            # là "giá trị muốn đổi thành", giữ hai dòng cùng source là mâu thuẫn.
            fresh = {row["source"] for row in additions}
            kept = [row for row in _normalize_pending(raw) if row["source"] not in fresh]
            return kept + additions

        merged = storage.update_extra_json("glossary_pending", _merge)
        log(
            f"[glossary-ai] Xong: {len(changed)} mục vào hàng chờ duyệt, "
            f"{unchanged} mục AI giữ nguyên, {len(entries) - len(results)} mục AI không trả lời. "
            f"Hàng chờ hiện có {len(merged)} mục."
        )
        return {
            "requested": len(sources),
            "queued": len(changed),
            "unchanged": unchanged,
            "missing": len(entries) - len(results),
            "skipped": len(invalid),
        }

    return _target


@router.post("/api/ebooks/{slug}/glossary/ai/retranslate")
def ebook_glossary_ai_retranslate(request: Request, slug: str, payload: GlossaryAiRequest):
    """Trợ lý AI: dịch lại HÀNG LOẠT các mục đã chọn → hàng chờ duyệt.

    Enqueue MỘT job (category=translate, khoá ebook) như các batch AI khác —
    gọi AI cho vài trăm mục mất hàng phút, quá lâu cho một request HTTP. Tiến
    độ xem ở trang Hàng đợi; kết quả hiện thành hàng vàng ở đầu bảng glossary.
    """
    sources: list[str] = []
    for raw in payload.sources:
        source = str(raw).strip()
        if source and source not in sources:
            sources.append(source)
    if not sources:
        raise HTTPException(status_code=400, detail="Chưa chọn mục nào để nhờ AI xử lý.")

    cfg = deps.resolved_cfg(slug)
    if not cfg.ai.openai.base_url:
        raise HTTPException(status_code=400, detail="Chưa cấu hình AI biên tập (mục AI trong Cài đặt).")

    spec = {
        "kind": "glossary-ai",
        "params": {"slug": slug, "sources": sources, "instruction": payload.instruction.strip()},
    }
    started = request.app.state.job.start_custom(
        "glossary-ai",
        glossary_ai_job_factory(spec["params"]),
        category="translate",
        ebook=slug,
        spec=spec,
    )
    if not started:
        raise HTTPException(status_code=409, detail="Đang có job khác chạy, vui lòng đợi.")
    return JSONResponse({"started": True, "requested": len(sources)})


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

    entries = _to_tuples(payload.get("entries"))
    for source, target, _note in entries:
        if source.strip() and target.strip():
            _validate_glossary_source(source)
    storage.write_glossary_entries("names.txt", entries)
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
    """Nhập glossary AI trả về: parse các dòng `Hán = Việt` sau nhãn
    `GLOSSARY:` rồi MERGE vào glossary hiện tại (source trùng → giá trị mới
    thắng, giữ ghi chú cũ). Ghi tất cả vào names.txt + dọn vietphrase.txt
    (consolidation). Trả thống kê `{added, updated, total}`."""
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    parsed = bulk_transfer.parse_glossary(text)
    if not parsed:
        raise HTTPException(
            status_code=400,
            detail="Không tìm thấy mục glossary nào (cần nhãn GLOSSARY: với các dòng `Hán = Việt`).",
        )
    for source in parsed:
        _validate_glossary_source(source)

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
        return re.compile(find if regex else re.escape(find), re.IGNORECASE)
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


_FIND_PREVIEW_LIMIT = 300


@router.get("/api/ebooks/{slug}/glossary/find-preview")
def ebook_glossary_find_preview(
    slug: str,
    find: str,
    replace: str = "",
    regex: bool = False,
    scope: str = "chapter",
    chapter_index: int = 0,
    source: str = "translated",
):
    """Xem trước các ĐOẠN (không phải từng chỗ khớp) chứa `find`, phục vụ
    modal thay thế cho phép chọn áp dụng theo từng đoạn tìm thấy hoặc tất cả.
    `scope=chapter` chỉ quét 1 chương, `scope=all` quét mọi chương.

    `source=translated` (mặc định) quét bản dịch của nhánh active, chia đoạn
    theo DÒNG (`split_paras`) — khớp `para/save`; `source=raw` quét bản gốc đã
    crawl (kể cả chương chưa dịch), chia đoạn theo KHỐI (`split_blocks`) —
    `para_index` khi đó là index KHỐI trong `app.chapter_compare`, không phải
    dòng. Giới hạn 300 đoạn để tránh trả về quá nặng với truyện dài.
    """
    find = find.strip()
    if not find:
        raise HTTPException(status_code=400, detail="Chuỗi cần tìm đang rỗng.")
    if scope not in ("chapter", "all"):
        raise HTTPException(status_code=400, detail="scope phải là 'chapter' hoặc 'all'.")
    if source not in ("translated", "raw"):
        raise HTTPException(status_code=400, detail="source phải là 'translated' hoặc 'raw'.")
    pattern = _compile_find(find, regex)
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")

    if scope == "chapter":
        if not chapter_index:
            raise HTTPException(status_code=400, detail="Thiếu chapter_index.")
        chapters = [c for c in manifest.chapters if c.index == chapter_index]
        if not chapters:
            raise HTTPException(status_code=404, detail="Không tìm thấy chương.")
    else:
        chapters = manifest.chapters

    def _read(ch):
        if source == "raw":
            return storage.read_raw(ch) if storage.has_raw(ch) else ""
        return storage.read_active_branch_text(ch) if storage.has_active_branch_text(ch) else ""

    def _split(text):
        if source == "raw":
            from app.chapter_compare import split_blocks as _sb
            return _sb(text)
        return split_paras(text)

    items: list[dict] = []
    truncated = False
    for ch in chapters:
        text = _read(ch)
        if not text:
            continue
        if regex:
            for idx, m in enumerate(pattern.finditer(text)):
                try:
                    after_text = m.expand(replace) if replace else ""
                except re.error as e:
                    raise HTTPException(status_code=400, detail=f"Regex thay thế không hợp lệ: {e}")
                items.append({
                    "chapter_index": ch.index,
                    "chapter_title": ch.title or f"Chương {ch.index}",
                    "para_index": -(idx + 1),
                    "count": 1,
                    "before": m.group(),
                    "after": after_text,
                })
                if len(items) >= _FIND_PREVIEW_LIMIT:
                    truncated = True
                    break
        else:
            paras = _split(text)
            for i, para in enumerate(paras):
                count = len(pattern.findall(para))
                if not count:
                    continue
                try:
                    after = pattern.sub(replace, para)
                except re.error as e:
                    raise HTTPException(status_code=400, detail=f"Regex thay thế không hợp lệ: {e}")
                items.append({
                    "chapter_index": ch.index,
                    "chapter_title": ch.title or f"Chương {ch.index}",
                    "para_index": i,
                    "count": count,
                    "before": para,
                    "after": after,
                })
                if len(items) >= _FIND_PREVIEW_LIMIT:
                    truncated = True
                    break
        if truncated:
            break
    return JSONResponse({"items": items, "truncated": truncated})


@router.post("/api/ebooks/{slug}/glossary/apply-selected")
def ebook_glossary_apply_selected(
    slug: str,
    find: str = Form(...),
    replace: str = Form(""),
    regex: bool = Form(False),
    selections: str = Form("[]"),
    source: str = Form("translated"),
    all_matches: bool = Form(False),
):
    """Áp dụng thay thế CHỈ cho các đoạn client đã chọn (từ `/find-preview`).

    `selections` là JSON list `[{"chapter_index": N, "para_index": N,
    "expected": "..."}, ...]`. `expected` chứa nội dung đoạn lúc preview — dùng
    làm stale protection: đoạn đã đổi sau khi preview thì bỏ qua (đếm vào
    `stale`), không ghi đè mù.

    `source=translated` (mặc định) sửa bản dịch của nhánh active — `para_index`
    theo DÒNG (`split_paras`), backup `before_find_replace[_branch]`.
    `source=raw` sửa bản gốc — `para_index` theo KHỐI (`split_blocks`), backup
    `before_find_replace_raw`. Raw không revision nên `expected` (nội dung khối)
    là khóa duy nhất chống ghi đè.
    """
    find, replace = find.strip(), replace.strip()
    if not find:
        raise HTTPException(status_code=400, detail="Cần chuỗi cần tìm.")
    if source not in ("translated", "raw"):
        raise HTTPException(status_code=400, detail="source phải là 'translated' hoặc 'raw'.")
    pattern = _compile_find(find, regex)
    cfg = deps.resolved_cfg(slug)
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="Chưa có manifest.")

    by_chapter: dict[int, dict[int, str | None]] = {}
    regex_fulltext = False
    if all_matches:
        if regex:
            regex_fulltext = True
            for ch in manifest.chapters:
                if source == "raw":
                    if not storage.has_raw(ch):
                        continue
                    text = storage.read_raw(ch)
                else:
                    if not storage.has_active_branch_text(ch):
                        continue
                    text = storage.read_active_branch_text(ch)
                if pattern.search(text):
                    by_chapter[ch.index] = {-1: None}
        else:
            for ch in manifest.chapters:
                if source == "raw":
                    if not storage.has_raw(ch):
                        continue
                    paras = split_blocks(storage.read_raw(ch))
                else:
                    if not storage.has_active_branch_text(ch):
                        continue
                    paras = split_paras(storage.read_active_branch_text(ch))
                matches = {i: para for i, para in enumerate(paras) if pattern.search(para)}
                if matches:
                    by_chapter[ch.index] = matches
    else:
        try:
            sel_list = json.loads(selections)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="selections không hợp lệ.")
        if not isinstance(sel_list, list) or not sel_list:
            raise HTTPException(status_code=400, detail="Chưa chọn đoạn nào để thay thế.")
        for sel in sel_list:
            if not isinstance(sel, dict):
                continue
            try:
                ci = int(sel["chapter_index"])
                pi = int(sel["para_index"])
            except (KeyError, TypeError, ValueError):
                continue
            expected = sel.get("expected")
            if pi < 0:
                regex_fulltext = True
            by_chapter.setdefault(ci, {})[pi] = str(expected) if expected is not None else None

    total_replaced = 0
    stale = 0
    chapters_touched = 0
    for ch in manifest.chapters:
        selected_paras = by_chapter.get(ch.index)
        if not selected_paras:
            continue

        if regex_fulltext:
            if source == "raw":
                if not storage.has_raw(ch):
                    continue
                text = storage.read_raw(ch)
            else:
                if not storage.has_active_branch_text(ch):
                    continue
                text = storage.read_active_branch_text(ch)
            expected_set = {
                exp for exp in selected_paras.values() if exp is not None
            }
            if expected_set:
                replaced_count = 0
                def _guarded_sub(m: re.Match) -> str:
                    nonlocal replaced_count
                    if m.group() in expected_set:
                        replaced_count += 1
                        return m.expand(replace) if replace else ""
                    return m.group()
                new_text = pattern.sub(_guarded_sub, text)
                count = replaced_count
                for exp in expected_set:
                    if exp not in text:
                        stale += 1
            else:
                new_text, count = pattern.subn(replace, text)
            if count and new_text != text:
                if source == "raw":
                    meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
                    meta["before_find_replace_raw"] = text
                    storage.write_meta(ch, meta)
                    storage.write_raw(ch, new_text)
                else:
                    branch = storage.active_branch(ch)
                    meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
                    backup_key = "before_find_replace" if branch == "ai" else f"before_find_replace_{branch}"
                    meta[backup_key] = text
                    storage.write_meta(ch, meta)
                    storage.write_branch_text(ch, branch, new_text)
                total_replaced += count
                chapters_touched += 1
            continue

        if source == "raw":
            if not storage.has_raw(ch):
                continue
            text = storage.read_raw(ch)
            from novel2epub.blocks import delete_block as _delete_block
            from novel2epub.blocks import edit_block as _edit_block
            paras = split_blocks(text)
            # Xử lý theo index giảm dần để xóa khối (replace rỗng) không làm
            # dịch chuyển các khối phía trước còn phải xử lý.
            selected = sorted(
                (pi for pi in selected_paras if 0 <= pi < len(paras)),
                reverse=True,
            )
            changed = False
            new_text = text
            for pi in selected:
                expected = selected_paras[pi]
                if expected is not None and paras[pi] != expected:
                    stale += 1
                    continue
                count = len(pattern.findall(paras[pi]))
                if not count:
                    continue
                replaced_block = pattern.sub(replace, paras[pi])
                if replaced_block.strip():
                    new_full, reason = _edit_block(new_text, pi, replaced_block)
                else:
                    # Thay bằng rỗng = xóa khối hẳn (kèm dòng trống ngăn cách).
                    new_full, reason = _delete_block(new_text, pi, paras[pi])
                if reason or new_full is None:
                    stale += 1
                    continue
                new_text = new_full
                total_replaced += count
                changed = True
            if changed:
                meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
                meta["before_find_replace_raw"] = text
                storage.write_meta(ch, meta)
                storage.write_raw(ch, new_text)
                chapters_touched += 1
            continue

        if not storage.has_active_branch_text(ch):
            continue
        branch = storage.active_branch(ch)
        translated = storage.read_branch_text(ch, branch)
        lines = translated.split("\n")
        para_line_indexes = [i for i, line in enumerate(lines) if line.strip()]
        changed = False
        for pi, expected in selected_paras.items():
            if not (0 <= pi < len(para_line_indexes)):
                stale += 1
                continue
            line_idx = para_line_indexes[pi]
            if expected is not None and lines[line_idx].strip() != expected.strip():
                stale += 1
                continue
            new_line, count = pattern.subn(replace, lines[line_idx])
            if count:
                lines[line_idx] = new_line
                total_replaced += count
                changed = True
        if changed:
            meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
            backup_key = "before_find_replace" if branch == "ai" else f"before_find_replace_{branch}"
            meta[backup_key] = translated
            storage.write_meta(ch, meta)
            storage.write_branch_text(ch, branch, "\n".join(lines))
            chapters_touched += 1

    return JSONResponse({"replaced": total_replaced, "chapters": chapters_touched, "stale": stale})
