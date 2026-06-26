"""Gọi AI qua HTTP theo chuẩn OpenAI-Compatible (`POST {base_url}/chat/completions`,
`GET {base_url}/models`) — dùng chung cho translator.OpenAITranslator (dịch chương)
và glossary_ai (gợi ý/rewrite/evaluate), tránh lệch hành vi request/parse giữa 2 nơi.

Tương thích bất kỳ provider lộ endpoint kiểu OpenAI: OpenAI, OpenRouter, Ollama
(`http://localhost:11434/v1`), LM Studio, vLLM, llama.cpp server, v.v.
"""
from __future__ import annotations

import requests

from .config import OpenAIConfig


def _headers(cfg: OpenAIConfig) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"
    return headers


def list_models(base_url: str, api_key: str = "", timeout_seconds: int = 30) -> list[str]:
    """Gọi GET {base_url}/models, trả list model id. Raise nếu request lỗi.

    Dùng cho dropdown chọn model trong Settings — provider không hỗ trợ
    endpoint này (vd custom proxy) thì caller tự bắt exception và fallback
    sang input tự do.
    """
    url = base_url.rstrip("/") + "/models"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    resp = requests.get(url, headers=headers, timeout=timeout_seconds)
    resp.raise_for_status()
    data = resp.json()
    items = data.get("data", data) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    model_ids = []
    for item in items:
        if isinstance(item, dict) and item.get("id"):
            model_ids.append(str(item["id"]))
        elif isinstance(item, str):
            model_ids.append(item)
    return sorted(model_ids)


def run_chat(cfg: OpenAIConfig, prompt: str) -> str:
    """Gọi chat completion 1 lần (không retry), trả nội dung message đầu tiên.

    Raise RuntimeError nếu HTTP lỗi hoặc response không có nội dung hợp lệ.
    """
    url = cfg.base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg.model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": cfg.temperature,
    }
    try:
        resp = requests.post(
            url, headers=_headers(cfg), json=payload, timeout=cfg.timeout_seconds
        )
    except requests.exceptions.Timeout as e:
        raise RuntimeError(f"AI request quá thời gian ({cfg.timeout_seconds}s).") from e
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Không gọi được AI tại {url!r}: {e}") from e

    if resp.status_code != 200:
        detail = resp.text.strip()[:2000] or "(không có nội dung lỗi)"
        raise RuntimeError(f"AI trả về mã lỗi HTTP {resp.status_code}:\n{detail}")

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"AI trả về response không đúng định dạng OpenAI: {resp.text[:2000]}") from e

    if not content or not content.strip():
        raise RuntimeError("AI trả về nội dung rỗng — kiểm tra base_url/api_key/model trong config.")
    return content
