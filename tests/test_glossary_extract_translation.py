import re
from types import SimpleNamespace

import pytest

from novel2epub.config import DEFAULT_PROMPT, TranslateConfig
from novel2epub import glossary_extract_translation as preview


def config():
    return SimpleNamespace(translate=TranslateConfig(type="openai"))


def test_local_mt_translates_one_term_and_its_context_at_a_time(monkeypatch):
    cfg = config()
    calls = []
    def factory(options, **kwargs):
        assert options.type == "localmt"
        assert not options.auto_glossary
        return SimpleNamespace(translate=lambda text: calls.append(text) or "vi:" + text)
    monkeypatch.setattr(preview, "make_translator", factory)
    result = preview.translate_extracted_rows(cfg, None, [
        {"source": "灵石", "context": "拿出灵石"}, {"source": "神功", "context": "修炼神功"},
    ], "localmt")
    assert calls == ["灵石", "拿出灵石", "神功", "修炼神功"]
    assert result[0]["target"] == "vi:灵石"
    assert result[0]["context_target"] == "vi:拿出灵石"
    assert cfg.translate.type == "openai"


def test_llm_uses_default_prompt_and_batches_rows_with_label_mapping(monkeypatch):
    cfg = config()
    cfg.translate.openai.prompt_template = "custom template must not be used"
    prompts = []
    def chat(prompt):
        prompts.append(prompt)
        ids = re.findall(r"\[\[G\d+_(?:TERM|CONTEXT)\]\]", prompt)
        # Response order can differ: labels, not position, determine the mapping.
        return "\n".join(f"{key} vi:{key}" for key in reversed(ids))
    def factory(options, **kwargs):
        assert options.type == "openai"
        assert options.openai.prompt_template == DEFAULT_PROMPT
        return SimpleNamespace(_build_prompt=lambda text: text, _run_chat_with_retry=chat)
    monkeypatch.setattr(preview, "make_translator", factory)
    rows = [{"source": f"术语{i}", "context": f"语境{i}"} for i in range(21)]
    result = preview.translate_extracted_rows(cfg, None, rows, "openai")
    assert len(prompts) == 2
    assert "[[G0_TERM]]" in prompts[0] and "[[G19_CONTEXT]]" in prompts[0]
    assert "[[G20_TERM]]" in prompts[1]
    assert result[0]["target"] == "vi:[[G0_TERM]]"
    assert result[1]["context_target"] == "vi:[[G1_CONTEXT]]"
    assert cfg.translate.openai.prompt_template == "custom template must not be used"


@pytest.mark.parametrize("response", [
    "[[G0_TERM]] vi",  # missing context
    "[[G0_TERM]] vi\n[[G0_TERM]] other\n[[G0_CONTEXT]] vi",
    "[[G99_TERM]] vi\n[[G0_CONTEXT]] vi",
    "explanation\n[[G0_TERM]] vi\n[[G0_CONTEXT]] vi",
])
def test_malformed_llm_batch_cannot_shift_translations(monkeypatch, response):
    monkeypatch.setattr(preview, "make_translator", lambda *a, **kw: SimpleNamespace(
        _build_prompt=lambda text: text, _run_chat_with_retry=lambda prompt: response))
    result = preview.translate_extracted_rows(config(), None, [{"source": "灵石", "context": "灵石出现"}], "openai")
    assert result[0]["error"]
    assert result[0]["target"] == result[0]["context_target"] == ""


def test_llm_budget_counts_template_overhead(monkeypatch):
    cfg = config()
    cfg.translate.prompt_max_chars = 100
    monkeypatch.setattr(preview, "make_translator", lambda *a, **kw: SimpleNamespace(
        _build_prompt=lambda text: "x" * 101 + text,
        _run_chat_with_retry=lambda prompt: pytest.fail("over-budget API call")))
    result = preview.translate_extracted_rows(cfg, None, [{"source": "灵石", "context": ""}], "openai")
    assert "prompt_max_chars" in result[0]["error"]


def test_preview_engine_failure_is_visible_without_fake_translation(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("offline")
    monkeypatch.setattr(preview, "make_translator", fail)
    result = preview.translate_extracted_rows(config(), None, [{"source": "灵石", "context": ""}], "localmt")
    assert result[0]["error"] and not result[0]["target"]


def test_real_llm_prompt_renders_default_rules_and_multiple_rows(monkeypatch):
    from novel2epub.translator import OpenAITranslator
    from novel2epub import openai_client
    cfg = config()
    prompts = []
    def chat(options, prompt):
        prompts.append(prompt)
        return "\n".join(f"{label} bản dịch" for label in re.findall(r"\[\[G\d+_(?:TERM|CONTEXT)\]\]", prompt))
    monkeypatch.setattr(openai_client, "run_chat", chat)
    monkeypatch.setattr(preview, "make_translator", lambda options, **kw: OpenAITranslator(options))
    result = preview.translate_extracted_rows(cfg, None, [
        {"source": "灵石", "context": "拿出灵石"}, {"source": "神功", "context": "修炼神功"},
    ], "openai")
    assert len(prompts) == 1
    assert prompts[0].startswith(DEFAULT_PROMPT.splitlines()[0])
    assert "[[G0_TERM]] 灵石" in prompts[0] and "[[G1_CONTEXT]] 修炼神功" in prompts[0]
    assert "{text}" not in prompts[0] and "{glossary}" not in prompts[0]
    assert all(row["target"] == row["context_target"] == "bản dịch" and not row["error"] for row in result)


def test_running_preview_job_cooperates_with_queue_cancellation(tmp_path, monkeypatch):
    import threading
    from app import deps
    from app.queue import CATEGORIES, JobQueue
    from app.routes.glossary import glossary_extract_translate_job_factory
    from novel2epub.storage import Storage
    from tests.helpers.jobs import wait_until

    cfg = config()
    cfg.novel = SimpleNamespace(slug="t")
    cfg.output = SimpleNamespace(data_dir=str(tmp_path))
    Storage(tmp_path, "t").ensure_dirs()
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    cancel = threading.Event()
    calls = []
    def translate(text):
        calls.append(text)
        cancel.set()
        return "dịch"
    monkeypatch.setattr(preview, "make_translator", lambda *a, **kw: SimpleNamespace(translate=translate))
    queue = JobQueue(workers={**{c: 0 for c in CATEGORIES}, "local-mt": 1})
    params = {"slug": "t", "engine": "localmt", "entries": [{"source": "灵石", "context": "灵石出现"}]}
    job = queue.enqueue("local-mt", "glossary-extract-translate", glossary_extract_translate_job_factory(params),
                        ebook="t", cancel_event=cancel)
    assert wait_until(lambda: job.state == "cancelled")
    assert calls == ["灵石"]
    assert queue.job_snapshot(job.id)["outcome"] == {"entries": [], "engine": "localmt"}


def test_pending_preview_restores_and_returns_result_after_restart(tmp_path, monkeypatch):
    import json
    from app import deps
    from app.queue import CATEGORIES, JobQueue
    from app.routes.glossary import glossary_extract_translate_job_factory
    from novel2epub.db import get_connection, init_schema
    from novel2epub.storage import Storage

    cfg = config()
    cfg.novel = SimpleNamespace(slug="t")
    cfg.output = SimpleNamespace(data_dir=str(tmp_path / "books"))
    Storage(cfg.output.data_dir, "t").ensure_dirs()
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    monkeypatch.setattr(preview, "make_translator", lambda *a, **kw: SimpleNamespace(translate=lambda text: "dịch"))
    path = tmp_path / "queue.db"
    conn = get_connection(path)
    init_schema(conn)
    spec = {"kind": "glossary-extract-translate", "params": {
        "slug": "t", "engine": "localmt", "entries": [{"source": "灵石", "context": "灵石出现"}],
    }}
    with conn:
        conn.execute("INSERT INTO job_queue_pending (id, category, step, label, ebook, spec_json, position) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     ("old", "local-mt", "glossary-extract-translate", "Dịch", "t", json.dumps(spec), 0))
    queue = JobQueue(workers={c: 0 for c in CATEGORIES}, db_path=path)
    queue.register_kind("glossary-extract-translate", glossary_extract_translate_job_factory)
    assert queue.load_pending() == 1
    restored = queue.snapshot()["pending"]["local-mt"][0]
    assert restored["id"] == "old"  # browser polling remains valid after restart
    job = queue._jobs[restored["id"]]
    job.state = queue._execute(job)
    assert queue.job_snapshot(job.id)["outcome"]["entries"][0]["target"] == "dịch"
