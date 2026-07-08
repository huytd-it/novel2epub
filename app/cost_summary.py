"""Đọc OmniRoute cost summary — dùng chung giữa trang ebook và dashboard."""
from __future__ import annotations

from novel2epub.storage import Storage


def read_cost_summary(storage: Storage) -> dict | None:
    data = storage.read_extra_json("cost_summary")
    return data if isinstance(data, dict) else None
