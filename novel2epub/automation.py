"""Automation: chuỗi bước pipeline (fetch-toc → crawl-new → translate-pending
→ build) chạy theo lịch hoặc tay, lưu trong `workspace/.n2e/automations.yaml`
(xem spec automation-scheduling). Đọc–ghi round-trip bằng ruamel để giữ
comment người dùng tự thêm, theo cùng pattern với `sources.py`.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

STEPS = ("fetch-toc", "crawl-new", "translate-pending", "build")


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


@dataclass
class Automation:
    id: str
    ebook: str
    steps: list[str] = field(default_factory=lambda: ["build"])
    # "manual" | "daily@HH:MM"
    schedule: str = "manual"
    enabled: bool = True
    last_run_at: str = ""
    last_run_outcome: str = ""  # "" | "success" | "failure" | "partial"


def load_automations(path: str | Path) -> dict[str, Automation]:
    path = Path(path)
    if not path.exists():
        return {}
    raw = _yaml().load(path.read_text(encoding="utf-8")) or {}
    result: dict[str, Automation] = {}
    for item_id, item in (raw.get("automations") or {}).items():
        data = dict(item)
        data["id"] = item_id
        data.setdefault("steps", ["build"])
        result[item_id] = Automation(**data)
    return result


def save_automations(path: str | Path, automations: dict[str, Automation]) -> None:
    path = Path(path)
    data: CommentedMap
    if path.exists():
        loaded = _yaml().load(path.read_text(encoding="utf-8"))
        data = loaded if isinstance(loaded, CommentedMap) else CommentedMap()
    else:
        data = CommentedMap()
    items = CommentedMap()
    for item_id, automation in automations.items():
        item = CommentedMap()
        for k, v in asdict(automation).items():
            if k == "id":
                continue
            item[k] = v
        items[item_id] = item
    data["automations"] = items
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        _yaml().dump(data, f)


def add_automation(path: str | Path, ebook: str, steps: list[str], schedule: str = "manual") -> Automation:
    automations = load_automations(path)
    new_id = str(uuid.uuid4())
    automation = Automation(id=new_id, ebook=ebook, steps=list(steps), schedule=schedule)
    automations[new_id] = automation
    save_automations(path, automations)
    return automation


def update_automation(path: str | Path, automation_id: str, updates: dict[str, Any]) -> None:
    automations = load_automations(path)
    if automation_id not in automations:
        raise KeyError(f"không tìm thấy automation {automation_id!r}")
    current = automations[automation_id]
    data = asdict(current)
    data.update(updates)
    automations[automation_id] = Automation(**data)
    save_automations(path, automations)


def remove_automation(path: str | Path, automation_id: str) -> None:
    automations = load_automations(path)
    automations.pop(automation_id, None)
    save_automations(path, automations)
