"""Translate ebook metadata without requiring an existing ebook."""
from __future__ import annotations

import json
import threading
from typing import Any

from . import openai_client
from .config import Config
from .translator import LocalMTTranslator, _clean_output

_local_mt_lock = threading.Lock()
_local_mt_cache: dict[str, LocalMTTranslator] = {}

MAX_TITLE_CHARS = 1000
MAX_AUTHOR_CHARS = 1000
MAX_DESCRIPTION_CHARS = 20000
MAX_SUBJECT_CHARS = 500
MAX_SUBJECTS = 100


def _local_mt_translator(cfg: Config) -> LocalMTTranslator:
    model_key = cfg.translate.hachimimt.model_key
    with _local_mt_lock:
        translator = _local_mt_cache.get(model_key)
        if translator is None:
            translator = LocalMTTranslator(cfg.translate)
            _local_mt_cache[model_key] = translator
        return translator


def _clean_subjects(subjects: list[str] | None) -> list[str]:
    return [str(item).strip() for item in (subjects or []) if str(item).strip()]


def _validate_lengths(title: str, author: str, description: str, subjects: list[str]) -> None:
    limits = {
        "title": (title, MAX_TITLE_CHARS),
        "author": (author, MAX_AUTHOR_CHARS),
        "description": (description, MAX_DESCRIPTION_CHARS),
    }
    for field, (value, limit) in limits.items():
        if len(value) > limit:
            raise ValueError(f"{field} quá dài ({len(value)} ký tự, tối đa {limit}).")
    if len(subjects) > MAX_SUBJECTS:
        raise ValueError(f"subjects có quá nhiều mục ({len(subjects)}, tối đa {MAX_SUBJECTS}).")
    for index, subject in enumerate(subjects):
        if len(subject) > MAX_SUBJECT_CHARS:
            raise ValueError(
                f"subjects[{index}] quá dài ({len(subject)} ký tự, tối đa {MAX_SUBJECT_CHARS})."
            )


def _ai_prompt(title: str, author: str, description: str, subjects: list[str]) -> str:
    source = {
        key: value
        for key, value in {
            "title": title,
            "author": author,
            "description": description,
            "subjects": subjects,
        }.items()
        if value not in ("", [])
    }
    return """Bạn là biên tập viên metadata sách sang tiếng Việt.
Dịch đúng các field có trong JSON đầu vào. Giữ nguyên tên riêng khi không chắc.
Không thêm thông tin. Giữ nguyên số lượng, thứ tự và boundary từng phần tử subjects.
Chỉ trả về một JSON object hợp lệ với đúng các key đầu vào; subjects phải là mảng chuỗi.

JSON đầu vào:
""" + json.dumps(source, ensure_ascii=False)


def _parse_ai_json(raw: str) -> dict[str, Any]:
    text = _clean_output(raw).strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"AI không trả về JSON metadata hợp lệ: {exc.msg}.") from exc
    if not isinstance(value, dict):
        raise RuntimeError("AI không trả về JSON object metadata.")
    return value


def _translate_with_ai(
    cfg: Config,
    title: str,
    author: str,
    description: str,
    subjects: list[str],
) -> tuple[dict[str, Any], dict[str, str]]:
    raw = openai_client.run_chat(cfg.ai.openai, _ai_prompt(title, author, description, subjects))
    parsed = _parse_ai_json(raw)
    draft: dict[str, Any] = {"title": "", "author": "", "description": "", "subjects": []}
    errors: dict[str, str] = {}
    source = {
        "title": title,
        "author": author,
        "description": description,
        "subjects": subjects,
    }
    for field in ("title", "author", "description"):
        if not source[field]:
            continue
        value = parsed.get(field)
        if not isinstance(value, str) or not value.strip():
            errors[field] = f"AI không trả về {field} hợp lệ."
            draft[field] = source[field]
        else:
            draft[field] = value.strip()
    if subjects:
        value = parsed.get("subjects")
        if not isinstance(value, list) or len(value) != len(subjects) or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            errors["subjects"] = "AI không giữ đúng số lượng/boundary subjects."
            draft["subjects"] = subjects
        else:
            draft["subjects"] = [item.strip() for item in value]
    return draft, errors


def _translate_with_local_mt(
    cfg: Config,
    title: str,
    author: str,
    description: str,
    subjects: list[str],
) -> tuple[dict[str, Any], dict[str, str]]:
    translator = _local_mt_translator(cfg)
    draft: dict[str, Any] = {"title": "", "author": "", "description": "", "subjects": []}
    errors: dict[str, str] = {}
    operations = (
        ("title", title, lambda value: translator.translate_title(value, "tên sách")[0]),
        ("author", author, translator.translate),
        ("description", description, translator.translate),
    )
    with _local_mt_lock:
        for field, value, translate in operations:
            if not value:
                continue
            try:
                draft[field] = translate(value)
            except Exception as exc:
                draft[field] = value
                errors[field] = str(exc)
        for index, subject in enumerate(subjects):
            try:
                draft["subjects"].append(translator.translate(subject))
            except Exception as exc:
                draft["subjects"].append(subject)
                errors[f"subjects[{index}]"] = str(exc)
    return draft, errors


def translate_ebook_metadata(
    cfg: Config,
    *,
    title: str = "",
    author: str = "",
    description: str = "",
    subjects: list[str] | None = None,
    engine: str = "localmt",
    model: str = "",
    source_language: str = "",
) -> dict[str, Any]:
    """Return a structured, non-persistent Vietnamese metadata draft."""
    title = title.strip()
    author = author.strip()
    description = description.strip()
    subjects = _clean_subjects(subjects)
    if not any((title, author, description, subjects)):
        raise ValueError("Chưa có metadata để dịch.")
    _validate_lengths(title, author, description, subjects)

    source_language = (source_language or cfg.translate.source_language).strip().lower()
    engine = engine.strip().lower()
    if engine not in {"localmt", "ai"}:
        raise ValueError("engine không hợp lệ (localmt|ai).")

    if source_language == "vi":
        draft = {
            "title": title,
            "author": author,
            "description": description,
            "subjects": list(subjects),
        }
        used_model = "passthrough"
        errors: dict[str, str] = {}
    elif engine == "localmt":
        draft, errors = _translate_with_local_mt(cfg, title, author, description, subjects)
        used_model = cfg.translate.hachimimt.model_key
    else:
        original_model = cfg.ai.openai.model
        if model.strip():
            cfg.ai.openai.model = model.strip()
        try:
            draft, errors = _translate_with_ai(cfg, title, author, description, subjects)
            used_model = cfg.ai.openai.model
        finally:
            cfg.ai.openai.model = original_model

    return {
        "draft": draft,
        "title": draft["title"],
        "author": draft["author"],
        "description": draft["description"],
        "subjects": draft["subjects"],
        "engine": engine,
        "model": used_model,
        "source_language": source_language,
        "errors": errors,
    }
