"""Automation: chuỗi bước pipeline (fetch-toc → crawl-new → translate-pending
→ build → publish-reader) chạy theo lịch hoặc tay — lưu trong bảng
`automations` của DB thống nhất (trước đây là `workspace/.n2e/automations.yaml`
round-trip ruamel).
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from croniter import croniter

from .db import get_thread_connection

STEPS = ("fetch-toc", "crawl-new", "translate-pending", "cleanup-han", "build", "publish-reader")


def validate_schedule(s: str) -> bool:
    """True nếu `s` là lịch hợp lệ: "manual" hoặc biểu thức cron croniter
    chấp nhận (5 trường chuẩn; croniter cũng nhận @daily/6 trường — vẫn coi
    là hợp lệ vì scheduler xử lý được)."""
    if s == "manual":
        return True
    return croniter.is_valid(s)


logger = logging.getLogger("novel2epub.automation")

_LEGACY_DAILY = re.compile(r"^daily@(\d{1,2}):(\d{1,2})$")
_LEGACY_CONTINUOUS = re.compile(r"^continuous(?:@(-?\d+))?$")


def migrate_schedule(s: str) -> str:
    """Đổi lịch cú pháp cũ (daily@HH:MM / continuous[@N]) sang cron 5 trường.

    Giá trị đã hợp lệ giữ nguyên; không nhận diện được (kể cả daily@25:00,
    continuous@0, typo) → "manual" + log warning. Idempotent."""
    if validate_schedule(s):
        return s
    m = _LEGACY_DAILY.match(s)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return f"{mm} {hh} * * *"
        logger.warning("Lịch cũ không hợp lệ %r → manual", s)
        return "manual"
    m = _LEGACY_CONTINUOUS.match(s)
    if m:
        n = int(m.group(1)) if m.group(1) else 30
        if n < 1:
            logger.warning("Lịch cũ không hợp lệ %r → manual", s)
            return "manual"
        if n <= 59:
            return f"*/{n} * * * *"
        return f"0 */{min(23, max(1, round(n / 60)))} * * *"
    logger.warning("Lịch không nhận diện được %r → manual", s)
    return "manual"


@dataclass
class Automation:
    id: str
    ebook: str
    steps: list[str] = field(default_factory=lambda: ["build"])
    # "manual" | biểu thức cron 5 trường (vd "*/30 * * * *") — cú pháp cũ
    # daily@HH:MM / continuous[@N] được load_automations tự migrate
    schedule: str = "manual"
    enabled: bool = True
    last_run_at: str = ""
    last_run_outcome: str = ""  # "" | "success" | "failure" | "partial"
    last_run_error: str = ""  # "{step}: {lỗi}" của lần chạy gần nhất, "" nếu thành công
    last_run_stats: dict = field(default_factory=dict)  # {"chapters_total", "crawled", "translated", "han_fixed"}
    created_at: str = ""  # ISO datetime lúc tạo — base tính đến hạn khi chưa từng chạy


def load_automations(db_path: str | Path) -> dict[str, Automation]:
    """Đọc toàn bộ automation; tiện thể migrate lịch cú pháp cũ sang cron và
    backfill `created_at` còn trống (ghi lại DB khi có thay đổi — idempotent)."""
    conn = get_thread_connection(db_path)
    rows = conn.execute("SELECT * FROM automations").fetchall()
    result: dict[str, Automation] = {}
    changed = False
    for r in rows:
        schedule = migrate_schedule(r["schedule"])
        created_at = r["created_at"] or datetime.now().isoformat()
        if schedule != r["schedule"] or created_at != r["created_at"]:
            changed = True
        result[r["id"]] = Automation(
            id=r["id"],
            ebook=r["ebook"],
            steps=json.loads(r["steps_json"] or '["build"]'),
            schedule=schedule,
            enabled=bool(r["enabled"]),
            last_run_at=r["last_run_at"],
            last_run_outcome=r["last_run_outcome"],
            last_run_error=r["last_run_error"],
            last_run_stats=json.loads(r["last_run_stats_json"] or "{}"),
            created_at=created_at,
        )
    if changed:
        save_automations(db_path, result)
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
                     last_run_at, last_run_outcome, last_run_error, last_run_stats_json,
                     created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    a.id, a.ebook, json.dumps(a.steps, ensure_ascii=False), a.schedule,
                    int(a.enabled), a.last_run_at, a.last_run_outcome, a.last_run_error,
                    json.dumps(a.last_run_stats, ensure_ascii=False), a.created_at,
                ),
            )


def add_automation(db_path: str | Path, ebook: str, steps: list[str], schedule: str = "manual") -> Automation:
    automations = load_automations(db_path)
    new_id = str(uuid.uuid4())
    automation = Automation(
        id=new_id, ebook=ebook, steps=list(steps), schedule=schedule,
        created_at=datetime.now().isoformat(),
    )
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
