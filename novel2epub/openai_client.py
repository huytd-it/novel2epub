"""Gọi AI qua HTTP theo chuẩn OpenAI-Compatible (`POST {base_url}/chat/completions`,
`GET {base_url}/models`) — dùng chung cho translator.OpenAITranslator (dịch chương)
và glossary_ai (gợi ý/rewrite/evaluate), tránh lệch hành vi request/parse giữa 2 nơi.

Tương thích bất kỳ provider lộ endpoint kiểu OpenAI: OpenAI, OpenRouter, Ollama
(`http://localhost:11434/v1`), LM Studio, vLLM, llama.cpp server, OmniRoute
(`http://localhost:20128/v1`), v.v.
"""
from __future__ import annotations

import json
import time
from typing import Any

import requests

from .config import OpenAIConfig


class RetryableAIError(RuntimeError):
    """Lỗi tạm thời từ provider/proxy — gọi lại thường rơi sang node/model khác.

    Timeout, rate limit và 5xx đều là lỗi hạ tầng, không phải lỗi logic prompt;
    lần gọi sau với đúng prompt đó thường thành công.
    """


# Mã lỗi HTTP cho thấy lỗi hạ tầng tạm thời (có thể thử lại).
_RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524})
# Mã lỗi provider/proxy trong body (kể cả SSE `error.code`) tạm thời.
_RETRYABLE_CODE_HINTS = (
    "timeout", "timedout", "rate_limit", "ratelimit", "overload", "upstream",
    "unavailable", "server_error", "internal_error", "capacity", "busy",
    "temporar", "thời hạn", "try_again",
)


def _is_retryable_code(code: str, detail: str = "") -> bool:
    """Mã lỗi provider có phải lỗi tạm thời (đáng gọi lại) không."""
    text = f"{code} {detail}".lower()
    return any(hint in text for hint in _RETRYABLE_CODE_HINTS)


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


def _truncate_log(text: str, limit: int = 500) -> str:
    """Rút gọn một dòng log: gộp whitespace, cắt ở `limit` ký tự."""
    single = " ".join(str(text).split())
    if len(single) > limit:
        return single[:limit] + f"…(+{len(single) - limit} ký tự)"
    return single


def _parse_sse_lines(lines) -> tuple[str, str, bool]:
    """Ghép chat chunks; chỉ dùng final message nếu không có delta để tránh lặp.

    Diagnostic tóm tắt cấu trúc (số events, keys, finish_reason, error message
    rút gọn) để đủ dữ liệu debug mà không đổ nguyên nội dung AI/reasoning vào
    log — xem `test_run_chat_with_meta_sse_empty_diagnostics_no_response_body`.
    Trả `(content, diagnostic, retryable)`: `retryable` đúng khi stream rỗng vì
    lỗi tạm thời (timeout/rate limit/5xx) nên đáng gọi lại.
    """
    parts: list[str] = []
    final_message = ""
    events = 0
    choices_seen = 0
    finish_reason = ""
    error_code = ""
    error_detail = ""
    choice_hint = ""
    invalid_sample = ""
    for line in lines:
        if isinstance(line, bytes):
            line = line.decode("utf-8", errors="replace")
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if not payload or payload == "[DONE]":
            continue
        events += 1
        try:
            data = json.loads(payload)
        except (ValueError, TypeError):
            if not invalid_sample and payload:
                invalid_sample = _truncate_log(payload, 200)
            continue
        if not isinstance(data, dict):
            continue
        error = data.get("error")
        if isinstance(error, dict):
            code = error.get("code") or error.get("type")
            if isinstance(code, str) and code.replace("_", "").replace("-", "").isalnum():
                error_code = code[:80]
            if not error_detail:
                for key in ("message", "detail", "msg", "error", "description"):
                    val = error.get(key)
                    if isinstance(val, str) and val.strip():
                        error_detail = _truncate_log(val, 500)
                        break
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            continue
        choices_seen += 1
        choice = choices[0]
        if isinstance(choice.get("finish_reason"), str):
            reason = choice["finish_reason"]
            if reason.replace("_", "").isalnum():
                finish_reason = reason[:80]
        delta = choice.get("delta")
        if isinstance(delta, dict) and isinstance(delta.get("content"), str):
            parts.append(delta["content"])
        message = choice.get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            final_message = message["content"]
        if not choice_hint:
            hints: list[str] = []
            if isinstance(delta, dict):
                hints.append("delta_keys=" + ",".join(sorted(str(k) for k in delta.keys()))[:120])
                if delta.get("tool_calls"):
                    hints.append("has_tool_calls=True")
                if delta.get("reasoning_content") or delta.get("reasoning"):
                    hints.append("has_reasoning=True")
            if isinstance(message, dict):
                hints.append("message_keys=" + ",".join(sorted(str(k) for k in message.keys()))[:120])
                if message.get("tool_calls"):
                    hints.append("has_tool_calls=True")
            role = (delta or {}).get("role") if isinstance(delta, dict) else None
            if isinstance(role, str) and role.replace("_", "").isalnum():
                hints.append(f"role={role[:32]}")
            if hints:
                choice_hint = " ".join(hints)[:300]
    diagnostic = f"events={events}, choices={choices_seen}"
    if finish_reason:
        diagnostic += f", finish_reason={finish_reason}"
    if error_code:
        diagnostic += f", error={error_code}"
    if error_detail:
        diagnostic += f", error_detail={error_detail}"
    if not "".join(parts) and not final_message and choice_hint:
        diagnostic += f", choice[{choice_hint}]"
    if events and not choices_seen and invalid_sample and not error_detail:
        diagnostic += f", sample={invalid_sample}"
    return "".join(parts) or final_message, diagnostic, _is_retryable_code(error_code, error_detail)


def _parse_sse_response_by_lines(resp: requests.Response) -> str:
    """Đọc streaming `resp.iter_lines()` và ghép `delta.content` từ từng chunk SSE.

    Xử lý từng dòng `data: {...}` ngay khi server gửi — không đợi toàn bộ
    response như `_parse_sse_response`. Bỏ qua `event: progress` nếu OmniRoute
    gửi kèm X-OmniRoute-Progress header.
    """
    content, _diagnostic, _retryable = _parse_sse_lines(resp.iter_lines())
    return content


def _parse_sse_response(text: str) -> str:
    """Parse Server-Sent Events (SSE) `text/event-stream` response từ OpenAI-Compatible
    API — một số provider (vd Qwen, GLM) tự stream dù client không yêu cầu.

    Trả nội dung `delta.content` ghép từ tất cả chunk `data: {...}` (bỏ qua
    `data: [DONE]` và chunk không có content).
    """
    content, _diagnostic, _retryable = _parse_sse_lines(text.splitlines())
    return content


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
        raise RetryableAIError(f"AI request quá thời gian ({cfg.timeout_seconds}s).") from e
    except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError) as e:
        raise RetryableAIError(f"AI không giữ được kết nối tại {url!r}: {e}") from e
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Không gọi được AI tại {url!r}: {e}") from e

    if resp.status_code != 200:
        detail = resp.text.strip()[:2000] or "(không có nội dung lỗi)"
        message = f"AI trả về mã lỗi HTTP {resp.status_code}:\n{detail}"
        if resp.status_code in _RETRYABLE_STATUS or _is_retryable_code("", detail):
            raise RetryableAIError(message)
        raise RuntimeError(message)

    meta = _parse_omniroute_headers(resp.headers)
    content_type = (resp.headers.get("Content-Type") or "").lower()

    if "text/event-stream" in content_type:
        content, diagnostic, retryable = _parse_sse_lines(resp.iter_lines())
        if not content.strip():
            message = f"AI trả về SSE stream nhưng không có content ({diagnostic})."
            raise (RetryableAIError if retryable else RuntimeError)(message)
        return content, meta

    # Provider trả về non-streaming dù `stream: true` -> fallback
    raw = resp.text
    if raw.lstrip().startswith("data:"):
        content, diagnostic, retryable = _parse_sse_lines(raw.splitlines())
        if not content.strip():
            message = f"AI trả về SSE stream (từ full body) nhưng không có content ({diagnostic})."
            raise (RetryableAIError if retryable else RuntimeError)(message)
        return content, meta

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"AI trả về response không đúng định dạng OpenAI: {raw[:2000]}") from e

    if not content or not content.strip():
        raise RuntimeError("AI trả về nội dung rỗng — kiểm tra base_url/api_key/model trong config.")
    return content, meta


def run_chat_with_retry(
    cfg: OpenAIConfig,
    prompt: str,
    *,
    attempts: int = 2,
    delay_seconds: float = 0.0,
    log=None,
) -> str:
    """`run_chat` có thử lại khi provider báo lỗi tạm thời.

    Chỉ thử lại `RetryableAIError` (timeout, rate limit, 5xx): API thường
    round-robin node/model nên gọi lại cùng prompt thường rơi sang node khác
    và pass. Lỗi logic (401, sai định dạng) không thử lại — raise ngay để
    caller quyết định.
    """
    attempts = max(1, int(attempts))
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return run_chat(cfg, prompt)
        except RetryableAIError as exc:
            last = exc
            if attempt == attempts:
                break
            if log is not None:
                log(f"AI lỗi tạm thời ({exc}); thử lại lần {attempt + 1}/{attempts} sau {delay_seconds:.0f}s.")
            if delay_seconds > 0:
                time.sleep(delay_seconds)
    raise last


def run_chat(cfg: OpenAIConfig, prompt: str) -> str:
    """Gọi chat completion 1 lần (không retry), trả nội dung message đầu tiên.

    Raise RuntimeError nếu HTTP lỗi hoặc response không có nội dung hợp lệ.
    """
    content, _meta = run_chat_with_meta(cfg, prompt)
    return content


def chat_with_tools(
    cfg: OpenAIConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    """Gọi chat completion kèm `tools` (OpenAI function-calling), không stream.

    Trả message đầu tiên nguyên dạng dict: `{"role", "content", "tool_calls"}` —
    `tool_calls` là list `{"id", "name", "arguments"}` (arguments đã parse JSON,
    lỗi parse → dict rỗng). Không có tool call thì `tool_calls` rỗng.
    Raise RuntimeError nếu HTTP lỗi / response sai định dạng.
    """
    url = cfg.base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg.model,
        "messages": messages,
        "temperature": cfg.temperature,
        "tools": tools,
        "tool_choice": "auto",
    }
    try:
        resp = requests.post(
            url, headers=_headers(cfg), json=payload, timeout=cfg.timeout_seconds,
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
        message = data["choices"][0]["message"]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise RuntimeError(
            f"AI trả về response không đúng định dạng OpenAI: {resp.text[:2000]}"
        ) from e

    raw_calls = message.get("tool_calls") or []
    tool_calls: list[dict[str, Any]] = []
    for call in raw_calls:
        if not isinstance(call, dict):
            continue
        fn = call.get("function") or {}
        name = fn.get("name") or ""
        raw_args = fn.get("arguments") or "{}"
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
        except (ValueError, TypeError):
            args = {}
        if not isinstance(args, dict):
            args = {}
        tool_calls.append({"id": call.get("id") or "", "name": str(name), "arguments": args})
    return {
        "role": message.get("role") or "assistant",
        "content": message.get("content") or "",
        "tool_calls": tool_calls,
    }

