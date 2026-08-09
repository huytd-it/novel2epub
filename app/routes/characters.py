"""Trang "Nhân vật" theo ebook — bảng nhân vật + ngôi xưng dùng cho prompt dịch.

Khác trang Glossary (map tên → tên), bảng này mang thuộc tính (giới tính, tự
xưng, cách lời kể gọi, alias) và quan hệ CÓ HƯỚNG giữa hai nhân vật kèm mốc
chương — thứ LLM không đoán được từ văn bản.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Form, HTTPException, Request
from fastapi.responses import JSONResponse

from novel2epub.storage import Storage

from .. import deps

router = APIRouter()


def _storage(slug: str) -> Storage:
    # Per-ebook giống glossary.py: dùng resolved_cfg (override riêng ebook nếu
    # có) thay vì cfg() chung — output.data_dir có thể khác giữa các ebook.
    cfg = deps.resolved_cfg(slug)
    return Storage(cfg.output.data_dir, cfg.novel.slug)


@router.get("/api/ebook/{slug}/characters/list")
def characters_list(slug: str):
    storage = _storage(slug)
    targets = {row[0]: row[1] for row in storage.read_character_entries()}
    by_a: dict[str, list[dict]] = {}
    for row in storage.read_relation_entries():
        a, b, from_chapter, a_calls_b, a_self, note = row[:6]
        to_chapter, a_calls_b_raw, a_self_raw, evidence, inferred, confidence = row[6:12]
        by_a.setdefault(a, []).append({
            "b_source": b,
            "b_target": targets.get(b, ""),
            "from_chapter": from_chapter,
            "a_calls_b": a_calls_b,
            "a_self": a_self,
            "note": note,
            "to_chapter": to_chapter,
            "a_calls_b_raw": a_calls_b_raw,
            "a_self_raw": a_self_raw,
            "evidence": evidence,
            "inferred": bool(inferred),
            "confidence": confidence,
        })
    entries = [
        {
            "source": row[0], "target": row[1], "aliases": row[2], "gender": row[3],
            "self_pronoun": row[4], "narrator_ref": row[5], "role_note": row[6],
            "importance": row[7], "aliases_vi": row[8] if len(row) > 8 else "",
            "relations": by_a.get(row[0], []),
        }
        for row in storage.read_character_entries()
    ]
    return JSONResponse({"entries": entries, "total": len(entries)})


@router.post("/api/ebook/{slug}/characters/entry")
def characters_upsert(
    slug: str,
    source: str = Form(...),
    target: str = Form(""),
    aliases: str = Form(""),
    gender: str = Form(""),
    self_pronoun: str = Form(""),
    narrator_ref: str = Form(""),
    role_note: str = Form(""),
    importance: str = Form("side"),
    original_source: str = Form(""),
):
    """Autosave MỘT nhân vật. Đổi tên gốc (original_source khác source) → di
    chuyển (KHÔNG xoá) mọi quan hệ đang dính tới tên cũ sang tên mới, thay vì
    xoá thẳng theo cách trang Idioms xử lý (Idioms không có quan hệ nên xoá là
    an toàn; nhân vật thì có character_relations ở cả 2 phía a_source/b_source
    — xoá trước sẽ mất sạch quan hệ vì `delete_character` dọn theo CẢ HAI
    chiều, xem `Storage.delete_character`)."""
    source = source.strip()
    if not source:
        raise HTTPException(status_code=400, detail="Cần tên gốc của nhân vật.")
    storage = _storage(slug)
    orig = original_source.strip()
    if orig and orig != source:
        relations_to_migrate = [
            row for row in storage.read_relation_entries()
            if row[0] == orig or row[1] == orig
        ]
        storage.delete_character(orig)
        storage.upsert_character(source, target, aliases, gender, self_pronoun,
                                 narrator_ref, role_note, importance)
        for row in relations_to_migrate:
            a, b, from_chapter, a_calls_b, a_self, note = row[:6]
            to_chapter, a_calls_b_raw, a_self_raw, evidence, inferred, confidence = row[6:12]
            new_a = source if a == orig else a
            new_b = source if b == orig else b
            storage.upsert_relation(
                new_a, new_b, from_chapter, a_calls_b, a_self, note,
                to_chapter=to_chapter, a_calls_b_raw=a_calls_b_raw,
                a_self_raw=a_self_raw, evidence=evidence,
                inferred=bool(inferred), confidence=confidence,
            )
    else:
        storage.upsert_character(source, target, aliases, gender, self_pronoun,
                                 narrator_ref, role_note, importance)
    return JSONResponse({"ok": True})


@router.post("/api/ebook/{slug}/characters/delete")
def characters_delete(slug: str, sources: str = Form(...)):
    """Xoá một hoặc nhiều nhân vật (ngăn bằng `|`), kéo theo quan hệ liên quan."""
    storage = _storage(slug)
    removed = sum(1 for s in sources.split("|") if storage.delete_character(s))
    return JSONResponse({"ok": True, "removed": removed})


@router.post("/api/ebook/{slug}/characters/relation")
def characters_upsert_relation(
    slug: str,
    a_source: str = Form(...),
    b_source: str = Form(...),
    from_chapter: int = Form(0),
    a_calls_b: str = Form(""),
    a_self: str = Form(""),
    note: str = Form(""),
):
    if not _storage(slug).upsert_relation(a_source, b_source, from_chapter,
                                          a_calls_b, a_self, note):
        raise HTTPException(status_code=400, detail="Cần cả hai nhân vật.")
    return JSONResponse({"ok": True})


@router.post("/api/ebook/{slug}/characters/relation/delete")
def characters_delete_relation(
    slug: str,
    a_source: str = Form(...),
    b_source: str = Form(...),
    from_chapter: int = Form(0),
):
    removed = _storage(slug).delete_relation(a_source, b_source, from_chapter)
    return JSONResponse({"ok": True, "removed": removed})


# ----- hàng chờ duyệt đề xuất AI (sub-project B) -----

_PENDING_KEY = "characters_pending"


def _read_pending(storage: Storage) -> dict:
    """Hàng chờ đề xuất AI. Trả về dict hai mảng, chịu được dữ liệu cũ/hỏng."""
    raw = storage.read_extra_json(_PENDING_KEY)
    if not isinstance(raw, dict):
        return {"characters": [], "relations": []}
    chars = raw.get("characters")
    rels = raw.get("relations")
    return {
        "characters": chars if isinstance(chars, list) else [],
        "relations": rels if isinstance(rels, list) else [],
    }


@router.get("/api/ebook/{slug}/characters/pending")
def characters_pending(slug: str):
    pending = _read_pending(_storage(slug))
    return JSONResponse({
        "characters": pending["characters"],
        "relations": pending["relations"],
        "counts": {"characters": len(pending["characters"]),
                   "relations": len(pending["relations"])},
    })


def _rel_key(item: dict) -> tuple:
    try:
        chapter = int(item.get("from_chapter") or 0)
    except (TypeError, ValueError):
        chapter = 0
    return (str(item.get("a_source", "")), str(item.get("b_source", "")), chapter)


@router.post("/api/ebook/{slug}/characters/pending/approve")
def characters_pending_approve(slug: str, payload: dict = Body(...)):
    """Duyệt đề xuất: NHÂN VẬT TRƯỚC, QUAN HỆ SAU.

    Thứ tự đó là bắt buộc — duyệt quan hệ trước thì hai đầu chưa tồn tại. Quan
    hệ có đầu vừa không được chọn vừa chưa có trong bảng sẽ bị CHẶN kèm thông
    báo nêu đích danh, không tạo quan hệ mồ côi và không im lặng bỏ qua. Nhân
    vật hợp lệ vẫn được lưu bình thường. Quan hệ bị chặn ở LẠI hàng chờ để
    người dùng duyệt nhân vật thiếu rồi thử lại.
    """
    storage = _storage(slug)
    pending = _read_pending(storage)
    by_source = {c.get("source"): c for c in pending["characters"]}
    by_rel = {_rel_key(r): r for r in pending["relations"]}

    picked_chars = [str(c.get("source", "")).strip()
                    for c in payload.get("characters", []) if isinstance(c, dict)]
    picked_rels = [_rel_key(r) for r in payload.get("relations", [])
                   if isinstance(r, dict)]

    # --- nhân vật trước ---
    approved_chars: list[str] = []
    for source in picked_chars:
        item = by_source.get(source)
        if not item:
            continue
        if item.get("update_only"):
            existing = {r[0]: r for r in storage.read_character_entries()}.get(source)
            if existing is None:
                continue
            old_raw = [a for a in (existing[2] or "").split("|") if a]
            old_vi = [a for a in (existing[8] or "").split("|") if a]
            for a in item.get("new_aliases_raw", []):
                if a not in old_raw:
                    old_raw.append(a)
            for a in item.get("new_aliases_vi", []):
                if a not in old_vi:
                    old_vi.append(a)
            storage.upsert_character(
                source, existing[1], "|".join(old_raw), existing[3], existing[4],
                existing[5], existing[6], existing[7], aliases_vi="|".join(old_vi),
            )
        else:
            storage.upsert_character(
                source,
                item.get("target", ""),
                "|".join(item.get("aliases_raw", [])),
                item.get("gender", ""),
                item.get("self_pronoun", ""),
                item.get("narrator_ref", ""),
                item.get("role_note", ""),
                item.get("importance", "side"),
                aliases_vi="|".join(item.get("aliases_vi", [])),
            )
        approved_chars.append(source)

    # --- quan hệ sau ---
    known = {r[0] for r in storage.read_character_entries()}
    names = {c.get("source"): c.get("target", "") for c in pending["characters"]}
    # Chỉ quan hệ LƯU ĐƯỢC mới bị gỡ khỏi hàng chờ; quan hệ bị chặn phải ở lại.
    approved_rel_keys: set[tuple] = set()
    blocked: list[str] = []
    for key in picked_rels:
        item = by_rel.get(key)
        if not item:
            continue
        missing = [s for s in (item["a_source"], item["b_source"]) if s not in known]
        if missing:
            for s in missing:
                label = f"{s} ({names.get(s)})" if names.get(s) else s
                blocked.append(
                    f'Quan hệ "{item["a_source"]} → {item["b_source"]}" không lưu '
                    f"được: nhân vật {label} chưa có trong bảng và không được "
                    f"chọn duyệt."
                )
            continue
        storage.upsert_relation(
            item["a_source"], item["b_source"], key[2],
            item.get("a_calls_b_vi", ""), item.get("a_self_vi", ""),
            item.get("reason", ""),
            to_chapter=item.get("to_chapter"),
            a_calls_b_raw=item.get("a_calls_b_raw", ""),
            a_self_raw=item.get("a_self_raw", ""),
            evidence=item.get("evidence", ""),
            inferred=bool(item.get("inferred")),
            confidence=item.get("confidence", ""),
        )
        approved_rel_keys.add(key)

    approved_char_keys = set(approved_chars)
    remaining = {
        "characters": [c for c in pending["characters"]
                       if c.get("source") not in approved_char_keys],
        "relations": [r for r in pending["relations"]
                      if _rel_key(r) not in approved_rel_keys],
    }
    storage.write_extra_json(_PENDING_KEY, remaining)
    return JSONResponse({
        "approved_characters": len(approved_chars),
        "approved_relations": len(approved_rel_keys),
        "blocked": blocked,
        "remaining": {"characters": len(remaining["characters"]),
                      "relations": len(remaining["relations"])},
    })


@router.post("/api/ebook/{slug}/characters/pending/clear")
def characters_pending_clear(slug: str, payload: dict = Body(...)):
    """Bỏ đề xuất khỏi hàng chờ mà KHÔNG đưa vào bảng."""
    storage = _storage(slug)
    pending = _read_pending(storage)
    if payload.get("all"):
        total = len(pending["characters"]) + len(pending["relations"])
        storage.write_extra_json(_PENDING_KEY, {"characters": [], "relations": []})
        return JSONResponse({"cleared": total})
    sources = {str(s).strip() for s in payload.get("characters", []) if str(s).strip()}
    rel_keys = {_rel_key(r) for r in payload.get("relations", []) if isinstance(r, dict)}
    remaining = {
        "characters": [c for c in pending["characters"] if c.get("source") not in sources],
        "relations": [r for r in pending["relations"] if _rel_key(r) not in rel_keys],
    }
    cleared = (len(pending["characters"]) + len(pending["relations"])
               - len(remaining["characters"]) - len(remaining["relations"]))
    storage.write_extra_json(_PENDING_KEY, remaining)
    return JSONResponse({"cleared": cleared})
