"""Tính tiến độ chương (raw/dịch/xoá Hán) dùng chung giữa trang chủ, trang ebook
và dashboard — tránh lặp lại vòng lặp `for ch in manifest.chapters` ở nhiều nơi.
"""
from __future__ import annotations

from novel2epub.storage import Manifest, Storage


def chapter_progress(storage: Storage, manifest: Manifest | None) -> dict:
    """Đếm số chương đã cào/dịch + phần trăm hoàn thành so với tổng số chương."""
    chapters = manifest.chapters if manifest else []
    total = len(chapters)
    raw_count = sum(1 for ch in chapters if storage.has_raw(ch))
    translated_count = sum(1 for ch in chapters if storage.has_translated(ch))
    return {
        "total": total,
        "raw_count": raw_count,
        "translated_count": translated_count,
        "raw_pct": round(raw_count / total * 100) if total else 0,
        "translated_pct": round(translated_count / total * 100) if total else 0,
    }


def han_fixed_total(storage: Storage, manifest: Manifest | None) -> int:
    """Tổng số ký tự/chỗ Hán đã được AI biên tập sửa qua các lần cleanup-han."""
    chapters = manifest.chapters if manifest else []
    return sum(
        storage.read_meta(ch).get("han_cleanup", {}).get("fixed_count", 0)
        for ch in chapters
        if storage.has_meta(ch)
    )
