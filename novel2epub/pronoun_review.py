"""Bounded, read-only web previews and exact-preview approval for pronoun edits."""
from __future__ import annotations

import difflib
import hashlib
import hmac
import json
import re
import uuid

from .chapter_versions import BRANCH_COLUMNS, ChapterVersionError, ChapterVersionService
from .ops_baseline import full_content_hash
from .pronouns import DIALOGUE_MARK_MODES, RULE_VERSION, DialogueMarks, normalize_pronouns

MAX_CHAPTERS = 50
MAX_TEXT_BYTES = 2_000_000


class PronounPreviewStale(ValueError):
    pass


def _preview(storage, branch: str, indexes: list[int], dialogue_marks: DialogueMarks) -> tuple[dict, list[dict]]:
    if branch not in BRANCH_COLUMNS:
        raise ValueError("Chọn nhánh AI hoặc Local MT.")
    if dialogue_marks not in DIALOGUE_MARK_MODES:
        raise ValueError("Kiểu dấu bao quanh không hợp lệ.")
    if not indexes or len(indexes) > MAX_CHAPTERS:
        raise ValueError(f"Chọn từ 1 đến {MAX_CHAPTERS} chương mỗi lượt.")
    if any(type(index) is not int or index < 0 for index in indexes):
        raise ValueError("Index chương phải là số nguyên không âm.")
    if len(set(indexes)) != len(indexes):
        raise ValueError("Danh sách chương không được trùng index.")
    columns = BRANCH_COLUMNS[branch]
    terms = sorted({
        term for entity in storage.read_merged_entities() if entity.protect
        for term in (entity.source, entity.target) if term
    })
    chapters, skipped, documents, fingerprints = [], [], [], []
    scanned = total_bytes = 0
    for index in sorted(indexes):
        row = storage.conn.execute(
            f"SELECT {columns['title']} AS title, {columns['text']} AS text, "
            f"{columns['revision']} AS revision, skipped, meta_json "
            "FROM chapters WHERE ebook_slug=? AND idx=?", (storage.slug, index),
        ).fetchone()
        if row is None:
            raise ValueError(f"Không tìm thấy chương có index {index}.")
        title, text, revision = row["title"] or "", row["text"] or "", int(row["revision"] or 0)
        total_bytes += len(text.encode("utf-8"))
        if total_bytes > MAX_TEXT_BYTES:
            raise ValueError("Nội dung vượt 2 MB mỗi lượt. Hãy chọn ít chương hơn.")
        try:
            meta = json.loads(row["meta_json"] or "{}")
        except (ValueError, TypeError):
            meta = {}
        complete_key = "complete" if branch == "ai" else "local_mt_complete"
        complete = bool(meta.get(complete_key, True)) if isinstance(meta, dict) else False
        source_hash = full_content_hash(title, text)
        fingerprints.append([index, revision, source_hash, bool(row["skipped"]), complete])
        if row["skipped"] or not text or not complete:
            skipped.append({"index": index, "reason": "Đã đánh dấu bỏ qua" if row["skipped"] else "Nhánh chưa có bản dịch hoàn chỉnh"})
            continue
        scanned += 1
        result = normalize_pronouns(text, protected_terms=terms, dialogue_marks=dialogue_marks)
        if not result.changes:
            continue
        diff = "".join(
            line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
            for line in difflib.unified_diff(
                text.splitlines(keepends=True), result.text.splitlines(keepends=True),
                fromfile=f"Chương {index} · Trước", tofile=f"Chương {index} · Sau",
            )
        )
        chapters.append({
            "index": index, "title": title, "revision": revision,
            "replacements": len(result.changes), "diff": diff,
        })
        documents.append({
            "index": index, "title": title, "before": text, "after": result.text,
            "revision": revision, "hash": source_hash, "replacements": len(result.changes),
        })
    payload = {
        "slug": storage.slug, "branch": branch, "rules": RULE_VERSION,
        "dialogue_marks": dialogue_marks,
        "terms": terms, "fingerprints": fingerprints,
        "outputs": [full_content_hash(doc["title"], doc["after"]) for doc in documents],
    }
    token = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "branch": branch, "indexes": sorted(indexes), "token": token,
        "dialogue_marks": dialogue_marks,
        "scanned": scanned, "unchanged": scanned - len(chapters), "skipped": skipped,
        "chapters": chapters, "replacements": sum(item["replacements"] for item in chapters),
    }, documents


def preview_pronouns(storage, *, branch: str, indexes: list[int], dialogue_marks: DialogueMarks = "standard") -> dict:
    # No read_document here: legacy baseline healing would write during preview.
    return _preview(storage, branch, indexes, dialogue_marks)[0]


def apply_pronoun_preview(storage, *, branch: str, indexes: list[int], token: str, dialogue_marks: DialogueMarks = "standard") -> dict:
    report, documents = _preview(storage, branch, indexes, dialogue_marks)
    if not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{64}", token) or not hmac.compare_digest(token, report["token"]):
        raise PronounPreviewStale("Bản xem trước đã cũ. Hãy xem trước lại rồi xác nhận.")
    service = ChapterVersionService(storage)
    applied, failed = [], []
    replacements = 0
    for document in documents:
        index = document["index"]
        try:
            base = service.read_document(index, branch)
            if base.content_hash != document["hash"] or (document["revision"] > 0 and base.revision != document["revision"]):
                raise ChapterVersionError("document_conflict", "Chương đã thay đổi; xem trước lại trước khi ghi.")
            # Recheck eligibility: another editor may skip/mark incomplete while
            # history is reconciled. The content write itself uses revision/hash CAS.
            current = storage.get_chapter(index)
            if current is None or current.skipped or not storage.has_branch_text(current, branch):
                raise ChapterVersionError("document_conflict", "Trạng thái chương đã đổi; không ghi.")
            service.commit_document(
                chapter_index=index, branch=branch, expected_revision=base.revision,
                expected_content_hash=base.content_hash, title=base.title, translated=document["after"],
                client_operation_id=f"pronouns:{uuid.uuid4()}", kind="normalize_pronouns",
                message="Chuẩn hóa xưng hô ta/ngươi từ bản xem trước Web UI",
                metadata={"rules": RULE_VERSION, "replacements": document["replacements"], "preview_token": token, "dialogue_marks": dialogue_marks},
            )
            applied.append(index)
            replacements += document["replacements"]
        except ChapterVersionError as exc:
            failed.append({"index": index, "code": exc.code, "error": exc.message})
    return {"applied": applied, "failed": failed, "replacements": replacements}
