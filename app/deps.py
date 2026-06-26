"""Helper dùng chung giữa các router: đọc config (global hoặc theo ebook trong
library.yaml), resolve đường dẫn, và Jinja2 templates.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import HTTPException
from fastapi.templating import Jinja2Templates

from novel2epub.config import load_config, load_library
from novel2epub.sources import load_presets

BASE_DIR = Path(__file__).resolve().parent
# File cấu hình gộp duy nhất (defaults + sources + ebooks). NOVEL2EPUB_CONFIG
# giữ làm fallback để tương thích lệnh/script cũ.
WORKSPACE_PATH = os.environ.get(
    "NOVEL2EPUB_FILE", os.environ.get("NOVEL2EPUB_CONFIG", "novel2epub.yaml")
)
# Alias: nhiều route/template còn tham chiếu 3 tên cũ — đều trỏ về 1 file gộp.
CONFIG_PATH = WORKSPACE_PATH
LIBRARY_PATH = WORKSPACE_PATH
SOURCES_PATH = WORKSPACE_PATH
# Sidecar workspace state (lịch sử queue, automation, archived flags...) —
# nằm cạnh file config gộp, không commit (xem design.md D3).
WORKSPACE_DIR = Path(WORKSPACE_PATH).resolve().parent / ".n2e"
AUTOMATIONS_PATH = WORKSPACE_DIR / "automations.yaml"
LIBRARY_STATE_PATH = WORKSPACE_DIR / "library_state.json"

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def cfg():
    try:
        return load_config(WORKSPACE_PATH)
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=400,
            detail=f"{e} — copy novel2epub.example.yaml thành {WORKSPACE_PATH} rồi chỉnh sửa.",
        ) from e


def library():
    return load_library(WORKSPACE_PATH)


def presets():
    return load_presets(WORKSPACE_PATH)


def resolve_path(base: Path, value: str) -> str:
    if not value:
        return value
    p = Path(value)
    if p.is_absolute():
        return value
    return str((base / p).resolve())


def ebook_config_path(slug: str) -> str:
    # File gộp: mọi ebook nằm inline trong cùng file. Trả về để hiển thị.
    return WORKSPACE_PATH


def ebook_cfg(slug: str):
    try:
        return load_config(WORKSPACE_PATH, slug)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


def resolved_cfg(slug: str):
    """cfg theo ebook nếu file gộp có khai báo ebook, ngược lại dùng defaults."""
    return ebook_cfg(slug) if library().ebooks else cfg()
