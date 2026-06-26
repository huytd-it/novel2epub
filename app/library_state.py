"""Cờ archive/unarchive cho ebook trong thư viện — lưu riêng khỏi config gộp
vì là trạng thái UI thuần (không ảnh hưởng pipeline crawl/dịch/build). File
máy-ghi nên dùng JSON thường (xem design.md D3), tại
`workspace/.n2e/library_state.json`.
"""
from __future__ import annotations

import json
from pathlib import Path


def _load(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {"archived": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"archived": []}
    data.setdefault("archived", [])
    return data


def _save(path: str | Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def archived_slugs(path: str | Path) -> set[str]:
    return set(_load(path)["archived"])


def set_archived(path: str | Path, slug: str, archived: bool) -> None:
    data = _load(path)
    slugs = set(data["archived"])
    if archived:
        slugs.add(slug)
    else:
        slugs.discard(slug)
    data["archived"] = sorted(slugs)
    _save(path, data)
