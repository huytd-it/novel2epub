"""Version service cho chapter document theo nhánh.

Mọi commit đi qua một transaction ``BEGIN IMMEDIATE``: kiểm tra idempotency,
đối chiếu current state với immutable history head, optimistic concurrency,
thêm operation/revision rồi CAS current state. Module không dùng active_branch;
mutation target luôn là branch tường minh.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from .ops_baseline import ENCODING_ZLIB, compress_content, decompress_content, full_content_hash

BRANCH_COLUMNS = {
    "ai": {
        "title": "title",
        "text": "translated_text",
        "revision": "revision",
        "hash": "ai_content_hash",
    },
    "local_mt": {
        "title": "local_mt_title",
        "text": "local_mt_text",
        "revision": "local_mt_revision",
        "hash": "local_mt_content_hash",
    },
}
MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
MAX_CLIENT_OPERATION_ID = 255
MAX_MESSAGE_BYTES = 4096


class ChapterVersionError(RuntimeError):
    """Domain error có stable code và metadata để route ánh xạ HTTP."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class ChapterDocument:
    ebook_slug: str
    chapter_index: int
    branch: str
    revision: int
    content_hash: str
    title: str
    translated: str
    head_revision_id: int


@dataclass(frozen=True)
class CommitResult:
    status: str
    document: ChapterDocument
    operation_id: int | None = None
    revision_id: int | None = None
    idempotent_replay: bool = False


@dataclass(frozen=True)
class IntegrityReport:
    valid: bool
    errors: tuple[dict[str, Any], ...] = field(default_factory=tuple)


def _strict_branch(branch: str) -> dict[str, str]:
    if branch not in BRANCH_COLUMNS:
        raise ChapterVersionError("invalid_request", "branch phải là 'ai' hoặc 'local_mt'")
    return BRANCH_COLUMNS[branch]


def _require_hash(value: str, field_name: str) -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise ChapterVersionError("invalid_request", f"{field_name} phải là SHA-256 đầy đủ")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ChapterVersionError("invalid_request", f"{field_name} phải là SHA-256 đầy đủ") from exc


def _request_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _validate_commit(
    *, branch: str, expected_revision: int, expected_content_hash: str,
    title: str, translated: str, client_operation_id: str, message: str,
) -> dict[str, str]:
    cols = _strict_branch(branch)
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 1:
        raise ChapterVersionError("invalid_request", "expected_revision phải là số nguyên dương")
    _require_hash(expected_content_hash, "expected_content_hash")
    if not isinstance(title, str) or not isinstance(translated, str):
        raise ChapterVersionError("invalid_request", "title và translated phải là chuỗi")
    if not isinstance(client_operation_id, str) or not client_operation_id:
        raise ChapterVersionError("invalid_request", "client_operation_id là bắt buộc")
    if len(client_operation_id.encode("utf-8")) > MAX_CLIENT_OPERATION_ID:
        raise ChapterVersionError("invalid_request", "client_operation_id quá dài")
    if not isinstance(message, str):
        raise ChapterVersionError("invalid_request", "message phải là chuỗi")
    if len(message.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise ChapterVersionError("invalid_request", "message quá dài")
    if len(title.encode("utf-8")) + len(translated.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise ChapterVersionError("document_too_large", "document vượt giới hạn kích thước")
    return cols


def _head_row(conn: sqlite3.Connection, slug: str, index: int, branch: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM chapter_revisions WHERE ebook_slug=? AND chapter_index=? "
        "AND branch=? ORDER BY revision_number DESC, id DESC LIMIT 1",
        (slug, index, branch),
    ).fetchone()


def _current_row(conn: sqlite3.Connection, slug: str, index: int, cols: dict[str, str]) -> sqlite3.Row | None:
    return conn.execute(
        f"SELECT {cols['title']} AS title, {cols['text']} AS translated, "
        f"{cols['revision']} AS revision, {cols['hash']} AS content_hash "
        "FROM chapters WHERE ebook_slug=? AND idx=?",
        (slug, index),
    ).fetchone()


def _verify_pair(current: sqlite3.Row, head: sqlite3.Row, *, slug: str, index: int, branch: str) -> ChapterDocument:
    try:
        if head["content_encoding"] != ENCODING_ZLIB or head["content_blob"] is None:
            raise ValueError("unsupported or missing snapshot encoding")
        snapshot = decompress_content(head["content_blob"])
    except Exception as exc:
        raise ChapterVersionError(
            "history_state_diverged", "Không thể giải nén history head",
            details={"chapter_index": index, "branch": branch, "reason": str(exc)},
        ) from exc
    snapshot_hash = full_content_hash(head["title"], snapshot)
    current_title = current["title"] or ""
    current_text = current["translated"] if current["translated"] is not None else ""
    current_hash = current["content_hash"] or ""
    mismatches: list[str] = []
    if snapshot_hash != head["content_hash"]:
        mismatches.append("snapshot_hash")
    if int(current["revision"]) != int(head["revision_number"]):
        mismatches.append("revision")
    if current_hash != head["content_hash"]:
        mismatches.append("content_hash")
    if current_title != head["title"] or current_text != snapshot:
        mismatches.append("content")
    if mismatches:
        raise ChapterVersionError(
            "history_state_diverged", "Current state và history head không đồng nhất",
            details={"chapter_index": index, "branch": branch, "mismatches": mismatches},
        )
    return ChapterDocument(
        ebook_slug=slug, chapter_index=index, branch=branch,
        revision=int(current["revision"]), content_hash=current_hash,
        title=current_title, translated=current_text, head_revision_id=int(head["id"]),
    )


class ChapterVersionService:
    def __init__(self, storage):
        self.storage = storage

    @property
    def conn(self) -> sqlite3.Connection:
        return self.storage.conn

    def read_document(self, chapter_index: int, branch: str) -> ChapterDocument:
        cols = _strict_branch(branch)
        current = _current_row(self.conn, self.storage.slug, chapter_index, cols)
        if current is None:
            raise ChapterVersionError("chapter_not_found", "Không tìm thấy chương")
        if current["translated"] is None:
            raise ChapterVersionError("branch_not_initialized", "Nhánh chưa được khởi tạo")
        head = _head_row(self.conn, self.storage.slug, chapter_index, branch)
        if head is None:
            raise ChapterVersionError("branch_not_initialized", "Nhánh chưa có baseline history")
        return _verify_pair(current, head, slug=self.storage.slug, index=chapter_index, branch=branch)

    def commit_document(
        self, *, chapter_index: int, branch: str, expected_revision: int,
        expected_content_hash: str, title: str, translated: str,
        client_operation_id: str, message: str = "", kind: str = "manual",
        actor_issuer: str = "", actor_subject: str = "",
    ) -> CommitResult:
        cols = _validate_commit(
            branch=branch, expected_revision=expected_revision,
            expected_content_hash=expected_content_hash, title=title,
            translated=translated, client_operation_id=client_operation_id,
            message=message,
        )
        if not isinstance(chapter_index, int) or isinstance(chapter_index, bool) or chapter_index < 0:
            raise ChapterVersionError("invalid_request", "chapter_index không hợp lệ")
        if not isinstance(kind, str) or not kind:
            raise ChapterVersionError("invalid_request", "kind là bắt buộc")
        new_hash = full_content_hash(title, translated)
        blob = compress_content(translated)
        request_hash = _request_hash({
            "ebook_slug": self.storage.slug, "chapter_index": chapter_index,
            "branch": branch, "expected_revision": expected_revision,
            "expected_content_hash": expected_content_hash, "title": title,
            "translated": translated, "message": message, "kind": kind,
            "actor_issuer": actor_issuer, "actor_subject": actor_subject,
        })
        conn = self.conn
        try:
            conn.execute("BEGIN IMMEDIATE")
            prior = conn.execute(
                "SELECT * FROM chapter_operations WHERE client_operation_id=?",
                (client_operation_id,),
            ).fetchone()
            if prior is not None:
                if prior["request_hash"] != request_hash:
                    raise ChapterVersionError(
                        "idempotency_key_reused", "client_operation_id đã được dùng cho payload khác"
                    )
                revision = conn.execute(
                    "SELECT * FROM chapter_revisions WHERE operation_id=? ORDER BY id LIMIT 1",
                    (prior["id"],),
                ).fetchone()
                if revision is None:
                    raise ChapterVersionError("history_state_diverged", "Operation không có revision")
                if (
                    revision["ebook_slug"] != self.storage.slug
                    or int(revision["chapter_index"]) != chapter_index
                    or revision["branch"] != branch
                ):
                    raise ChapterVersionError(
                        "history_state_diverged", "Operation idempotency trỏ sai document"
                    )
                try:
                    replay_text = decompress_content(revision["content_blob"])
                except Exception as exc:
                    raise ChapterVersionError(
                        "history_state_diverged", "Không thể giải nén revision idempotency"
                    ) from exc
                if full_content_hash(revision["title"], replay_text) != revision["content_hash"]:
                    raise ChapterVersionError(
                        "history_state_diverged", "Revision idempotency có hash không hợp lệ"
                    )
                document = ChapterDocument(
                    ebook_slug=self.storage.slug,
                    chapter_index=chapter_index,
                    branch=branch,
                    revision=int(revision["revision_number"]),
                    content_hash=revision["content_hash"],
                    title=revision["title"],
                    translated=replay_text,
                    head_revision_id=int(revision["id"]),
                )
                conn.commit()
                return CommitResult(
                    "committed", document, int(prior["id"]), int(revision["id"]), True
                )

            current = _current_row(conn, self.storage.slug, chapter_index, cols)
            if current is None:
                raise ChapterVersionError("chapter_not_found", "Không tìm thấy chương")
            if current["translated"] is None:
                raise ChapterVersionError("branch_not_initialized", "Nhánh chưa được khởi tạo")
            head = _head_row(conn, self.storage.slug, chapter_index, branch)
            if head is None:
                raise ChapterVersionError("branch_not_initialized", "Nhánh chưa có baseline history")
            document = _verify_pair(
                current, head, slug=self.storage.slug, index=chapter_index, branch=branch
            )
            if document.revision != expected_revision or document.content_hash != expected_content_hash:
                raise ChapterVersionError(
                    "document_conflict", "Document đã thay đổi",
                    details={
                        "expected_revision": expected_revision,
                        "expected_content_hash": expected_content_hash,
                        "current_revision": document.revision,
                        "current_content_hash": document.content_hash,
                    },
                )
            if new_hash == document.content_hash:
                conn.commit()
                return CommitResult("unchanged", document)

            op = conn.execute(
                "INSERT INTO chapter_operations (ebook_slug, kind, message, actor_issuer, "
                "actor_subject, client_operation_id, request_hash, metadata_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, '{}')",
                (
                    self.storage.slug, kind, message, actor_issuer, actor_subject,
                    client_operation_id, request_hash,
                ),
            )
            operation_id = int(op.lastrowid)
            revision_number = document.revision + 1
            revision = conn.execute(
                "INSERT INTO chapter_revisions (operation_id, ebook_slug, chapter_index, "
                "branch, revision_number, parent_revision_id, title, content_blob, "
                "content_encoding, content_hash, base_content_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    operation_id, self.storage.slug, chapter_index, branch,
                    revision_number, document.head_revision_id, title, blob,
                    ENCODING_ZLIB, new_hash, document.content_hash,
                ),
            )
            revision_id = int(revision.lastrowid)
            cur = conn.execute(
                f"UPDATE chapters SET {cols['title']}=?, {cols['text']}=?, "
                f"{cols['revision']}=?, {cols['hash']}=?, updated_by_issuer=?, "
                "updated_by_subject=?, translated_updated_at=unixepoch('now') "
                f"WHERE ebook_slug=? AND idx=? AND {cols['revision']}=? AND {cols['hash']}=?",
                (
                    title, translated, revision_number, new_hash, actor_issuer,
                    actor_subject, self.storage.slug, chapter_index,
                    expected_revision, expected_content_hash,
                ),
            )
            if cur.rowcount != 1:
                raise ChapterVersionError("document_conflict", "CAS current document thất bại")
            post_current = _current_row(conn, self.storage.slug, chapter_index, cols)
            post_head = _head_row(conn, self.storage.slug, chapter_index, branch)
            post = _verify_pair(
                post_current, post_head, slug=self.storage.slug,
                index=chapter_index, branch=branch,
            )
            if post.head_revision_id != revision_id:
                raise ChapterVersionError("history_state_diverged", "Postcondition head không khớp revision mới")
            conn.commit()
            return CommitResult("committed", post, operation_id, revision_id)
        except ChapterVersionError:
            conn.rollback()
            raise
        except sqlite3.OperationalError as exc:
            conn.rollback()
            if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                raise ChapterVersionError("database_busy", "SQLite đang bận") from exc
            raise
        except Exception:
            conn.rollback()
            raise

    def validate_integrity(self, *, chapter_index: int | None = None) -> IntegrityReport:
        errors: list[dict[str, Any]] = []
        params: list[Any] = [self.storage.slug]
        where = "WHERE ebook_slug=?"
        if chapter_index is not None:
            where += " AND idx=?"
            params.append(chapter_index)
        rows = self.conn.execute(f"SELECT idx FROM chapters {where} ORDER BY idx", params).fetchall()
        for row in rows:
            for branch, cols in BRANCH_COLUMNS.items():
                current = _current_row(self.conn, self.storage.slug, int(row["idx"]), cols)
                if current["translated"] is None:
                    continue
                head = _head_row(self.conn, self.storage.slug, int(row["idx"]), branch)
                if head is None:
                    errors.append({"code": "branch_not_initialized", "chapter_index": row["idx"], "branch": branch})
                    continue
                try:
                    _verify_pair(current, head, slug=self.storage.slug, index=int(row["idx"]), branch=branch)
                except ChapterVersionError as exc:
                    errors.append({"code": exc.code, **exc.details})
        return IntegrityReport(not errors, tuple(errors))
