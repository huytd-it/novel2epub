from __future__ import annotations

from app.routes import webui
from novel2epub.db import get_connection, init_schema


def _seed(db_path, count: int = 5) -> None:
    conn = get_connection(db_path)
    init_schema(conn)
    with conn:
        for i in range(count):
            conn.execute(
                "INSERT INTO ebooks (slug, title, author, archived, date_added) VALUES (?, ?, ?, ?, ?)",
                (f"book-{i}", f"Book {i}", "Nguyễn A" if i != 3 else "Tác giả khác", i == 4, f"2026-01-{i + 1:02d}"),
            )
    conn.close()


def test_library_list_pages_and_filters_before_hydrating_summaries(monkeypatch, tmp_path):
    db_path = tmp_path / "library.db"
    _seed(db_path)
    hydrated: list[str] = []

    monkeypatch.setattr(webui.deps, "DB_PATH", db_path)
    monkeypatch.setattr(webui.deps, "resolved_cfg", lambda slug: slug)
    monkeypatch.setattr(
        webui,
        "_ebook_summary",
        lambda slug, _cfg, **_kwargs: hydrated.append(slug) or {"slug": slug},
    )

    result = webui.library_list(page=1, limit=2)

    assert result["total"] == 4
    assert [item["slug"] for item in result["ebooks"]] == ["book-2", "book-3"]
    assert hydrated == ["book-2", "book-3"]
    assert result["archived_count"] == 1

    hydrated.clear()
    result = webui.library_list(q="tác giả khác", show_archived=True, current_slug="book-0")

    assert result["total"] == 1
    assert [item["slug"] for item in result["ebooks"]] == ["book-3"]
    assert result["current"] == {"slug": "book-0"}
    assert hydrated == ["book-0", "book-3"]
