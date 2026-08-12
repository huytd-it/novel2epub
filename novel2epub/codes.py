"""Stable, human-readable codes used to identify sources, ebooks and chapters."""
from __future__ import annotations

import re
import sqlite3
import unicodedata


def acronym(value: str, fallback: str, *, max_length: int = 8) -> str:
    """Return an uppercase ASCII acronym suitable for operational identifiers."""
    normalized = unicodedata.normalize("NFKD", (value or "").replace("Đ", "D").replace("đ", "d"))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[A-Za-z0-9]+", ascii_text)
    code = "".join(word[0] for word in words if word).upper()
    if not code and words:
        code = "".join(words).upper()
    return (code or fallback).upper()[:max_length]


def chapter_code(ebook_code: str, index: int) -> str:
    return f"{ebook_code}-{int(index):04d}"


def _unique(base: str, used: set[str]) -> str:
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def backfill_codes(conn: sqlite3.Connection) -> None:
    """Fill missing codes without changing codes that have already been assigned."""
    source_rows = conn.execute("SELECT name, code FROM sources ORDER BY name").fetchall()
    used_sources = {row["code"] for row in source_rows if row["code"]}
    for row in source_rows:
        if not row["code"]:
            code = _unique(acronym(row["name"], "SRC"), used_sources)
            conn.execute("UPDATE sources SET code = ? WHERE name = ?", (code, row["name"]))

    source_codes = {
        row["name"]: row["code"]
        for row in conn.execute("SELECT name, code FROM sources").fetchall()
    }
    ebook_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(ebooks)").fetchall()
    }
    select = ["slug", "code"]
    for column in ("title", "source_preset"):
        select.append(column if column in ebook_columns else f"'' AS {column}")
    ebook_rows = conn.execute(
        f"SELECT {', '.join(select)} FROM ebooks ORDER BY slug"
    ).fetchall()
    used_ebooks = {row["code"] for row in ebook_rows if row["code"]}
    for row in ebook_rows:
        if row["code"]:
            continue
        source_code = source_codes.get(row["source_preset"], "SRC")
        book_code = acronym(row["title"] or row["slug"], "BOOK")
        code = _unique(f"{source_code}-{book_code}", used_ebooks)
        conn.execute("UPDATE ebooks SET code = ? WHERE slug = ?", (code, row["slug"]))

    used_chapters = {
        row["code"]
        for row in conn.execute("SELECT code FROM chapters WHERE code <> ''").fetchall()
    }
    for row in conn.execute("SELECT slug, code FROM ebooks").fetchall():
        # Chapter code là định danh ổn định, không phải số thứ tự hiển thị.
        # Chỉ gán cho hàng còn thiếu. Nếu code theo idx đã thuộc về một chương
        # vừa được dịch chuyển, thêm suffix thay vì đổi định danh chương cũ.
        missing = conn.execute(
            "SELECT idx FROM chapters WHERE ebook_slug = ? AND code = '' ORDER BY idx",
            (row["slug"],),
        ).fetchall()
        for chapter in missing:
            code = _unique(chapter_code(row["code"], chapter["idx"]), used_chapters)
            conn.execute(
                "UPDATE chapters SET code = ? WHERE ebook_slug = ? AND idx = ?",
                (code, row["slug"], chapter["idx"]),
            )


def ebook_identity(conn: sqlite3.Connection, slug: str) -> tuple[str, dict[int, str]]:
    """Resolve operational ebook/chapter codes for a queue job."""
    row = conn.execute("SELECT code FROM ebooks WHERE slug = ?", (slug,)).fetchone()
    ebook_code = row["code"] if row and row["code"] else slug
    chapters = {
        int(row["idx"]): row["code"]
        for row in conn.execute(
            "SELECT idx, code FROM chapters WHERE ebook_slug = ?", (slug,)
        ).fetchall()
    }
    return ebook_code, chapters
