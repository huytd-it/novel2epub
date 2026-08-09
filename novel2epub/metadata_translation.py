"""Translate shared ebook metadata without requiring an existing ebook."""
from __future__ import annotations

import re
import threading

from . import openai_client
from .config import Config
from .translator import LocalMTTranslator, _clean_output


_TITLE_MARKER = re.compile(r"^TITLE:\s*(.*)$", re.IGNORECASE)
_DESCRIPTION_MARKER = re.compile(r"^DESCRIPTION:\s*(.*)$", re.IGNORECASE)
_local_mt_lock = threading.Lock()
_local_mt_cache: dict[str, LocalMTTranslator] = {}


def _local_mt_translator(cfg: Config) -> LocalMTTranslator:
    model_key = cfg.translate.hachimimt.model_key
    with _local_mt_lock:
        translator = _local_mt_cache.get(model_key)
        if translator is None:
            translator = LocalMTTranslator(cfg.translate)
            _local_mt_cache[model_key] = translator
        return translator


def _translate_with_ai(cfg: Config, title: str, description: str) -> tuple[str, str]:
    prompt = f"""Bạn là biên tập viên metadata sách Trung-Việt.
Dịch thông tin sau sang tiếng Việt tự nhiên, rõ nghĩa và phù hợp để hiển thị trong thư viện.
Giữ nguyên tên riêng khi không chắc cách dịch. Không thêm nhận xét, quảng cáo hoặc thông tin không có trong bản gốc.

Trả lời đúng định dạng:
TITLE: <tên sách tiếng Việt>
DESCRIPTION: <mô tả tiếng Việt; được phép nhiều dòng>

TITLE: {title}
DESCRIPTION: {description}"""
    raw = _clean_output(openai_client.run_chat(cfg.ai.openai, prompt))
    translated_title = ""
    description_lines: list[str] = []
    in_description = False
    for line in raw.splitlines():
        title_match = _TITLE_MARKER.match(line)
        if title_match:
            translated_title = title_match.group(1).strip()
            in_description = False
            continue
        description_match = _DESCRIPTION_MARKER.match(line)
        if description_match:
            description_lines = [description_match.group(1).strip()]
            in_description = True
            continue
        if in_description:
            description_lines.append(line)
    if not translated_title and title:
        raise RuntimeError("AI không trả về TITLE đúng định dạng.")
    translated_description = "\n".join(description_lines).strip()
    if not translated_description and description:
        raise RuntimeError("AI không trả về DESCRIPTION đúng định dạng.")
    return translated_title or title, translated_description or description


def translate_ebook_metadata(
    cfg: Config,
    *,
    title: str = "",
    description: str = "",
    engine: str = "localmt",
) -> dict[str, str]:
    """Translate title/description for the add-ebook preview form."""
    title = title.strip()
    description = description.strip()
    if not title and not description:
        raise ValueError("Chưa có title hoặc description để dịch.")

    engine = engine.strip().lower()
    if engine == "localmt":
        translator = _local_mt_translator(cfg)
        with _local_mt_lock:
            translated_title = translator.translate_title(title, "tên sách")[0] if title else ""
            translated_description = translator.translate(description) if description else ""
    elif engine == "ai":
        translated_title, translated_description = _translate_with_ai(cfg, title, description)
    else:
        raise ValueError("engine không hợp lệ (localmt|ai).")

    return {
        "title": translated_title,
        "description": translated_description,
        "engine": engine,
    }
