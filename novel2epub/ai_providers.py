"""Preset provider AI OpenAI-compatible dùng lại (name → base_url), để chọn từ
danh sách thay vì gõ tay mỗi lần cấu hình Global AI / AI riêng từng ebook.

Lưu trong bảng `ai_providers` của DB thống nhất — cùng khuôn với `sources.py`
(name PK, data_json blob) nhưng tối giản hơn nhiều: không có domains/usage
tracking/test dry-run, vì đây chỉ là một shortcut điền base_url.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .db import get_thread_connection


@dataclass
class AiProviderPreset:
    name: str
    base_url: str = ""


_UPSERT_AI_PROVIDER_SQL = """
    INSERT INTO ai_providers (name, data_json) VALUES (?, ?)
    ON CONFLICT(name) DO UPDATE SET
        data_json = excluded.data_json,
        updated_at = datetime('now')
"""


def load_presets(path: str | Path) -> dict[str, AiProviderPreset]:
    """Đọc bảng `ai_providers` của DB tại `path`."""
    db_path = Path(path).resolve()
    if not db_path.exists():
        return {}
    conn = get_thread_connection(db_path)
    presets: dict[str, AiProviderPreset] = {}
    for r in conn.execute("SELECT name, data_json FROM ai_providers ORDER BY name"):
        item = json.loads(r["data_json"] or "{}")
        presets[r["name"]] = AiProviderPreset(
            name=r["name"], base_url=str(item.get("base_url") or "")
        )
    return presets


def save_preset(path: str | Path, preset: AiProviderPreset) -> None:
    """Lưu đúng 1 provider bằng UPSERT — không ảnh hưởng preset khác."""
    db_path = Path(path).resolve()
    conn = get_thread_connection(db_path)
    data = {k: v for k, v in asdict(preset).items() if k != "name"}
    with conn:
        conn.execute(_UPSERT_AI_PROVIDER_SQL, (preset.name, json.dumps(data, ensure_ascii=False)))


def delete_preset(path: str | Path, name: str) -> None:
    """Xóa đúng 1 provider theo name; nếu không tồn tại thì bỏ qua."""
    db_path = Path(path).resolve()
    if not db_path.exists():
        return
    conn = get_thread_connection(db_path)
    with conn:
        conn.execute("DELETE FROM ai_providers WHERE name = ?", (name,))
