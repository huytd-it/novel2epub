"""Fixture dùng chung cho test — chủ yếu để dựng nhanh 1 file `.db` cấu hình
(settings/sources/ebooks) thay cho việc viết YAML tay như trước SQLite
unification."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from novel2epub.db import get_connection, init_schema

_SETTINGS_SECTIONS = ("novel", "crawl", "translate", "ai", "output", "queue", "reader", "api", "wireguard")


def write_db_config(
    path: str | Path,
    defaults: dict[str, Any] | None = None,
    sources: dict[str, Any] | None = None,
    ebooks: dict[str, Any] | None = None,
) -> Path:
    """Tạo 1 file `.db` tại `path` với settings/sources/ebooks cho trước.

    Shape của `ebooks[slug]` giống hệt khối `ebooks.<slug>` trong YAML cũ:
    `{"name": ..., "source": <preset name>, "novel": {...}, "crawl": {...},
    "output": {...}}`.
    """
    path = Path(path)
    conn = get_connection(str(path))
    init_schema(conn)
    defaults = defaults or {}
    with conn:
        conn.execute(
            """
            INSERT INTO settings (id, novel_json, crawl_json, translate_json, ai_json, output_json, queue_json, reader_json, api_json, wireguard_json)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                novel_json = excluded.novel_json, crawl_json = excluded.crawl_json,
                translate_json = excluded.translate_json, ai_json = excluded.ai_json,
                output_json = excluded.output_json, queue_json = excluded.queue_json,
                reader_json = excluded.reader_json, api_json = excluded.api_json,
                wireguard_json = excluded.wireguard_json
            """,
            tuple(json.dumps(defaults.get(s, {}), ensure_ascii=False) for s in _SETTINGS_SECTIONS),
        )
        for name, data in (sources or {}).items():
            conn.execute(
                "INSERT INTO sources (name, data_json) VALUES (?, ?)",
                (name, json.dumps(data, ensure_ascii=False)),
            )
        for slug, block in (ebooks or {}).items():
            novel = dict(block.get("novel") or {})
            novel.setdefault("slug", slug)
            crawl_over = block.get("crawl") or {}
            output_over = block.get("output") or {}
            reader_over = block.get("reader") or {}
            translate_over = block.get("translate") or {}
            ai_over = block.get("ai") or {}
            conn.execute(
                """
                INSERT INTO ebooks
                    (slug, name, source_preset, title, author, description, language,
                     publisher, pubdate, date_added, subjects_json, series, series_index,
                     identifier, cover_url, crawl_overrides_json, output_overrides_json, epub_path,
                     reader_overrides_json, translate_overrides_json, ai_overrides_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    slug, block.get("name", ""), block.get("source"),
                    novel.get("title", ""), novel.get("author", ""), novel.get("description", ""),
                    novel.get("language", "vi"), novel.get("publisher", ""), novel.get("pubdate", ""),
                    novel.get("date_added", ""), json.dumps(novel.get("subjects", []), ensure_ascii=False),
                    novel.get("series", ""), novel.get("series_index", ""), novel.get("identifier", ""),
                    novel.get("cover_url", ""), json.dumps(crawl_over, ensure_ascii=False),
                    json.dumps(output_over, ensure_ascii=False), output_over.get("epub_path", ""),
                    json.dumps(reader_over, ensure_ascii=False),
                    json.dumps(translate_over, ensure_ascii=False),
                    json.dumps(ai_over, ensure_ascii=False),
                ),
            )
    conn.close()
    return path
