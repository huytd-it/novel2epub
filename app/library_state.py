"""Cờ archive/unarchive cho ebook trong thư viện — cột `ebooks.archived` trong
DB thống nhất (trước đây là `workspace/.n2e/library_state.json` riêng)."""
from __future__ import annotations

from pathlib import Path

from novel2epub.db import get_thread_connection


def archived_slugs(db_path: str | Path) -> set[str]:
    conn = get_thread_connection(db_path)
    rows = conn.execute("SELECT slug FROM ebooks WHERE archived = 1").fetchall()
    return {r["slug"] for r in rows}


def set_archived(db_path: str | Path, slug: str, archived: bool) -> None:
    conn = get_thread_connection(db_path)
    with conn:
        conn.execute(
            """
            INSERT INTO ebooks (slug, archived) VALUES (?, ?)
            ON CONFLICT(slug) DO UPDATE SET archived = excluded.archived
            """,
            (slug, int(archived)),
        )
