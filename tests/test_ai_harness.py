from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from novel2epub import ai_harness
from novel2epub.db import get_connection, init_schema, schema_version, SCHEMA_VERSION


class FakeStorage:
    def __init__(self, text="Một người đi qua."):
        self.text = text
        self.glossary = [("张三", "Trương Tam", "")]
        self.writes = []
        self.meta = {}

    def has_raw(self, _ch): return True
    def read_raw(self, _ch): return "张三走过。"
    def has_active_branch_text(self, _ch): return bool(self.text)
    def read_active_branch_text(self, _ch): return self.text
    def active_branch(self, _ch): return "ai"
    def read_branch_text(self, _ch, _branch): return self.text
    def read_glossary_entries_merged(self): return self.glossary
    def has_meta(self, _ch): return bool(self.meta)
    def read_meta(self, _ch): return self.meta
    def write_meta(self, _ch, meta): self.meta = meta
    def write_branch_text(self, _ch, _branch, text):
        self.text = text
        self.writes.append(text)


def test_schema_v28_persists_runs_and_results():
    conn = get_connection(":memory:")
    init_schema(conn)
    with conn:
        conn.execute("INSERT INTO ebooks (slug, title) VALUES ('demo', 'Demo')")
    run_id = ai_harness.create_run(conn, "demo", [1, 2])
    ai_harness.save_chapter_result(conn, run_id, 1, [])
    ai_harness.save_chapter_result(conn, run_id, 2, None, "model timeout")
    ai_harness.finish_run(conn, run_id)
    run = ai_harness.get_run(conn, "demo", run_id)
    assert schema_version(conn) == SCHEMA_VERSION
    assert run["status"] == "partial"
    assert [ch["status"] for ch in run["chapters"]] == ["clean", "failed"]
    assert run["failed"] == 1


def test_invalid_model_response_is_failure_not_clean():
    cfg = SimpleNamespace(ai=SimpleNamespace(openai=object()))
    storage = FakeStorage()
    chapter = SimpleNamespace(index=1)
    with pytest.raises(ValueError, match="JSON"):
        ai_harness.scan_chapter(cfg, storage, chapter, lambda *_: "not json")


def test_scan_anchors_unique_paragraph_and_blocks_ambiguous():
    cfg = SimpleNamespace(ai=SimpleNamespace(openai=object()))
    chapter = SimpleNamespace(index=1)
    response = json.dumps({"issues": [{
        "category": "mistranslation", "severity": "high", "source": "张三",
        "current": "người", "suggestion": "Trương Tam", "reason": "Sai tên",
    }]})
    result = ai_harness.scan_chapter(cfg, FakeStorage(), chapter, lambda *_: response)
    assert result[0]["status"] == "pending"
    assert result[0]["para_index"] == 0
    assert result[0]["after_text"] == "Một Trương Tam đi qua."
    ambiguous = ai_harness.scan_chapter(cfg, FakeStorage("người A\nngười B"), chapter, lambda *_: response)
    assert ambiguous[0]["status"] == "blocked"
    unknown_glossary = ai_harness._normalize_issue({
        "category": "glossary", "source": "不存在", "current": "người",
        "suggestion": "Trương Tam", "reason": "Không rõ",
    }, 1, "ai", "Một người đi qua.", {"张三": "Trương Tam"})
    assert unknown_glossary["status"] == "blocked"


def test_preview_marks_changed_translation_stale():
    storage = FakeStorage()
    chapter = SimpleNamespace(index=1)
    rows = [{"id": 5, "kind": "text", "chapter_index": 1, "branch": "ai",
             "content_hash": ai_harness._hash(storage.text), "para_index": 0,
             "before_text": storage.text, "after_text": "Trương Tam đi qua."}]
    manifest = SimpleNamespace(chapters=[chapter])
    assert ai_harness.preview_selected(storage, manifest, rows)["stale"] == 0
    storage.text = "Bản dịch đã sửa."
    assert ai_harness.preview_selected(storage, manifest, rows)["stale"] == 1


def test_selected_apply_changes_only_selected_paragraph_and_keeps_backup():
    conn = get_connection(":memory:")
    init_schema(conn)
    with conn:
        conn.execute("INSERT INTO ebooks (slug, title) VALUES ('demo', 'Demo')")
    run_id = ai_harness.create_run(conn, "demo", [1])
    storage = FakeStorage("Một người đi qua.\nMột con mèo ngủ.")
    issue = ai_harness._normalize_issue({
        "category": "mistranslation", "severity": "high", "source": "张三",
        "current": "người", "suggestion": "Trương Tam", "reason": "Sai tên",
    }, 1, "ai", storage.text, {})
    ai_harness.save_chapter_result(conn, run_id, 1, [issue])
    rows = ai_harness.selected_issues(conn, "demo", run_id, [1])
    result = ai_harness.apply_selected(conn, storage, SimpleNamespace(chapters=[SimpleNamespace(index=1)]), rows)
    assert result["applied"] == 1
    assert storage.text == "Một Trương Tam đi qua.\nMột con mèo ngủ."
    assert storage.meta["before_find_replace"] == "Một người đi qua.\nMột con mèo ngủ."
    assert ai_harness.get_run(conn, "demo", run_id)["issues"][0]["status"] == "applied"


def test_routes_list_runs_and_reject_scan_without_manifest(tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    from tests.conftest import write_db_config
    import app.deps as deps

    db_path = write_db_config(
        tmp_path / "novel2epub.db", ebooks={"demo": {"novel": {"title": "Demo"}}}
    )
    monkeypatch.setattr(deps, "DB_PATH", str(db_path))
    monkeypatch.setattr(deps, "WORKSPACE_PATH", str(db_path))
    from app.main import app

    client = TestClient(app)
    assert client.get("/api/ui/ebooks/demo/ai-harness/runs").json() == {"runs": []}
    response = client.post("/api/ui/ebooks/demo/ai-harness/runs")
    assert response.status_code == 400


def test_scan_job_records_clean_issues_and_failed_chapters(monkeypatch):
    from app.routes import ai_harness as routes

    conn = get_connection(":memory:")
    init_schema(conn)
    with conn:
        conn.execute("INSERT INTO ebooks (slug, title) VALUES ('demo', 'Demo')")
    run_id = ai_harness.create_run(conn, "demo", [1, 2, 3])
    chapters = [SimpleNamespace(index=i) for i in [1, 2, 3]]
    monkeypatch.setattr(routes, "_conn", lambda: conn)
    monkeypatch.setattr(routes, "_storage", lambda _slug: (object(), object(), SimpleNamespace(chapters=chapters)))

    def fake_scan(_cfg, _storage, ch):
        if ch.index == 3:
            raise RuntimeError("provider secret could be in this message")
        if ch.index == 2:
            return [ai_harness._normalize_issue({
                "category": "hanviet", "current": "người", "suggestion": "Trương Tam",
                "reason": "Tên riêng", "source": "张三",
            }, 2, "ai", "Một người đi qua.", {})]
        return []

    monkeypatch.setattr(ai_harness, "scan_chapter", fake_scan)
    routes.scan_job_factory({"slug": "demo", "run_id": run_id})(lambda _message: None)
    run = ai_harness.get_run(conn, "demo", run_id)
    assert run["status"] == "partial"
    assert [ch["status"] for ch in run["chapters"]] == ["clean", "issues", "failed"]
    assert run["chapters"][2]["error"] == "RuntimeError"
    assert len(run["issues"]) == 1


def test_apply_rejects_preview_token_after_scope_changes(monkeypatch):
    from fastapi import HTTPException
    from app.routes import ai_harness as routes

    storage = FakeStorage()
    manifest = SimpleNamespace(chapters=[SimpleNamespace(index=1)])
    rows = [{"id": 1, "kind": "text", "chapter_index": 1, "branch": "ai",
             "content_hash": ai_harness._hash(storage.text), "para_index": 0,
             "before_text": storage.text, "after_text": "Trương Tam đi qua."}]
    monkeypatch.setattr(routes, "_storage", lambda _slug: (object(), storage, manifest))
    monkeypatch.setattr(routes, "_selected", lambda *_args: rows)
    with pytest.raises(HTTPException) as error:
        routes.apply("demo", 1, routes.Approval(ids=[1], token="old-preview"))
    assert error.value.status_code == 409
    assert storage.writes == []
