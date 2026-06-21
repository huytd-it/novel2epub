"""Helper dùng chung giữa các router: đọc config (global hoặc theo ebook trong
library.yaml), resolve đường dẫn, và Jinja2 templates.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import HTTPException
from fastapi.templating import Jinja2Templates

from novel2epub.config import load_config, load_library

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = os.environ.get("NOVEL2EPUB_CONFIG", "config.yaml")
LIBRARY_PATH = os.environ.get("NOVEL2EPUB_LIBRARY", "library.yaml")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def cfg():
    try:
        return load_config(CONFIG_PATH)
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=400,
            detail=f"{e} — copy config.example.yaml thành {CONFIG_PATH} rồi chỉnh sửa.",
        ) from e


def library():
    return load_library(LIBRARY_PATH)


def resolve_path(base: Path, value: str) -> str:
    if not value:
        return value
    p = Path(value)
    if p.is_absolute():
        return value
    return str((base / p).resolve())


def ebook_config_path(slug: str) -> str:
    lib = library()
    entry = lib.ebooks.get(slug)
    if entry and entry.config:
        return resolve_path(Path(LIBRARY_PATH).resolve().parent, entry.config)
    return CONFIG_PATH


def ebook_cfg(slug: str):
    try:
        return load_config(ebook_config_path(slug))
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def resolved_cfg(slug: str):
    """cfg theo ebook nếu library.yaml có khai báo, ngược lại dùng config global."""
    return ebook_cfg(slug) if library().ebooks else cfg()
