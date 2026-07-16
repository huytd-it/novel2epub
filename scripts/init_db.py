"""Khởi tạo file DB mới (novel2epub.db) từ mẫu `novel2epub.example.yaml` —
dùng cho cài đặt MỚI, sau khi chuyển sang lưu trữ SQLite thống nhất.

Không đụng tới bất kỳ file `.yaml`/`.json` nào của cài đặt hiện có — script
di chuyển dữ liệu từ cài đặt cũ (`scripts/migrate_to_sqlite.py`) sẽ được thêm
ở phase sau.

Chạy:
    python scripts/init_db.py [--db novel2epub.db] [--force]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from novel2epub.db import get_connection, init_schema  # noqa: E402

EXAMPLE_PATH = ROOT / "novel2epub.example.yaml"

_SETTINGS_SECTIONS = ("crawl", "translate", "ai", "output", "queue", "reader")


def _section_json(defaults: dict, key: str) -> str:
    return json.dumps(defaults.get(key) or {}, ensure_ascii=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="novel2epub.db", help="Đường dẫn file DB cần tạo")
    parser.add_argument("--force", action="store_true", help="Ghi đè nếu file đã tồn tại")
    args = parser.parse_args()

    db_path = Path(args.db)
    if db_path.exists():
        if not args.force:
            print(f"{db_path} đã tồn tại — dùng --force để ghi đè.", file=sys.stderr)
            return 1
        db_path.unlink()

    if not EXAMPLE_PATH.exists():
        print(f"Không tìm thấy {EXAMPLE_PATH}", file=sys.stderr)
        return 1

    raw = yaml.safe_load(EXAMPLE_PATH.read_text(encoding="utf-8")) or {}
    defaults = raw.get("defaults") or {}
    sources = raw.get("sources") or {}

    conn = get_connection(db_path)
    try:
        init_schema(conn)
        with conn:
            conn.execute(
                """
                INSERT INTO settings (id, novel_json, crawl_json, translate_json, ai_json, output_json, queue_json, reader_json)
                VALUES (1, '{}', ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    crawl_json = excluded.crawl_json,
                    translate_json = excluded.translate_json,
                    ai_json = excluded.ai_json,
                    output_json = excluded.output_json,
                    queue_json = excluded.queue_json,
                    reader_json = excluded.reader_json
                """,
                tuple(_section_json(defaults, s) for s in _SETTINGS_SECTIONS),
            )
            for name, data in sources.items():
                conn.execute(
                    """
                    INSERT INTO sources (name, data_json) VALUES (?, ?)
                    ON CONFLICT(name) DO UPDATE SET data_json = excluded.data_json
                    """,
                    (name, json.dumps(data, ensure_ascii=False)),
                )
    finally:
        conn.close()

    print(f"Đã tạo {db_path} (schema + settings mặc định từ {EXAMPLE_PATH.name}, {len(sources)} source preset).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
