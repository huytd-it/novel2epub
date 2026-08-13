"""Kho dữ liệu canonical: backfill source, segment và alignment có thể chạy lại.

Backfill là thao tác explicit, không chạy lúc startup. Nó không sửa raw/workspace,
không tự đánh dấu dữ liệu eligible/gold; alignment ordinal chỉ là đề xuất độ tin
cậy thấp để con người hoặc validator/LLM xác minh sau.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass

from .ops_baseline import (
    ENCODING_ZLIB,
    compress_content,
    decompress_content,
    full_content_hash,
    initialize_branch_revisions,
)

KIND_SOURCE_BASELINE = "migration_source_baseline"
KIND_ALIGNMENT_BASELINE = "migration_alignment_baseline"
_SPLITTER = "nonempty_line_v1"


@dataclass(frozen=True)
class DatasetBackfillResult:
    source_revisions: int = 0
    translation_links: int = 0
    source_segments: int = 0
    translation_segments: int = 0
    alignments: int = 0


def _operation_id(conn, slug: str, kind: str, suffix: str) -> int:
    client_id = f"dataset-store-v1:{suffix}:{slug}"
    request_hash = hashlib.sha256(client_id.encode("utf-8")).hexdigest()
    conn.execute(
        "INSERT INTO chapter_operations (ebook_slug, kind, message, client_operation_id, "
        "request_hash, metadata_json) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(client_operation_id) DO NOTHING",
        (slug, kind, "Dataset canonical backfill v1", client_id, request_hash,
         json.dumps({"backfilled": True}, ensure_ascii=False)),
    )
    row = conn.execute(
        "SELECT id, ebook_slug, kind, request_hash FROM chapter_operations "
        "WHERE client_operation_id=?", (client_id,),
    ).fetchone()
    if row is None or row["ebook_slug"] != slug or row["kind"] != kind or row["request_hash"] != request_hash:
        raise RuntimeError("dataset backfill idempotency operation không khớp")
    return int(row["id"])


def _segments(text: str) -> list[tuple[int, int, str, str]]:
    """Các dòng không rỗng cùng offset chính xác trong immutable document."""
    result: list[tuple[int, int, str, str]] = []
    cursor = 0
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        start = cursor
        cursor += len(line)
        if not content.strip():
            continue
        result.append((start, start + len(content), content, hashlib.sha256(content.encode("utf-8")).hexdigest()))
    # splitlines() không tạo item cho chuỗi rỗng; trường hợp một dòng không newline
    # đã được xử lý. `text == ""` hợp lệ và cho danh sách rỗng.
    return result


def backfill_dataset_store(storage) -> DatasetBackfillResult:
    """Dựng canonical source/segments/alignment cho một ebook, idempotent.

    Translation baseline được tạo trước bằng service hiện có. Toàn bộ phần dataset
    sau đó ghi trong một BEGIN IMMEDIATE; lỗi rollback sạch và không đổi workspace.
    """
    initialize_branch_revisions(storage)
    conn = storage.conn
    slug = storage.slug

    raw_rows = conn.execute(
        "SELECT idx, url, title_zh, raw_text FROM chapters "
        "WHERE ebook_slug=? AND raw_text IS NOT NULL ORDER BY idx", (slug,),
    ).fetchall()
    prepared_sources = [
        {
            "index": int(row["idx"]), "url": row["url"] or "",
            "title": row["title_zh"] or "", "text": row["raw_text"] or "",
            "hash": full_content_hash(row["title_zh"] or "", row["raw_text"] or ""),
            "blob": compress_content(row["raw_text"] or ""),
        }
        for row in raw_rows
    ]

    counts = {"source_revisions": 0, "translation_links": 0, "source_segments": 0,
              "translation_segments": 0, "alignments": 0}
    try:
        conn.execute("BEGIN IMMEDIATE")
        source_op = _operation_id(conn, slug, KIND_SOURCE_BASELINE, "source")
        alignment_op = _operation_id(conn, slug, KIND_ALIGNMENT_BASELINE, "alignment")

        for item in prepared_sources:
            current = conn.execute(
                "SELECT title_zh, raw_text FROM chapters WHERE ebook_slug=? AND idx=?",
                (slug, item["index"]),
            ).fetchone()
            if current is None or (current["title_zh"] or "") != item["title"] or (current["raw_text"] or "") != item["text"]:
                raise RuntimeError(f"dataset source changed: chapter={item['index']}")
            source = conn.execute(
                "SELECT * FROM chapter_source_revisions WHERE ebook_slug=? AND chapter_index=? "
                "ORDER BY revision_number DESC, id DESC LIMIT 1", (slug, item["index"]),
            ).fetchone()
            if source is None:
                cur = conn.execute(
                    "INSERT INTO chapter_source_revisions (operation_id, ebook_slug, chapter_index, "
                    "revision_number, source_url, fetcher_kind, fetch_metadata_json, title, content_blob, "
                    "content_encoding, content_hash, base_content_hash) "
                    "VALUES (?, ?, ?, 1, ?, 'legacy_unknown', ?, ?, ?, ?, ?, '')",
                    (source_op, slug, item["index"], item["url"],
                     json.dumps({"backfilled": True}, ensure_ascii=False), item["title"],
                     item["blob"], ENCODING_ZLIB, item["hash"]),
                )
                source_id = int(cur.lastrowid)
                counts["source_revisions"] += 1
            else:
                source_id = int(source["id"])
                if source["content_hash"] != item["hash"]:
                    raise RuntimeError(f"source history đã tồn tại nhưng raw hiện hành lệch: chapter={item['index']}")

            cur = conn.execute(
                "UPDATE chapter_revisions SET source_revision_id=?, provenance_json=? "
                "WHERE ebook_slug=? AND chapter_index=? AND source_revision_id IS NULL",
                (source_id, json.dumps({"backfilled": True, "source_link": "same_chapter"}, ensure_ascii=False),
                 slug, item["index"]),
            )
            counts["translation_links"] += cur.rowcount

            if not conn.execute(
                "SELECT 1 FROM source_revision_segments WHERE source_revision_id=? LIMIT 1", (source_id,),
            ).fetchone():
                for ordinal, (start, end, text, content_hash) in enumerate(_segments(item["text"])):
                    segment = conn.execute(
                        "INSERT INTO chapter_segments (ebook_slug, chapter_index, stable_key, "
                        "created_from_source_revision_id) VALUES (?, ?, ?, ?)",
                        (slug, item["index"], uuid.uuid4().hex, source_id),
                    )
                    conn.execute(
                        "INSERT INTO source_revision_segments (source_revision_id, segment_id, ordinal, "
                        "char_start, char_end, content_text, content_hash, splitter, splitter_version) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)",
                        (source_id, int(segment.lastrowid), ordinal, start, end, text, content_hash, _SPLITTER),
                    )
                    counts["source_segments"] += 1

            revisions = conn.execute(
                "SELECT * FROM chapter_revisions WHERE ebook_slug=? AND chapter_index=? "
                "ORDER BY branch, revision_number", (slug, item["index"]),
            ).fetchall()
            source_segments = conn.execute(
                "SELECT srs.segment_id, srs.ordinal FROM source_revision_segments srs "
                "WHERE srs.source_revision_id=? ORDER BY srs.ordinal", (source_id,),
            ).fetchall()
            for revision in revisions:
                revision_id = int(revision["id"])
                if not conn.execute(
                    "SELECT 1 FROM translation_revision_segments WHERE translation_revision_id=? LIMIT 1",
                    (revision_id,),
                ).fetchone():
                    text = decompress_content(revision["content_blob"])
                    if full_content_hash(revision["title"], text) != revision["content_hash"]:
                        raise RuntimeError(f"translation revision hash lỗi: revision={revision_id}")
                    for ordinal, (start, end, segment_text, content_hash) in enumerate(_segments(text)):
                        conn.execute(
                            "INSERT INTO translation_revision_segments (translation_revision_id, ordinal, "
                            "char_start, char_end, content_text, content_hash, splitter, splitter_version) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                            (revision_id, ordinal, start, end, segment_text, content_hash, _SPLITTER),
                        )
                        counts["translation_segments"] += 1

                alignment = conn.execute(
                    "SELECT id FROM segment_alignments WHERE source_revision_id=? AND "
                    "translation_revision_id=? AND alignment_set='ordinal-v1'", (source_id, revision_id),
                ).fetchone()
                if alignment is None:
                    cur = conn.execute(
                        "INSERT INTO segment_alignments (source_revision_id, translation_revision_id, "
                        "alignment_set, method, confidence, status, operation_id, metadata_json) "
                        "VALUES (?, ?, 'ordinal-v1', 'ordinal_backfill', 0.25, 'proposed', ?, ?)",
                        (source_id, revision_id, alignment_op,
                         json.dumps({"training_eligible": False}, ensure_ascii=False)),
                    )
                    alignment_id = int(cur.lastrowid)
                    target_segments = conn.execute(
                        "SELECT id, ordinal FROM translation_revision_segments "
                        "WHERE translation_revision_id=? ORDER BY ordinal", (revision_id,),
                    ).fetchall()
                    max_len = max(len(source_segments), len(target_segments))
                    for group in range(max_len):
                        if group < len(source_segments):
                            conn.execute(
                                "INSERT INTO segment_alignment_members (alignment_id, group_ordinal, side, "
                                "source_segment_id, ordinal) VALUES (?, ?, 'source', ?, 0)",
                                (alignment_id, group, int(source_segments[group]["segment_id"])),
                            )
                        if group < len(target_segments):
                            conn.execute(
                                "INSERT INTO segment_alignment_members (alignment_id, group_ordinal, side, "
                                "translation_segment_id, ordinal) VALUES (?, ?, 'translation', ?, 0)",
                                (alignment_id, group, int(target_segments[group]["id"])),
                            )
                    counts["alignments"] += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return DatasetBackfillResult(**counts)
