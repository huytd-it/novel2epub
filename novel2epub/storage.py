"""Lưu trữ & cache: manifest chương + nội dung raw/đã dịch — hậu thuẫn bởi
SQLite thống nhất (xem kế hoạch SQLite unification), không còn ghi file rời.

`Storage(data_dir, slug)` giữ signature cũ để ~30 call site không phải đổi:
`data_dir` giờ chỉ dùng để suy ra đường dẫn file `.db` thống nhất (sibling của
`data_dir`), không còn là thư mục chứa file `.md`/`.json` của ebook.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .db import get_thread_connection, resolve_db_path


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
            "SELECT raw_text, translated_text, translated_mt_text, meta_json, "
            "translated_updated_at FROM chapters WHERE ebook_slug=? AND idx=?",
            (self.slug, ch.index),
        ).fetchone()

    def bulk_chapter_stats(self) -> dict[int, dict]:
        rows = self.conn.execute(
            "SELECT idx,"
            " CASE WHEN raw_text IS NOT NULL AND raw_text != '' THEN 1 ELSE 0 END AS has_raw_int,"
            " CASE WHEN translated_text IS NOT NULL AND translated_text != '' THEN 1 ELSE 0 END AS has_tr_int,"
            " LENGTH(translated_text) AS translated_len,"
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
                has_translated = bool(meta.get("complete", True))
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
        """Xóa toàn bộ dữ liệu bản dịch: translated, translated_mt, meta."""
        with self.conn:
            self.conn.execute(
                "UPDATE chapters SET translated_text=NULL, translated_mt_text=NULL, "
                "meta_json='{}', translated_updated_at=NULL WHERE ebook_slug=? AND idx=?",
                (self.slug, ch.index),
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
    def read_character_entries(self) -> list[tuple[str, str, str, str, str, str, str, str]]:
        """Đọc nhân vật của ebook → list tuple 8 phần tử, thứ tự khớp
        `characters.characters_from_rows`."""
        rows = self.conn.execute(
            "SELECT source, target, aliases, gender, self_pronoun, narrator_ref, "
            "role_note, importance FROM characters WHERE ebook_slug=? ORDER BY position",
            (self.slug,),
        ).fetchall()
        return [
            (r["source"], r["target"], r["aliases"], r["gender"], r["self_pronoun"],
             r["narrator_ref"], r["role_note"], r["importance"])
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
                    self_pronoun, narrator_ref, role_note, importance, position)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ebook_slug, source) DO UPDATE SET
                    target = excluded.target, aliases = excluded.aliases,
                    gender = excluded.gender, self_pronoun = excluded.self_pronoun,
                    narrator_ref = excluded.narrator_ref, role_note = excluded.role_note,
                    importance = excluded.importance
                """,
                (self.slug, source, (target or "").strip(), (aliases or "").strip(),
                 (gender or "").strip(), (self_pronoun or "").strip(),
                 (narrator_ref or "").strip(), (role_note or "").strip(),
                 importance, row["next_pos"]),
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

    def read_relation_entries(self) -> list[tuple[str, str, int, str, str, str]]:
        """Đọc quan hệ của ebook → list tuple 6 phần tử, thứ tự khớp
        `characters.relations_from_rows`."""
        rows = self.conn.execute(
            "SELECT a_source, b_source, from_chapter, a_calls_b, a_self, note "
            "FROM character_relations WHERE ebook_slug=? "
            "ORDER BY a_source, b_source, from_chapter",
            (self.slug,),
        ).fetchall()
        return [
            (r["a_source"], r["b_source"], int(r["from_chapter"]),
             r["a_calls_b"], r["a_self"], r["note"])
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
    ) -> bool:
        """Thêm/cập nhật MỘT mốc quan hệ có hướng. Bỏ qua nếu thiếu một đầu."""
        a_source = (a_source or "").strip()
        b_source = (b_source or "").strip()
        if not a_source or not b_source:
            return False
        try:
            from_chapter = int(from_chapter)
        except (TypeError, ValueError):
            from_chapter = 0
        self.ensure_dirs()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO character_relations (ebook_slug, a_source, b_source,
                    from_chapter, a_calls_b, a_self, note)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ebook_slug, a_source, b_source, from_chapter) DO UPDATE SET
                    a_calls_b = excluded.a_calls_b, a_self = excluded.a_self,
                    note = excluded.note
                """,
                (self.slug, a_source, b_source, from_chapter,
                 (a_calls_b or "").strip(), (a_self or "").strip(), (note or "").strip()),
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
