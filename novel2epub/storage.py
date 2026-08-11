"""Lưu trữ & cache: manifest chương + nội dung raw/đã dịch — hậu thuẫn bởi
SQLite thống nhất (xem kế hoạch SQLite unification), không còn ghi file rời.

`Storage(data_dir, slug)` giữ signature cũ để ~30 call site không phải đổi:
`data_dir` giờ chỉ dùng để suy ra đường dẫn file `.db` thống nhất (sibling của
`data_dir`), không còn là thư mục chứa file `.md`/`.json` của ebook.
"""
from __future__ import annotations

import json
import re
import sqlite3
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .db import get_thread_connection, resolve_db_path
from . import entities, preview, revisions


def parse_glossary_line(line: str) -> tuple[str, str, str] | None:
    """Tách 1 dòng glossary `Hán = Việt | ghi chú` thành (source, target, note).

    - Phần `| ghi chú` là tùy chọn (tương thích ngược dòng cũ `Hán = Việt`).
    - Trả None nếu dòng rỗng, là comment (`#`) hoặc không có dấu `=`.
    """
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    source, rest = line.split("=", 1)
    source = source.strip()
    if "|" in rest:
        target, note = rest.split("|", 1)
        target, note = target.strip(), note.strip()
    else:
        target, note = rest.strip(), ""
    if not source or not target:
        return None
    return source, target, note


# Hàng chờ duyệt auto-glossary — schema replacement chuẩn, mỗi row:
#   {"source", "existing_target", "target", "chapter_index", "note"}
def normalize_glossary_pending(raw) -> list[dict]:
    """Normalize một snapshot hàng chờ `glossary_pending` về schema chuẩn.
    Bỏ row hỏng, trim mọi field, ép kiểu chapter_index. Row cũ (thiếu
    existing_target/note) vẫn qua được — existing_target rỗng nghĩa là mục
    chưa có trong glossary (thêm mới, không cần lan truyền)."""
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
        out.append(
            {
                "source": source,
                "existing_target": str(p.get("existing_target", "")).strip(),
                "target": target,
                "chapter_index": chapter_index,
                "note": str(p.get("note", "")).strip(),
            }
        )
    return out


# Các key trong meta_json chương được phép quét khi lan truyền thay đổi
# glossary (recursive) — những trường khác (complete, warnings, cost...) là
# trạng thái kỹ thuật, không phải nội dung dịch cần cập nhật.
_META_REPLACE_KEYS = frozenset({"ai_review", "ai_rewrite", "ai_suggestions", "glossary_conflicts"})
_EBOK_REPLACE_COLS = ("title", "description", "title_note", "series", "subjects_json")


def _replacement_matcher(pairs: list[tuple[str, str]]):
    """Dựng bộ thay thế literal ĐỒNG THỜI cho `pairs` (old→new).

    Một lượt quét (output không bị quét lại nên không cascade), ưu tiên old
    dài hơn (longest-first — mô hình `_apply_glossary` trong translator). Trả
    `(active_pairs, compiled_pattern)` hoặc None nếu không có cặp khả dụng."""
    active = [(old, new) for old, new in pairs if old and new and old != new]
    if not active:
        return None
    active.sort(key=lambda kv: len(kv[0]), reverse=True)
    pattern = re.compile("|".join(re.escape(old) for old, _new in active))
    return active, pattern


def _replace_in_node(node, repl: Callable[[str], tuple[str, int]]) -> tuple[Any, int]:
    """Áp `repl` lên MỌI chuỗi trong cấu trúc dict/list lồng nhau. `repl` trả
    (bản mới, số lần thay). Trả (bản mới của node, tổng số lần thay)."""
    if isinstance(node, str):
        return repl(node)
    if isinstance(node, dict):
        out: dict = {}
        total = 0
        for k, v in node.items():
            nv, n = _replace_in_node(v, repl)
            out[k] = nv
            total += n
        return out, total
    if isinstance(node, list):
        out_list: list = []
        total = 0
        for v in node:
            nv, n = _replace_in_node(v, repl)
            out_list.append(nv)
            total += n
        return out_list, total
    return node, 0


def _replace_in_meta(meta: dict, repl: Callable[[str], tuple[str, int]]) -> tuple[dict, int]:
    """Áp `repl` CHỈ vào các key allowlist trong meta chương (đệ quy)."""
    out = dict(meta)
    total = 0
    for key in _META_REPLACE_KEYS:
        if key in out:
            node, n = _replace_in_node(out[key], repl)
            out[key] = node
            total += n
    return out, total


@dataclass
class Chapter:
    index: int
    url: str
    title: str = ""
    title_zh: str = ""
    title_note: str = ""
    missing_fields: list[str] = field(default_factory=list)
    duplicate_of: int | None = None
    last_action_status: str = ""
    skipped: bool = False

    @property
    def stem(self) -> str:
        return f"{self.index:04d}"


@dataclass
class Manifest:
    slug: str
    source_url: str = ""
    title: str = ""
    author: str = ""
    description: str = ""
    cover_url: str = ""
    cover_file: str = ""
    title_note: str = ""
    metadata_missing: list[str] = field(default_factory=list)
    curated_fields: list[str] = field(default_factory=list)
    chapters: list[Chapter] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(
            {
                "slug": self.slug,
                "source_url": self.source_url,
                "title": self.title,
                "author": self.author,
                "description": self.description,
                "cover_url": self.cover_url,
                "cover_file": self.cover_file,
                "title_note": self.title_note,
                "metadata_missing": self.metadata_missing,
                "curated_fields": self.curated_fields,
                "chapters": [asdict(c) for c in self.chapters],
            },
            ensure_ascii=False,
            indent=2,
        )


class Storage:
    def __init__(self, data_dir: str | Path, slug: str):
        self.data_dir = Path(data_dir)
        self.slug = slug
        self._db_path = resolve_db_path(self.data_dir)

    @property
    def conn(self) -> sqlite3.Connection:
        """Kết nối SQLite của thread hiện tại — KHÔNG cache trên instance vì
        cùng 1 `Storage` có thể bị nhiều worker thread dùng chung (vd dịch
        song song nhiều chương, xem `pipeline._translate_chapters_parallel`)."""
        return get_thread_connection(self._db_path)

    # ----- bootstrap -----
    def ensure_dirs(self) -> None:
        """Tên cũ giữ để tương thích call site — nay đảm bảo có row `ebooks`."""
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO ebooks (slug) VALUES (?)", (self.slug,)
            )

    def exists(self) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM ebooks WHERE slug = ?", (self.slug,)
        ).fetchone()
        return row is not None

    def _ensure_chapter_row(self, ch: Chapter) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO chapters (ebook_slug, idx, url) VALUES (?, ?, ?)",
            (self.slug, ch.index, ch.url),
        )

    def _chapter_row(self, ch: Chapter) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT raw_text, translated_text, translated_mt_text, active_branch, "
            "title, title_zh, "
            "local_mt_text, local_mt_revision, local_mt_title, local_mt_title_zh, "
            "local_mt_mt_snapshot, meta_json, translated_updated_at "
            "FROM chapters WHERE ebook_slug=? AND idx=?",
            (self.slug, ch.index),
        ).fetchone()

    def translated_stats(self) -> tuple[int, float]:
        """`(số chương có bản dịch, mốc thời gian dịch mới nhất)` bằng MỘT query.

        Dùng cho quyết định "EPUB đã cũ chưa" ở `epub_autobuild` — gọi
        `has_translated` cho từng chương sẽ là 2907 round-trip DB trên MỖI
        request OPDS.

        Khác `has_translated` ở một điểm: không đọc `meta_json` nên chương
        đang dịch dở cũng được đếm. Chấp nhận được — kết quả chỉ dùng để
        quyết định CÓ build hay không, còn bản thân `step_build_selected`
        vẫn lọc bằng `has_translated` nên chương dở không lọt vào EPUB.
        """
        row = self.conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(MAX(translated_updated_at), 0.0) AS ts "
            "FROM chapters WHERE ebook_slug = ? AND ("
            " (active_branch = 'local_mt' AND local_mt_text IS NOT NULL AND local_mt_text != '') OR"
            " (COALESCE(active_branch, 'ai') = 'ai' AND translated_text IS NOT NULL AND translated_text != '')"
            ")",
            (self.slug,),
        ).fetchone()
        if row is None:
            return 0, 0.0
        return int(row["n"] or 0), float(row["ts"] or 0.0)

    def bulk_chapter_stats(self) -> dict[int, dict]:
        rows = self.conn.execute(
            "SELECT idx, active_branch,"
            " CASE WHEN raw_text IS NOT NULL AND raw_text != '' THEN 1 ELSE 0 END AS has_raw_int,"
            " CASE WHEN active_branch = 'local_mt'"
            " THEN CASE WHEN local_mt_text IS NOT NULL AND local_mt_text != '' THEN 1 ELSE 0 END"
            " ELSE CASE WHEN translated_text IS NOT NULL AND translated_text != '' THEN 1 ELSE 0 END"
            " END AS has_tr_int,"
            " CASE WHEN active_branch = 'local_mt' THEN LENGTH(local_mt_text)"
            " ELSE LENGTH(translated_text) END AS translated_len,"
            " LENGTH(raw_text) AS raw_len,"
            " meta_json"
            " FROM chapters WHERE ebook_slug = ?",
            (self.slug,),
        ).fetchall()
        result: dict[int, dict] = {}
        for row in rows:
            has_tr_raw = bool(row["has_tr_int"])
            if has_tr_raw:
                try:
                    meta = json.loads(row["meta_json"] or "{}")
                except Exception:
                    meta = {}
                branch = revisions.normalize_branch(row["active_branch"])
                has_translated = bool(meta.get(self._BRANCH_COMPLETE_META[branch], True))
            else:
                has_translated = False
            result[row["idx"]] = {
                "has_raw": bool(row["has_raw_int"]),
                "has_translated": has_translated,
                "translated_len": row["translated_len"] or 0,
                "raw_len": row["raw_len"] or 0,
                "meta_json": row["meta_json"],
            }
        return result

    # ----- manifest -----
    def load_manifest(self) -> Manifest | None:
        row = self.conn.execute(
            "SELECT * FROM ebooks WHERE slug = ?", (self.slug,)
        ).fetchone()
        if row is None:
            return None
        chapter_rows = self.conn.execute(
            "SELECT idx, url, title, title_zh, title_note, missing_fields_json, "
            "duplicate_of, last_action_status, skipped FROM chapters "
            "WHERE ebook_slug = ? ORDER BY idx",
            (self.slug,),
        ).fetchall()
        chapters = [
            Chapter(
                index=cr["idx"],
                url=cr["url"],
                title=cr["title"],
                title_zh=cr["title_zh"],
                title_note=cr["title_note"],
                missing_fields=json.loads(cr["missing_fields_json"] or "[]"),
                duplicate_of=cr["duplicate_of"],
                last_action_status=cr["last_action_status"],
                skipped=bool(cr["skipped"]),
            )
            for cr in chapter_rows
        ]
        return Manifest(
            slug=row["slug"],
            source_url=row["source_url"],
            title=row["title"],
            author=row["author"],
            description=row["description"],
            cover_url=row["cover_url"],
            cover_file=row["cover_file"],
            title_note=row["title_note"],
            metadata_missing=json.loads(row["metadata_missing_json"] or "[]"),
            curated_fields=json.loads(row["curated_fields_json"] or "[]"),
            chapters=chapters,
        )

    def get_chapter(self, index: int) -> Chapter | None:
        row = self.conn.execute(
            "SELECT idx, url, title, title_zh, title_note, missing_fields_json, "
            "duplicate_of, last_action_status, skipped "
            "FROM chapters WHERE ebook_slug = ? AND idx = ?",
            (self.slug, index),
        ).fetchone()
        if row is None:
            return None
        return Chapter(
            index=row["idx"],
            url=row["url"],
            title=row["title"],
            title_zh=row["title_zh"],
            title_note=row["title_note"],
            missing_fields=json.loads(row["missing_fields_json"] or "[]"),
            duplicate_of=row["duplicate_of"],
            last_action_status=row["last_action_status"],
            skipped=bool(row["skipped"]),
        )

    def save_manifest(self, manifest: Manifest) -> None:
        self.ensure_dirs()
        with self.conn:
            self.conn.execute(
                """
                UPDATE ebooks SET
                    source_url = ?, title = ?, author = ?, description = ?,
                    cover_url = ?, cover_file = ?, title_note = ?,
                    metadata_missing_json = ?, curated_fields_json = ?,
                    updated_at = datetime('now')
                WHERE slug = ?
                """,
                (
                    manifest.source_url, manifest.title, manifest.author,
                    manifest.description, manifest.cover_url, manifest.cover_file,
                    manifest.title_note,
                    json.dumps(manifest.metadata_missing, ensure_ascii=False),
                    json.dumps(manifest.curated_fields, ensure_ascii=False),
                    self.slug,
                ),
            )
            kept_idx = [ch.index for ch in manifest.chapters]
            for ch in manifest.chapters:
                self.conn.execute(
                    """
                    INSERT INTO chapters (ebook_slug, idx, url, title, title_zh, title_note,
                                           missing_fields_json, duplicate_of, last_action_status, skipped)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(ebook_slug, idx) DO UPDATE SET
                        url = excluded.url,
                        title = excluded.title,
                        title_zh = excluded.title_zh,
                        title_note = excluded.title_note,
                        missing_fields_json = excluded.missing_fields_json,
                        duplicate_of = excluded.duplicate_of,
                        last_action_status = excluded.last_action_status,
                        skipped = excluded.skipped
                    """,
                    (
                        self.slug, ch.index, ch.url, ch.title, ch.title_zh, ch.title_note,
                        json.dumps(ch.missing_fields, ensure_ascii=False), ch.duplicate_of,
                        ch.last_action_status, int(ch.skipped),
                    ),
                )
            if kept_idx:
                placeholders = ",".join("?" * len(kept_idx))
                self.conn.execute(
                    f"DELETE FROM chapters WHERE ebook_slug = ? AND idx NOT IN ({placeholders})",
                    (self.slug, *kept_idx),
                )
            else:
                self.conn.execute("DELETE FROM chapters WHERE ebook_slug = ?", (self.slug,))
            from .codes import backfill_codes
            backfill_codes(self.conn)

    def reorder_chapters(self, desired_order: list[int]) -> Manifest:
        """Đổi thứ tự chương nguyên tử, giữ toàn bộ nội dung gắn với chương.

        ``idx`` hiện vừa là vị trí vừa là khóa lưu trữ, vì vậy không được đổi
        index qua ``save_manifest``. Dùng namespace index âm trong cùng một
        transaction để tránh va chạm khóa khi hoán vị, đồng thời remap các bảng
        phụ đang tham chiếu index chương.
        """
        manifest = self.load_manifest()
        if manifest is None:
            raise ValueError("Chưa có manifest.")
        current = [chapter.index for chapter in manifest.chapters]
        if len(desired_order) != len(current):
            raise ValueError("Thứ tự mới phải chứa đủ toàn bộ chương.")
        if len(set(desired_order)) != len(desired_order):
            raise ValueError("Thứ tự mới chứa index bị trùng.")
        if set(desired_order) != set(current):
            missing = sorted(set(current) - set(desired_order))
            unknown = sorted(set(desired_order) - set(current))
            details = []
            if missing:
                details.append(f"thiếu {missing}")
            if unknown:
                details.append(f"không tồn tại {unknown}")
            raise ValueError("Thứ tự mới không hợp lệ: " + ", ".join(details) + ".")

        mapping = {old: new for new, old in enumerate(desired_order, 1)}
        if all(old == new for old, new in mapping.items()):
            return manifest

        dependent_columns = (
            ("ai_revisions", "idx"),
            ("preview_tokens", "idx"),
            ("chapter_revisions", "chapter_index"),
        )
        with self.conn:
            # Đưa mọi khóa sang số âm trước để các phép hoán vị không đè nhau.
            for old in current:
                self.conn.execute(
                    "UPDATE chapters SET idx = ? WHERE ebook_slug = ? AND idx = ?",
                    (-old, self.slug, old),
                )
            for table, column in dependent_columns:
                exists = self.conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone()
                if exists:
                    self.conn.execute(
                        f"UPDATE {table} SET {column} = -{column} WHERE ebook_slug = ?",
                        (self.slug,),
                    )
            self.conn.execute(
                "UPDATE chapters SET duplicate_of = -duplicate_of "
                "WHERE ebook_slug = ? AND duplicate_of IS NOT NULL",
                (self.slug,),
            )

            for old, new in mapping.items():
                self.conn.execute(
                    "UPDATE chapters SET idx = ? WHERE ebook_slug = ? AND idx = ?",
                    (new, self.slug, -old),
                )
                for table, column in dependent_columns:
                    exists = self.conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                    ).fetchone()
                    if exists:
                        self.conn.execute(
                            f"UPDATE {table} SET {column} = ? WHERE ebook_slug = ? AND {column} = ?",
                            (new, self.slug, -old),
                        )
                self.conn.execute(
                    "UPDATE chapters SET duplicate_of = ? "
                    "WHERE ebook_slug = ? AND duplicate_of = ?",
                    (new, self.slug, -old),
                )

            # Bản build cũ không còn khớp thứ tự mục lục.
            self.conn.execute(
                "UPDATE build_artifacts SET status='stale' WHERE ebook_slug = ?",
                (self.slug,),
            )

        result = self.load_manifest()
        if result is None:  # pragma: no cover - transaction đã giữ ebook tồn tại
            raise RuntimeError("Không thể nạp manifest sau khi sắp xếp.")
        return result

    def insert_chapter(self, ch: Chapter) -> None:
        with self.conn:
            ebook = self.conn.execute(
                "SELECT 1 FROM ebooks WHERE slug = ?", (self.slug,)
            ).fetchone()
            if ebook is None:
                raise ValueError("Chưa có manifest.")

            count = self.conn.execute(
                "SELECT COUNT(*) FROM chapters WHERE ebook_slug = ?", (self.slug,)
            ).fetchone()[0]
            if ch.index < 1 or ch.index > count + 1:
                raise ValueError(f"Vị trí phải từ 1 đến {count + 1}.")

            duplicate = self.conn.execute(
                "SELECT 1 FROM chapters WHERE ebook_slug = ? AND url = ?",
                (self.slug, ch.url),
            ).fetchone()
            if duplicate is not None:
                raise ValueError("URL nguồn đã tồn tại trong danh mục.")

            indexes = self.conn.execute(
                "SELECT idx FROM chapters WHERE ebook_slug = ? AND idx >= ? ORDER BY idx DESC",
                (self.slug, ch.index),
            ).fetchall()
            for row in indexes:
                self.conn.execute(
                    "UPDATE chapters SET idx = ? WHERE ebook_slug = ? AND idx = ?",
                    (row["idx"] + 1, self.slug, row["idx"]),
                )

            self.conn.execute(
                """
                INSERT INTO chapters (
                    ebook_slug, idx, url, title, title_zh, title_note,
                    missing_fields_json, duplicate_of, last_action_status, skipped
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.slug, ch.index, ch.url, ch.title, ch.title_zh, ch.title_note,
                    json.dumps(ch.missing_fields, ensure_ascii=False), ch.duplicate_of,
                    ch.last_action_status, int(ch.skipped),
                ),
            )
            from .codes import backfill_codes
            backfill_codes(self.conn)

    def save_chapter(self, ch: Chapter) -> None:
        """Lưu hoặc cập nhật thông tin chi tiết của 1 chương (metadata, status, skipped...)."""
        self.ensure_dirs()
        with self.conn:
            self._ensure_chapter_row(ch)
            self.conn.execute(
                """
                UPDATE chapters SET
                    url = ?,
                    title = ?,
                    title_zh = ?,
                    title_note = ?,
                    missing_fields_json = ?,
                    duplicate_of = ?,
                    last_action_status = ?,
                    skipped = ?
                WHERE ebook_slug = ? AND idx = ?
                """,
                (
                    ch.url, ch.title, ch.title_zh, ch.title_note,
                    json.dumps(ch.missing_fields, ensure_ascii=False), ch.duplicate_of,
                    ch.last_action_status, int(ch.skipped),
                    self.slug, ch.index
                ),
            )

    # ----- nội dung chương: raw -----
    def has_raw(self, ch: Chapter) -> bool:
        row = self._chapter_row(ch)
        return bool(row and row["raw_text"])

    def raw_len(self, ch: Chapter) -> int | None:
        """Số ký tự raw_text, hoặc None nếu CHƯA từng crawl (khác rỗng)."""
        row = self._chapter_row(ch)
        if row is None or row["raw_text"] is None:
            return None
        return len(row["raw_text"])

    def write_raw(self, ch: Chapter, content: str) -> None:
        self.ensure_dirs()
        with self.conn:
            self._ensure_chapter_row(ch)
            self.conn.execute(
                "UPDATE chapters SET raw_text = ? WHERE ebook_slug=? AND idx=?",
                (content, self.slug, ch.index),
            )

    def read_raw(self, ch: Chapter) -> str:
        row = self._chapter_row(ch)
        return row["raw_text"] if row and row["raw_text"] is not None else ""

    # ----- nội dung chương: translated (cột "Biên tập") -----
    def has_translated(self, ch: Chapter) -> bool:
        """Phân biệt bản dịch hoàn tất với bản dịch dở (job bị crash giữa
        chunk) — back-compat: meta rỗng/thiếu `complete` coi như hoàn tất."""
        row = self._chapter_row(ch)
        if row is None or not row["translated_text"]:
            return False
        try:
            meta = json.loads(row["meta_json"] or "{}")
        except json.JSONDecodeError:
            meta = {}
        return bool(meta.get("complete", True))

    def write_translated(self, ch: Chapter, content: str) -> None:
        self.ensure_dirs()
        with self.conn:
            self._ensure_chapter_row(ch)
            self.conn.execute(
                "UPDATE chapters SET translated_text = ?, translated_updated_at = unixepoch('now') "
                "WHERE ebook_slug=? AND idx=?",
                (content, self.slug, ch.index),
            )

    def read_translated(self, ch: Chapter) -> str:
        row = self._chapter_row(ch)
        return row["translated_text"] if row and row["translated_text"] is not None else ""

    def translated_updated_at(self, ch: Chapter) -> float:
        row = self._chapter_row(ch)
        return float(row["translated_updated_at"] or 0.0) if row else 0.0

    def has_any_translation_data(self, ch: Chapter) -> bool:
        """True nếu chương có BẤT KỲ dữ liệu dịch nào (translated, MT snapshot
        hoặc meta) — dùng khi xóa dịch hàng loạt, không quan tâm `complete`."""
        row = self._chapter_row(ch)
        if row is None:
            return False
        return bool(
            row["translated_text"]
            or row["translated_mt_text"]
            or (row["meta_json"] and row["meta_json"] != "{}")
        )

    # ----- nội dung chương: translated_mt (snapshot máy dịch, cột "VI") -----
    def has_translated_mt(self, ch: Chapter) -> bool:
        row = self._chapter_row(ch)
        return bool(row and row["translated_mt_text"])

    def write_translated_mt(self, ch: Chapter, content: str) -> None:
        """Ghi snapshot bản dịch máy (cột VI). Độc lập với `write_translated`
        (cột Biên tập sửa tay/AI)."""
        self.ensure_dirs()
        with self.conn:
            self._ensure_chapter_row(ch)
            self.conn.execute(
                "UPDATE chapters SET translated_mt_text = ? WHERE ebook_slug=? AND idx=?",
                (content, self.slug, ch.index),
            )

    def read_translated_mt(self, ch: Chapter) -> str:
        """Đọc snapshot bản dịch máy; fallback về `translated` (degrade an
        toàn) cho chương cũ dịch trước khi có snapshot."""
        row = self._chapter_row(ch)
        if row and row["translated_mt_text"]:
            return row["translated_mt_text"]
        return row["translated_text"] if row and row["translated_text"] else ""

    # ----- candidate revisions (hộp bản nháp AI) + optimistic lock -----
    def read_revision(self, ch: Chapter) -> int:
        """Số phiên bản `chapters.revision` — khoá optimistic cho `translated_text`."""
        row = self.conn.execute(
            "SELECT revision FROM chapters WHERE ebook_slug=? AND idx=?",
            (self.slug, ch.index),
        ).fetchone()
        return int(row["revision"]) if row and row["revision"] is not None else 0

    def create_ai_revision(self, cand: "revisions.RevisionCandidate") -> int:
        """Ghi một candidate (bản nháp AI) vào `ai_revisions`, trả id.

        Candidate luôn bắt đầu ở `status='pending'` (chưa kích hoạt)."""
        self.ensure_dirs()
        with self.conn:
            self._ensure_chapter_row(Chapter(index=cand.idx, url=""))
            cur = self.conn.execute(
                """
                INSERT INTO ai_revisions (
                    ebook_slug, idx, branch, engine, status, base_rev,
                    base_translated_text, payload_json, has_raw,
                    created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.slug, cand.idx, cand.branch, cand.engine, cand.status, cand.base_rev,
                    cand.base_translated_text, cand.payload, int(cand.has_raw),
                    cand.created_at, cand.expires_at,
                ),
            )
        return int(cur.lastrowid)

    def read_ai_revision(self, ch: Chapter, revision_id: int) -> "revisions.RevisionCandidate | None":
        row = self.conn.execute(
            "SELECT * FROM ai_revisions WHERE ebook_slug=? AND idx=? AND id=?",
            (self.slug, ch.index, revision_id),
        ).fetchone()
        return revisions.from_row(row) if row else None

    def list_ai_revisions(self, ch: Chapter, *, status: str | None = None) -> list[dict]:
        """Liệt kê bản nháp AI của chương (mới nhất trước), filter theo status."""
        sql = (
            "SELECT id, branch, engine, status, base_rev, base_translated_text, "
            "payload_json, has_raw, created_at, expires_at, applied_at "
            "FROM ai_revisions WHERE ebook_slug=? AND idx=?"
        )
        params: list = [self.slug, ch.index]
        if status:
            sql += " AND status=?"
            params.append(status)
        sql += " ORDER BY id DESC"
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def mark_ai_revision(self, ch: Chapter, revision_id: int, *, status: str) -> bool:
        """Đổi status một candidate; trả False nếu không có hàng để đổi."""
        with self.conn:
            cur = self.conn.execute(
                "UPDATE ai_revisions SET status=?, applied_at="
                "CASE WHEN ? = 'applied' THEN datetime('now') ELSE applied_at END "
                "WHERE ebook_slug=? AND idx=? AND id=?",
                (status, status, self.slug, ch.index, revision_id),
            )
        return cur.rowcount > 0

    def revision_chapter(self, revision_id: int) -> int:
        """Trả `idx` chương của một candidate; -1 nếu không tồn tại."""
        row = self.conn.execute(
            "SELECT idx FROM ai_revisions WHERE id=?", (revision_id,)
        ).fetchone()
        return int(row["idx"]) if row else -1

    def expire_stale_revisions(self, ch: Chapter) -> int:
        """Đánh dấu `expired` các candidate `pending` đã quá hạn (`expires_at`)."""
        with self.conn:
            cur = self.conn.execute(
                "UPDATE ai_revisions SET status='expired', applied_at=datetime('now') "
                "WHERE ebook_slug=? AND idx=? AND status='pending' "
                "AND expires_at != '' AND expires_at <= datetime('now')",
                (self.slug, ch.index),
            )
        return cur.rowcount

    def compare_and_swap_translation(
        self, ch: Chapter, *, expected_rev: int, new_text: str
    ) -> bool:
        """Ghi `translated_text` CÓ ĐIỀU KIỆN — optimistic lock trên `revision`.

        Chỉ ghi khi `chapters.revision == expected_rev`; nếu thành công thì tăng
        `revision` lên 1 (bản nháp ai khác sinh từ bản cũ sẽ bị từ chối). Trả
        False nếu revision đã đổi (bản dịch bị sửa xen giữa) — không ghi gì.
        """
        with self.conn:
            cur = self.conn.execute(
                "UPDATE chapters SET translated_text=?, translated_updated_at=unixepoch('now'), "
                "revision=revision+1 "
                "WHERE ebook_slug=? AND idx=? AND revision=?",
                (new_text, self.slug, ch.index, expected_rev),
            )
        return cur.rowcount == 1

    # ----- nhánh bản dịch (ai_translation vs local_mt) -----
    # Mỗi chương có 2 nhánh độc lập: `ai` (cột `translated_*`) và `local_mt`
    # (cột `local_mt_*`). Mỗi nhánh có title/workspace/revision/edit RIÊNG.
    # `active_branch` quyết định bản nào đi vào EPUB/Reader. So sánh dùng
    # compare-and-swap theo revision CỦA NHÁNH đó.
    _BRANCH_COLUMNS = {
        "ai": {
            "text": "translated_text",
            "revision": "revision",
            "title": "title",
            "title_zh": "title_zh",
            "mt": "translated_mt_text",
        },
        "local_mt": {
            "text": "local_mt_text",
            "revision": "local_mt_revision",
            "title": "local_mt_title",
            "title_zh": "local_mt_title_zh",
            "mt": "local_mt_mt_snapshot",
        },
    }
    # Key meta đánh dấu "đã dịch xong" cho từng nhánh (độc lập, không share).
    _BRANCH_COMPLETE_META = {"ai": "complete", "local_mt": "local_mt_complete"}

    def active_branch(self, ch: Chapter) -> str:
        row = self._chapter_row(ch)
        return revisions.normalize_branch(row["active_branch"] if row else None)

    def set_active_branch(self, ch: Chapter, branch: str) -> str:
        """Đổi nhánh đang hoạt động của chương (thứ đi vào EPUB/Reader)."""
        branch = revisions.normalize_branch(branch)
        self.ensure_dirs()
        with self.conn:
            self._ensure_chapter_row(ch)
            self.conn.execute(
                "UPDATE chapters SET active_branch=? WHERE ebook_slug=? AND idx=?",
                (branch, self.slug, ch.index),
            )
        return branch

    def read_active_branch_text(self, ch: Chapter) -> str:
        """Bản dịch của nhánh ĐANG HOẠT ĐỘNG (thứ đi vào EPUB/Reader)."""
        return self.read_branch_text(ch, self.active_branch(ch))

    def read_active_branch_title(self, ch: Chapter) -> str:
        """Tiêu đề của nhánh đang hoạt động, fallback về tiêu đề manifest."""
        return self.read_branch_title(ch, self.active_branch(ch)) or ch.title

    def has_active_branch_text(self, ch: Chapter) -> bool:
        """Nhánh đang hoạt động có bản dịch hoàn tất? (giống `has_translated`
        nhưng theo `active_branch` chứ không cứng theo nhánh AI.)"""
        branch = self.active_branch(ch)
        row = self._chapter_row(ch)
        if row is None:
            return False
        if not (row[self._BRANCH_COLUMNS[branch]["text"]] or ""):
            return False
        try:
            meta = json.loads(row["meta_json"] or "{}")
        except json.JSONDecodeError:
            meta = {}
        return bool(meta.get(self._BRANCH_COMPLETE_META[branch], True))

    def read_branch_text(self, ch: Chapter, branch: str) -> str:
        branch = revisions.normalize_branch(branch)
        row = self._chapter_row(ch)
        if row is None:
            return ""
        return row[self._BRANCH_COLUMNS[branch]["text"]] or ""

    def write_branch_text(self, ch: Chapter, branch: str, content: str) -> None:
        """Ghi bản dịch vào nhánh và TĂNG revision của nhánh đó."""
        branch = revisions.normalize_branch(branch)
        col = self._BRANCH_COLUMNS[branch]["text"]
        self.ensure_dirs()
        with self.conn:
            self._ensure_chapter_row(ch)
            self.conn.execute(
                f"UPDATE chapters SET {col}=?, translated_updated_at=unixepoch('now'), "
                f"{self._BRANCH_COLUMNS[branch]['revision']}={self._BRANCH_COLUMNS[branch]['revision']}+1 "
                "WHERE ebook_slug=? AND idx=?",
                (content, self.slug, ch.index),
            )

    def has_branch_text(self, ch: Chapter, branch: str) -> bool:
        """Nhánh `ai` tôn trọng `meta.complete` (job dịch dở không lọt vào);
        nhánh `local_mt` tôn trọng `meta.local_mt_complete`."""
        branch = revisions.normalize_branch(branch)
        row = self._chapter_row(ch)
        if row is None or not row[self._BRANCH_COLUMNS[branch]["text"]]:
            return False
        try:
            meta = json.loads(row["meta_json"] or "{}")
        except json.JSONDecodeError:
            meta = {}
        return bool(meta.get(self._BRANCH_COMPLETE_META[branch], True))

    def mark_branch_complete(self, ch: Chapter, branch: str, *, meta_extra: dict | None = None) -> None:
        """Đánh dấu nhánh đã dịch xong (key complete riêng cho từng nhánh)."""
        branch = revisions.normalize_branch(branch)
        meta = self.read_meta(ch) if self.has_meta(ch) else {}
        if meta_extra:
            meta.update(meta_extra)
        meta[self._BRANCH_COMPLETE_META[branch]] = True
        self.write_meta(ch, meta)

    def read_branch_revision(self, ch: Chapter, branch: str) -> int:
        branch = revisions.normalize_branch(branch)
        col = self._BRANCH_COLUMNS[branch]["revision"]
        row = self.conn.execute(
            f"SELECT {col} AS rev FROM chapters WHERE ebook_slug=? AND idx=?",
            (self.slug, ch.index),
        ).fetchone()
        return int(row["rev"]) if row and row["rev"] is not None else 0

    def compare_and_swap_branch(
        self, ch: Chapter, branch: str, *, expected_rev: int, new_text: str
    ) -> bool:
        """CAS trên revision CỦA NHÁNH — áp bản nháp chỉ khi nhánh còn khớp
        snapshot; nếu chương được sửa (ở nhánh nào) giữa chừng → từ chối."""
        branch = revisions.normalize_branch(branch)
        text_col = self._BRANCH_COLUMNS[branch]["text"]
        rev_col = self._BRANCH_COLUMNS[branch]["revision"]
        with self.conn:
            cur = self.conn.execute(
                f"UPDATE chapters SET {text_col}=?, translated_updated_at=unixepoch('now'), "
                f"{rev_col}={rev_col}+1 "
                f"WHERE ebook_slug=? AND idx=? AND {rev_col}=?",
                (new_text, self.slug, ch.index, expected_rev),
            )
        return cur.rowcount == 1

    def read_branch_title(self, ch: Chapter, branch: str) -> str:
        branch = revisions.normalize_branch(branch)
        row = self._chapter_row(ch)
        if row is None:
            return ""
        return row[self._BRANCH_COLUMNS[branch]["title"]] or ""

    def read_branch_title_zh(self, ch: Chapter, branch: str) -> str:
        branch = revisions.normalize_branch(branch)
        row = self._chapter_row(ch)
        if row is None:
            return ""
        return row[self._BRANCH_COLUMNS[branch]["title_zh"]] or ""

    def write_branch_titles(self, ch: Chapter, branch: str, title: str, title_zh: str = "") -> None:
        """Ghi tiêu đề của RIÊNG nhánh đó (title/title_zh độc lập mỗi nhánh)."""
        branch = revisions.normalize_branch(branch)
        title_col = self._BRANCH_COLUMNS[branch]["title"]
        zh_col = self._BRANCH_COLUMNS[branch]["title_zh"]
        self.ensure_dirs()
        with self.conn:
            self._ensure_chapter_row(ch)
            self.conn.execute(
                f"UPDATE chapters SET {title_col}=?, {zh_col}=? "
                "WHERE ebook_slug=? AND idx=?",
                (title, title_zh, self.slug, ch.index),
            )

    def read_branch_mt_snapshot(self, ch: Chapter, branch: str) -> str:
        branch = revisions.normalize_branch(branch)
        row = self._chapter_row(ch)
        if row is None:
            return ""
        return row[self._BRANCH_COLUMNS[branch]["mt"]] or ""

    def write_branch_mt_snapshot(self, ch: Chapter, branch: str, content: str) -> None:
        """Snapshot bản dịch máy của RIÊNG nhánh (cột "VI" cho editor 3 cột)."""
        branch = revisions.normalize_branch(branch)
        col = self._BRANCH_COLUMNS[branch]["mt"]
        self.ensure_dirs()
        with self.conn:
            self._ensure_chapter_row(ch)
            self.conn.execute(
                f"UPDATE chapters SET {col}=? WHERE ebook_slug=? AND idx=?",
                (content, self.slug, ch.index),
            )

    def branch_chapter_snapshots(self) -> dict[int, dict]:
        """Fingerprint nội dung đi vào build: {idx: {branch, revision, has_text,
        title, content_hash}} cho mọi chương có bản dịch ở nhánh ĐANG HOẠT ĐỘNG.
        Dùng để phát hiện build stale (bản dịch đổi sau khi build → snapshot
        lệch). `content_hash` = hash tiêu đề+nội dung bản dịch đúng thứ sẽ đi
        vào EPUB (`reader_sync.content_hash`)."""
        from .reader_sync import content_hash as _content_hash

        rows = self.conn.execute(
            "SELECT idx, active_branch, revision, local_mt_revision, "
            "translated_text, local_mt_text, title, local_mt_title "
            "FROM chapters WHERE ebook_slug=?",
            (self.slug,),
        ).fetchall()
        out: dict[int, dict] = {}
        for row in rows:
            branch = revisions.normalize_branch(row["active_branch"])
            if branch == "ai":
                text = row["translated_text"] or ""
                rev = row["revision"]
                title = row["title"] or ""
            else:
                text = row["local_mt_text"] or ""
                rev = row["local_mt_revision"]
                title = row["local_mt_title"] or ""
            out[int(row["idx"])] = {
                "branch": branch,
                "revision": int(rev or 0),
                "has_text": bool(text),
                "title": title,
                "content_hash": _content_hash(title, text) if text else "",
            }
        return out

    # ----- sửa/xóa KHỐI trong khung đối chiếu 3 cột -----
    # Khung đối chiếu chia theo KHỐI (cách bởi dòng trống), KHÁC `notes.split_paras`
    # theo TỪNG DÒNG — mọi thao tác ở đây map block → dòng gốc qua `blocks.py`.

    def write_raw_conditional(self, ch: Chapter, expected: str, new_text: str) -> bool:
        """Ghi `raw_text` CÓ ĐIỀU KIỆN — optimistic protection cho bản gốc vốn
        không có revision: chỉ ghi khi `raw_text` hiện tại khớp `expected`
        (normalize `\r\n` → `\n` để chống lệch sai do đổi newline). Trả False
        khi lệch (stale) — không ghi gì."""
        expected = (expected or "").replace("\r\n", "\n")
        self.ensure_dirs()
        with self.conn:
            self._ensure_chapter_row(ch)
            cur = self.conn.execute(
                "UPDATE chapters SET raw_text=? WHERE ebook_slug=? AND idx=? "
                "AND raw_text IS NOT NULL AND replace(raw_text, char(13)||char(10), char(10)) = ?",
                (new_text, self.slug, ch.index, expected),
            )
        return cur.rowcount == 1

    def delete_aligned_paragraph(
        self,
        ch: Chapter,
        *,
        branch: str,
        raw_expected: str,
        block_index: int,
        expected_rev: int,
    ) -> dict:
        """Xóa ĐỒNG BỘ đoạn `block_index` khỏi raw, snapshot MT và bản dịch
        hoạt động của nhánh — MỘT transaction.

        Đoạn đếm theo DÒNG không rỗng (`split_paragraphs`), trùng với chế độ
        Đọc. Semantics theo thiết kế: xóa đoạn gốc thì xóa luôn đoạn dịch máy
        và đoạn dịch hiện tại (cùng hàng trong khung đối chiếu). Chỉ đụng nhánh
        đang hoạt động; nhánh không active giữ nguyên. Có stale protection kép:
        `raw_expected` (nội dung raw đoạn) và `expected_rev` (revision nhánh).

        Trả `{"deleted": bool, "revision": int, "reason": str}` — `reason` rỗng
        khi thành công, khác rỗng khi stale/không hợp lệ (không ghi gì).
        """
        from . import blocks as _blocks

        branch = revisions.normalize_branch(branch)
        text_col = self._BRANCH_COLUMNS[branch]["text"]
        rev_col = self._BRANCH_COLUMNS[branch]["revision"]
        mt_col = self._BRANCH_COLUMNS[branch]["mt"]
        conn = self.conn
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT raw_text, translated_text, translated_mt_text, active_branch, "
                "local_mt_text, local_mt_mt_snapshot, local_mt_revision, revision "
                "FROM chapters WHERE ebook_slug=? AND idx=?",
                (self.slug, ch.index),
            ).fetchone()
            if row is None:
                conn.rollback()
                return {"deleted": False, "revision": expected_rev, "reason": "Chương không tồn tại."}

            raw = (row["raw_text"] or "").replace("\r\n", "\n")
            if not raw.strip():
                conn.rollback()
                return {"deleted": False, "revision": expected_rev, "reason": "Chương không có bản gốc."}

            paras = _blocks.split_paragraphs(raw)
            if not (0 <= block_index < len(paras)):
                conn.rollback()
                return {"deleted": False, "revision": expected_rev, "reason": "Đoạn đã thay đổi — tải lại trang."}
            if paras[block_index].strip() != (raw_expected or "").replace("\r\n", "\n").strip():
                conn.rollback()
                return {"deleted": False, "revision": expected_rev, "reason": "Bản gốc đã thay đổi — tải lại trang."}

            cur_rev = int(row[rev_col] or 0)
            if cur_rev != expected_rev:
                conn.rollback()
                return {"deleted": False, "revision": cur_rev, "reason": "Bản dịch đã thay đổi — tải lại trang."}

            new_raw, raw_reason = _blocks.delete_paragraph(raw, block_index, paras[block_index])
            if raw_reason:
                conn.rollback()
                return {"deleted": False, "revision": cur_rev, "reason": raw_reason}

            # Đối tác MT/translated: cùng index đoạn trong cột tương ứng (nếu có).
            mt_paras = _blocks.split_paragraphs(row[mt_col] or "")
            edited_paras = _blocks.split_paragraphs(row[text_col] or "")
            new_mt = row[mt_col]
            if 0 <= block_index < len(mt_paras):
                new_mt, _ = _blocks.delete_paragraph(row[mt_col] or "", block_index, mt_paras[block_index])
            new_edited = row[text_col]
            if 0 <= block_index < len(edited_paras):
                new_edited, _ = _blocks.delete_paragraph(row[text_col] or "", block_index, edited_paras[block_index])

            conn.execute(
                f"UPDATE chapters SET raw_text=?, {text_col}=?, {rev_col}={rev_col}+1, "
                f"{mt_col}=?, translated_updated_at=unixepoch('now') "
                "WHERE ebook_slug=? AND idx=?",
                (new_raw, new_edited, new_mt, self.slug, ch.index),
            )
            conn.commit()
            return {"deleted": True, "revision": expected_rev + 1, "reason": ""}
        except Exception:
            conn.rollback()
            raise

    def edit_block_text(
        self,
        ch: Chapter,
        *,
        branch: str,
        target: str,
        block_index: int,
        expected_text: str,
        new_text: str,
        expected_rev: int,
    ) -> dict:
        """Sửa KHỐI của đúng một cột trong khung đối chiếu.

        - `target="raw"`: sửa `raw_text` (không đụng MT/translated). Expected là
          nội dung raw khối (raw không revision).
        - `target="translated"`: sửa bản dịch của nhánh `branch`. Expected là
          revision nhánh (đúng CAS của `compare_and_swap_branch`).

        Trả `{"saved": bool, "revision": int, "reason": str}` — `reason` rỗng
        khi thành công, khác rỗng khi stale (không ghi gì)."""
        from . import blocks as _blocks

        branch = revisions.normalize_branch(branch)
        if target == "raw":
            # Raw không revision — dùng expected_text (nội dung khối) làm lock.
            new_raw, reason = _blocks.replace_block(
                self.read_raw(ch), block_index, expected_text, new_text
            )
            if reason:
                return {"saved": False, "revision": expected_rev, "reason": reason}
            ok = self.write_raw_conditional(ch, self.read_raw(ch), new_raw)
            if not ok:
                return {
                    "saved": False,
                    "revision": expected_rev,
                    "reason": "Bản gốc đã thay đổi — tải lại trang.",
                }
            return {"saved": True, "revision": expected_rev, "reason": ""}

        if target == "translated":
            current = self.read_branch_text(ch, branch)
            new_text_block, reason = _blocks.replace_block(
                current, block_index, expected_text, new_text
            )
            if reason:
                return {"saved": False, "revision": expected_rev, "reason": reason}
            if not self.compare_and_swap_branch(
                ch, branch, expected_rev=expected_rev, new_text=new_text_block
            ):
                return {
                    "saved": False,
                    "revision": self.read_branch_revision(ch, branch),
                    "reason": "Bản dịch đã thay đổi — tải lại trang.",
                }
            return {
                "saved": True,
                "revision": self.read_branch_revision(ch, branch),
                "reason": "",
            }

        return {"saved": False, "revision": expected_rev, "reason": f"target không hợp lệ: {target!r}"}

    # ----- từ điển entity (global + override theo ebook) -----
    def read_entity_entries(self) -> list[tuple[str, str, int]]:
        """Toàn bộ entity global → list `(source, target, protect)` theo source."""
        rows = self.conn.execute(
            "SELECT source, target, protect FROM entity_dictionary ORDER BY source COLLATE NOCASE"
        ).fetchall()
        return [(r["source"], r["target"], int(r["protect"])) for r in rows]

    def count_entities(self, query: str = "") -> int:
        query = (query or "").strip()
        if query:
            like = f"%{query}%"
            row = self.conn.execute(
                "SELECT COUNT(*) AS c FROM entity_dictionary "
                "WHERE source LIKE ? OR target LIKE ?",
                (like, like),
            ).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) AS c FROM entity_dictionary").fetchone()
        return int(row["c"])

    _ENTITY_SORT_COLS = {"source": "source", "target": "target"}

    def read_entities_page(
        self,
        offset: int,
        limit: int,
        query: str = "",
        sort_field: str | None = None,
        sort_dir: str = "asc",
    ) -> list[tuple[str, str, int]]:
        col = self._ENTITY_SORT_COLS.get(sort_field or "", "") or "source"
        direction = "DESC" if str(sort_dir).lower() == "desc" else "ASC"
        order = f"{col} COLLATE NOCASE {direction}"
        where = "1=1"
        params: list = []
        query = (query or "").strip()
        if query:
            like = f"%{query}%"
            where += " AND (source LIKE ? OR target LIKE ?)"
            params += [like, like]
        params += [int(limit), int(offset)]
        rows = self.conn.execute(
            f"SELECT source, target, protect FROM entity_dictionary WHERE {where} "
            f"ORDER BY {order} LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [(r["source"], r["target"], int(r["protect"])) for r in rows]

    def upsert_entity(self, source: str, target: str, protect: int = 0) -> bool:
        source = (source or "").strip()
        target = (target or "").strip()
        protect = 1 if protect else 0
        if not source or not target:
            return False
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO entity_dictionary (source, target, protect)
                VALUES (?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    target = excluded.target, protect = excluded.protect,
                    updated_at = datetime('now')
                """,
                (source, target, protect),
            )
        return True

    def delete_entity(self, source: str) -> bool:
        source = (source or "").strip()
        if not source:
            return False
        with self.conn:
            cur = self.conn.execute("DELETE FROM entity_dictionary WHERE source=?", (source,))
        return cur.rowcount > 0

    def write_entity_entries(self, entries: list[tuple[str, str, int]]) -> None:
        seen: dict[str, tuple[str, int]] = {}
        order: list[str] = []
        for entry in entries:
            source = (entry[0] or "").strip()
            target = (entry[1] or "").strip()
            protect = 1 if (len(entry) > 2 and entry[2]) else 0
            if not source or not target:
                continue
            if source not in seen:
                order.append(source)
            seen[source] = (target, protect)
        with self.conn:
            self.conn.execute("DELETE FROM entity_dictionary")
            for source in order:
                target, protect = seen[source]
                self.conn.execute(
                    "INSERT INTO entity_dictionary (source, target, protect) VALUES (?, ?, ?)",
                    (source, target, protect),
                )

    def seed_entities_if_empty(self, entries: list[tuple[str, str, int]]) -> int:
        if self.count_entities() > 0:
            return 0
        self.write_entity_entries(entries)
        return self.count_entities()

    def export_entities(self) -> list[dict]:
        """Xuất toàn bộ entity global dạng list[{source,target,protect}]."""
        return [
            {"source": s, "target": t, "protect": bool(p)}
            for s, t, p in self.read_entity_entries()
        ]

    def import_entities(self, rows: list[dict], *, merge: bool = False) -> dict:
        """Import entity global từ list[{source,target,protect?}].

        `merge=True`: upsert từng mục (giữ mục hiện có không có trong import).
        `merge=False` (mặc định): thay thế toàn bộ bảng.
        Trả {imported, skipped, total}.
        """
        imported = skipped = 0
        if merge:
            for row in rows:
                source = (row.get("source") or "").strip()
                target = (row.get("target") or "").strip()
                if source and target:
                    self.upsert_entity(source, target, int(bool(row.get("protect", False))))
                    imported += 1
                else:
                    skipped += 1
        else:
            clean = []
            for row in rows:
                source = (row.get("source") or "").strip()
                target = (row.get("target") or "").strip()
                if source and target:
                    clean.append((source, target, int(bool(row.get("protect", False)))))
                    imported += 1
                else:
                    skipped += 1
            self.write_entity_entries(clean)
        return {"imported": imported, "skipped": skipped, "total": self.count_entities()}

    # ----- override entity theo ebook (thắng mục global cùng source) -----
    def read_entity_overrides(self) -> list[tuple[str, str, int]]:
        rows = self.conn.execute(
            "SELECT source, target, protect FROM ebook_entity_overrides "
            "WHERE ebook_slug=? ORDER BY source COLLATE NOCASE",
            (self.slug,),
        ).fetchall()
        return [(r["source"], r["target"], int(r["protect"])) for r in rows]

    def count_entity_overrides(self, query: str = "") -> int:
        query = (query or "").strip()
        if query:
            like = f"%{query}%"
            row = self.conn.execute(
                "SELECT COUNT(*) AS c FROM ebook_entity_overrides "
                "WHERE ebook_slug=? AND (source LIKE ? OR target LIKE ?)",
                (self.slug, like, like),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) AS c FROM ebook_entity_overrides WHERE ebook_slug=?",
                (self.slug,),
            ).fetchone()
        return int(row["c"])

    def read_entity_overrides_page(
        self,
        offset: int,
        limit: int,
        query: str = "",
        sort_field: str | None = None,
        sort_dir: str = "asc",
    ) -> list[tuple[str, str, int]]:
        col = self._ENTITY_SORT_COLS.get(sort_field or "", "") or "source"
        direction = "DESC" if str(sort_dir).lower() == "desc" else "ASC"
        order = f"{col} COLLATE NOCASE {direction}"
        where = "ebook_slug=?"
        params: list = [self.slug]
        query = (query or "").strip()
        if query:
            like = f"%{query}%"
            where += " AND (source LIKE ? OR target LIKE ?)"
            params += [like, like]
        params += [int(limit), int(offset)]
        rows = self.conn.execute(
            f"SELECT source, target, protect FROM ebook_entity_overrides WHERE {where} "
            f"ORDER BY {order} LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [(r["source"], r["target"], int(r["protect"])) for r in rows]

    def upsert_entity_override(self, source: str, target: str, protect: int = 0) -> bool:
        source = (source or "").strip()
        target = (target or "").strip()
        protect = 1 if protect else 0
        if not source or not target:
            return False
        self.ensure_dirs()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO ebook_entity_overrides (ebook_slug, source, target, protect)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(ebook_slug, source) DO UPDATE SET
                    target = excluded.target, protect = excluded.protect,
                    updated_at = datetime('now')
                """,
                (self.slug, source, target, protect),
            )
        return True

    def delete_entity_override(self, source: str) -> bool:
        source = (source or "").strip()
        if not source:
            return False
        with self.conn:
            cur = self.conn.execute(
                "DELETE FROM ebook_entity_overrides WHERE ebook_slug=? AND source=?",
                (self.slug, source),
            )
        return cur.rowcount > 0

    def read_merged_entities(self) -> list["entities.Entity"]:
        """Entity hợp nhất (override ebook thắng mục global cùng `source`)."""
        return entities.merge_entries(self.read_entity_entries(), self.read_entity_overrides())

    def export_entity_overrides(self) -> list[dict]:
        """Xuất toàn bộ override entity của ebook dạng list[{source,target,protect}]."""
        return [
            {"source": s, "target": t, "protect": bool(p)}
            for s, t, p in self.read_entity_overrides()
        ]

    def import_entity_overrides(self, rows: list[dict], *, merge: bool = False) -> dict:
        """Import override entity cho ebook từ list[{source,target,protect?}].

        `merge=True`: upsert từng mục.  `merge=False`: xóa toàn bộ override cũ rồi insert.
        Trả {imported, skipped, total}.
        """
        imported = skipped = 0
        if not merge:
            with self.conn:
                self.conn.execute(
                    "DELETE FROM ebook_entity_overrides WHERE ebook_slug=?", (self.slug,)
                )
        for row in rows:
            source = (row.get("source") or "").strip()
            target = (row.get("target") or "").strip()
            if source and target:
                self.upsert_entity_override(source, target, int(bool(row.get("protect", False))))
                imported += 1
            else:
                skipped += 1
        return {"imported": imported, "skipped": skipped, "total": self.count_entity_overrides()}

    # ----- preview token chính xác (duyệt bản nháp) -----
    def issue_preview_token(
        self, ch: Chapter, *, branch: str, revision_id: int,
        ttl_seconds: int = preview.DEFAULT_TOKEN_TTL_SECONDS,
    ) -> str:
        """Cấp token duyệt bản nháp — snapshot `base_rev`/`base_text` là trạng
        thái HIỆN TẠI của nhánh. Token một lần, có hạn."""
        import secrets as _secrets
        branch = revisions.normalize_branch(branch)
        token = _secrets.token_urlsafe(32)
        base_rev = self.read_branch_revision(ch, branch)
        base_text = self.read_branch_text(ch, branch)
        from .revisions import _expires_at
        self.ensure_dirs()
        with self.conn:
            self._ensure_chapter_row(ch)
            self.conn.execute(
                """
                INSERT INTO preview_tokens (
                    token, ebook_slug, idx, branch, revision_id, base_rev,
                    base_text, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (token, self.slug, ch.index, branch, revision_id, base_rev,
                 base_text, _expires_at(ttl_seconds)),
            )
        return token

    def read_preview_token(self, token: str) -> "preview.PreviewToken | None":
        row = self.conn.execute(
            "SELECT * FROM preview_tokens WHERE token=?", (token,)
        ).fetchone()
        if row is None:
            return None
        return preview.PreviewToken(
            token=row["token"], idx=row["idx"], branch=revisions.normalize_branch(row["branch"]),
            revision_id=row["revision_id"], base_rev=row["base_rev"], base_text=row["base_text"],
            expires_at=row["expires_at"], consumed=bool(row["consumed"]), created_at=row["created_at"],
        )

    def validate_preview_token(self, token: str, *, branch: str, revision_id: int) -> str | None:
        """Trả None nếu token còn dùng được, hoặc lý do từ chối (hết hạn / đã
        dùng / snapshot lệch khỏi bản dịch hiện tại của nhánh)."""
        tok = self.read_preview_token(token)
        if tok is None:
            return "Token không hợp lệ."
        if revisions.normalize_branch(tok.branch) != revisions.normalize_branch(branch):
            return "Token không thuộc nhánh này."
        if tok.revision_id != revision_id:
            return "Token không khớp bản nháp đang duyệt."
        ch = Chapter(index=tok.idx, url="")
        return preview.validate_token(
            tok,
            current_rev=self.read_branch_revision(ch, tok.branch),
            current_text=self.read_branch_text(ch, tok.branch),
        )

    def consume_preview_token(self, token: str, *, branch: str, revision_id: int) -> None:
        """Xác thực rồi đánh dấu token đã dùng (atomic với việc áp bản nháp)."""
        reason = self.validate_preview_token(token, branch=branch, revision_id=revision_id)
        if reason:
            raise preview.PreviewTokenError(reason)
        with self.conn:
            cur = self.conn.execute(
                "UPDATE preview_tokens SET consumed=1 WHERE token=? AND consumed=0", (token,)
            )
        if cur.rowcount != 1:
            raise preview.PreviewTokenError("Token đã được dùng.")

    def invalidate_preview_tokens(self, ch: Chapter, branch: str) -> int:
        """Vô hiệu hoá token CHƯA DÙNG của chương+nhánh (bản dịch đổi → token
        cũ hết hiệu lực ngay, không cần chờ hết hạn). Trả số token đã xoá."""
        branch = revisions.normalize_branch(branch)
        with self.conn:
            cur = self.conn.execute(
                "DELETE FROM preview_tokens WHERE ebook_slug=? AND idx=? AND branch=? AND consumed=0",
                (self.slug, ch.index, branch),
            )
        return cur.rowcount

    # ----- token bulk-preview / bulk-confirm (hợp đồng hành động hàng loạt) -----
    def issue_bulk_token(
        self,
        *,
        action: str,
        options: dict,
        config_hash: str,
        chapters: list[dict],
        eligibility: dict,
        estimates: dict,
        ttl_seconds: int = 1800,
    ) -> str:
        """Cấp token dùng MỘT lần cho một bản preview hành động hàng loạt.
        Token chứa snapshot đánh giá + vân tay config; hết hạn sau `ttl`."""
        token = uuid.uuid4().hex
        with self.conn:
            self.conn.execute(
                "INSERT INTO bulk_tokens (token, ebook_slug, action, options_json, "
                "config_hash, chapters_json, eligibility_json, estimates_json, "
                "expires_at, consumed) VALUES (?,?,?,?,?,?,?,?,?,0)",
                (
                    token,
                    self.slug,
                    action,
                    json.dumps(options, ensure_ascii=False, sort_keys=True),
                    config_hash,
                    json.dumps(chapters, ensure_ascii=False, sort_keys=True),
                    json.dumps(eligibility, ensure_ascii=False, sort_keys=True),
                    json.dumps(estimates, ensure_ascii=False, sort_keys=True),
                    str(time.time() + ttl_seconds),
                ),
            )
        return token

    def read_bulk_token(self, token: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM bulk_tokens WHERE token=?", (token,)
        ).fetchone()

    def validate_bulk_token(self, token: str, *, config_hash: str) -> tuple[bool, str, dict]:
        """Kiểm tra token còn dùng được với `config_hash` hiện tại. Trả
        `(ok, reason, options)` — options rỗng nếu không ok."""
        tok = self.read_bulk_token(token)
        if tok is None:
            return False, "Token không hợp lệ hoặc không tồn tại.", {}
        if tok["consumed"]:
            return False, "Token đã được dùng — hãy preview lại.", {}
        try:
            if float(tok["expires_at"]) < time.time():
                return False, "Token đã hết hạn — hãy preview lại.", {}
        except (TypeError, ValueError):
            return False, "Token hết hạn — hãy preview lại.", {}
        if tok["ebook_slug"] != self.slug:
            return False, "Token không thuộc ebook này.", {}
        if config_hash and tok["config_hash"] and config_hash != tok["config_hash"]:
            return False, "Cấu hình đã thay đổi — hãy preview lại.", {}
        try:
            options = json.loads(tok["options_json"] or "{}")
        except json.JSONDecodeError:
            options = {}
        return True, "", options

    def consume_bulk_token(self, token: str) -> None:
        """Đánh dấu token đã dùng (one-use)."""
        with self.conn:
            cur = self.conn.execute(
                "UPDATE bulk_tokens SET consumed=1 WHERE token=? AND consumed=0", (token,)
            )
        if cur.rowcount != 1:
            raise RuntimeError("Token đã được dùng.")

    def chapters_from_bulk_token(self, token: str) -> list[dict]:
        row = self.read_bulk_token(token)
        if row is None:
            return []
        try:
            return json.loads(row["chapters_json"] or "[]")
        except json.JSONDecodeError:
            return []

    def invalidate_bulk_tokens(self, *, action: str = "") -> int:
        """Xoá token bulk CHƯA DÙNG của ebook (config/dữ liệu đổi → token cũ
        hết hiệu lực). Lọc theo action nếu có; trả số token đã xoá."""
        if action:
            with self.conn:
                cur = self.conn.execute(
                    "DELETE FROM bulk_tokens WHERE ebook_slug=? AND consumed=0 AND action=?",
                    (self.slug, action),
                )
        else:
            with self.conn:
                cur = self.conn.execute(
                    "DELETE FROM bulk_tokens WHERE ebook_slug=? AND consumed=0",
                    (self.slug,),
                )
        return cur.rowcount

    # ----- trạng thái build artifact + blocker -----
    def read_build(self) -> dict:
        row = self.conn.execute(
            "SELECT * FROM build_artifacts WHERE ebook_slug=?", (self.slug,)
        ).fetchone()
        if row is None:
            return {
                "lock_owner": "", "started_at": "", "finished_at": "",
                "status": "none", "error": "", "manifest_snapshot": "[]",
            }
        return dict(row)

    def acquire_build(self, owner: str, *, manifest_snapshot: list) -> bool:
        """Giành quyền build (blocker). Chỉ thành công khi chưa có ai đang build
        (status none/done/failed/stale → building). Trả False nếu đang bận."""
        snapshot = json.dumps(manifest_snapshot, ensure_ascii=False)
        self.ensure_dirs()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO build_artifacts (ebook_slug, lock_owner, started_at, status, "
                "finished_at, manifest_snapshot) VALUES (?, ?, datetime('now'), 'building', '', ?) "
                "ON CONFLICT(ebook_slug) DO UPDATE SET "
                "lock_owner = excluded.lock_owner, started_at = datetime('now'), "
                "status = 'building', finished_at = '', manifest_snapshot = excluded.manifest_snapshot "
                "WHERE build_artifacts.status NOT IN ('building')",
                (self.slug, owner, snapshot),
            )
        return cur.rowcount == 1

    def release_build(self, *, status: str, error: str = "", manifest_snapshot: list | None = None) -> None:
        """Trả quyền build sau khi xong (status 'done'/'failed'), lưu fingerprint."""
        snapshot = json.dumps(manifest_snapshot, ensure_ascii=False) if manifest_snapshot is not None else None
        with self.conn:
            if snapshot is not None:
                self.conn.execute(
                    "UPDATE build_artifacts SET status=?, error=?, finished_at=datetime('now'), "
                    "lock_owner='', manifest_snapshot=? WHERE ebook_slug=?",
                    (status, error, snapshot, self.slug),
                )
            else:
                self.conn.execute(
                    "UPDATE build_artifacts SET status=?, error=?, finished_at=datetime('now'), "
                    "lock_owner='' WHERE ebook_slug=?",
                    (status, error, self.slug),
                )

    def build_stale(self) -> bool:
        """True nếu bản dịch của nhánh đang hoạt động đã đổi khỏi fingerprint
        lúc build (EPUB cũ so với workspace hiện tại). So trên tập key chung
        `{branch, revision, content_hash}` để chấp nhận snapshot cũ (chưa có
        title/content_hash) mà không phát âm thầm thành stale."""
        _STALE_KEYS = ("branch", "revision", "content_hash")

        def _subset(mapping: dict) -> dict:
            return {k: v for k, v in mapping.items() if k in _STALE_KEYS}

        build = self.read_build()
        if build["status"] == "building" or not build["finished_at"]:
            return False
        try:
            stored = json.loads(build["manifest_snapshot"] or "[]")
        except json.JSONDecodeError:
            stored = []
        if isinstance(stored, list):
            stored = {
                int(item["idx"]): _subset(item)
                for item in stored if isinstance(item, dict) and "idx" in item
            }
        current = {int(k): _subset(v) for k, v in self.branch_chapter_snapshots().items()}
        return json.dumps(current, sort_keys=True) != json.dumps(
            {int(k): v for k, v in stored.items()}, sort_keys=True
        )

    def build_blockers(self, chapters: list[Chapter]) -> list[dict]:
        """Chương nào trong danh sách (non-skipped) THIẾU bản dịch ở nhánh đang
        hoạt động — build strict phải chặn (không rơi về raw). Trả
        `[{index, title, branch, reason}]`."""
        blockers: list[dict] = []
        for ch in chapters:
            if ch.skipped:
                continue
            branch = self.active_branch(ch)
            if not self.has_branch_text(ch, branch):
                blockers.append({
                    "index": ch.index,
                    "title": ch.title or f"Chương {ch.index}",
                    "branch": branch,
                    "reason": f"Nhánh '{revisions.branch_label(branch)}' chưa có bản dịch.",
                })
        return blockers

    # ----- legacy migration: meta['ai_rewrite'] cũ (v10 trở về trước) -----
    def migrate_legacy_ai_rewrite(self, ch: Chapter) -> int:
        """Nâng bản nháp cũ nhét trong `meta['ai_rewrite']` (chưa có
        `revision_id`) thành candidate trong `ai_revisions` — KHÔNG xoá dữ liệu
        gốc, chỉ ghi `revision_id` vào meta. Idempotent; trả 0 nếu không có gì
        để nâng (đã migrate hoặc không phải draft rewrite)."""
        meta = self.read_meta(ch) if self.has_meta(ch) else {}
        draft = meta.get("ai_rewrite")
        if not isinstance(draft, dict) or not (draft.get("text") or "").strip():
            return 0
        if draft.get("revision_id"):
            return int(draft["revision_id"])
        current = self.read_translated(ch)
        if not current.strip():
            return 0
        cand = revisions.create_revision(
            engine="rewrite",
            idx=ch.index,
            payload=draft["text"],
            base_translated_text=current,
            base_rev=self.read_revision(ch),
            has_raw=False,
        )
        revision_id = self.create_ai_revision(cand)
        draft["revision_id"] = revision_id
        meta["ai_rewrite"] = draft
        self.write_meta(ch, meta)
        return revision_id

    def migrate_legacy_local_mt(self, ch: Chapter) -> bool:
        """Fill nhánh `local_mt` từ dữ liệu legacy của nhánh AI — CHỈ khi nhánh
        local_mt còn rỗng (an toàn, không đè dữ liệu mới đã dịch). Nguồn:
        `translated_mt_text` (snapshot bản dịch máy) làm `local_mt_mt_snapshot`,
        `translated_text` làm `local_mt_text`, title/title_zh theo. Đánh dấu
        `local_mt_complete=True` để nhánh mới dùng được ngay. Idempotent."""
        row = self._chapter_row(ch)
        if row is None or (row["local_mt_text"] or "").strip():
            return False
        if not (row["translated_text"] or "").strip():
            return False
        with self.conn:
            self._ensure_chapter_row(ch)
            self.conn.execute(
                "UPDATE chapters SET local_mt_text=?, local_mt_mt_snapshot=?, "
                "local_mt_title=?, local_mt_title_zh=?, local_mt_revision=1 "
                "WHERE ebook_slug=? AND idx=?",
                (
                    row["translated_text"],
                    row["translated_mt_text"] or row["translated_text"],
                    row["title"] or "",
                    row["title_zh"] or "",
                    self.slug,
                    ch.index,
                ),
            )
        meta = self.read_meta(ch) if self.has_meta(ch) else {}
        meta["local_mt_complete"] = True
        self.write_meta(ch, meta)
        return True

    def legacy_ai_rewrite_report(self) -> dict:
        """Báo cáo bản nháp legacy: {chapters, legacy, migrated, remaining}."""
        manifest = self.load_manifest()
        if manifest is None:
            return {"chapters": 0, "legacy": 0, "migrated": 0, "remaining": 0}
        legacy = migrated = remaining = 0
        for ch in manifest.chapters:
            if not self.has_meta(ch):
                continue
            draft = self.read_meta(ch).get("ai_rewrite")
            if not isinstance(draft, dict) or not (draft.get("text") or "").strip():
                continue
            legacy += 1
            if draft.get("revision_id"):
                migrated += 1
            else:
                remaining += 1
        return {
            "chapters": len(manifest.chapters),
            "legacy": legacy,
            "migrated": migrated,
            "remaining": remaining,
        }

    # ----- meta dịch (complete flag, warnings, cost...) -----
    def has_meta(self, ch: Chapter) -> bool:
        row = self._chapter_row(ch)
        return bool(row and row["meta_json"] and row["meta_json"] != "{}")

    def read_meta(self, ch: Chapter) -> dict:
        row = self._chapter_row(ch)
        if not row or not row["meta_json"]:
            return {}
        try:
            return json.loads(row["meta_json"])
        except json.JSONDecodeError:
            return {}

    def write_meta(self, ch: Chapter, meta: dict) -> None:
        self.ensure_dirs()
        with self.conn:
            self._ensure_chapter_row(ch)
            self.conn.execute(
                "UPDATE chapters SET meta_json = ? WHERE ebook_slug=? AND idx=?",
                (json.dumps(meta, ensure_ascii=False), self.slug, ch.index),
            )

    def mark_translated_complete(self, ch: Chapter, *, meta_extra: dict | None = None) -> None:
        """Đánh dấu chương đã dịch xong (set `complete: true` trong meta).

        Đọc meta hiện tại (nếu có) để không phá các key đã có (warnings,
        generated_at, ...), merge thêm `meta_extra` (vd. length_raw) rồi
        set `complete=True` và ghi lại. Pipeline gọi đúng một lần ở cuối
        `_translate_one` (xem `translate-chunk-streaming` spec).
        """
        meta = self.read_meta(ch) if self.has_meta(ch) else {}
        if meta_extra:
            meta.update(meta_extra)
        meta["complete"] = True
        self.write_meta(ch, meta)

    def append_translated_chunk(
        self, ch: Chapter, chunk_text: str, *, is_first: bool
    ) -> None:
        """Ghi 1 chunk của bản dịch: chunk đầu tạo, các chunk sau nối thêm.

        Chèn `\n` ngăn cách giữa 2 chunk để tránh dính ký tự cuối chunk
        trước với đầu chunk sau khi `_split_into_chunks` cắt ở ranh giới
        đoạn văn (xem `translate-chunk-streaming` spec).
        """
        self.ensure_dirs()
        with self.conn:
            self._ensure_chapter_row(ch)
            if is_first:
                self.conn.execute(
                    "UPDATE chapters SET translated_text = ?, translated_updated_at = unixepoch('now') "
                    "WHERE ebook_slug=? AND idx=?",
                    (chunk_text, self.slug, ch.index),
                )
            else:
                self.conn.execute(
                    "UPDATE chapters SET translated_text = COALESCE(translated_text, '') || ? || ?, "
                    "translated_updated_at = unixepoch('now') WHERE ebook_slug=? AND idx=?",
                    ("\n", chunk_text, self.slug, ch.index),
                )

    def delete_translated(self, ch: Chapter) -> None:
        """Xóa toàn bộ dữ liệu bản dịch: translated, translated_mt, local_mt,
        meta và reset active_branch về 'ai'."""
        with self.conn:
            self.conn.execute(
                "UPDATE chapters SET translated_text=NULL, translated_mt_text=NULL, "
                "local_mt_text=NULL, local_mt_mt_snapshot=NULL, "
                "local_mt_title='', local_mt_title_zh='', "
                "active_branch='ai', meta_json='{}', translated_updated_at=NULL "
                "WHERE ebook_slug=? AND idx=?",
                (self.slug, ch.index),
            )

    def append_branch_chunk(self, ch: Chapter, branch: str, chunk_text: str, *, is_first: bool) -> None:
        """Ghi 1 chunk của bản dịch vào NHÁNH chỉ định (chunk đầu tạo, các chunk
        sau nối thêm với `\n` ngăn cách). Stream cho `_translate_one`."""
        branch = revisions.normalize_branch(branch)
        col = self._BRANCH_COLUMNS[branch]["text"]
        self.ensure_dirs()
        with self.conn:
            self._ensure_chapter_row(ch)
            if is_first:
                self.conn.execute(
                    f"UPDATE chapters SET {col} = ?, translated_updated_at = unixepoch('now') "
                    "WHERE ebook_slug=? AND idx=?",
                    (chunk_text, self.slug, ch.index),
                )
            else:
                self.conn.execute(
                    f"UPDATE chapters SET {col} = COALESCE({col}, '') || ? || ?, "
                    "translated_updated_at = unixepoch('now') WHERE ebook_slug=? AND idx=?",
                    ("\n", chunk_text, self.slug, ch.index),
                )

    # ----- ảnh bìa -----
    def write_cover(self, content: bytes, ext: str) -> str:
        """Lưu ảnh bìa (BLOB), trả tên "cover.<ext>" để ghi vào manifest.cover_file."""
        self.ensure_dirs()
        ext = (ext or "jpg").lstrip(".").lower() or "jpg"
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO ebook_covers (ebook_slug, ext, content) VALUES (?, ?, ?)
                ON CONFLICT(ebook_slug) DO UPDATE SET
                    ext = excluded.ext, content = excluded.content, updated_at = datetime('now')
                """,
                (self.slug, ext, content),
            )
        return f"cover.{ext}"

    def read_cover_bytes(self) -> tuple[bytes, str] | None:
        row = self.conn.execute(
            "SELECT ext, content FROM ebook_covers WHERE ebook_slug = ?", (self.slug,)
        ).fetchone()
        return (row["content"], row["ext"]) if row else None

    def cover_fs_path(self, manifest: "Manifest") -> Path | None:
        """Shim tương thích ngược cho code còn cần 1 Path thật (ebooklib,
        FileResponse): ghi blob bìa ra file tạm rồi trả Path. Nguồn thật vẫn
        là `ebook_covers` (BLOB) — file tạm chỉ để đọc, không phải nơi lưu."""
        if not manifest.cover_file:
            return None
        data = self.read_cover_bytes()
        if data is None:
            return None
        content, ext = data
        if manifest.cover_file != f"cover.{ext}":
            return None
        tmp = Path(tempfile.gettempdir()) / f"n2e-cover-{self.slug}.{ext}"
        tmp.write_bytes(content)
        return tmp

    # ----- glossary -----
    def read_glossary_file(self, name: str) -> dict[str, str]:
        """Trả về dict source→target (bỏ ghi chú nếu có)."""
        rows = self.conn.execute(
            "SELECT source, target FROM glossary_entries WHERE ebook_slug=? AND list_name=? ORDER BY position",
            (self.slug, name),
        ).fetchall()
        return {r["source"]: r["target"] for r in rows}

    def read_glossary_entries(self, name: str) -> list[tuple[str, str, str]]:
        """Đọc glossary thành list `(source, target, note)`, GIỮ ghi chú và
        thứ tự — trang Glossary (data table) cần cả 2."""
        rows = self.conn.execute(
            "SELECT source, target, note FROM glossary_entries WHERE ebook_slug=? AND list_name=? ORDER BY position",
            (self.slug, name),
        ).fetchall()
        return [(r["source"], r["target"], r["note"]) for r in rows]

    def read_glossary_entries_merged(self) -> list[tuple[str, str, str]]:
        """Gộp 2 list thành MỘT danh sách (source, target, note).

        `names.txt` là list chuẩn duy nhất (đã bỏ phân loại names/vietphrase);
        entry `vietphrase.txt` cũ chưa consolidate vẫn được đọc kèm, nhưng khi
        trùng source thì names.txt thắng.
        """
        merged = list(self.read_glossary_entries("names.txt"))
        seen = {source for source, _t, _n in merged}
        for entry in self.read_glossary_entries("vietphrase.txt"):
            if entry[0] not in seen:
                merged.append(entry)
        return merged

    def write_glossary_entries(self, name: str, entries: list[tuple[str, str, str]]) -> None:
        """Ghi list `(source, target, note)` — trim từng field, bỏ mục thiếu
        source/target, dedup theo source (mục SAU thắng)."""
        self.ensure_dirs()
        seen: dict[str, tuple[str, str]] = {}
        order: list[str] = []
        for entry in entries:
            source = (entry[0] or "").strip()
            target = (entry[1] or "").strip()
            note = (entry[2] or "").strip() if len(entry) > 2 else ""
            if not source or not target:
                continue
            if source not in seen:
                order.append(source)
            seen[source] = (target, note)
        with self.conn:
            self.conn.execute(
                "DELETE FROM glossary_entries WHERE ebook_slug=? AND list_name=?",
                (self.slug, name),
            )
            for position, source in enumerate(order):
                target, note = seen[source]
                self.conn.execute(
                    "INSERT INTO glossary_entries (ebook_slug, list_name, source, target, note, position) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (self.slug, name, source, target, note, position),
                )

    def write_glossary_file(self, name: str, content: str) -> None:
        """Parse nội dung dạng `source = target | note` (1 dòng/mục, bỏ dòng
        rỗng/comment/không hợp lệ) rồi ghi qua `write_glossary_entries`."""
        content = content.replace("\r\n", "\n")
        entries = [
            parsed for line in content.split("\n")
            if (parsed := parse_glossary_line(line)) is not None
        ]
        self.write_glossary_entries(name, entries)

    def read_glossary_notes(self) -> dict[str, str]:
        """Gộp names.txt + vietphrase.txt, trả {target: note} cho mục có ghi chú.

        Target (từ tiếng Việt) là chuỗi dùng để dò trong bản dịch khi sinh footnote.
        """
        notes: dict[str, str] = {}
        for name in ("names.txt", "vietphrase.txt"):
            for _source, target, note in self.read_glossary_entries(name):
                if note:
                    notes[target] = note
        return notes

    def append_glossary_line(self, name: str, line: str) -> None:
        """Thêm/cập nhật 1 dòng glossary đã format 'source = target [| note]'.
        Dùng UPSERT nên atomic tự nhiên (thay lock+file-append cũ)."""
        parsed = parse_glossary_line(line)
        if not parsed:
            return
        source, target, note = parsed
        self.ensure_dirs()
        with self.conn:
            row = self.conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS next_pos FROM glossary_entries "
                "WHERE ebook_slug=? AND list_name=?",
                (self.slug, name),
            ).fetchone()
            self.conn.execute(
                """
                INSERT INTO glossary_entries (ebook_slug, list_name, source, target, note, position)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(ebook_slug, list_name, source) DO UPDATE SET
                    target = excluded.target, note = excluded.note
                """,
                (self.slug, name, source, target, note, row["next_pos"]),
            )

    # ----- glossary: phân trang + thao tác từng mục (trang Glossary web) -----
    _GLOSS_SORT_COLS = {"source": "source", "target": "target", "note": "note"}

    def count_glossary_entries(self, name: str, query: str = "") -> int:
        """Đếm số mục trong 1 list, có thể lọc theo `query` (substring trên
        source/target/note). Dùng cho phân trang server-side."""
        query = (query or "").strip()
        if query:
            like = f"%{query}%"
            row = self.conn.execute(
                "SELECT COUNT(*) AS c FROM glossary_entries "
                "WHERE ebook_slug=? AND list_name=? "
                "AND (source LIKE ? OR target LIKE ? OR note LIKE ?)",
                (self.slug, name, like, like, like),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) AS c FROM glossary_entries WHERE ebook_slug=? AND list_name=?",
                (self.slug, name),
            ).fetchone()
        return int(row["c"])

    def read_glossary_page(
        self,
        name: str,
        offset: int,
        limit: int,
        query: str = "",
        sort_field: str | None = None,
        sort_dir: str = "asc",
    ) -> list[tuple[str, str, str]]:
        """Một trang glossary `(source, target, note)` qua SQL LIMIT/OFFSET.

        `sort_field` ∈ {source, target, note}; mặc định giữ thứ tự `position`.
        Sắp xếp COLLATE NOCASE (đủ dùng cho Latin; Hán/Việt so sánh binary)."""
        col = self._GLOSS_SORT_COLS.get(sort_field or "", "")
        direction = "DESC" if str(sort_dir).lower() == "desc" else "ASC"
        order = f"{col} COLLATE NOCASE {direction}, position ASC" if col else f"position {direction}"

        where = "ebook_slug=? AND list_name=?"
        params: list = [self.slug, name]
        query = (query or "").strip()
        if query:
            like = f"%{query}%"
            where += " AND (source LIKE ? OR target LIKE ? OR note LIKE ?)"
            params += [like, like, like]
        params += [int(limit), int(offset)]

        rows = self.conn.execute(
            f"SELECT source, target, note FROM glossary_entries WHERE {where} "
            f"ORDER BY {order} LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [(r["source"], r["target"], r["note"]) for r in rows]

    def upsert_glossary_entry(
        self, source: str, target: str, note: str = "", name: str = "names.txt"
    ) -> bool:
        """Thêm/cập nhật MỘT mục (autosave từng dòng). Trim; bỏ qua nếu thiếu
        source/target. Mục mới nhận position = max+1; trùng source → cập nhật
        target/note. Trả True nếu có ghi."""
        source = (source or "").strip()
        target = (target or "").strip()
        note = (note or "").strip()
        if not source or not target:
            return False
        self.ensure_dirs()
        with self.conn:
            row = self.conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS next_pos FROM glossary_entries "
                "WHERE ebook_slug=? AND list_name=?",
                (self.slug, name),
            ).fetchone()
            self.conn.execute(
                """
                INSERT INTO glossary_entries (ebook_slug, list_name, source, target, note, position)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(ebook_slug, list_name, source) DO UPDATE SET
                    target = excluded.target, note = excluded.note
                """,
                (self.slug, name, source, target, note, row["next_pos"]),
            )
        return True

    def delete_glossary_entry(self, source: str) -> bool:
        """Xoá MỘT mục theo source khỏi CẢ 2 list (names + vietphrase legacy).
        Trả True nếu có dòng bị xoá."""
        source = (source or "").strip()
        if not source:
            return False
        with self.conn:
            cur = self.conn.execute(
                "DELETE FROM glossary_entries WHERE ebook_slug=? AND source=? "
                "AND list_name IN ('names.txt', 'vietphrase.txt')",
                (self.slug, source),
            )
        return cur.rowcount > 0

    def consolidate_glossary(self) -> bool:
        """Gộp vietphrase.txt (legacy) vào names.txt (names thắng khi trùng) rồi
        xoá sạch vietphrase.txt — để phân trang chỉ cần quét names.txt. Idempotent;
        chỉ ghi khi vietphrase còn dữ liệu. Trả True nếu có consolidate."""
        if not self.read_glossary_entries("vietphrase.txt"):
            return False
        self.write_glossary_entries("names.txt", self.read_glossary_entries_merged())
        self.write_glossary_entries("vietphrase.txt", [])
        return True

    def clean_glossary(self) -> tuple[int, int]:
        """Dọn toàn bộ glossary: trim, bỏ mục thiếu Hán/Việt, dedup theo source
        (mục sau thắng), gộp về names.txt và xoá vietphrase.txt. Trả (trước, sau)."""
        before = self.count_glossary_entries("names.txt") + self.count_glossary_entries(
            "vietphrase.txt"
        )
        self.write_glossary_entries("names.txt", self.read_glossary_entries_merged())
        self.write_glossary_entries("vietphrase.txt", [])
        return before, self.count_glossary_entries("names.txt")

    # ----- idioms: từ điển thành ngữ DÙNG CHUNG (global, không gắn slug) -----
    def read_idiom_entries(self) -> list[tuple[str, str, str, int]]:
        """Đọc toàn bộ idiom global → list `(source, target, literals, protect)`
        theo thứ tự position. `literals` là chuỗi ngăn bằng `|`; `protect` 0/1."""
        rows = self.conn.execute(
            "SELECT source, target, literals, protect FROM idioms ORDER BY position"
        ).fetchall()
        return [(r["source"], r["target"], r["literals"], int(r["protect"])) for r in rows]

    def count_idioms(self, query: str = "") -> int:
        query = (query or "").strip()
        if query:
            like = f"%{query}%"
            row = self.conn.execute(
                "SELECT COUNT(*) AS c FROM idioms "
                "WHERE source LIKE ? OR target LIKE ? OR literals LIKE ?",
                (like, like, like),
            ).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) AS c FROM idioms").fetchone()
        return int(row["c"])

    _IDIOM_SORT_COLS = {"source": "source", "target": "target", "literals": "literals"}

    def read_idioms_page(
        self,
        offset: int,
        limit: int,
        query: str = "",
        sort_field: str | None = None,
        sort_dir: str = "asc",
    ) -> list[tuple[str, str, str, int]]:
        col = self._IDIOM_SORT_COLS.get(sort_field or "", "")
        direction = "DESC" if str(sort_dir).lower() == "desc" else "ASC"
        order = f"{col} COLLATE NOCASE {direction}, position ASC" if col else f"position {direction}"
        where = "1=1"
        params: list = []
        query = (query or "").strip()
        if query:
            like = f"%{query}%"
            where += " AND (source LIKE ? OR target LIKE ? OR literals LIKE ?)"
            params += [like, like, like]
        params += [int(limit), int(offset)]
        rows = self.conn.execute(
            f"SELECT source, target, literals, protect FROM idioms WHERE {where} "
            f"ORDER BY {order} LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [(r["source"], r["target"], r["literals"], int(r["protect"])) for r in rows]

    def upsert_idiom(self, source: str, target: str, literals: str = "", protect: int = 0) -> bool:
        """Thêm/cập nhật MỘT idiom. Trim; bỏ qua nếu thiếu source/target. Mục
        mới nhận position = max+1; trùng source → cập nhật. Trả True nếu ghi."""
        source = (source or "").strip()
        target = (target or "").strip()
        literals = (literals or "").strip()
        protect = 1 if protect else 0
        if not source or not target:
            return False
        with self.conn:
            row = self.conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS next_pos FROM idioms"
            ).fetchone()
            self.conn.execute(
                """
                INSERT INTO idioms (source, target, literals, protect, position)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    target = excluded.target, literals = excluded.literals,
                    protect = excluded.protect
                """,
                (source, target, literals, protect, row["next_pos"]),
            )
        return True

    def delete_idiom(self, source: str) -> bool:
        source = (source or "").strip()
        if not source:
            return False
        with self.conn:
            cur = self.conn.execute("DELETE FROM idioms WHERE source=?", (source,))
        return cur.rowcount > 0

    def write_idiom_entries(self, entries: list[tuple[str, str, str, int]]) -> None:
        """Ghi đè toàn bộ idiom global. Trim, bỏ mục thiếu source/target, dedup
        theo source (mục SAU thắng), giữ thứ tự xuất hiện đầu."""
        seen: dict[str, tuple[str, str, int]] = {}
        order: list[str] = []
        for entry in entries:
            source = (entry[0] or "").strip()
            target = (entry[1] or "").strip()
            literals = (entry[2] or "").strip() if len(entry) > 2 else ""
            protect = 1 if (len(entry) > 3 and entry[3]) else 0
            if not source or not target:
                continue
            if source not in seen:
                order.append(source)
            seen[source] = (target, literals, protect)
        with self.conn:
            self.conn.execute("DELETE FROM idioms")
            for position, source in enumerate(order):
                target, literals, protect = seen[source]
                self.conn.execute(
                    "INSERT INTO idioms (source, target, literals, protect, position) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (source, target, literals, protect, position),
                )

    def seed_idioms_if_empty(self, entries: list[tuple[str, str, str, int]]) -> int:
        """Seed idiom mẫu CHỈ khi kho còn trống (idempotent). Trả số mục đã seed
        (0 nếu đã có dữ liệu)."""
        if self.count_idioms() > 0:
            return 0
        self.write_idiom_entries(entries)
        return self.count_idioms()

    # ----- ghi chú lỗi dịch (trang đọc) -----
    def read_notes(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT data_json FROM notes WHERE ebook_slug=? ORDER BY id", (self.slug,)
        ).fetchall()
        result: list[dict] = []
        for r in rows:
            try:
                result.append(json.loads(r["data_json"]))
            except json.JSONDecodeError:
                continue
        return result

    def write_notes(self, notes: list[dict]) -> None:
        self.ensure_dirs()
        with self.conn:
            self.conn.execute("DELETE FROM notes WHERE ebook_slug=?", (self.slug,))
            for note in notes:
                self.conn.execute(
                    "INSERT INTO notes (ebook_slug, data_json) VALUES (?, ?)",
                    (self.slug, json.dumps(note, ensure_ascii=False)),
                )

    # ----- kho JSON phụ theo ebook (cost summary, glossary conflicts, ...) -----
    def read_extra_json(self, key: str) -> Any:
        row = self.conn.execute(
            "SELECT data_json FROM ebook_extra_json WHERE ebook_slug=? AND key=?",
            (self.slug, key),
        ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row["data_json"])
        except json.JSONDecodeError:
            return None

    def write_extra_json(self, key: str, data: Any) -> None:
        self.ensure_dirs()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO ebook_extra_json (ebook_slug, key, data_json) VALUES (?, ?, ?)
                ON CONFLICT(ebook_slug, key) DO UPDATE SET data_json = excluded.data_json
                """,
                (self.slug, key, json.dumps(data, ensure_ascii=False)),
            )

    def update_extra_json(self, key: str, update: Callable[[Any], Any]) -> Any:
        """Atomically read, transform, and write one ebook JSON value.

        ``BEGIN IMMEDIATE`` serializes concurrent read-modify-write operations
        from translation workers and web requests so neither can overwrite a
        newer glossary queue snapshot.
        """
        self.ensure_dirs()
        conn = self.conn
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT data_json FROM ebook_extra_json WHERE ebook_slug=? AND key=?",
                (self.slug, key),
            ).fetchone()
            current = None
            if row is not None:
                try:
                    current = json.loads(row["data_json"])
                except json.JSONDecodeError:
                    pass
            result = update(current)
            conn.execute(
                """
                INSERT INTO ebook_extra_json (ebook_slug, key, data_json) VALUES (?, ?, ?)
                ON CONFLICT(ebook_slug, key) DO UPDATE SET data_json = excluded.data_json
                """,
                (self.slug, key, json.dumps(result, ensure_ascii=False)),
            )
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise

    # ----- hàng chờ duyệt glossary (replacement) + lan truyền vào bản dịch -----
    def migrate_glossary_queue(self) -> bool:
        """Lazy, idempotent, atomic migration hàng chờ auto-glossary CŨ
        (`glossary_pending` schema cũ + `glossary_conflicts`) sang schema
        replacement chuẩn. Chạy ĐÚNG 1 lần (marker extra json
        `glossary_queue_v2`); trả True nếu lần này vừa migrate.

        Trùng source → first-wins (pending cũ trước, conflicts sau). Row cũ
        không có existing_target/note được lấp từ glossary hiện tại (rỗng nếu
        mục chưa tồn tại — thêm mới, không cần lan truyền).
        """
        self.ensure_dirs()
        conn = self.conn
        try:
            conn.execute("BEGIN IMMEDIATE")
            marker = conn.execute(
                "SELECT 1 FROM ebook_extra_json WHERE ebook_slug=? AND key='glossary_queue_v2'",
                (self.slug,),
            ).fetchone()
            if marker is not None:
                conn.commit()
                return False

            def _read(key: str):
                row = conn.execute(
                    "SELECT data_json FROM ebook_extra_json WHERE ebook_slug=? AND key=?",
                    (self.slug, key),
                ).fetchone()
                if row is None:
                    return None
                try:
                    return json.loads(row["data_json"])
                except json.JSONDecodeError:
                    return None

            glossary_target = {s: t for s, t, _n in self.read_glossary_entries_merged()}
            merged: dict[str, dict] = {}

            def _add(row: dict, *, fallback_existing: str = "") -> None:
                source = str(row.get("source", "")).strip()
                target = str(row.get("target", "")).strip()
                if not source or not target or source in merged:
                    return
                try:
                    ci = int(row.get("chapter_index", 0))
                except (TypeError, ValueError):
                    ci = 0
                merged[source] = {
                    "source": source,
                    "existing_target": str(row.get("existing_target", fallback_existing)).strip(),
                    "target": target,
                    "chapter_index": ci,
                    "note": str(row.get("note", "")).strip(),
                }

            pending_raw = _read("glossary_pending")
            for p in pending_raw if isinstance(pending_raw, list) else []:
                if isinstance(p, dict):
                    _add(
                        p,
                        fallback_existing=glossary_target.get(str(p.get("source", "")).strip(), ""),
                    )
            conflicts_raw = _read("glossary_conflicts")
            for c in conflicts_raw if isinstance(conflicts_raw, list) else []:
                if isinstance(c, dict):
                    _add(
                        {
                            "source": c.get("source", ""),
                            "target": c.get("new", ""),
                            "existing_target": c.get("existing", ""),
                            "chapter_index": c.get("chapter_index", 0),
                            "note": c.get("note", ""),
                        }
                    )

            conn.execute(
                """
                INSERT INTO ebook_extra_json (ebook_slug, key, data_json) VALUES (?, 'glossary_pending', ?)
                ON CONFLICT(ebook_slug, key) DO UPDATE SET data_json = excluded.data_json
                """,
                (self.slug, json.dumps(list(merged.values()), ensure_ascii=False)),
            )
            conn.execute(
                "DELETE FROM ebook_extra_json WHERE ebook_slug=? AND key='glossary_conflicts'",
                (self.slug,),
            )
            conn.execute(
                """
                INSERT INTO ebook_extra_json (ebook_slug, key, data_json) VALUES (?, 'glossary_queue_v2', 'true')
                ON CONFLICT(ebook_slug, key) DO UPDATE SET data_json = excluded.data_json
                """,
                (self.slug,),
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise

    def approve_glossary_rows(self, rows: list[dict]) -> dict:
        """Duyệt (hàng loạt) đề xuất thay thế trong MỘT transaction: upsert từng
        mục vào `names.txt` + gỡ source đã duyệt khỏi hàng chờ `glossary_pending`.

        `rows` là `[{source, target, note}]` — giá trị đã sửa tay trên UI. Row
        thiếu source/target bị bỏ. Source không còn trong hàng chờ (stale — đã
        bị duyệt/bỏ bởi luồng khác) được bỏ qua, chấp nhận count drift.
        `existing_target` lấy từ hàng chờ HIỆN TẠI (giá trị tại thời điểm duyệt).
        Trả {"approved": [{source, existing_target, target, note}], "remaining": [...]}.
        """
        self.ensure_dirs()
        conn = self.conn
        try:
            conn.execute("BEGIN IMMEDIATE")
            pend_row = conn.execute(
                "SELECT data_json FROM ebook_extra_json WHERE ebook_slug=? AND key='glossary_pending'",
                (self.slug,),
            ).fetchone()
            raw = json.loads(pend_row["data_json"]) if pend_row else None
            pending = normalize_glossary_pending(raw)
            by_source = {p["source"]: p for p in pending}

            approved: list[dict] = []
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict):
                    continue
                source = str(row.get("source", "")).strip()
                target = str(row.get("target", "")).strip()
                if not source or not target:
                    continue
                pending_row = by_source.get(source)
                if pending_row is None:
                    continue
                approved.append(
                    {
                        "source": source,
                        "existing_target": pending_row["existing_target"],
                        "target": target,
                        "note": str(row.get("note", "")).strip(),
                    }
                )

            for a in approved:
                pos_row = conn.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 AS next_pos FROM glossary_entries "
                    "WHERE ebook_slug=? AND list_name='names.txt'",
                    (self.slug,),
                ).fetchone()
                conn.execute(
                    """
                    INSERT INTO glossary_entries (ebook_slug, list_name, source, target, note, position)
                    VALUES (?, 'names.txt', ?, ?, ?, ?)
                    ON CONFLICT(ebook_slug, list_name, source) DO UPDATE SET
                        target = excluded.target, note = excluded.note
                    """,
                    (self.slug, a["source"], a["target"], a["note"], pos_row["next_pos"]),
                )

            approved_keys = {a["source"] for a in approved}
            remaining = [p for p in pending if p["source"] not in approved_keys]
            conn.execute(
                """
                INSERT INTO ebook_extra_json (ebook_slug, key, data_json) VALUES (?, 'glossary_pending', ?)
                ON CONFLICT(ebook_slug, key) DO UPDATE SET data_json = excluded.data_json
                """,
                (self.slug, json.dumps(remaining, ensure_ascii=False)),
            )
            conn.commit()
            return {"approved": approved, "remaining": remaining}
        except Exception:
            conn.rollback()
            raise

    def replacement_counts(self, pairs: list[tuple[str, str]]) -> dict:
        """Preview: đếm số lần khớp từng `old` (longest-first, 1 lượt) trong phạm
        vi chính xác — chapters `translated_text`/`title`/`title_note` + meta_json
        allowlist (đệ quy), và cột ebook `title`/`description`/`title_note`/
        `series`/`subjects_json`. Trả {"pairs": [{old,new,count,chapters}], "total"}.
        """
        matcher = _replacement_matcher(pairs)
        if matcher is None:
            return {
                "pairs": [{"old": old, "new": new, "count": 0, "chapters": 0} for old, new in pairs],
                "total": 0,
            }
        active, pattern = matcher
        counts = {old: 0 for old, _new in active}
        chapter_hits = {old: 0 for old in counts}

        def _scan(text: str, local: dict) -> None:
            if not text:
                return

            def _m(m):
                local[m.group(0)] += 1
                return m.group(0)

            pattern.sub(_m, text)

        def _scan_node(node, local: dict) -> None:
            if isinstance(node, str):
                _scan(node, local)
            elif isinstance(node, dict):
                for v in node.values():
                    _scan_node(v, local)
            elif isinstance(node, list):
                for v in node:
                    _scan_node(v, local)

        for row in self.conn.execute(
            "SELECT idx, translated_text, title, title_note, meta_json FROM chapters WHERE ebook_slug=?",
            (self.slug,),
        ).fetchall():
            local = {old: 0 for old in counts}
            _scan(row["translated_text"], local)
            _scan(row["title"], local)
            _scan(row["title_note"], local)
            try:
                meta = json.loads(row["meta_json"] or "{}")
            except json.JSONDecodeError:
                meta = {}
            if isinstance(meta, dict):
                for key in _META_REPLACE_KEYS:
                    if key in meta:
                        _scan_node(meta[key], local)
            for old, n in local.items():
                counts[old] += n
                if n:
                    chapter_hits[old] += 1

        ebook_row = self.conn.execute(
            "SELECT title, description, title_note, series, subjects_json FROM ebooks WHERE slug=?",
            (self.slug,),
        ).fetchone()
        if ebook_row is not None:
            local = {old: 0 for old in counts}
            for col in _EBOK_REPLACE_COLS[:4]:
                _scan(ebook_row[col], local)
            try:
                subjects = json.loads(ebook_row["subjects_json"] or "[]")
            except json.JSONDecodeError:
                subjects = []
            _scan_node(subjects, local)
            for old, n in local.items():
                counts[old] += n

        return {
            "pairs": [
                {"old": old, "new": new, "count": counts.get(old, 0), "chapters": chapter_hits.get(old, 0)}
                for old, new in pairs
            ],
            "total": sum(counts.values()),
        }

    def apply_replacements(self, pairs: list[tuple[str, str]]) -> dict:
        """Lan truyền (đồng thời, longest-old first, một lượt) các thay đổi
        `old→new` vào phạm vi chính xác: chapters `translated_text`/`title`/
        `title_note` + meta_json allowlist (đệ quy), và cột ebook `title`/
        `description`/`title_note`/`series`/`subjects_json`. Một transaction.
        Trả {"total": int, "chapters": int (số chương đổi), "ebook": bool}.
        """
        self.ensure_dirs()
        conn = self.conn
        try:
            conn.execute("BEGIN IMMEDIATE")
            matcher = _replacement_matcher(pairs)
            if matcher is None:
                conn.commit()
                return {"total": 0, "chapters": 0, "ebook": False}
            _active, pattern = matcher
            mapping = dict(_active)

            def _replace_text(text: str) -> tuple[str, int]:
                if not text:
                    return text, 0
                hits = {"n": 0}

                def _m(m):
                    hits["n"] += 1
                    return mapping[m.group(0)]

                return pattern.sub(_m, text), hits["n"]

            total = 0
            chapters_changed = 0
            for row in conn.execute(
                "SELECT idx, translated_text, title, title_note, meta_json FROM chapters WHERE ebook_slug=?",
                (self.slug,),
            ).fetchall():
                idx = row["idx"]
                new_translated = row["translated_text"]
                new_title = row["title"]
                new_title_note = row["title_note"]
                new_meta = row["meta_json"]
                changed_here = False
                tr_changed = False
                if new_translated:
                    new_translated, n = _replace_text(new_translated)
                    if n:
                        total += n
                        changed_here = True
                        tr_changed = True
                if new_title:
                    new_title, n = _replace_text(new_title)
                    if n:
                        total += n
                        changed_here = True
                if new_title_note:
                    new_title_note, n = _replace_text(new_title_note)
                    if n:
                        total += n
                        changed_here = True
                if new_meta:
                    try:
                        meta_obj = json.loads(new_meta)
                    except json.JSONDecodeError:
                        meta_obj = None
                    if isinstance(meta_obj, dict):
                        meta_new, meta_n = _replace_in_meta(meta_obj, _replace_text)
                        if meta_n:
                            total += meta_n
                            changed_here = True
                            new_meta = json.dumps(meta_new, ensure_ascii=False)
                if changed_here:
                    if tr_changed:
                        conn.execute(
                            "UPDATE chapters SET translated_text=?, translated_updated_at=unixepoch('now'), "
                            "title=?, title_note=?, meta_json=? WHERE ebook_slug=? AND idx=?",
                            (new_translated, new_title, new_title_note, new_meta, self.slug, idx),
                        )
                    else:
                        conn.execute(
                            "UPDATE chapters SET title=?, title_note=?, meta_json=? "
                            "WHERE ebook_slug=? AND idx=?",
                            (new_title, new_title_note, new_meta, self.slug, idx),
                        )
                    chapters_changed += 1

            ebook_changed = False
            ebook_row = conn.execute(
                "SELECT title, description, title_note, series, subjects_json FROM ebooks WHERE slug=?",
                (self.slug,),
            ).fetchone()
            if ebook_row is not None:
                e_sets: list[str] = []
                e_params: list = []

                def _set_col(col: str, value) -> None:
                    nonlocal ebook_changed, total
                    if value is None:
                        return
                    new_value, n = _replace_text(value)
                    if n:
                        total += n
                        ebook_changed = True
                        e_sets.append(f"{col} = ?")
                        e_params.append(new_value)

                for col in _EBOK_REPLACE_COLS[:4]:
                    _set_col(col, ebook_row[col])
                try:
                    subjects = json.loads(ebook_row["subjects_json"] or "[]")
                except json.JSONDecodeError:
                    subjects = []
                new_subjects, subj_n = _replace_in_node(subjects, _replace_text)
                if subj_n:
                    total += subj_n
                    ebook_changed = True
                    e_sets.append("subjects_json = ?")
                    e_params.append(json.dumps(new_subjects, ensure_ascii=False))
                if ebook_changed:
                    e_params.append(self.slug)
                    conn.execute(
                        f"UPDATE ebooks SET {', '.join(e_sets)}, updated_at = datetime('now') WHERE slug = ?",
                        e_params,
                    )
            conn.commit()
            return {"total": total, "chapters": chapters_changed, "ebook": ebook_changed}
        except Exception:
            conn.rollback()
            raise

    # ----- báo cáo dung lượng + dọn dẹp (thay app/storage_report.py cũ) -----
    def content_bytes(self) -> dict[str, int]:
        """Ước lượng dung lượng (byte, UTF-8) theo từng loại nội dung của
        ebook — dùng cho trang /storage. `epub`/tổng epub không tính ở đây
        (file build ra vẫn nằm ngoài DB, xem `app/storage_report.py`)."""
        row = self.conn.execute(
            """
            SELECT
                COALESCE(SUM(LENGTH(raw_text)), 0) AS raw,
                COALESCE(SUM(LENGTH(translated_text)), 0) AS translated,
                COALESCE(SUM(LENGTH(translated_mt_text)), 0) AS translated_mt,
                COALESCE(SUM(LENGTH(meta_json)), 0) AS meta
            FROM chapters WHERE ebook_slug = ?
            """,
            (self.slug,),
        ).fetchone()
        glossary_row = self.conn.execute(
            "SELECT COALESCE(SUM(LENGTH(source) + LENGTH(target) + LENGTH(note)), 0) AS n "
            "FROM glossary_entries WHERE ebook_slug = ?",
            (self.slug,),
        ).fetchone()
        cover_row = self.conn.execute(
            "SELECT COALESCE(SUM(LENGTH(content)), 0) AS n FROM ebook_covers WHERE ebook_slug = ?",
            (self.slug,),
        ).fetchone()
        return {
            "raw": row["raw"],
            "translated": row["translated"],
            "translated_mt": row["translated_mt"],
            "meta": row["meta"],
            "glossary": glossary_row["n"],
            "cover": cover_row["n"],
        }

    def content_counts(self) -> dict[str, int]:
        """Số chương CÓ nội dung theo từng loại + số mục glossary — trang
        /storage hiển thị kèm dung lượng. Tách khỏi `content_bytes` để
        `ebook_storage_report` (dashboard cũng gọi, mỗi lần là 1 lượt quét bảng)
        không phải gánh thêm query mà nó không dùng."""
        row = self.conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN raw_text IS NOT NULL AND raw_text != '' THEN 1 ELSE 0 END), 0) AS raw,
                COALESCE(SUM(CASE WHEN translated_text IS NOT NULL AND translated_text != '' THEN 1 ELSE 0 END), 0) AS translated,
                COALESCE(SUM(CASE WHEN translated_mt_text IS NOT NULL AND translated_mt_text != '' THEN 1 ELSE 0 END), 0) AS translated_mt
            FROM chapters WHERE ebook_slug = ?
            """,
            (self.slug,),
        ).fetchone()
        glossary_row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM glossary_entries WHERE ebook_slug = ?",
            (self.slug,),
        ).fetchone()
        return {
            "raw": row["raw"],
            "translated": row["translated"],
            "translated_mt": row["translated_mt"],
            "glossary": glossary_row["n"],
        }

    def purge_raw(self) -> int:
        """Xóa toàn bộ raw_text (bản gốc đã crawl). KHÔNG đụng translated_text
        (bản đã biên tập tay). Trả số byte ước lượng đã giải phóng."""
        row = self.conn.execute(
            "SELECT COALESCE(SUM(LENGTH(raw_text)), 0) AS n FROM chapters WHERE ebook_slug=?",
            (self.slug,),
        ).fetchone()
        with self.conn:
            self.conn.execute(
                "UPDATE chapters SET raw_text = NULL WHERE ebook_slug = ?", (self.slug,)
            )
        return row["n"]

    def purge_translated_mt(self) -> int:
        """Xóa snapshot máy dịch (translated_mt_text, cột "VI"). KHÔNG đụng
        translated_text (cột đã biên tập)."""
        row = self.conn.execute(
            "SELECT COALESCE(SUM(LENGTH(translated_mt_text)), 0) AS n FROM chapters WHERE ebook_slug=?",
            (self.slug,),
        ).fetchone()
        with self.conn:
            self.conn.execute(
                "UPDATE chapters SET translated_mt_text = NULL WHERE ebook_slug = ?", (self.slug,)
            )
        return row["n"]

    # ----- nhân vật & ngôi xưng (per-ebook) -----
    def read_character_entries(
        self,
    ) -> list[tuple[str, str, str, str, str, str, str, str, str]]:
        """Đọc nhân vật của ebook → list tuple 9 phần tử, thứ tự khớp
        `characters.characters_from_rows`. Cột `aliases_vi` (sub-project B) nối
        ở CUỐI để không phá vỡ vị trí 8 cột cũ."""
        rows = self.conn.execute(
            "SELECT source, target, aliases, gender, self_pronoun, narrator_ref, "
            "role_note, importance, aliases_vi FROM characters "
            "WHERE ebook_slug=? ORDER BY position",
            (self.slug,),
        ).fetchall()
        return [
            (r["source"], r["target"], r["aliases"], r["gender"], r["self_pronoun"],
             r["narrator_ref"], r["role_note"], r["importance"], r["aliases_vi"])
            for r in rows
        ]

    def upsert_character(
        self,
        source: str,
        target: str = "",
        aliases: str = "",
        gender: str = "",
        self_pronoun: str = "",
        narrator_ref: str = "",
        role_note: str = "",
        importance: str = "side",
        aliases_vi: str = "",
    ) -> bool:
        """Thêm/cập nhật MỘT nhân vật. Trim; bỏ qua nếu thiếu source. Mục mới
        nhận position = max+1; trùng source → cập nhật tại chỗ."""
        source = (source or "").strip()
        if not source:
            return False
        importance = (importance or "").strip() or "side"
        self.ensure_dirs()
        with self.conn:
            row = self.conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS next_pos FROM characters "
                "WHERE ebook_slug=?",
                (self.slug,),
            ).fetchone()
            self.conn.execute(
                """
                INSERT INTO characters (ebook_slug, source, target, aliases, gender,
                    self_pronoun, narrator_ref, role_note, importance, position,
                    aliases_vi)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ebook_slug, source) DO UPDATE SET
                    target = excluded.target, aliases = excluded.aliases,
                    gender = excluded.gender, self_pronoun = excluded.self_pronoun,
                    narrator_ref = excluded.narrator_ref, role_note = excluded.role_note,
                    importance = excluded.importance, aliases_vi = excluded.aliases_vi
                """,
                (self.slug, source, (target or "").strip(), (aliases or "").strip(),
                 (gender or "").strip(), (self_pronoun or "").strip(),
                 (narrator_ref or "").strip(), (role_note or "").strip(),
                 importance, row["next_pos"], (aliases_vi or "").strip()),
            )
        return True

    def delete_character(self, source: str) -> bool:
        """Xoá nhân vật VÀ mọi quan hệ dính tới nó (cả hai chiều).

        Dọn tường minh ở đây thay vì FK ghép khoá tới `characters` — quan hệ mồ
        côi không gây lỗi nhưng làm bẩn dữ liệu và bảng quan hệ trên web.
        """
        source = (source or "").strip()
        if not source:
            return False
        with self.conn:
            self.conn.execute(
                "DELETE FROM character_relations WHERE ebook_slug=? AND (a_source=? OR b_source=?)",
                (self.slug, source, source),
            )
            cur = self.conn.execute(
                "DELETE FROM characters WHERE ebook_slug=? AND source=?",
                (self.slug, source),
            )
        return cur.rowcount > 0

    def read_relation_entries(
        self,
    ) -> list[tuple[str, str, int, str, str, str, int | None, str, str, str, int, str]]:
        """Đọc quan hệ của ebook → list tuple 12 phần tử, thứ tự khớp
        `characters.relations_from_rows`. Sáu cột cuối (sub-project B: mốc kết
        thúc, chữ Hán gốc, bằng chứng, độ tin cậy) nối ở CUỐI để không phá vỡ vị
        trí 6 cột cũ."""
        rows = self.conn.execute(
            "SELECT a_source, b_source, from_chapter, a_calls_b, a_self, note, "
            "to_chapter, a_calls_b_raw, a_self_raw, evidence, inferred, confidence "
            "FROM character_relations WHERE ebook_slug=? "
            "ORDER BY a_source, b_source, from_chapter",
            (self.slug,),
        ).fetchall()
        return [
            (r["a_source"], r["b_source"], int(r["from_chapter"]),
             r["a_calls_b"], r["a_self"], r["note"],
             r["to_chapter"], r["a_calls_b_raw"], r["a_self_raw"],
             r["evidence"], int(r["inferred"]), r["confidence"])
            for r in rows
        ]

    def upsert_relation(
        self,
        a_source: str,
        b_source: str,
        from_chapter: int = 0,
        a_calls_b: str = "",
        a_self: str = "",
        note: str = "",
        to_chapter: int | None = None,
        a_calls_b_raw: str = "",
        a_self_raw: str = "",
        evidence: str = "",
        inferred: bool = False,
        confidence: str = "",
    ) -> bool:
        """Thêm/cập nhật MỘT mốc quan hệ có hướng. Bỏ qua nếu thiếu một đầu.

        `to_chapter` giữ nguyên `None` thành SQL NULL — KHÔNG ép về 0, vì NULL
        mang nghĩa "còn hiệu lực tới mốc kế tiếp hoặc mãi mãi" (xem
        `characters.resolve_relations`)."""
        a_source = (a_source or "").strip()
        b_source = (b_source or "").strip()
        if not a_source or not b_source:
            return False
        try:
            from_chapter = int(from_chapter)
        except (TypeError, ValueError):
            from_chapter = 0
        if to_chapter is not None:
            try:
                to_chapter = int(to_chapter)
            except (TypeError, ValueError):
                to_chapter = None
        self.ensure_dirs()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO character_relations (ebook_slug, a_source, b_source,
                    from_chapter, a_calls_b, a_self, note, to_chapter,
                    a_calls_b_raw, a_self_raw, evidence, inferred, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ebook_slug, a_source, b_source, from_chapter) DO UPDATE SET
                    a_calls_b = excluded.a_calls_b, a_self = excluded.a_self,
                    note = excluded.note, to_chapter = excluded.to_chapter,
                    a_calls_b_raw = excluded.a_calls_b_raw,
                    a_self_raw = excluded.a_self_raw, evidence = excluded.evidence,
                    inferred = excluded.inferred, confidence = excluded.confidence
                """,
                (self.slug, a_source, b_source, from_chapter,
                 (a_calls_b or "").strip(), (a_self or "").strip(), (note or "").strip(),
                 to_chapter, (a_calls_b_raw or "").strip(), (a_self_raw or "").strip(),
                 (evidence or "").strip(), 1 if inferred else 0,
                 (confidence or "").strip()),
            )
        return True

    def delete_relation(self, a_source: str, b_source: str, from_chapter: int = 0) -> bool:
        """Xoá MỘT mốc quan hệ có hướng theo cặp (a_source, b_source, from_chapter)."""
        a_source = (a_source or "").strip()
        b_source = (b_source or "").strip()
        if not a_source or not b_source:
            return False
        with self.conn:
            cur = self.conn.execute(
                "DELETE FROM character_relations WHERE ebook_slug=? AND a_source=? "
                "AND b_source=? AND from_chapter=?",
                (self.slug, a_source, b_source, int(from_chapter)),
            )
        return cur.rowcount > 0
