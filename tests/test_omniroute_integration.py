"""Tests cho tích hợp OmniRoute: parse cost/tokens headers, aggregate qua
nhiều chunk, drain_last_meta."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from novel2epub import openai_client
from novel2epub.config import OpenAIConfig, TranslateConfig
from novel2epub.translator import OpenAITranslator


# ── openai_client: _parse_omniroute_headers ──────────────────────────


def _make_response_headers(d: dict) -> SimpleNamespace:
    return SimpleNamespace(get=lambda k, default=None: d.get(k, default))


def test_parse_omniroute_headers_full():
    """Đầy đủ headers → dict chứa tất cả field parse được."""
    headers = _make_response_headers({
        "X-OmniRoute-Version": "3.8.40",
        "X-OmniRoute-Response-Cost": "0.001234",
        "X-OmniRoute-Tokens-In": "1234",
        "X-OmniRoute-Tokens-Out": "567",
        "X-OmniRoute-Model": "cc/claude-opus-4-6",
        "X-OmniRoute-Provider": "claude-code",
        "X-OmniRoute-Latency-Ms": "1500",
        "X-OmniRoute-Cache-Hit": "true",
        "X-OmniRoute-Cost-Saved": "0.005",
        "X-OmniRoute-Request-Id": "req-abc-123",
    })
    meta = openai_client._parse_omniroute_headers(headers)
    assert meta["version"] == "3.8.40"
    assert meta["cost_usd"] == 0.001234
    assert meta["tokens_in"] == 1234
    assert meta["tokens_out"] == 567
    assert meta["actual_model"] == "cc/claude-opus-4-6"
    assert meta["provider"] == "claude-code"
    assert meta["latency_ms"] == 1500
    assert meta["cache_hit"] is True
    assert meta["cost_saved_usd"] == 0.005
    assert meta["request_id"] == "req-abc-123"


def test_parse_omniroute_headers_no_version():
    """Thiếu X-OmniRoute-Version → dict rỗng (không phải response từ OmniRoute)."""
    headers = _make_response_headers({
        "X-OmniRoute-Response-Cost": "0.001",
        "Content-Type": "application/json",
    })
    assert openai_client._parse_omniroute_headers(headers) == {}


def test_parse_omniroute_headers_invalid_numbers():
    """Header cost/tokens không phải số → bỏ qua field đó, không raise."""
    headers = _make_response_headers({
        "X-OmniRoute-Version": "3.8.40",
        "X-OmniRoute-Response-Cost": "not-a-number",
        "X-OmniRoute-Tokens-In": "abc",
        "X-OmniRoute-Latency-Ms": "xyz",
    })
    meta = openai_client._parse_omniroute_headers(headers)
    assert meta["version"] == "3.8.40"
    assert "cost_usd" not in meta
    assert "tokens_in" not in meta
    assert "latency_ms" not in meta


def test_parse_omniroute_headers_cache_hit_false():
    """cache_hit='false' → False (không phải truthy string)."""
    headers = _make_response_headers({
        "X-OmniRoute-Version": "3.8.40",
        "X-OmniRoute-Cache-Hit": "false",
    })
    meta = openai_client._parse_omniroute_headers(headers)
    assert meta["cache_hit"] is False


# ── run_chat_with_meta ───────────────────────────────────────────────


class _FakeResp:
    def __init__(self, status_code=200, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._json_data

    def iter_lines(self):
        for line in self.text.splitlines():
            yield line.encode("utf-8")


def test_run_chat_with_meta_returns_content_and_meta(monkeypatch):
    """Happy path: response có OmniRoute headers → tuple (content, meta)."""
    cfg = OpenAIConfig(
        base_url="https://api.test/v1",
        model="m",
        api_key="k",
    )
    headers = {
        "X-OmniRoute-Version": "3.8.40",
        "X-OmniRoute-Response-Cost": "0.001",
        "X-OmniRoute-Tokens-In": "100",
        "X-OmniRoute-Tokens-Out": "50",
    }
    resp = _FakeResp(
        status_code=200,
        json_data={"choices": [{"message": {"content": "Xin chào"}}]},
        headers=headers,
    )
    monkeypatch.setattr(openai_client.requests, "post", lambda *a, **k: resp)
    content, meta = openai_client.run_chat_with_meta(cfg, "hi")
    assert content == "Xin chào"
    assert meta["version"] == "3.8.40"
    assert meta["cost_usd"] == 0.001
    assert meta["tokens_in"] == 100


def test_run_chat_with_meta_non_omniroute_returns_empty_meta(monkeypatch):
    """Response từ OpenAI thường (không có X-OmniRoute-Version) → meta rỗng."""
    cfg = OpenAIConfig(base_url="https://api.openai.com/v1", model="m", api_key="k")
    resp = _FakeResp(
        status_code=200,
        json_data={"choices": [{"message": {"content": "Hi"}}]},
        headers={"Content-Type": "application/json"},
    )
    monkeypatch.setattr(openai_client.requests, "post", lambda *a, **k: resp)
    content, meta = openai_client.run_chat_with_meta(cfg, "hi")
    assert content == "Hi"
    assert meta == {}


def test_run_chat_with_meta_raises_on_http_error(monkeypatch):
    """HTTP 401 → RuntimeError, không trả tuple."""
    cfg = OpenAIConfig(base_url="https://api.test/v1", model="m", api_key="k")
    resp = _FakeResp(status_code=401, text="unauthorized", headers={})
    monkeypatch.setattr(openai_client.requests, "post", lambda *a, **k: resp)
    with pytest.raises(RuntimeError, match="401"):
        openai_client.run_chat_with_meta(cfg, "hi")


def test_run_chat_backward_compat_still_returns_str(monkeypatch):
    """run_chat (không có _with_meta) vẫn trả str, không phá backward compat."""
    cfg = OpenAIConfig(base_url="https://api.test/v1", model="m", api_key="k")
    resp = _FakeResp(
        status_code=200,
        json_data={"choices": [{"message": {"content": "X"}}]},
        headers={"X-OmniRoute-Version": "3.8.40"},
    )
    monkeypatch.setattr(openai_client.requests, "post", lambda *a, **k: resp)
    result = openai_client.run_chat(cfg, "hi")
    assert isinstance(result, str)
    assert result == "X"


# ── OpenAITranslator: drain_last_meta + _merge_meta ──────────────────


def _make_openai_translator(**kwargs) -> OpenAITranslator:
    cfg = TranslateConfig(
        type="openai",
        openai=OpenAIConfig(
            base_url="https://api.test/v1",
            model="test-model",
            api_key="test-key",
            prompt_template="",
            title_prompt_template="",
        ),
        **kwargs,
    )
    return OpenAITranslator(cfg)


def test_drain_last_meta_empty_when_no_omniroute():
    """Translator chưa gọi AI → drain_last_meta trả dict rỗng."""
    t = _make_openai_translator()
    assert t.drain_last_meta() == {}
    # drain 2 lần vẫn rỗng
    assert t.drain_last_meta() == {}


def test_translate_aggregates_omniroute_meta(monkeypatch):
    """Khi response có X-OmniRoute-* headers, _last_chapter_meta được set sau translate()."""
    t = _make_openai_translator()

    def _mock_run_with_meta(cfg_, prompt):
        return ("Xin chào", {
            "version": "3.8.40",
            "cost_usd": 0.001,
            "tokens_in": 100,
            "tokens_out": 50,
            "actual_model": "cc/claude-opus-4-6",
            "latency_ms": 1500,
        })

    monkeypatch.setattr(
        "novel2epub.translator.openai_client.run_chat_with_meta", _mock_run_with_meta
    )
    result = t.translate("原文")
    assert result == "Xin chào"
    meta = t.drain_last_meta()
    assert meta["cost_usd"] == 0.001
    assert meta["tokens_in"] == 100
    assert meta["tokens_out"] == 50
    assert meta["actual_model"] == "cc/claude-opus-4-6"
    # drain lần 2 → rỗng
    assert t.drain_last_meta() == {}


def test_translate_aggregates_meta_across_chunks(monkeypatch):
    """Chapter dài chia 3 chunk → cost/tokens được cộng dồn."""
    t = _make_openai_translator()
    t.cfg.chunk = t.cfg.chunk.__class__(max_chars=5, overlap_paragraphs=0)

    call_count = {"n": 0}

    def _mock_run_with_meta(cfg_, prompt):
        call_count["n"] += 1
        return (f"chunk {call_count['n']}", {
            "version": "3.8.40",
            "cost_usd": 0.001,
            "tokens_in": 10,
            "tokens_out": 5,
        })

    monkeypatch.setattr(
        "novel2epub.translator.openai_client.run_chat_with_meta", _mock_run_with_meta
    )
    t.translate("a\nb\nc\nd\ne\nf")  # 6 dòng, mỗi chunk 5 ký tự
    meta = t.drain_last_meta()
    assert meta["tokens_in"] == 10 * call_count["n"]
    assert meta["tokens_out"] == 5 * call_count["n"]
    assert meta["cost_usd"] == pytest.approx(0.001 * call_count["n"])


def test_translate_meta_includes_cache_hits(monkeypatch):
    """Nhiều chunk có cache_hit → tổng cache_hits > 0."""
    t = _make_openai_translator()
    t.cfg.chunk = t.cfg.chunk.__class__(max_chars=5, overlap_paragraphs=0)

    responses = [
        ("X", {"version": "3.8.40", "cache_hit": True, "cost_usd": 0}),
        ("Y", {"version": "3.8.40", "cache_hit": True, "cost_usd": 0}),
        ("Z", {"version": "3.8.40", "cache_hit": False, "cost_usd": 0.001}),
    ]
    call_count = {"n": 0}

    def _mock_run_with_meta(cfg_, prompt):
        out = responses[call_count["n"]]
        call_count["n"] += 1
        return out

    monkeypatch.setattr(
        "novel2epub.translator.openai_client.run_chat_with_meta", _mock_run_with_meta
    )
    t.translate("a\nb\nc\nd\ne\nf")
    meta = t.drain_last_meta()
    assert meta["cache_hits"] == 2


def test_translate_meta_empty_when_provider_not_omniroute(monkeypatch):
    """Response KHÔNG có X-OmniRoute-Version → _last_chapter_meta = {}."""
    t = _make_openai_translator()

    def _mock_run_with_meta(cfg_, prompt):
        return ("Xin chào", {})  # empty meta

    monkeypatch.setattr(
        "novel2epub.translator.openai_client.run_chat_with_meta", _mock_run_with_meta
    )
    t.translate("原文")
    assert t.drain_last_meta() == {}


# ── Preset registration ──────────────────────────────────────────────


def test_omniroute_preset_registered():
    """Preset 'omniroute' phải có trong registry và load_preset() trả dict hợp lệ."""
    from novel2epub.presets import available, load

    assert "omniroute" in available()
    preset = load("omniroute")
    assert "prompt_template" in preset
    assert "title_prompt_template" in preset
    assert "{text}" in preset["prompt_template"]
    assert "{glossary}" in preset["prompt_template"]
    # Auto-glossary marker tương thích với OpenAITranslator._split_response
    assert "===GLOSSARY===" in preset["prompt_template"]


def test_omniroute_preset_title_has_two_line_format():
    """Title prompt có format TIÊU ĐỀ / GIẢI THÍCH để tương thích _parse_title_response."""
    from novel2epub.presets import load

    preset = load("omniroute")
    title = preset["title_prompt_template"]
    assert "TIÊU ĐỀ" in title
    assert "GIẢI THÍCH" in title
    assert "{kind}" in title
    assert "{text}" in title


# ── CLI: `models` subcommand ───────────────────────────────────────


def test_cli_models_lists_models(tmp_path, monkeypatch, capsys):
    """`python -m novel2epub models` gọi list_models và in từng model id 1 dòng."""
    from novel2epub import cli, openai_client
    from tests.conftest import write_db_config

    cfg_path = write_db_config(
        tmp_path / "novel2epub.db",
        defaults={"translate": {"type": "openai", "openai": {
            "base_url": "https://api.test/v1", "api_key": "test-key", "model": "m",
        }}},
        ebooks={"t": {"novel": {"slug": "t"}, "crawl": {"toc_url": "http://x"}}},
    )
    monkeypatch.setattr(
        openai_client, "list_models",
        lambda base_url, api_key, timeout_seconds=30: ["m1", "m2", "auto", "cc/claude-opus-4-6"],
    )
    rc = cli.main(["--config", str(cfg_path), "models"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "m1" in out
    assert "m2" in out
    assert "auto" in out
    assert "4 model" in out


def test_cli_models_free_filter(tmp_path, monkeypatch, capsys):
    """`--free` filter ra các model có prefix free/, kr/, qoder/, v.v."""
    from novel2epub import cli, openai_client
    from tests.conftest import write_db_config

    cfg_path = write_db_config(
        tmp_path / "novel2epub.db",
        defaults={"translate": {"type": "openai", "openai": {
            "base_url": "https://api.test/v1", "api_key": "k", "model": "m",
        }}},
        ebooks={"t": {"novel": {"slug": "t"}, "crawl": {"toc_url": "http://x"}}},
    )
    monkeypatch.setattr(
        openai_client, "list_models",
        lambda base_url, api_key, timeout_seconds=30: [
            "free/gpt-4o", "kr/claude-sonnet", "openai/gpt-4o", "qoder/codestral",
        ],
    )
    rc = cli.main(["--config", str(cfg_path), "models", "--free"])
    out = capsys.readouterr().out
    assert rc == 0
    # 3 free models (kr/, free/, qoder/) — openai/gpt-4o bị filter
    assert "openai/gpt-4o" not in out
    assert "free/gpt-4o" in out
    assert "kr/claude-sonnet" in out
    assert "qoder/codestral" in out
    assert "3 model" in out


def test_cli_models_json_format(tmp_path, monkeypatch, capsys):
    """`--format json` trả JSON object với `models` và `count`."""
    import json
    from novel2epub import cli, openai_client
    from tests.conftest import write_db_config

    cfg_path = write_db_config(
        tmp_path / "novel2epub.db",
        defaults={"translate": {"type": "openai", "openai": {
            "base_url": "https://api.test/v1", "api_key": "k", "model": "m",
        }}},
        ebooks={"t": {"novel": {"slug": "t"}, "crawl": {"toc_url": "http://x"}}},
    )
    monkeypatch.setattr(
        openai_client, "list_models",
        lambda base_url, api_key, timeout_seconds=30: ["a", "b"],
    )
    rc = cli.main(["--config", str(cfg_path), "models", "--format", "json"])
    out = capsys.readouterr().out
    assert rc == 0
    parsed = json.loads(out)
    assert parsed["count"] == 2
    assert parsed["models"] == ["a", "b"]


def test_cli_models_no_base_url(tmp_path, capsys):
    """base_url rỗng → lỗi + return 1, không gọi list_models."""
    from novel2epub import cli
    from tests.conftest import write_db_config

    cfg_path = write_db_config(
        tmp_path / "novel2epub.db",
        defaults={"translate": {"type": "openai", "openai": {"base_url": "", "model": "m"}}},
        ebooks={"t": {"novel": {"slug": "t"}, "crawl": {"toc_url": "http://x"}}},
    )
    rc = cli.main(["--config", str(cfg_path), "models"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "base_url" in err


def test_cli_models_list_models_raises(tmp_path, monkeypatch, capsys):
    """list_models raise → exit code 1 + in lỗi ra stderr."""
    from novel2epub import cli, openai_client
    from tests.conftest import write_db_config

    cfg_path = write_db_config(
        tmp_path / "novel2epub.db",
        defaults={"translate": {"type": "openai", "openai": {
            "base_url": "https://api.test/v1", "api_key": "k", "model": "m",
        }}},
        ebooks={"t": {"novel": {"slug": "t"}, "crawl": {"toc_url": "http://x"}}},
    )

    def _raise(*a, **k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(openai_client, "list_models", _raise)
    rc = cli.main(["--config", str(cfg_path), "models"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "connection refused" in err


# ── Settings route: /settings/translate/test ────────────────────────


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._json_data


def test_settings_test_translate_connection_omniroute(tmp_path, monkeypatch):
    """Test route trả version OmniRoute + model_count khi response có X-OmniRoute-Version."""
    from fastapi.testclient import TestClient

    from app import deps
    from app.routes import settings as settings_routes
    from novel2epub.config import (
        Config,
        CrawlConfig,
        NovelConfig,
        OutputConfig,
        TranslateConfig,
    )

    cfg = Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/", delay_seconds=0),
        translate=TranslateConfig(type="openai", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)

    fake_resp = _FakeResponse(
        status_code=200,
        json_data={"data": [{"id": "m1"}, {"id": "m2"}]},
        headers={"X-OmniRoute-Version": "3.8.40"},
    )
    monkeypatch.setattr(
        settings_routes.requests, "get",
        lambda *a, **k: fake_resp,
    )

    from app.main import app
    client = TestClient(app)
    resp = client.post(
        "/ebooks/t/settings/translate/test",
        data={"base_url": "http://localhost:20128/v1", "api_key": "sk-test"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["model_count"] == 2
    assert body["omniroute_version"] == "3.8.40"
    assert "latency_ms" in body


def test_settings_test_translate_connection_openai(tmp_path, monkeypatch):
    """Test route KHÔNG trả version khi response không có X-OmniRoute-Version."""
    from fastapi.testclient import TestClient

    from app import deps
    from app.routes import settings as settings_routes
    from novel2epub.config import (
        Config,
        CrawlConfig,
        NovelConfig,
        OutputConfig,
        TranslateConfig,
    )

    cfg = Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/", delay_seconds=0),
        translate=TranslateConfig(type="openai", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)

    fake_resp = _FakeResponse(
        status_code=200,
        json_data={"data": [{"id": "gpt-4o"}]},
        headers={"Content-Type": "application/json"},
    )
    monkeypatch.setattr(
        settings_routes.requests, "get",
        lambda *a, **k: fake_resp,
    )

    from app.main import app
    client = TestClient(app)
    resp = client.post(
        "/ebooks/t/settings/translate/test",
        data={"base_url": "https://api.openai.com/v1", "api_key": "sk-test"},
    )
    body = resp.json()
    assert body["ok"] is True
    assert body["model_count"] == 1
    assert "omniroute_version" not in body


def test_settings_test_translate_connection_http_error(tmp_path, monkeypatch):
    """Test route trả ok=False khi response không 200."""
    from fastapi.testclient import TestClient

    from app import deps
    from app.routes import settings as settings_routes
    from novel2epub.config import (
        Config,
        CrawlConfig,
        NovelConfig,
        OutputConfig,
        TranslateConfig,
    )

    cfg = Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/", delay_seconds=0),
        translate=TranslateConfig(type="openai", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)

    fake_resp = _FakeResponse(status_code=401, text="unauthorized", headers={})
    monkeypatch.setattr(
        settings_routes.requests, "get",
        lambda *a, **k: fake_resp,
    )

    from app.main import app
    client = TestClient(app)
    resp = client.post(
        "/ebooks/t/settings/translate/test",
        data={"base_url": "https://api.test/v1", "api_key": "bad"},
    )
    body = resp.json()
    assert body["ok"] is False
    assert "HTTP 401" in body["error"]


def test_settings_test_translate_connection_timeout(tmp_path, monkeypatch):
    """Test route trả ok=False khi request timeout."""
    from fastapi.testclient import TestClient

    from app import deps
    from app.routes import settings as settings_routes
    from novel2epub.config import (
        Config,
        CrawlConfig,
        NovelConfig,
        OutputConfig,
        TranslateConfig,
    )
    import requests as _requests

    cfg = Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/", delay_seconds=0),
        translate=TranslateConfig(type="openai", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)

    def _raise(*a, **k):
        raise _requests.exceptions.Timeout("timed out")

    monkeypatch.setattr(settings_routes.requests, "get", _raise)

    from app.main import app
    client = TestClient(app)
    resp = client.post(
        "/ebooks/t/settings/translate/test",
        data={"base_url": "https://api.test/v1"},
    )
    body = resp.json()
    assert body["ok"] is False
    assert "Timeout" in body["error"]


# ── SSE fallback: provider trả text/event-stream ──────────────────────


def test_parse_sse_response_typical():
    """SSE response chuẩn — parse delta.content từ các chunk `data: {...}`."""
    sse = (
        'data: {"id":"x","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"role":"assistant","content":""}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"# "}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"Chương 1\\n\\n"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"âM"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"áº¥y cÃ¡i tháº±ng nhÃ³c con kia"}}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        'data: [DONE]\n\n'
    )
    out = openai_client._parse_sse_response(sse)
    assert out == "# Chương 1\n\nâMáº¥y cÃ¡i tháº±ng nhÃ³c con kia"


def test_parse_sse_response_handles_empty_and_garbage():
    """Empty + line không phải `data:` + JSON lỗi → trả chuỗi rỗng, không raise."""
    sse = "\n\n:ping\nnot-a-data-line\ndata: not-json\ndata: [DONE]\n"
    out = openai_client._parse_sse_response(sse)
    assert out == ""


def test_parse_sse_response_skips_done_marker():
    """`data: [DONE]` không được ghép vào content."""
    sse = (
        'data: {"choices":[{"delta":{"content":"Xin"}}]}\n\n'
        'data: [DONE]\n\n'
        'data: {"choices":[{"delta":{"content":"chào"}}]}\n\n'
    )
    out = openai_client._parse_sse_response(sse)
    assert out == "Xinchào"


def test_run_chat_with_meta_parses_sse_when_content_type_event_stream(monkeypatch):
    """Provider trả Content-Type: text/event-stream — fallback parse SSE."""
    cfg = OpenAIConfig(base_url="https://api.test/v1", model="m", api_key="k")
    sse_body = (
        'data: {"choices":[{"delta":{"role":"assistant","content":""}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"# Tiêu đề"}}]}\n\n'
        'data: [DONE]\n\n'
    )
    resp = _FakeResp(
        status_code=200,
        text=sse_body,
        headers={
            "Content-Type": "text/event-stream",
            "X-OmniRoute-Version": "3.8.40",
        },
    )
    monkeypatch.setattr(openai_client.requests, "post", lambda *a, **k: resp)
    content, meta = openai_client.run_chat_with_meta(cfg, "hi")
    assert content == "# Tiêu đề"
    assert meta["version"] == "3.8.40"


def test_run_chat_with_meta_sse_detected_from_raw_when_no_content_type(monkeypatch):
    """Khi Content-Type thiếu nhưng body bắt đầu bằng `data:` → vẫn parse SSE."""
    cfg = OpenAIConfig(base_url="https://api.test/v1", model="m", api_key="k")
    sse_body = (
        'data: {"choices":[{"delta":{"content":"Qwen"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":" nói"}}]}\n\n'
        'data: [DONE]\n\n'
    )
    resp = _FakeResp(
        status_code=200,
        text=sse_body,
        headers={},  # no Content-Type
    )
    monkeypatch.setattr(openai_client.requests, "post", lambda *a, **k: resp)
    content, _ = openai_client.run_chat_with_meta(cfg, "hi")
    assert content == "Qwen nói"


def test_run_chat_with_meta_sse_no_content_raises(monkeypatch):
    """SSE stream không có delta.content nào → raise lỗi rõ ràng."""
    cfg = OpenAIConfig(base_url="https://api.test/v1", model="m", api_key="k")
    sse_body = (
        'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
        'data: [DONE]\n\n'
    )
    resp = _FakeResp(
        status_code=200,
        text=sse_body,
        headers={"Content-Type": "text/event-stream"},
    )
    monkeypatch.setattr(openai_client.requests, "post", lambda *a, **k: resp)
    with pytest.raises(RuntimeError, match="SSE stream"):
        openai_client.run_chat_with_meta(cfg, "hi")


def test_run_chat_with_meta_sends_stream_true(monkeypatch):
    """Payload phải chứa `stream: true` để nhận SSE chunks sớm."""
    cfg = OpenAIConfig(base_url="https://api.test/v1", model="m", api_key="k")
    captured = {}

    def _capture_post(*a, **k):
        captured["payload"] = k.get("json")
        return _FakeResp(
            status_code=200,
            json_data={"choices": [{"message": {"content": "OK"}}]},
            headers={},
        )

    monkeypatch.setattr(openai_client.requests, "post", _capture_post)
    openai_client.run_chat_with_meta(cfg, "hi")
    assert captured["payload"]["stream"] is True
    assert captured["payload"].get("stream") is True
