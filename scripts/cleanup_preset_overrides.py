"""Dọn override thừa mà `propagate_preset_update` (đã xoá) để lại.

Propagate từng copy giá trị preset vào `crawl_overrides_json` của ebook. Những
override đó vừa thừa (load_config đã resolve preset live) vừa có hại: chúng
đóng băng ebook ở giá trị preset tại thời điểm copy, khiến preset sửa về sau
không còn tác dụng lên ebook đó.

Script này bỏ các key trùng khít preset, giữ nguyên key user thật sự override.
Chạy MỘT LẦN là đủ — nguồn sinh override bẩn đã bị xoá.

    python -m scripts.cleanup_preset_overrides --dry-run
    python -m scripts.cleanup_preset_overrides
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from novel2epub.db import get_thread_connection
from novel2epub.sources import load_presets, strip_preset_defaults


def cleanup_overrides(
    db_path: str | Path,
    dry_run: bool = False,
) -> dict[str, list[str]]:
    """Bỏ override trùng preset khỏi mọi ebook có `source_preset`.

    Trả ``{slug: [key đã bỏ]}`` — chỉ gồm ebook thực sự đổi. Ebook không có
    source, hoặc trỏ tới preset không tồn tại, được bỏ qua nguyên vẹn.
    Idempotent: chạy lần hai trả ``{}``.
    """
    path = Path(db_path).resolve()
    if not path.exists():
        return {}
    presets = load_presets(path)
    conn = get_thread_connection(path)
    rows = conn.execute(
        "SELECT slug, source_preset, crawl_overrides_json FROM ebooks "
        "WHERE source_preset IS NOT NULL AND source_preset != ''"
    ).fetchall()

    report: dict[str, list[str]] = {}
    updates: list[tuple[str, str]] = []
    for row in rows:
        preset = presets.get(row["source_preset"])
        if preset is None:
            continue  # preset đã bị xoá — không có gì để so, giữ nguyên
        crawl = json.loads(row["crawl_overrides_json"] or "{}")
        cleaned, removed = strip_preset_defaults(crawl, preset)
        if not removed:
            continue
        report[row["slug"]] = removed
        updates.append((json.dumps(cleaned, ensure_ascii=False), row["slug"]))

    if updates and not dry_run:
        with conn:
            conn.executemany(
                "UPDATE ebooks SET crawl_overrides_json = ? WHERE slug = ?",
                updates,
            )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-c", "--config",
        default=os.environ.get("NOVEL2EPUB_DB", "novel2epub.db"),
        help="Đường dẫn file DB gộp (mặc định: novel2epub.db)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Chỉ in ra những gì SẼ xoá, không ghi vào DB.",
    )
    args = parser.parse_args()

    report = cleanup_overrides(args.config, dry_run=args.dry_run)
    if not report:
        print("Không có override thừa nào. Không cần làm gì.")
        return

    prefix = "[dry-run] SẼ bỏ" if args.dry_run else "Đã bỏ"
    total = 0
    for slug, keys in sorted(report.items()):
        print(f"{prefix} khỏi {slug}: {', '.join(keys)}")
        total += len(keys)
    print(f"\n{len(report)} ebook, {total} override.")
    if args.dry_run:
        print("Chạy lại không có --dry-run để áp dụng.")


if __name__ == "__main__":
    main()
