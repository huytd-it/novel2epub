"""Gọi AI qua HTTP theo chuẩn OpenAI-Compatible (`POST {base_url}/chat/completions`,
`GET {base_url}/models`) — dùng chung cho translator.OpenAITranslator (dịch chương)
và glossary_ai (gợi ý/rewrite/evaluate), tránh lệch hành vi request/parse giữa 2 nơi.

Tương thích bất kỳ provider lộ endpoint kiểu OpenAI: OpenAI, OpenRouter, Ollama
(`http://localhost:11434/v1`), LM Studio, vLLM, llama.cpp server, OmniRoute
(`http://localhost:20128/v1`), v.v.
"""
from __future__ import annotations

import json

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


def _parse_omniroute_headers(headers) -> dict[str, Any]:
    """Trích các X-OmniRoute-* headers (cost, tokens, latency, cache...) từ
    response. Trả dict rỗng nếu response không phải từ OmniRoute (thiếu header
    `X-OmniRoute-Version`).

    Xem https://github.com/diegosouzapw/OmniRoute/blob/main/docs/reference/API_REFERENCE.md
    cho đầy đủ ý nghĩa các header.
    """
    if not headers:
        return {}
    get = headers.get if hasattr(headers, "get") else lambda k, d=None: d
    version = get("X-OmniRoute-Version")
    if not version:
        return {}
    meta: dict[str, Any] = {"version": str(version)}
    cost = get("X-OmniRoute-Response-Cost")
    if cost is not None:
        try:
            meta["cost_usd"] = float(cost)
        except (TypeError, ValueError):
            pass
    for header, key in (
        ("X-OmniRoute-Tokens-In", "tokens_in"),
        ("X-OmniRoute-Tokens-Out", "tokens_out"),
    ):
        val = get(header)
        if val is not None:
            try:
                meta[key] = int(val)
            except (TypeError, ValueError):
                pass
    actual_model = get("X-OmniRoute-Model")
    if actual_model:
        meta["actual_model"] = str(actual_model)
    provider = get("X-OmniRoute-Provider")
    if provider:
        meta["provider"] = str(provider)
    latency = get("X-OmniRoute-Latency-Ms")
    if latency is not None:
        try:
            meta["latency_ms"] = int(latency)
        except (TypeError, ValueError):
            pass
    cache_hit = get("X-OmniRoute-Cache-Hit")
    if cache_hit is not None:
        meta["cache_hit"] = str(cache_hit).lower() == "true"
    cost_saved = get("X-OmniRoute-Cost-Saved")
    if cost_saved is not None:
        try:
            meta["cost_saved_usd"] = float(cost_saved)
        except (TypeError, ValueError):
            pass
    req_id = get("X-OmniRoute-Request-Id")
    if req_id:
        meta["request_id"] = str(req_id)
    return meta


def _parse_sse_response_by_lines(resp: requests.Response) -> str:
    """Đọc streaming `resp.iter_lines()` và ghép `delta.content` từ từng chunk SSE.

    Xử lý từng dòng `data: {...}` ngay khi server gửi — không đợi toàn bộ
    response như `_parse_sse_response`. Bỏ qua `event: progress` nếu OmniRoute
    gửi kèm X-OmniRoute-Progress header.
    """
    parts: list[str] = []
    for line in resp.iter_lines():
        if not line:
            continue
        decoded = line.decode("utf-8", errors="replace").strip()
        if not decoded.startswith("data:"):
            continue
        payload = decoded[len("data:"):].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            data = json.loads(payload)
        except (ValueError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        choices = data.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta") or {}
        chunk_content = delta.get("content")
        if chunk_content:
            parts.append(chunk_content)
    return "".join(parts)


def _parse_sse_response(text: str) -> str:
    """Parse Server-Sent Events (SSE) `text/event-stream` response từ OpenAI-Compatible
    API — một số provider (vd Qwen, GLM) tự stream dù client không yêu cầu.

    Trả nội dung `delta.content` ghép từ tất cả chunk `data: {...}` (bỏ qua
    `data: [DONE]` và chunk không có content).
    """
    parts: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            data = json.loads(payload)
        except (ValueError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        choices = data.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta") or {}
        chunk_content = delta.get("content")
        if chunk_content:
            parts.append(chunk_content)
    return "".join(parts)


def run_chat_with_meta(
    cfg: OpenAIConfig, prompt: str
) -> tuple[str, dict[str, Any]]:
    """Giống `run_chat` nhưng trả thêm dict metadata về response (OmniRoute headers).

    Return: (content, meta). `meta` rỗng nếu response không từ OmniRoute.
    Raise RuntimeError nếu HTTP lỗi / response không hợp lệ.

    Gửi `stream: true` để nhận SSE chunks ngay khi AI sinh — giảm first-token
    latency so với `stream: false` (chờ toàn bộ response). Nếu server trả về
    `text/event-stream`, parse từng dòng `data: {...}` và ghép `delta.content`.
    Kèm header `X-OmniRoute-Progress: true` để nhận progress events khi proxy
    qua OmniRoute.
    """
    url = cfg.base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg.model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": cfg.temperature,
        "stream": True,
    }
    headers = _headers(cfg)
    headers["X-OmniRoute-Progress"] = "true"
    try:
        resp = requests.post(
            url, headers=headers, json=payload,
            timeout=cfg.timeout_seconds, stream=True,
        )
    except requests.exceptions.Timeout as e:
        raise RuntimeError(f"AI request quá thời gian ({cfg.timeout_seconds}s).") from e
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Không gọi được AI tại {url!r}: {e}") from e

    if resp.status_code != 200:
        detail = resp.text.strip()[:2000] or "(không có nội dung lỗi)"
        raise RuntimeError(f"AI trả về mã lỗi HTTP {resp.status_code}:\n{detail}")

    meta = _parse_omniroute_headers(resp.headers)
    content_type = (resp.headers.get("Content-Type") or "").lower()

    if "text/event-stream" in content_type:
        content = _parse_sse_response_by_lines(resp)
        if not content.strip():
            raise RuntimeError("AI trả về SSE stream nhưng không có content.")
        return content, meta

    # Provider trả về non-streaming dù `stream: true` -> fallback
    raw = resp.text
    if raw.lstrip().startswith("data:"):
        content = _parse_sse_response(raw)
        if not content.strip():
            raise RuntimeError("AI trả về SSE stream (từ full body) nhưng không có content.")
        return content, meta

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"AI trả về response không đúng định dạng OpenAI: {raw[:2000]}") from e

    if not content or not content.strip():
        raise RuntimeError("AI trả về nội dung rỗng — kiểm tra base_url/api_key/model trong config.")
    return content, meta


def run_chat(cfg: OpenAIConfig, prompt: str) -> str:
    """Gọi chat completion 1 lần (không retry), trả nội dung message đầu tiên.

    Raise RuntimeError nếu HTTP lỗi hoặc response không có nội dung hợp lệ.
    """
    content, _meta = run_chat_with_meta(cfg, prompt)
    return content

