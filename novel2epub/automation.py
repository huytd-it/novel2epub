"""Automation: chuỗi bước pipeline (fetch-toc → crawl-new → translate-pending
→ build → publish-reader) chạy theo lịch hoặc tay — lưu trong bảng
`automations` của DB thống nhất (trước đây là `workspace/.n2e/automations.yaml`
round-trip ruamel).
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .db import get_thread_connection

STEPS = ("fetch-toc", "crawl-new", "translate-pending", "cleanup-han", "build", "publish-reader")


@dataclass
class Automation:
    id: str
    ebook: str
    steps: list[str] = field(default_factory=lambda: ["build"])
    # "manual" | "daily@HH:MM" | "continuous" | "continuous@N" (N phút cooldown)
    schedule: str = "manual"
    enabled: bool = True
    last_run_at: str = ""
    last_run_outcome: str = ""  # "" | "success" | "failure" | "partial"
    last_run_error: str = ""  # "{step}: {lỗi}" của lần chạy gần nhất, "" nếu thành công
    last_run_stats: dict = field(default_factory=dict)  # {"chapters_total", "crawled", "translated", "han_fixed"}


def load_automations(db_path: str | Path) -> dict[str, Automation]:
    conn = get_thread_connection(db_path)
    rows = conn.execute("SELECT * FROM automations").fetchall()
    result: dict[str, Automation] = {}
    for r in rows:
        result[r["id"]] = Automation(
            id=r["id"],
            ebook=r["ebook"],
            steps=json.loads(r["steps_json"] or '["build"]'),
            schedule=r["schedule"],
            enabled=bool(r["enabled"]),
            last_run_at=r["last_run_at"],
            last_run_outcome=r["last_run_outcome"],
            last_run_error=r["last_run_error"],
            last_run_stats=json.loads(r["last_run_stats_json"] or "{}"),
        )
    return result


def save_automations(db_path: str | Path, automations: dict[str, Automation]) -> None:
    conn = get_thread_connection(db_path)
    with conn:
        conn.execute("DELETE FROM automations")
        for a in automations.values():
            conn.execute(
                """
                INSERT INTO automations
                    (id, ebook, steps_json, schedule, enabled,
                     last_run_at, last_run_outcome, last_run_error, last_run_stats_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    a.id, a.ebook, json.dumps(a.steps, ensure_ascii=False), a.schedule,
                    int(a.enabled), a.last_run_at, a.last_run_outcome, a.last_run_error,
                    json.dumps(a.last_run_stats, ensure_ascii=False),
                ),
            )


def add_automation(db_path: str | Path, ebook: str, steps: list[str], schedule: str = "manual") -> Automation:
    automations = load_automations(db_path)
    new_id = str(uuid.uuid4())
    automation = Automation(id=new_id, ebook=ebook, steps=list(steps), schedule=schedule)
    automations[new_id] = automation
    save_automations(db_path, automations)
    return automation


def update_automation(db_path: str | Path, automation_id: str, updates: dict[str, Any]) -> None:
    automations = load_automations(db_path)
    if automation_id not in automations:
        raise KeyError(f"không tìm thấy automation {automation_id!r}")
    current = automations[automation_id]
    data = asdict(current)
    data.update(updates)
    automations[automation_id] = Automation(**data)
    save_automations(db_path, automations)


def remove_automation(db_path: str | Path, automation_id: str) -> None:
    automations = load_automations(db_path)
    automations.pop(automation_id, None)
    save_automations(db_path, automations)
