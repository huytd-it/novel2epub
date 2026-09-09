"""Tính tiến độ chương (đã cào/đã dịch) dùng chung giữa trang chủ, trang ebook
và dashboard — tránh lặp lại vòng lặp đếm ở nhiều nơi.

Nguồn dữ liệu là projection hẹp `chapter_ui_state` (qua
`storage.bulk_chapter_states()`), KHÔNG phải `Manifest`: dựng manifest là một
lượt quét bảng `chapters` — bảng giữ blob raw/dịch — cho mỗi ebook.
"""
from __future__ import annotations

from collections.abc import Iterable


def progress_from_states(states: Iterable[dict]) -> dict:
    """Số chương đã cào/đã dịch + phần trăm hoàn thành so với tổng số chương."""
    states = list(states)
    total = len(states)
    raw_count = sum(1 for s in states if s.get("has_raw"))
    translated_count = sum(1 for s in states if s.get("has_translated"))
    return {
        "total": total,
        "raw_count": raw_count,
        "translated_count": translated_count,
        "raw_pct": round(raw_count / total * 100) if total else 0,
        "translated_pct": round(translated_count / total * 100) if total else 0,
    }
