"""Tính tiến độ chương (raw/dịch/xoá Hán) dùng chung giữa trang chủ, trang ebook
và dashboard — tránh lặp lại vòng lặp `for ch in manifest.chapters` ở nhiều nơi.

Mỗi hàm nhận `stats_map` tuỳ chọn (từ `Storage.bulk_chapter_stats()`) để tính
toàn bộ ebook bằng 1 query thay vì 1 query/chương — xem docs/superpowers/specs/
2026-07-15-webui-performance-design.md. Không truyền thì vẫn chạy như cũ.
"""
from __future__ import annotations

from novel2epub.storage import Manifest, Storage


def chapter_progress(
    storage: Storage,
    manifest: Manifest | None,
    stats_map: dict[int, dict] | None = None,
) -> dict:
    """Đếm số chương đã cào/dịch + phần trăm hoàn thành so với tổng số chương."""
    chapters = manifest.chapters if manifest else []
    total = len(chapters)
    if stats_map is not None:
        raw_count = sum(1 for ch in chapters if stats_map.get(ch.index, {}).get("has_raw"))
        translated_count = sum(
            1 for ch in chapters if stats_map.get(ch.index, {}).get("has_translated")
        )
    else:
        raw_count = sum(1 for ch in chapters if storage.has_raw(ch))
        translated_count = sum(1 for ch in chapters if storage.has_translated(ch))
    return {
        "total": total,
        "raw_count": raw_count,
        "translated_count": translated_count,
        "raw_pct": round(raw_count / total * 100) if total else 0,
        "translated_pct": round(translated_count / total * 100) if total else 0,
    }


def han_fixed_total(
    storage: Storage,
    manifest: Manifest | None,
    stats_map: dict[int, dict] | None = None,
) -> int:
    """Tổng số ký tự/chỗ Hán đã được AI biên tập sửa qua các lần cleanup-han."""
    chapters = manifest.chapters if manifest else []
    if stats_map is None:
        return sum(
            storage.read_meta(ch).get("han_cleanup", {}).get("fixed_count", 0)
            for ch in chapters
            if storage.has_meta(ch)
        )

    return sum(int(stats_map.get(ch.index, {}).get("han_fixed_count", 0) or 0) for ch in chapters)
