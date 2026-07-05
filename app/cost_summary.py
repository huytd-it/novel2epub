"""Đọc OmniRoute cost summary (translation_meta/_cost_summary.json) — dùng chung
giữa trang ebook và dashboard."""
from __future__ import annotations

import json

from novel2epub.storage import Storage


def read_cost_summary(storage: Storage) -> dict | None:
    path = storage.root / "translation_meta" / "_cost_summary.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
