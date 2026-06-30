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
CONFIG_PATH = WORKSPACE_PATH
LIBRARY_PATH = WORKSPACE_PATH
# File sources tách riêng, nằm cùng thư mục với config.
_cfg_dir = str(Path(WORKSPACE_PATH).resolve().parent)
SOURCES_PATH = os.path.join(_cfg_dir, "sources.yaml")
# Sidecar workspace state (lịch sử queue, automation, archived flags...) —
# nằm cạnh file config gộp, không commit (xem design.md D3).
WORKSPACE_DIR = Path(WORKSPACE_PATH).resolve().parent / ".n2e"
AUTOMATIONS_PATH = WORKSPACE_DIR / "automations.yaml"
LIBRARY_STATE_PATH = WORKSPACE_DIR / "library_state.json"

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# ── Config default values ───────────────────────────────────────────
# Mirrors dataclass defaults from novel2epub/config.py for UI display.
# Keyed: section -> field -> default_value
_CONFIG_DEFAULTS: dict[str, dict[str, object]] = {
    "novel": {
        "title": "",
        "author": "",
        "language": "vi",
        "publisher": "",
        "pubdate": "",
        "subjects": [],
        "series": "",
        "series_index": "",
        "identifier": "",
    },
    "crawl": {
        "toc_url": "",
        "chapter_link_pattern": r".*",
        "max_chapters": 0,
        "delay_seconds": 1.0,
        "content_selector": "",
        "headless": True,
        "scrapling": {"mode": "fetcher", "solve_cloudflare": False, "network_idle": True, "impersonate": ""},
        "next_page_selector": "",
        "next_page_url_pattern": "",
        "max_pages_per_chapter": 10,
        "retry": {"attempts": 3, "delay_seconds": 5.0, "backoff": 2.0, "max_delay_seconds": 120.0, "respect_retry_after": True},
        "max_workers": 1,
        "concurrency_cap": 0,
        "ai_fallback": False,
        "ai_fallback_max_html": 32000,
    },
    "ai": {
        "openai": {"base_url": "https://api.openai.com/v1", "api_key": "", "model": "gpt-4o-mini", "timeout_seconds": 300, "temperature": 0.7},
    },
    "translate": {
        "type": "hachimimt",
        "model": "",
        "preset": "",
        "source_language": "",
        "target_language": "vi",
        "genre": "",
        "style": {"tone": "mượt, tự nhiên, có chất cổ trang", "pronoun_policy": "contextual", "title_mode": "creative", "han_viet_level": "balanced", "keep_paragraphs": True},
        "retry": {"attempts": 1, "delay_seconds": 0.0},
        "chunk": {"max_chars": 0, "overlap_paragraphs": 0},
        "openai": {"base_url": "https://api.openai.com/v1", "api_key": "", "model": "gpt-4o-mini", "timeout_seconds": 300, "temperature": 0.7},
        "hachimimt": {"model_key": "HachimiMT-60", "backend": "ctranslate2", "beam_size": 2, "chunk_mode": "sentence"},
        "delay_seconds": 0.5,
        "max_workers": 1,
    },
    "output": {
        "data_dir": "data",
        "epub_path": "",
    },
}


def defaults_for(section: str, field: str) -> object:
    """Return the default value for a config field, or None if unknown."""
    sec = _CONFIG_DEFAULTS.get(section)
    if sec is None:
        return None
    return sec.get(field)


def is_default(current: object, section: str, field: str) -> bool:
    """Check if a config field currently holds its default value."""
    default = defaults_for(section, field)
    return current == default


templates.env.filters["default_value"] = defaults_for
templates.env.filters["is_default"] = is_default
templates.env.globals["default_value"] = defaults_for
templates.env.globals["is_default"] = is_default


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
    return load_presets(SOURCES_PATH)


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
