"""Versioned, review-first AI workflow for a translated ebook.

Model output is only a proposal. Every write is anchored to a saved snapshot and
is initiated by the review UI, never by the scanning job.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Callable

from . import assistant, openai_client
from .notes import split_paras

WORKFLOW_VERSION = 1
MAX_CHUNK_CHARS = 9000
CATEGORIES = {"glossary", "consistency", "mistranslation", "hanviet", "fluency", "other"}
SEVERITIES = {"high", "medium", "low"}


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _rows(conn, sql: str, args: tuple = ()) -> list[dict]:
    return [dict(row) for row in conn.execute(sql, args).fetchall()]


def create_run(conn, slug: str, indexes: list[int]) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO ai_harness_runs (ebook_slug, workflow_version, total) VALUES (?, ?, ?)",
            (slug, WORKFLOW_VERSION, len(indexes)),
        )
        run_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO ai_harness_chapters (run_id, chapter_index) VALUES (?, ?)",
            [(run_id, index) for index in indexes],
        )
    return int(run_id)


def list_runs(conn, slug: str) -> list[dict]:
    return _rows(conn, "SELECT * FROM ai_harness_runs WHERE ebook_slug=? ORDER BY id DESC LIMIT 20", (slug,))


def get_run(conn, slug: str, run_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM ai_harness_runs WHERE id=? AND ebook_slug=?", (run_id, slug)).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["chapters"] = _rows(
        conn, "SELECT * FROM ai_harness_chapters WHERE run_id=? ORDER BY chapter_index", (run_id,)
    )
    result["issues"] = _rows(
        conn, "SELECT * FROM ai_harness_issues WHERE run_id=? ORDER BY chapter_index, id", (run_id,)
    )
    return result


def _chunks(raw: str, translated: str):
    """Bound model context while preserving paragraph numbers for the translation."""
    raw_paras = split_paras(raw)
    translated_paras = split_paras(translated)
    start = 0
    while start < len(translated_paras):
        end = start
        size = 0
        while end < len(translated_paras):
            raw_hint = raw_paras[end] if end < len(raw_paras) else ""
            added = len(raw_hint) + len(translated_paras[end]) + 32
            if end > start and size + added > MAX_CHUNK_CHARS:
                break
            size += added
            end += 1
        yield start, raw_paras[start:end], translated_paras[start:end]
        start = end


def _parse_response(text: str) -> list[dict]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError("Model trả JSON không hợp lệ") from exc
    if not isinstance(data, dict) or not isinstance(data.get("issues"), list):
        raise ValueError("Model thiếu danh sách issues")
    if len(data["issues"]) > 100:
        raise ValueError("Model trả quá nhiều issues trong một lượt")
    return data["issues"]


def _prompt(raw_paras: list[str], translated_paras: list[str], start: int, glossary: list[tuple]) -> str:
    source = "\n".join(f"[{start+i}] {p}" for i, p in enumerate(raw_paras))
    target = "\n".join(f"[{start+i}] {p}" for i, p in enumerate(translated_paras))
    terms = "\n".join(f"{s} = {t}" for s, t, *_ in glossary if s in source or t in target)[:6000]
    return (
        "Rà soát bản dịch Trung→Việt. Tìm sai tên riêng/glossary, xưng hô, chữ Hán sót, "
        "sai nghĩa và câu văn bất thường. Chỉ nêu lỗi có bằng chứng; không tự sửa dữ liệu. "
        "Trả JSON object duy nhất dạng {\"issues\":[{\"category\":\"glossary|consistency|mistranslation|hanviet|fluency|other\","
        "\"severity\":\"high|medium|low\",\"source\":\"đoạn Hán liên quan\","
        "\"current\":\"chuỗi nguyên văn trong bản dịch cần sửa\","
        "\"suggestion\":\"chuỗi thay thế chính xác\",\"reason\":\"lý do ngắn\"}]}. "
        "Với lỗi Glossary, source phải là khóa Hán đã có trong bảng, current là giá trị Việt cũ, "
        "suggestion là giá trị Việt mới. Với lỗi nội dung, current phải xuất hiện nguyên văn "
        "trong đúng một đoạn của bản dịch dưới đây. Không có lỗi thì trả {\"issues\":[]}.\n\n"
        f"Glossary liên quan:\n{terms or '(trống)'}\n\nBản gốc:\n{source}\n\nBản dịch:\n{target}"
    )


def _normalize_issue(item: dict, index: int, branch: str, translated: str, glossary: dict[str, str]) -> dict:
    if not isinstance(item, dict):
        raise ValueError("Issue không phải object")
    category = str(item.get("category", "other"))
    severity = str(item.get("severity", "low"))
    source = str(item.get("source", "")).strip()
    current = str(item.get("current", "")).strip()
    suggestion = str(item.get("suggestion", "")).strip()
    reason = str(item.get("reason", "")).strip()
    if not current or not suggestion or current == suggestion:
        raise ValueError("Issue thiếu bản hiện tại hoặc đề xuất sửa")
    kind = "glossary" if category == "glossary" else "text"
    issue = dict(
        chapter_index=index, category=category if category in CATEGORIES else "other",
        severity=severity if severity in SEVERITIES else "low", kind=kind,
        source=source, current=current, suggestion=suggestion, reason=reason,
        para_index=None, before_text="", after_text="", branch=branch,
        content_hash=_hash(translated), status="pending", error="",
    )
    if kind == "glossary":
        if source not in glossary:
            issue.update(status="blocked", error="Không tìm thấy khóa Hán trong Glossary")
        elif glossary[source] != current:
            issue.update(status="blocked", error="Giá trị Glossary hiện tại không khớp đề xuất")
        return issue
    paras = split_paras(translated)
    matches = [i for i, para in enumerate(paras) if para.count(current) == 1]
    if len(matches) != 1:
        issue.update(status="blocked", error="Không xác định được duy nhất một đoạn cần sửa")
        return issue
    pi = matches[0]
    if "\n" in suggestion or (current != paras[pi] and len(suggestion) > max(len(current) * 3, len(paras[pi]))):
        issue.update(status="blocked", error="Bản sửa quá rộng cho một cụm từ; cần sửa tay")
        return issue
    issue.update(para_index=pi, before_text=paras[pi], after_text=paras[pi].replace(current, suggestion, 1))
    return issue


def scan_chapter(cfg, storage, ch, model_call: Callable | None = None) -> list[dict]:
    if not storage.has_raw(ch) or not storage.has_active_branch_text(ch):
        raise ValueError("Chương thiếu bản gốc hoặc bản dịch")
    raw = storage.read_raw(ch)
    translated = storage.read_active_branch_text(ch)
    if not split_paras(translated):
        raise ValueError("Chương chưa có đoạn bản dịch để rà soát")
    branch = storage.active_branch(ch)
    glossary_rows = storage.read_glossary_entries_merged()
    glossary = {s: t for s, t, *_ in glossary_rows}
    call = model_call or openai_client.run_chat
    result: list[dict] = []
    seen: set[tuple] = set()
    for start, raw_paras, translated_paras in _chunks(raw, translated):
        for item in _parse_response(call(cfg.ai.openai, _prompt(raw_paras, translated_paras, start, glossary_rows))):
            issue = _normalize_issue(item, ch.index, branch, translated, glossary)
            key = (issue["kind"], issue["source"], issue["current"], issue["suggestion"], issue["para_index"])
            if key not in seen:
                result.append(issue)
                seen.add(key)
    return result


def save_chapter_result(conn, run_id: int, index: int, issues: list[dict] | None, error: str = "") -> None:
    with conn:
        if issues:
            conn.executemany(
                """INSERT INTO ai_harness_issues
                (run_id, chapter_index, category, severity, kind, status, source, current,
                 suggestion, reason, para_index, before_text, after_text, branch, content_hash, error)
                VALUES (:run_id, :chapter_index, :category, :severity, :kind, :status, :source,
                        :current, :suggestion, :reason, :para_index, :before_text, :after_text,
                        :branch, :content_hash, :error)""",
                [dict(issue, run_id=run_id) for issue in issues],
            )
        status = "failed" if error else "issues" if issues else "clean"
        conn.execute(
            "UPDATE ai_harness_chapters SET status=?, issue_count=?, error=? WHERE run_id=? AND chapter_index=?",
            (status, len(issues or []), error[:1000], run_id, index),
        )
        conn.execute(
            "UPDATE ai_harness_runs SET processed=processed+1, failed=failed+? WHERE id=?",
            (int(bool(error)), run_id),
        )


def finish_run(conn, run_id: int) -> None:
    with conn:
        conn.execute(
            "UPDATE ai_harness_runs SET status=CASE WHEN failed>0 THEN 'partial' ELSE 'completed' END, finished_at=datetime('now') WHERE id=?",
            (run_id,),
        )


def selected_issues(conn, slug: str, run_id: int, ids: list[int], *, allow_blocked: bool = False) -> list[dict]:
    if not ids or len(ids) > 500:
        raise ValueError("Chọn từ 1 đến 500 đề xuất")
    placeholders = ",".join("?" for _ in ids)
    rows = _rows(conn,
        f"""SELECT i.* FROM ai_harness_issues i JOIN ai_harness_runs r ON r.id=i.run_id
            WHERE r.ebook_slug=? AND i.run_id=? AND i.id IN ({placeholders})""",
        (slug, run_id, *ids),
    )
    allowed = {"pending", "blocked"} if allow_blocked else {"pending"}
    if len(rows) != len(set(ids)) or any(row["status"] not in allowed for row in rows):
        raise ValueError("Đề xuất không tồn tại hoặc đã được xử lý")
    if not allow_blocked and len({row["kind"] for row in rows}) != 1:
        raise ValueError("Duyệt sửa nội dung và Glossary thành hai đợt riêng")
    return rows


def preview_selected(storage, manifest, rows: list[dict]) -> dict:
    if rows[0]["kind"] == "glossary":
        edits = _glossary_edits(storage, rows)
        preview = assistant.preview_glossary_edits(storage, edits)
        replacements = [{"find": row["current"], "replace": row["suggestion"], "regex": False} for row in rows]
        samples = assistant.preview_find_replace_batch(storage, manifest, replacements, limit=20)
        return {"kind": "glossary", **preview, "samples": samples}
    chapters = {ch.index: ch for ch in manifest.chapters}
    items = []
    selected_paragraphs = [(row["chapter_index"], row["para_index"]) for row in rows]
    for row in rows:
        ch = chapters.get(row["chapter_index"])
        stale = ch is None or storage.active_branch(ch) != row["branch"]
        if not stale:
            text = storage.read_branch_text(ch, row["branch"])
            paras = split_paras(text)
            pi = row["para_index"]
            stale = _hash(text) != row["content_hash"] or pi is None or pi >= len(paras) or paras[pi] != row["before_text"]
        conflict = selected_paragraphs.count((row["chapter_index"], row["para_index"])) > 1
        items.append({"id": row["id"], "chapter_index": row["chapter_index"],
                      "before": row["before_text"], "after": row["after_text"], "stale": stale or conflict})
    return {"kind": "text", "items": items, "stale": sum(bool(i["stale"]) for i in items)}


def _glossary_edits(storage, rows: list[dict]) -> list[dict]:
    current = {s: t for s, t, *_ in storage.read_glossary_entries_merged()}
    by_source: dict[str, dict] = {}
    for row in rows:
        source = row["source"]
        if current.get(source) != row["current"]:
            raise ValueError(f"Glossary {source} đã đổi; cần rà soát lại")
        if source in by_source and by_source[source]["target"] != row["suggestion"]:
            raise ValueError(f"Nhiều đề xuất xung đột cho {source}")
        by_source[source] = {"source": source, "target": row["suggestion"], "note": "", "original_source": source}
    return list(by_source.values())


def apply_selected(conn, storage, manifest, rows: list[dict]) -> dict:
    preview = preview_selected(storage, manifest, rows)
    if rows[0]["kind"] == "glossary":
        edits = _glossary_edits(storage, rows)
        if preview["errors"]:
            raise ValueError("Glossary preview còn lỗi")
        result = assistant.apply_glossary_edits(storage, edits)
    else:
        if preview["stale"]:
            raise ValueError("Nội dung đã đổi; xem trước lại trước khi áp dụng")
        groups: dict[int, list[dict]] = defaultdict(list)
        for row in rows:
            groups[row["chapter_index"]].append(row)
        chapters = {ch.index: ch for ch in manifest.chapters}
        for index, group in groups.items():
            indexes = [row["para_index"] for row in group]
            if len(indexes) != len(set(indexes)):
                raise ValueError(f"Chương {index} có nhiều đề xuất trên cùng một đoạn; chọn từng lỗi")
        for index, group in groups.items():
            ch = chapters[index]
            text = storage.read_branch_text(ch, group[0]["branch"])
            # Preserve blank lines through the same paragraph replacement semantics as the editor.
            from .notes import replace_para
            updated = text
            for row in group:
                updated, err = replace_para(updated, row["para_index"], row["before_text"], row["after_text"])
                if updated is None:
                    raise ValueError(err or "Không thể áp dụng đoạn")
            assistant._backup_and_write(storage, ch, "translated", text, updated)
            with conn:
                conn.executemany("UPDATE ai_harness_issues SET status='applied' WHERE id=?", [(row["id"],) for row in group])
        result = {"applied": len(rows), "chapters": len(groups)}
    if rows[0]["kind"] == "glossary":
        with conn:
            conn.executemany("UPDATE ai_harness_issues SET status='applied' WHERE id=?", [(row["id"],) for row in rows])
    return result


def export_markdown(run: dict) -> str:
    lines = [f"# AI Harness — {run['ebook_slug']}", "", f"Run #{run['id']} · {run['status']} · workflow v{run['workflow_version']}", ""]
    for chapter in run["chapters"]:
        lines.append(f"## Chương {chapter['chapter_index']} — {chapter['status']}")
        if chapter["error"]:
            lines.append(f"Lỗi: {chapter['error']}")
        for issue in (i for i in run["issues"] if i["chapter_index"] == chapter["chapter_index"]):
            lines.extend(["", f"- **{issue['category']} / {issue['severity']}** ({issue['status']}): {issue['reason']}",
                          f"  - Hiện tại: {issue['current']}", f"  - Đề xuất: {issue['suggestion']}"])
        lines.append("")
    return "\n".join(lines)
