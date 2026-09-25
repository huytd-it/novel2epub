"""Domain logic cho Assistant Panel (SPA /app) — lịch sử chat theo ebook.

SQLite là nguồn sự thật duy nhất: `assistant_threads` + `assistant_messages`.
Route trong `app/routes/assistant.py` giữ mỏng, mọi đọc/ghi DB và resolve
config LLM nằm ở đây để test được.
"""
from __future__ import annotations

import json
import sqlite3

from .config import Config, OpenAIConfig


def list_threads(conn: sqlite3.Connection, slug: str) -> list[dict]:
    rows = conn.execute(
        "SELECT id, ebook_slug, provider_base_url, model, created_at"
        " FROM assistant_threads WHERE ebook_slug = ? ORDER BY id DESC",
        (slug,),
    ).fetchall()
    return [dict(r) for r in rows]


def create_thread(
    conn: sqlite3.Connection,
    slug: str,
    provider_base_url: str = "",
    model: str = "",
) -> dict:
    with conn:
        cur = conn.execute(
            "INSERT INTO assistant_threads (ebook_slug, provider_base_url, model)"
            " VALUES (?, ?, ?)",
            (slug, (provider_base_url or "").strip(), (model or "").strip()),
        )
        thread_id = cur.lastrowid
    return get_thread(conn, int(thread_id))


def get_thread(conn: sqlite3.Connection, thread_id: int) -> dict:
    row = conn.execute(
        "SELECT id, ebook_slug, provider_base_url, model, created_at"
        " FROM assistant_threads WHERE id = ?",
        (thread_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"không tìm thấy thread {thread_id}")
    return dict(row)


def update_thread_provider(
    conn: sqlite3.Connection,
    thread_id: int,
    provider_base_url: str | None = None,
    model: str | None = None,
) -> dict:
    thread = get_thread(conn, thread_id)
    base_url = thread["provider_base_url"] if provider_base_url is None else provider_base_url.strip()
    model_val = thread["model"] if model is None else model.strip()
    with conn:
        conn.execute(
            "UPDATE assistant_threads SET provider_base_url = ?, model = ? WHERE id = ?",
            (base_url, model_val, thread_id),
        )
    return get_thread(conn, thread_id)


def delete_thread(conn: sqlite3.Connection, thread_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM assistant_messages WHERE thread_id = ?", (thread_id,))
        cur = conn.execute("DELETE FROM assistant_threads WHERE id = ?", (thread_id,))
    if cur.rowcount == 0:
        raise KeyError(f"không tìm thấy thread {thread_id}")


def list_messages(conn: sqlite3.Connection, thread_id: int, limit: int = 200) -> list[dict]:
    # Thread phải tồn tại — tránh đọc ké message của ebook khác.
    get_thread(conn, thread_id)
    rows = conn.execute(
        "SELECT id, thread_id, role, content, created_at FROM assistant_messages"
        " WHERE thread_id = ? ORDER BY id ASC LIMIT ?",
        (thread_id, max(1, limit)),
    ).fetchall()
    return [dict(r) for r in rows]


def add_message(conn: sqlite3.Connection, thread_id: int, role: str, content: str) -> dict:
    if role not in ("user", "assistant", "system"):
        raise ValueError("role phải là 'user', 'assistant' hoặc 'system'.")
    get_thread(conn, thread_id)
    with conn:
        cur = conn.execute(
            "INSERT INTO assistant_messages (thread_id, role, content) VALUES (?, ?, ?)",
            (thread_id, role, content or ""),
        )
        message_id = cur.lastrowid
    row = conn.execute(
        "SELECT id, thread_id, role, content, created_at FROM assistant_messages WHERE id = ?",
        (message_id,),
    ).fetchone()
    return dict(row)


def default_provider_for_ebook(cfg: Config) -> dict[str, str]:
    """Mặc định nạp từ `ai.openai` của ebook đang mở (đã merge global + per-ebook)."""
    return {
        "provider_base_url": cfg.ai.openai.base_url or "",
        "model": cfg.ai.openai.model or "",
    }


def resolve_chat_config(cfg: Config, thread: dict) -> OpenAIConfig:
    """OpenAIConfig hiệu lực cho 1 lượt chat: thread override base_url/model.

    API key/timeout/temperature lấy từ config hiệu lực (preset không lưu key)
    nên không bao giờ rò rỉ key qua thread.
    """
    base = OpenAIConfig(
        base_url=cfg.ai.openai.base_url,
        api_key=cfg.ai.openai.api_key,
        model=cfg.ai.openai.model,
        prompt_template=cfg.ai.openai.prompt_template,
        title_prompt_template=cfg.ai.openai.title_prompt_template,
        timeout_seconds=cfg.ai.openai.timeout_seconds,
        temperature=cfg.ai.openai.temperature,
    )
    override_url = str(thread.get("provider_base_url") or "").strip()
    override_model = str(thread.get("model") or "").strip()
    if override_url:
        base.base_url = override_url
    if override_model:
        base.model = override_model
    return base


def build_chat_prompt(content: str, context: dict | None = None) -> str:
    """Ghép ngữ cảnh (slug/index/selection) vào prompt. Phase 0 giữ tối giản."""
    text = (content or "").strip()
    if not text:
        raise ValueError("Nội dung chat trống.")
    ctx = context or {}
    lines: list[str] = []
    slug = str(ctx.get("ebook_slug") or "").strip()
    if slug:
        lines.append(f"[ebook: {slug}]")
    chapter = ctx.get("chapter_index")
    if chapter is not None and chapter != "":
        lines.append(f"[chương: {chapter}]")
    selection = str(ctx.get("selection") or "").strip()
    if selection:
        lines.append("[đoạn đang chọn]")
        lines.append(selection[:4000])
    if lines:
        return "\n".join(lines) + "\n\n" + text
    return text


# ── Tools đọc (Phase 2) ──────────────────────────────────────────────────
# Bọc logic find-preview/search theo đúng semantics: `translated` quét bản dịch
# nhánh active chia `split_paras` (khớp para/save), `raw` quét bản gốc chia
# `split_blocks` (khớp khung đối chiếu). Giới hạn 300 đoạn như find-preview.

SEARCH_LIMIT = 300
CHAPTER_MAX_CHARS = 8000


def compile_find(find: str, regex: bool):
    """Biên dịch chuỗi tìm kiếm. `regex=False` coi là literal (escape)."""
    import re as _re

    try:
        return _re.compile(find if regex else _re.escape(find), _re.IGNORECASE)
    except _re.error as e:
        raise ValueError(f"Regex không hợp lệ: {e}") from e


def search_ebook(
    storage,
    manifest,
    find: str,
    regex: bool = False,
    source: str = "translated",
    scope: str = "all",
    chapter_index: int = 0,
    limit: int = SEARCH_LIMIT,
) -> dict:
    """Tìm ĐOẠN chứa `find` trong phạm vi ebook hiện tại (read-only).

    Trả `{"items": [...], "truncated": bool}` — mỗi item gồm chapter_index,
    chapter_title, para_index (translated: index dòng `split_paras`; raw: index
    khối `split_blocks`), count và before (nội dung đoạn khớp).
    """
    from .blocks import split_blocks
    from .notes import split_paras

    find = (find or "").strip()
    if not find:
        raise ValueError("Chuỗi cần tìm đang rỗng.")
    if source not in ("translated", "raw"):
        raise ValueError("source phải là 'translated' hoặc 'raw'.")
    if scope not in ("chapter", "all"):
        raise ValueError("scope phải là 'chapter' hoặc 'all'.")
    pattern = compile_find(find, regex)
    limit = max(1, min(int(limit or SEARCH_LIMIT), SEARCH_LIMIT))

    if manifest is None:
        raise ValueError("Chưa có manifest.")
    if scope == "chapter":
        if not chapter_index:
            raise ValueError("Thiếu chapter_index.")
        chapters = [c for c in manifest.chapters if c.index == chapter_index]
        if not chapters:
            raise ValueError("Không tìm thấy chương.")
    else:
        chapters = manifest.chapters

    def _read(ch) -> str:
        if source == "raw":
            return storage.read_raw(ch) if storage.has_raw(ch) else ""
        return (
            storage.read_active_branch_text(ch)
            if storage.has_active_branch_text(ch)
            else ""
        )

    def _split(text: str) -> list[str]:
        return split_blocks(text) if source == "raw" else split_paras(text)

    items: list[dict] = []
    truncated = False
    for ch in chapters:
        text = _read(ch)
        if not text:
            continue
        for i, para in enumerate(_split(text)):
            count = len(pattern.findall(para))
            if not count:
                continue
            items.append(
                {
                    "chapter_index": ch.index,
                    "chapter_title": ch.title or f"Chương {ch.index}",
                    "para_index": i,
                    "count": count,
                    "before": para,
                }
            )
            if len(items) >= limit:
                truncated = True
                break
        if truncated:
            break
    return {"items": items, "truncated": truncated}


def get_chapter(
    storage,
    manifest,
    index: int,
    include_raw: bool = False,
    include_translated: bool = True,
    max_chars: int = CHAPTER_MAX_CHARS,
) -> dict:
    """Đọc 1 chương trong ebook hiện tại: tiêu đề + đoạn theo đúng split.

    `translated` là bản dịch nhánh active (`split_paras`), `raw` là bản gốc
    (`split_blocks`). Chương chưa dịch → `translated_paras` rỗng (không lấp).
    Cắt ở `max_chars` mỗi phía, báo `truncated`.
    """
    from .blocks import split_blocks
    from .notes import split_paras

    if manifest is None:
        raise ValueError("Chưa có manifest.")
    ch = next((c for c in manifest.chapters if c.index == index), None)
    if ch is None:
        raise ValueError(f"Không tìm thấy chương {index}.")
    max_chars = max(500, min(int(max_chars or CHAPTER_MAX_CHARS), 20000))

    out: dict = {
        "index": ch.index,
        "title": ch.title or f"Chương {ch.index}",
        "title_zh": ch.title_zh or "",
        "active_branch": storage.active_branch(ch),
        "has_raw": bool(storage.has_raw(ch)),
        "has_translated": bool(storage.has_active_branch_text(ch)),
    }
    if include_translated:
        text = (
            storage.read_active_branch_text(ch)
            if storage.has_active_branch_text(ch)
            else ""
        )
        paras = split_paras(text) if text else []
        joined = "\n".join(paras)
        cut = len(joined) > max_chars
        out["translated_paras"] = [
            {"para_index": i, "text": p}
            for i, p in enumerate(paras)
            if sum(len(q) + 1 for q in paras[:i]) < max_chars
        ]
        out["translated_truncated"] = cut
    if include_raw:
        raw = storage.read_raw(ch) if storage.has_raw(ch) else ""
        blocks = split_blocks(raw) if raw else []
        joined = "\n".join(blocks)
        cut = len(joined) > max_chars
        kept = []
        total = 0
        for i, b in enumerate(blocks):
            if total >= max_chars:
                break
            kept.append({"para_index": i, "text": b})
            total += len(b) + 1
        out["raw_paras"] = kept
        out["raw_truncated"] = cut
    return out


def get_glossary(storage, query: str = "", limit: int = 300) -> dict:
    """Glossary đã merge (names thắng) của ebook, lọc chuỗi con theo `query`."""
    entries = storage.read_glossary_entries_merged()
    q = (query or "").strip().lower()
    if q:
        entries = [e for e in entries if q in e[0].lower() or q in e[1].lower()]
    limit = max(1, min(int(limit or 300), 1000))
    truncated = len(entries) > limit
    return {
        "total": len(entries),
        "truncated": truncated,
        "entries": [
            {"source": s, "target": t, "note": n} for s, t, n in entries[:limit]
        ],
    }


def get_characters(storage, query: str = "", limit: int = 100) -> dict:
    """Bảng nhân vật + quan hệ của ebook, lọc chuỗi con theo `query`."""
    chars = storage.read_character_entries()
    q = (query or "").strip().lower()
    if q:
        chars = [c for c in chars if q in c[0].lower() or q in c[1].lower()]
    limit = max(1, min(int(limit or 100), 500))
    truncated = len(chars) > limit
    keys = ("source", "target", "aliases", "gender", "self_pronoun",
            "narrator_ref", "role_note", "importance", "aliases_vi")
    picked = [dict(zip(keys, c)) for c in chars[:limit]]
    relations: list[dict] = []
    try:
        rel_rows = storage.read_relation_entries()
    except AttributeError:
        rel_rows = []
    wanted = {c["source"] for c in picked} if q else set()
    for r in rel_rows:
        # read_relation_entries trả tuple 12 phần tử (a, b, from_ch, calls,
        # self, note, ...); chỉ giữ 6 cột đầu, bỏ qua shape lạ.
        if not isinstance(r, (list, tuple)) or len(r) < 6:
            continue
        if wanted and r[0] not in wanted and r[1] not in wanted:
            continue
        relations.append(
            {
                "a_source": r[0], "b_source": r[1], "from_chapter": r[2],
                "a_calls_b": r[3], "a_self": r[4], "note": r[5],
            }
        )
        if len(relations) >= 100:
            break
    return {
        "total": len(chars), "truncated": truncated,
        "characters": picked, "relations": relations,
    }


def get_idioms(storage, query: str = "", limit: int = 100) -> dict:
    """Từ điển idiom DÙNG CHUNG (global, không gắn ebook)."""
    entries = storage.read_idiom_entries()
    q = (query or "").strip().lower()
    if q:
        entries = [e for e in entries if q in e[0].lower() or q in e[1].lower()]
    limit = max(1, min(int(limit or 100), 500))
    truncated = len(entries) > limit
    return {
        "total": len(entries),
        "truncated": truncated,
        "entries": [
            {"source": s, "target": t, "literals": lit, "protect": bool(p)}
            for s, t, lit, p in entries[:limit]
        ],
    }


# ── Tools ghi CÓ PREVIEW (Phase 3) ─────────────────────────────────────
# Luồng bắt buộc: preview (read-only, diff theo đoạn) → người dùng tick chọn
# → apply (ghi kèm stale protection). Agent chỉ được gọi preview, KHÔNG gọi
# apply — human-in-the-loop. Tái dùng đúng semantics các route hiện có:
# para/save (`notes.replace_para`), find-preview/apply-selected (backup meta
# before_find_replace[_branch]/before_find_replace_raw), entries/preview +
# entries (`glossary_review.plan_glossary_edits`).

def _chapter_or_error(storage, manifest, index):
    if manifest is None:
        raise ValueError("Chưa có manifest.")
    ch = next((c for c in manifest.chapters if c.index == index), None)
    if ch is None:
        raise ValueError(f"Không tìm thấy chương {index}.")
    return ch


def preview_paragraph_edit(storage, manifest, index: int, para_index: int, new_text: str) -> dict:
    """Diff 1 đoạn bản dịch nhánh active mà KHÔNG ghi (read-only)."""
    from .notes import split_paras

    ch = _chapter_or_error(storage, manifest, int(index))
    if not storage.has_active_branch_text(ch):
        raise ValueError("Chương chưa có bản dịch.")
    paras = split_paras(storage.read_active_branch_text(ch))
    pi = int(para_index)
    if not 0 <= pi < len(paras):
        raise ValueError(f"para_index {pi} ngoài phạm vi ({len(paras)} đoạn).")
    return {
        "index": ch.index,
        "chapter_title": ch.title or f"Chương {ch.index}",
        "active_branch": storage.active_branch(ch),
        "para_index": pi,
        "before": paras[pi],
        "after": str(new_text or ""),
        "deleted": not str(new_text or "").strip(),
    }


def apply_paragraph_edit(
    storage, manifest, index: int, para_index: int, expected: str, new_text: str
) -> dict:
    """Ghi 1 đoạn đã preview: `expected` khớp mới ghi (chống ghi đè, như
    para/save). Tăng revision nhánh qua `write_branch_text`."""
    from .notes import replace_para, split_paras

    ch = _chapter_or_error(storage, manifest, int(index))
    branch = storage.active_branch(ch)
    if not storage.has_branch_text(ch, branch):
        raise ValueError("Chương không còn bản dịch.")
    translated = storage.read_branch_text(ch, branch)
    new_translated, err = replace_para(translated, int(para_index), expected or "", new_text or "")
    if new_translated is None:
        raise ValueError(err or "Không ghi được đoạn (bản dịch đã đổi).")
    storage.write_branch_text(ch, branch, new_translated)
    return {
        "saved": True,
        "index": ch.index,
        "para_index": int(para_index),
        "deleted": not str(new_text or "").strip(),
        "revision": storage.read_branch_revision(ch, branch),
    }


def preview_glossary_edits(storage, edits: list[dict]) -> dict:
    """Xem trước cả đợt sửa glossary: kind/error từng dòng + số chỗ lan truyền
    (tái dùng `plan_glossary_edits` + `replacement_counts` như entries/preview)."""
    from . import glossary_review

    if not isinstance(edits, list) or not edits:
        raise ValueError("Cần danh sách edits.")
    planned = glossary_review.plan_glossary_edits(
        storage.read_glossary_entries_merged(), edits
    )
    counts = storage.replacement_counts(glossary_review.replacement_pairs(planned))
    by_old = {c["old"]: c for c in counts["pairs"]}
    for row in planned:
        info = by_old.get(row["existing_target"]) if row["existing_target"] else None
        applies = info is not None and not row["error"] and row["kind"] != "unchanged"
        row["count"] = info["count"] if applies else 0
        row["chapters"] = info["chapters"] if applies else 0
    return {
        "entries": planned,
        "writes": sum(1 for r in planned if not r["error"] and r["kind"] != "unchanged"),
        "errors": sum(1 for r in planned if r["error"]),
        "total_matches": counts["total"],
    }


def apply_glossary_edits(storage, edits: list[dict]) -> dict:
    """Ghi cả đợt sửa glossary sau xác nhận: all-or-nothing ở mức xác thực
    (còn dòng lỗi → từ chối toàn bộ), rename xoá khoá cũ, đổi Việt lan truyền
    một lượt quét (như entries)."""
    from . import glossary_review

    if not isinstance(edits, list) or not edits:
        raise ValueError("Cần danh sách edits.")
    planned = glossary_review.plan_glossary_edits(
        storage.read_glossary_entries_merged(), edits
    )
    failed = [r for r in planned if r["error"]]
    if failed:
        first = failed[0]
        raise ValueError(
            f"{first['source'] or first['original_source'] or '(trống)'}: {first['error']}"
            + (f" (+{len(failed) - 1} dòng lỗi khác)" if len(failed) > 1 else "")
        )
    writes = [r for r in planned if r["kind"] != "unchanged"]
    pairs = glossary_review.replacement_pairs(planned)
    for row in writes:
        if row["kind"] == "rename":
            storage.delete_glossary_entry(row["original_source"])
        storage.upsert_glossary_entry(row["source"], row["target"], row["note"])
    stats = storage.apply_replacements(pairs) if pairs else {"total": 0, "chapters": 0, "ebook": False}
    return {
        "applied": len(writes),
        "added": sum(1 for r in writes if r["kind"] == "new"),
        "renamed": sum(1 for r in writes if r["kind"] == "rename"),
        "skipped": len(planned) - len(writes),
        "replacements": stats,
    }


def apply_selected_replacements(
    storage,
    manifest,
    find: str,
    replace: str,
    regex: bool = False,
    selections: list[dict] | None = None,
    source: str = "translated",
    all_matches: bool = False,
) -> dict:
    """Áp dụng thay thế CHỈ cho các đoạn đã chọn từ preview (như apply-selected).

    `selections` là list `{chapter_index, para_index, expected}` — `expected`
    là nội dung đoạn lúc preview, đoạn đã đổi thì bỏ qua (đếm `stale`).
    Backup `before_find_replace[_branch]` / `before_find_replace_raw` vào meta.
    """
    import re as _re

    from .blocks import delete_block as _delete_block
    from .blocks import edit_block as _edit_block
    from .blocks import split_blocks
    from .notes import split_paras

    find, replace = (find or "").strip(), (replace or "").strip()
    if not find:
        raise ValueError("Cần chuỗi cần tìm.")
    if source not in ("translated", "raw"):
        raise ValueError("source phải là 'translated' hoặc 'raw'.")
    pattern = compile_find(find, regex)
    if manifest is None:
        raise ValueError("Chưa có manifest.")

    by_chapter: dict[int, dict[int, str | None]] = {}
    regex_fulltext = False
    if all_matches:
        if regex:
            regex_fulltext = True
            for ch in manifest.chapters:
                text = (
                    storage.read_raw(ch)
                    if source == "raw" and storage.has_raw(ch)
                    else storage.read_active_branch_text(ch)
                    if source != "raw" and storage.has_active_branch_text(ch)
                    else ""
                )
                if text and pattern.search(text):
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
        if not isinstance(selections, list) or not selections:
            raise ValueError("Chưa chọn đoạn nào để thay thế.")
        for sel in selections:
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
            text = (
                storage.read_raw(ch)
                if source == "raw" and storage.has_raw(ch)
                else storage.read_active_branch_text(ch)
                if source != "raw" and storage.has_active_branch_text(ch)
                else ""
            )
            if not text:
                continue
            expected_set = {exp for exp in selected_paras.values() if exp is not None}
            if expected_set:
                replaced_count = 0

                def _guarded_sub(m: _re.Match) -> str:
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
                _backup_and_write(storage, ch, source, text, new_text)
                total_replaced += count
                chapters_touched += 1
            continue

        if source == "raw":
            if not storage.has_raw(ch):
                continue
            text = storage.read_raw(ch)
            paras = split_blocks(text)
            selected = sorted(
                (pi for pi in selected_paras if 0 <= pi < len(paras)), reverse=True
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
                    new_full, reason = _delete_block(new_text, pi, paras[pi])
                if reason or new_full is None:
                    stale += 1
                    continue
                new_text = new_full
                total_replaced += count
                changed = True
            if changed:
                _backup_and_write(storage, ch, source, text, new_text)
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
            if not 0 <= pi < len(para_line_indexes):
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
            _backup_and_write(storage, ch, source, translated, "\n".join(lines))

            chapters_touched += 1

    return {"replaced": total_replaced, "chapters": chapters_touched, "stale": stale}


def _backup_and_write(storage, ch, source: str, old_text: str, new_text: str) -> None:
    """Backup meta + ghi (tăng revision nhánh dịch / giữ nguyên raw không revision)."""
    if source == "raw":
        meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
        meta["before_find_replace_raw"] = old_text
        storage.write_meta(ch, meta)
        storage.write_raw(ch, new_text)
    else:
        branch = storage.active_branch(ch)
        meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
        backup_key = "before_find_replace" if branch == "ai" else f"before_find_replace_{branch}"
        meta[backup_key] = old_text
        storage.write_meta(ch, meta)
        storage.write_branch_text(ch, branch, new_text)


# ── Fill ngữ cảnh (Phase 4) ────────────────────────────────────────────
# Task NHANH chạy sync ngay trong lượt chat (dò tên riêng từ raw → hàng chờ
# duyệt, thuần CPU). Task LÂU (dịch lại hàng loạt bằng AI, trích nhân vật)
# enqueue job category=translate rồi link sang /queue.

FILL_MAX_CHAPTERS_SYNC = 50


def extract_and_queue_proper_names(
    storage,
    manifest,
    chapter_indexes: list[int] | None = None,
    min_frequency: int = 2,
    max_candidates: int = 100,
) -> dict:
    """Dò tên riêng từ raw rồi xếp hàng chờ duyệt (sync, không gọi AI/MT).

    `chapter_indexes` rỗng = quét toàn sách (cap 50 chương cho lượt sync).
    Không lấp raw hay bản dịch — chỉ thêm ứng viên vào `glossary_pending`.
    """
    from .proper_names import extract_proper_name_candidates, queue_proper_name_candidates

    if manifest is None:
        raise ValueError("Chưa có manifest.")
    selected = set(chapter_indexes or [])
    texts = [
        (ch.index, storage.read_raw(ch))
        for ch in manifest.chapters
        if (not selected or ch.index in selected) and storage.has_raw(ch)
    ][:FILL_MAX_CHAPTERS_SYNC]
    if not texts:
        return {"scanned_chapters": 0, "detected": 0, "queued": 0, "skipped_existing": 0}
    candidates = extract_proper_name_candidates(
        texts, min_frequency=max(1, min_frequency), max_candidates=max(1, max_candidates),
    )
    result = queue_proper_name_candidates(storage, candidates)
    return {"scanned_chapters": len(texts), **result}


# ── Tìm-thay thông minh (Phase 5) ──────────────────────────────────────
# Agent sinh regex + giải thích, đề xuất biến thể nghĩa (LLM rerank bằng kiến
# thức ngôn ngữ — chưa dựng vector store), rồi GỘP một preview duy nhất cho
# người dùng tick chọn theo đoạn. Ghi qua apply-batch (mỗi nhóm find/replace
# một lượt apply-selected, cộng dồn replaced/chapters/stale).
# Lưu ý: tìm kiếm luôn KHÔNG phân biệt hoa/thường (giữ semantics find-preview).

def preview_find_replace_batch(
    storage,
    manifest,
    replacements: list[dict],
    source: str = "translated",
    scope: str = "all",
    chapter_index: int = 0,
    limit: int = SEARCH_LIMIT,
) -> dict:
    """Preview GỘP nhiều cặp find/replace trong một lần gọi (read-only).

    Mỗi nhóm `{find, replace, regex}` quét như find-preview: literal → theo
    đoạn (`para_index` >= 0 kèm before/after), regex → theo chỗ khớp
    (`para_index` âm, before là đoạn khớp). Tổng không quá `limit` (300).
    """
    import re as _re

    from .blocks import split_blocks
    from .notes import split_paras

    if not isinstance(replacements, list) or not replacements:
        raise ValueError("Cần danh sách replacements.")
    if source not in ("translated", "raw"):
        raise ValueError("source phải là 'translated' hoặc 'raw'.")
    if scope not in ("chapter", "all"):
        raise ValueError("scope phải là 'chapter' hoặc 'all'.")
    if manifest is None:
        raise ValueError("Chưa có manifest.")
    limit = max(1, min(int(limit or SEARCH_LIMIT), SEARCH_LIMIT))

    if scope == "chapter":
        if not chapter_index:
            raise ValueError("Thiếu chapter_index.")
        chapters = [c for c in manifest.chapters if c.index == chapter_index]
        if not chapters:
            raise ValueError("Không tìm thấy chương.")
    else:
        chapters = manifest.chapters

    def _read(ch) -> str:
        if source == "raw":
            return storage.read_raw(ch) if storage.has_raw(ch) else ""
        return (
            storage.read_active_branch_text(ch)
            if storage.has_active_branch_text(ch)
            else ""
        )

    groups: list[dict] = []
    total = 0
    truncated = False
    for rep in replacements:
        if not isinstance(rep, dict):
            continue
        find, replace = str(rep.get("find") or "").strip(), str(rep.get("replace") or "")
        regex = bool(rep.get("regex", False))
        if not find:
            continue
        pattern = compile_find(find, regex)
        items: list[dict] = []
        group_truncated = False
        for ch in chapters:
            text = _read(ch)
            if not text:
                continue
            title = ch.title or f"Chương {ch.index}"
            if regex:
                try:
                    matches = list(pattern.finditer(text))
                except _re.error as e:
                    raise ValueError(f"Regex thay thế không hợp lệ: {e}") from e
                for idx, m in enumerate(matches):
                    try:
                        after_text = m.expand(replace) if replace else ""
                    except _re.error as e:
                        raise ValueError(f"Regex thay thế không hợp lệ: {e}") from e
                    items.append({
                        "chapter_index": ch.index, "chapter_title": title,
                        "para_index": -(idx + 1), "count": 1,
                        "before": m.group(), "after": after_text,
                    })
                    if total + len(items) >= limit:
                        group_truncated = True
                        break
            else:
                paras = split_blocks(text) if source == "raw" else split_paras(text)
                for i, para in enumerate(paras):
                    count = len(pattern.findall(para))
                    if not count:
                        continue
                    try:
                        after = pattern.sub(replace, para)
                    except _re.error as e:
                        raise ValueError(f"Regex thay thế không hợp lệ: {e}") from e
                    items.append({
                        "chapter_index": ch.index, "chapter_title": title,
                        "para_index": i, "count": count,
                        "before": para, "after": after,
                    })
                    if total + len(items) >= limit:
                        group_truncated = True
                        break
            if group_truncated:
                truncated = True
                break
        groups.append({"find": find, "replace": replace, "regex": regex,
                       "items": items, "truncated": group_truncated})
        total += len(items)
        if total >= limit:
            truncated = True
            break
    return {"groups": groups, "total": total, "truncated": truncated}


def apply_find_replace_batch(
    storage,
    manifest,
    groups: list[dict],
    source: str = "translated",
    all_matches: bool = False,
) -> dict:
    """Áp dụng nhiều nhóm find/replace đã preview: mỗi nhóm một lượt
    apply-selected (stale protection + backup meta), cộng dồn kết quả."""
    if not isinstance(groups, list) or not groups:
        raise ValueError("Cần danh sách groups.")
    replaced = chapters = stale = 0
    applied_groups = 0
    for g in groups:
        if not isinstance(g, dict):
            continue
        res = apply_selected_replacements(
            storage, manifest,
            find=str(g.get("find") or ""), replace=str(g.get("replace") or ""),
            regex=bool(g.get("regex", False)),
            selections=g.get("selections") or [],
            source=source, all_matches=bool(all_matches or g.get("all_matches", False)),
        )
        replaced += res["replaced"]
        chapters += res["chapters"]
        stale += res["stale"]
        applied_groups += 1
    return {"replaced": replaced, "chapters": chapters, "stale": stale,
            "applied_groups": applied_groups}


# ── Agent loop (tool-calling phía server) ────────────────────────────────

ASSISTANT_SYSTEM_PROMPT = """Bạn là trợ lý biên tập tiểu thuyết trong phạm vi MỘT ebook.
Quy tắc:
- Chỉ dùng các tool được cấp để đọc dữ liệu ebook (tìm đoạn, đọc chương, glossary, nhân vật, idiom). Không bịa nội dung chương.
- Phạm vi: raw, bản dịch nhánh active, tiêu đề, glossary, nhân vật, idiom của ebook hiện tại.
- Trả lời tiếng Việt, ngắn gọn, nêu rõ nguồn (chương nào, mục nào) khi trích dẫn.
- Muốn sửa phải gọi tool preview_* trước để lấy diff, rồi trình bày đề xuất và NHỜ NGƯỜI DÙNG XÁC NHẬN (nút Áp dụng trong panel mới ghi thật). Không tự ý ghi, không bịa preview.
- Khi người dùng nhờ tìm-thay: trước hết search chính xác để biết thực trạng, rồi sinh regex chính xác (giải thích regex đó khớp gì) + đề xuất thêm biến thể nghĩa (cách diễn đạt khác cùng nghĩa trong truyện), GỘP tất cả vào MỘT lần gọi preview_find_replace_batch. Tìm kiếm luôn không phân biệt hoa/thường — nói rõ điều này, không hứa chế độ khác.
"""

ASSISTANT_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_ebook",
            "description": "Tìm các đoạn chứa chuỗi/regex trong ebook (translated: bản dịch nhánh active; raw: bản gốc).",
            "parameters": {
                "type": "object",
                "properties": {
                    "find": {"type": "string"},
                    "regex": {"type": "boolean", "default": False},
                    "source": {"type": "string", "enum": ["translated", "raw"], "default": "translated"},
                    "scope": {"type": "string", "enum": ["all", "chapter"], "default": "all"},
                    "chapter_index": {"type": "integer", "default": 0},
                    "limit": {"type": "integer", "default": 300},
                },
                "required": ["find"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_chapter",
            "description": "Đọc một chương: tiêu đề + các đoạn (translated theo split_paras, raw theo split_blocks).",
            "parameters": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "include_raw": {"type": "boolean", "default": False},
                    "include_translated": {"type": "boolean", "default": True},
                    "max_chars": {"type": "integer", "default": 8000},
                },
                "required": ["index"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_glossary",
            "description": "Đọc glossary đã merge của ebook, lọc theo chuỗi con.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "default": ""},
                    "limit": {"type": "integer", "default": 300},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_characters",
            "description": "Đọc bảng nhân vật và quan hệ của ebook, lọc theo chuỗi con.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "default": ""},
                    "limit": {"type": "integer", "default": 100},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_idioms",
            "description": "Đọc từ điển idiom dùng chung (global).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "default": ""},
                    "limit": {"type": "integer", "default": 100},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "preview_paragraph_edit",
            "description": "Xem trước sửa 1 đoạn bản dịch (trả before/after, KHÔNG ghi). Người dùng phải tick xác nhận rồi mới ghi bằng nút Áp dụng.",
            "parameters": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "para_index": {"type": "integer"},
                    "new_text": {"type": "string"},
                },
                "required": ["index", "para_index", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_proper_names",
            "description": "Dò tên riêng từ raw các chương rồi xếp vào hàng chờ duyệt glossary (chạy ngay, không gọi AI).",
            "parameters": {
                "type": "object",
                "properties": {
                    "chapter_indexes": {
                        "type": "array", "items": {"type": "integer"},
                        "description": "Giới hạn chương; bỏ trống để quét toàn sách.",
                    },
                    "min_frequency": {"type": "integer", "default": 2},
                    "max_candidates": {"type": "integer", "default": 100},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enqueue_fill_context",
            "description": "Fill ngữ cảnh NẶNG (AI dịch lại hàng loạt mục glossary + trích nhân vật/quan hệ) bằng job nền category=translate; trả link /queue để theo dõi. Dùng khi người dùng nhờ 'fill', 'bổ sung ngữ cảnh', 'dịch lại glossary'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "chapter_indexes": {
                        "type": "array", "items": {"type": "integer"},
                        "description": "Giới hạn chương; bỏ trống để quét toàn sách.",
                    },
                    "with_retranslate": {"type": "boolean", "default": True},
                    "with_characters": {"type": "boolean", "default": True},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "preview_find_replace_batch",
            "description": "Preview GỘP nhiều cặp tìm-thay trong một lần gọi (KHÔNG ghi). Dùng khi người dùng nhờ thay thế: sinh regex chính xác + đề xuất biến thể nghĩa (cách diễn đạt khác cùng nghĩa), mỗi nhóm kèm giải thích trong câu trả lời. Tìm kiếm luôn không phân biệt hoa/thường.",
            "parameters": {
                "type": "object",
                "properties": {
                    "replacements": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "find": {"type": "string"},
                                "replace": {"type": "string", "default": ""},
                                "regex": {"type": "boolean", "default": False},
                            },
                            "required": ["find", "replace"],
                        },
                    },
                    "source": {"type": "string", "enum": ["translated", "raw"], "default": "translated"},
                    "scope": {"type": "string", "enum": ["all", "chapter"], "default": "all"},
                    "chapter_index": {"type": "integer", "default": 0},
                },
                "required": ["replacements"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "preview_glossary_edits",
            "description": "Xem trước cả đợt sửa glossary (phân loại new/update/rename, lỗi, số chỗ lan truyền — KHÔNG ghi).",
            "parameters": {
                "type": "object",
                "properties": {
                    "edits": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "source": {"type": "string"},
                                "target": {"type": "string"},
                                "note": {"type": "string", "default": ""},
                                "original_source": {"type": "string", "default": ""},
                            },
                            "required": ["source", "target"],
                        },
                    },
                },
                "required": ["edits"],
            },
        },
    },
]

AGENT_MAX_ITERS = 4


def execute_tool(storage, manifest, name: str, args: dict, enqueue_job=None) -> dict:
    """Chạy 1 tool, trả `{"ok": True, "result": ...}` hoặc `{"ok": False, "error": ...}`.

    `enqueue_job` là callback `dict params -> dict {job, queue_url}` do route
    cung cấp (cần job queue của app) — chỉ dùng cho `enqueue_fill_context`.
    """
    args = dict(args or {})
    try:
        if name == "search_ebook":
            result = search_ebook(
                storage, manifest,
                find=str(args.get("find") or ""),
                regex=bool(args.get("regex", False)),
                source=str(args.get("source") or "translated"),
                scope=str(args.get("scope") or "all"),
                chapter_index=int(args.get("chapter_index") or 0),
                limit=int(args.get("limit") or SEARCH_LIMIT),
            )
        elif name == "get_chapter":
            result = get_chapter(
                storage, manifest,
                index=int(args.get("index")),
                include_raw=bool(args.get("include_raw", False)),
                include_translated=bool(args.get("include_translated", True)),
                max_chars=int(args.get("max_chars") or CHAPTER_MAX_CHARS),
            )
        elif name == "get_glossary":
            result = get_glossary(
                storage, query=str(args.get("query") or ""),
                limit=int(args.get("limit") or 300),
            )
        elif name == "get_characters":
            result = get_characters(
                storage, query=str(args.get("query") or ""),
                limit=int(args.get("limit") or 100),
            )
        elif name == "get_idioms":
            result = get_idioms(
                storage, query=str(args.get("query") or ""),
                limit=int(args.get("limit") or 100),
            )
        elif name == "preview_paragraph_edit":
            result = preview_paragraph_edit(
                storage, manifest,
                index=int(args.get("index")),
                para_index=int(args.get("para_index")),
                new_text=str(args.get("new_text") or ""),
            )
        elif name == "preview_glossary_edits":
            edits = args.get("edits")
            if not isinstance(edits, list):
                raise ValueError("edits phải là danh sách.")
            result = preview_glossary_edits(storage, edits)
        elif name == "preview_find_replace_batch":
            reps = args.get("replacements")
            if not isinstance(reps, list):
                raise ValueError("replacements phải là danh sách.")
            result = preview_find_replace_batch(
                storage, manifest, reps,
                source=str(args.get("source") or "translated"),
                scope=str(args.get("scope") or "all"),
                chapter_index=int(args.get("chapter_index") or 0),
            )
        elif name == "extract_proper_names":
            raw_indexes = args.get("chapter_indexes") or []
            indexes = [int(i) for i in raw_indexes if isinstance(i, (int, float))]
            result = extract_and_queue_proper_names(
                storage, manifest,
                chapter_indexes=indexes or None,
                min_frequency=int(args.get("min_frequency") or 2),
                max_candidates=int(args.get("max_candidates") or 100),
            )
        elif name == "enqueue_fill_context":
            if enqueue_job is None:
                return {"ok": False, "error": "Không enqueue được trong ngữ cảnh này."}
            raw_indexes = args.get("chapter_indexes") or []
            result = enqueue_job({
                "chapter_indexes": [int(i) for i in raw_indexes if isinstance(i, (int, float))],
                "with_retranslate": bool(args.get("with_retranslate", True)),
                "with_characters": bool(args.get("with_characters", True)),
            })
        else:
            return {"ok": False, "error": f"Tool không hỗ trợ: {name}"}
        return {"ok": True, "result": result}
    except (ValueError, TypeError) as e:
        return {"ok": False, "error": str(e)}


def _preview_card(name: str, args: dict, result: dict) -> dict | None:
    """Gói kết quả preview_* thành thẻ human-in-the-loop cho UI: diff + payload
    ghi chính xác (endpoint + body) để nút Áp dụng gọi sau khi tick chọn."""
    if name == "preview_paragraph_edit":
        return {
            "kind": "paragraph",
            "title": f"Chương {result.get('index')} · đoạn {result.get('para_index')}",
            "before": result.get("before") or "",
            "after": result.get("after") or "",
            "deleted": bool(result.get("deleted")),
            "apply": {
                "endpoint": "edits/apply",
                "body": {
                    "index": result.get("index"),
                    "para_index": result.get("para_index"),
                    "expected": result.get("before") or "",
                    "new_text": result.get("after") or "",
                },
            },
        }
    if name == "preview_glossary_edits":
        entries = result.get("entries") or []
        return {
            "kind": "glossary",
            "title": f"{result.get('writes')} mục glossary ({result.get('errors')} lỗi)",
            "entries": entries[:50],
            "entries_truncated": len(entries) > 50,
            "total_matches": result.get("total_matches") or 0,
            "has_errors": bool(result.get("errors")),
            "apply": {
                "endpoint": "glossary/apply",
                "body": {"edits": args.get("edits") or []},
            },
        }
    if name == "preview_find_replace_batch":
        groups = result.get("groups") or []
        items: list[dict] = []
        for gi, g in enumerate(groups):
            for it in g.get("items") or []:
                items.append({**it, "group": gi})
        return {
            "kind": "find_replace",
            "title": f"{result.get('total')} đoạn khớp ({len(groups)} nhóm)",
            "groups": [
                {"find": g.get("find"), "replace": g.get("replace"),
                 "regex": g.get("regex"), "count": len(g.get("items") or [])}
                for g in groups
            ],
            "items": items[:300],
            "truncated": bool(result.get("truncated")),
            "source": args.get("source") or "translated",
            "apply": {
                "endpoint": "find-replace/apply-batch",
                "body": {
                    "groups": groups,
                    "source": args.get("source") or "translated",
                    "all_matches": False,
                },
            },
        }
    return None


def run_agent_turn(
    chat_cfg,
    storage,
    manifest,
    user_text: str,
    history: list[dict] | None = None,
    max_iters: int = AGENT_MAX_ITERS,
    enqueue_job=None,
) -> tuple[str, list[dict], list[dict]]:
    """Vòng lặp tool-calling: LLM gọi tool đọc/preview → thực thi → lặp.

    Agent chỉ được preview, không apply — ghi phải qua nút Áp dụng của người
    dùng (human-in-the-loop). Trả (reply, trace, previews): trace là list
    `{name, arguments, ok}`; previews là các thẻ `_preview_card`.
    Raise RuntimeError khi gọi AI lỗi (caller đổi thành HTTP 502).
    """
    from . import openai_client as _oc

    messages: list[dict] = [{"role": "system", "content": ASSISTANT_SYSTEM_PROMPT}]
    for h in history or []:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_text})

    trace: list[dict] = []
    previews: list[dict] = []
    for _ in range(max(1, max_iters)):
        answer = _oc.chat_with_tools(chat_cfg, messages, ASSISTANT_TOOLS)
        calls = answer.get("tool_calls") or []
        if not calls:
            return answer.get("content") or "", trace, previews
        messages.append(
            {
                "role": "assistant",
                "content": answer.get("content") or "",
                "tool_calls": [
                    {
                        "id": c.get("id") or "",
                        "type": "function",
                        "function": {
                            "name": c.get("name") or "",
                            "arguments": json.dumps(
                                c.get("arguments") or {}, ensure_ascii=False
                            ),
                        },
                    }
                    for c in calls
                ],
            }
        )
        for c in calls:
            name = c.get("name") or ""
            args = c.get("arguments") or {}
            outcome = execute_tool(storage, manifest, name, args, enqueue_job)
            trace.append({"name": name, "arguments": args, "ok": bool(outcome.get("ok"))})
            if outcome.get("ok") and name.startswith("preview_"):
                card = _preview_card(name, args, outcome.get("result") or {})
                if card is not None:
                    previews.append(card)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": c.get("id") or "",
                    "content": json.dumps(outcome, ensure_ascii=False)[:12000],
                }
            )
    # Hết vòng lặp mà LLM vẫn đòi tool → trả lời cuối không tool.
    final = _oc.chat_with_tools(
        chat_cfg,
        messages + [{"role": "user", "content": "Dựa trên kết quả tool, trả lời gọn."}],
        [],
    )
    return final.get("content") or "", trace, previews

