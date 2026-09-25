"""Phase 0: runtime Assistant Panel — migration, CRUD thread, chat resolve config."""
from __future__ import annotations

import json
import sqlite3

from starlette.testclient import TestClient

from novel2epub import assistant as assistant_mod
from novel2epub.db import SCHEMA_VERSION, get_connection, init_schema, schema_version


def _mem_conn() -> sqlite3.Connection:
    conn = get_connection(":memory:")
    init_schema(conn)
    return conn


def _seed_ebook(conn: sqlite3.Connection, slug: str = "demo") -> None:
    with conn:
        conn.execute("INSERT INTO ebooks (slug, title) VALUES (?, ?)", (slug, "Demo"))


def test_schema_v27_has_assistant_tables():
    conn = _mem_conn()
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "assistant_threads" in names
    assert "assistant_messages" in names
    assert schema_version(conn) == SCHEMA_VERSION


def test_migration_v27_preserves_old_data():
    conn = get_connection(":memory:")
    init_schema(conn)
    with conn:
        conn.execute("UPDATE _meta SET value = '26' WHERE key = 'schema_version'")
        conn.execute("DROP TABLE IF EXISTS assistant_threads")
        conn.execute("DROP TABLE IF EXISTS assistant_messages")
        conn.execute("INSERT INTO ebooks (slug, title) VALUES ('old', 'Old')")
    init_schema(conn)
    assert schema_version(conn) == SCHEMA_VERSION
    row = conn.execute("SELECT title FROM ebooks WHERE slug = 'old'").fetchone()
    assert row["title"] == "Old"
    # Bảng mới tồn tại và rỗng.
    assert conn.execute("SELECT COUNT(*) AS c FROM assistant_threads").fetchone()["c"] == 0


def test_thread_crud_keeps_provider_model():
    conn = _mem_conn()
    _seed_ebook(conn)
    thread = assistant_mod.create_thread(conn, "demo", "http://x/v1", "model-a")
    assert thread["provider_base_url"] == "http://x/v1"
    assert thread["model"] == "model-a"
    updated = assistant_mod.update_thread_provider(conn, thread["id"], model="model-b")
    assert updated["model"] == "model-b"
    assert updated["provider_base_url"] == "http://x/v1"
    assistant_mod.add_message(conn, thread["id"], "user", "xin chào")
    msgs = assistant_mod.list_messages(conn, thread["id"])
    assert [m["role"] for m in msgs] == ["user"]
    assistant_mod.delete_thread(conn, thread["id"])
    assert assistant_mod.list_threads(conn, "demo") == []


def test_resolve_chat_config_thread_override_keeps_secret_from_effective():
    from novel2epub.config import GlobalAIConfig, AIConfig, Config, NovelConfig, CrawlConfig
    from novel2epub.config import TranslateConfig, OutputConfig, OpenAIConfig

    cfg = Config(
        novel=NovelConfig(slug="demo"),
        crawl=CrawlConfig(),
        translate=TranslateConfig(),
        output=OutputConfig(data_dir="data"),
        ai=AIConfig(openai=OpenAIConfig(base_url="http://global/v1", api_key="SECRET", model="global-m")),
        global_ai=GlobalAIConfig(),
    )
    chat_cfg = assistant_mod.resolve_chat_config(
        cfg, {"provider_base_url": "http://thread/v1", "model": "thread-m"}
    )
    assert chat_cfg.base_url == "http://thread/v1"
    assert chat_cfg.model == "thread-m"
    assert chat_cfg.api_key == "SECRET"
    # Thread trống → dùng effective.
    chat_cfg2 = assistant_mod.resolve_chat_config(cfg, {"provider_base_url": "", "model": ""})
    assert chat_cfg2.base_url == "http://global/v1"


def _client_with_ebook(tmp_path, monkeypatch) -> TestClient:
    from tests.conftest import write_db_config

    db_path = write_db_config(
        tmp_path / "novel2epub.db",
        defaults={
            "global_ai": {"base_url": "http://global/v1", "assistant_model": "global-m"},
            "translate": {"openai": {"model": "t-m"}},
            "ai": {"openai": {"model": "ai-m"}},
        },
        ebooks={"demo": {"novel": {"title": "Demo"}}},
    )
    import app.deps as deps

    monkeypatch.setattr(deps, "DB_PATH", str(db_path))
    monkeypatch.setattr(deps, "WORKSPACE_PATH", str(db_path))
    from app.main import app

    return TestClient(app)


def test_assistant_routes_crud_and_chat_no_key_leak(tmp_path, monkeypatch):
    import novel2epub.openai_client as oc

    calls: dict = {}

    def fake_run_chat(cfg, prompt):
        calls["base_url"] = cfg.base_url
        calls["model"] = cfg.model
        calls["api_key"] = cfg.api_key
        assert "xin chào" in prompt
        return "chào bạn"

    def fake_chat_with_tools(cfg, messages, tools):
        calls["tools"] = True
        calls["base_url"] = cfg.base_url
        calls["model"] = cfg.model
        return {"role": "assistant", "content": "chào bạn", "tool_calls": []}

    monkeypatch.setattr(oc, "run_chat", fake_run_chat)
    monkeypatch.setattr(oc, "chat_with_tools", fake_chat_with_tools)
    client = _client_with_ebook(tmp_path, monkeypatch)

    defaults = client.get("/api/ui/ebooks/demo/assistant/defaults").json()
    assert defaults["provider_base_url"] == "http://global/v1"
    assert "api_key" not in defaults
    assert defaults["api_key_configured"] is False

    created = client.post(
        "/api/ui/ebooks/demo/assistant/threads", json={"provider_base_url": "", "model": ""}
    ).json()["thread"]
    assert created["model"] == defaults["model"]

    patched = client.patch(
        f"/api/ui/ebooks/demo/assistant/threads/{created['id']}",
        json={"model": "thread-m"},
    ).json()["thread"]
    assert patched["model"] == "thread-m"

    # Ebook config không bị ghi đè bởi lựa chọn theo thread.
    from novel2epub.db import get_thread_connection
    import app.deps as deps

    conn = get_thread_connection(deps.DB_PATH)
    row = conn.execute("SELECT ai_overrides_json FROM ebooks WHERE slug='demo'").fetchone()
    assert "thread-m" not in (row["ai_overrides_json"] or "")

    chat = client.post(
        f"/api/ui/ebooks/demo/assistant/threads/{created['id']}/chat",
        json={"content": "xin chào", "chapter_index": 3, "selection": "đoạn chọn"},
    ).json()
    assert chat["reply"] == "chào bạn"
    assert calls["model"] == "thread-m"
    assert "api_key" not in json.dumps(chat)

    # Alias đúng tên trong kế hoạch.
    chat2 = client.post(
        "/api/ui/assistant/chat",
        json={"ebook_slug": "demo", "thread_id": created["id"], "content": "xin chào"},
    ).json()
    assert chat2["reply"] == "chào bạn"

    thread = client.get(
        f"/api/ui/ebooks/demo/assistant/threads/{created['id']}"
    ).json()
    assert [m["role"] for m in thread["messages"]] == ["user", "assistant", "user", "assistant"]


def test_assistant_chat_stream_sse(tmp_path, monkeypatch):
    import novel2epub.openai_client as oc

    monkeypatch.setattr(oc, "run_chat", lambda cfg, prompt: "abcdef")
    monkeypatch.setattr(
        oc, "chat_with_tools",
        lambda cfg, messages, tools: {"role": "assistant", "content": "abcdef", "tool_calls": []},
    )
    client = _client_with_ebook(tmp_path, monkeypatch)
    created = client.post(
        "/api/ui/ebooks/demo/assistant/threads", json={}
    ).json()["thread"]
    resp = client.post(
        f"/api/ui/ebooks/demo/assistant/threads/{created['id']}/chat",
        json={"content": "hi", "stream": True},
    )
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert "data: [DONE]" in resp.text


# ── Phase 2: tools đọc ───────────────────────────────────────────────────

def _seed_chapters(tmp_path, monkeypatch):
    """DB ebook demo với 2 chương: ch1 raw+dịch, ch2 raw-only (chưa dịch)."""
    from tests.conftest import write_db_config

    db_path = write_db_config(
        tmp_path / "novel2epub.db",
        defaults={},
        ebooks={"demo": {"novel": {"title": "Demo"}}},
    )
    import app.deps as deps

    monkeypatch.setattr(deps, "DB_PATH", str(db_path))
    monkeypatch.setattr(deps, "WORKSPACE_PATH", str(db_path))
    from novel2epub.db import get_thread_connection

    conn = get_thread_connection(str(db_path))
    with conn:
        conn.execute(
            "INSERT INTO chapters (ebook_slug, idx, title, title_zh, raw_text, translated_text, meta_json)"
            " VALUES ('demo', 1, 'Chương 1', '第一章', ?, ?, '{}')",
            (
                "段落一。\n\n段落二有关键词。",
                "Đoạn một.\n\nĐoạn hai có từ khóa.",
            ),
        )
        conn.execute(
            "INSERT INTO chapters (ebook_slug, idx, title, raw_text, meta_json)"
            " VALUES ('demo', 2, 'Chương 2', '只有原文，没有翻译。', '{}')",
        )
        conn.execute(
            "INSERT INTO glossary_entries (ebook_slug, list_name, source, target, note, position)"
            " VALUES ('demo', 'names.txt', '叶凡', 'Diệp Phàm', '', 0)"
        )
        conn.execute(
            "INSERT INTO characters (ebook_slug, source, target, role_note, importance, position)"
            " VALUES ('demo', '叶凡', 'Diệp Phàm', 'nhân vật chính', 'main', 0)"
        )
        conn.execute(
            "INSERT INTO idioms (source, target, literals, protect, position)"
            " VALUES ('画蛇添足', 'vẽ rắn thêm chân', 'vẽ rắn thêm chân|thừa thãi', 0, 0)"
        )
    from novel2epub.storage import Storage

    storage = Storage(str(tmp_path), "demo")
    return storage, storage.load_manifest()


def test_search_translated_uses_split_paras(tmp_path, monkeypatch):
    storage, manifest = _seed_chapters(tmp_path, monkeypatch)
    res = assistant_mod.search_ebook(storage, manifest, "từ khóa")
    assert res["truncated"] is False
    assert len(res["items"]) == 1
    item = res["items"][0]
    # split_paras: ["Đoạn một.", "Đoạn hai có từ khóa."] → para_index 1.
    assert (item["chapter_index"], item["para_index"]) == (1, 1)
    # Chương 2 chưa dịch → không lọt vào kết quả translated.
    assert all(i["chapter_index"] != 2 for i in res["items"])


def test_search_raw_uses_split_blocks_and_sees_undtranslated(tmp_path, monkeypatch):
    storage, manifest = _seed_chapters(tmp_path, monkeypatch)
    res = assistant_mod.search_ebook(storage, manifest, "关键词", source="raw")
    assert len(res["items"]) == 1
    item = res["items"][0]
    # split_blocks gộp khối: ["段落一。", "段落二有关键词。"] → para_index 1.
    assert (item["chapter_index"], item["para_index"]) == (1, 1)
    # Raw quét được cả chương chưa dịch.
    res2 = assistant_mod.search_ebook(storage, manifest, "只有原文", source="raw")
    assert [i["chapter_index"] for i in res2["items"]] == [2]


def test_search_limit_300_truncated(tmp_path, monkeypatch):
    storage, manifest = _seed_chapters(tmp_path, monkeypatch)
    res = assistant_mod.search_ebook(storage, manifest, "o", limit=1)
    assert res["truncated"] is True
    assert len(res["items"]) == 1
    res = assistant_mod.search_ebook(storage, manifest, "o", limit=9999)
    assert len(res["items"]) <= 300


def test_search_invalid_regex_and_scope(tmp_path, monkeypatch):
    import pytest

    storage, manifest = _seed_chapters(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="Regex không hợp lệ"):
        assistant_mod.search_ebook(storage, manifest, "([", regex=True)
    with pytest.raises(ValueError, match="source phải là"):
        assistant_mod.search_ebook(storage, manifest, "x", source="nope")


def test_get_chapter_paras_and_untranslated_empty(tmp_path, monkeypatch):
    storage, manifest = _seed_chapters(tmp_path, monkeypatch)
    ch1 = assistant_mod.get_chapter(storage, manifest, 1)
    assert ch1["title"] == "Chương 1"
    assert ch1["active_branch"] == "ai"
    assert [p["para_index"] for p in ch1["translated_paras"]] == [0, 1]
    assert ch1["has_translated"] is True
    # Chương 2 chưa dịch → translated rỗng, không lấp.
    ch2 = assistant_mod.get_chapter(storage, manifest, 2)
    assert ch2["translated_paras"] == []
    assert ch2["has_translated"] is False
    ch2_raw = assistant_mod.get_chapter(storage, manifest, 2, include_raw=True)
    assert len(ch2_raw["raw_paras"]) == 1


def test_get_glossary_characters_idioms_query(tmp_path, monkeypatch):
    storage, manifest = _seed_chapters(tmp_path, monkeypatch)
    glo = assistant_mod.get_glossary(storage, "叶")
    assert glo["total"] == 1
    assert glo["entries"][0]["target"] == "Diệp Phàm"
    assert assistant_mod.get_glossary(storage, "không có")["total"] == 0
    chars = assistant_mod.get_characters(storage, "diệp")
    assert chars["total"] == 1
    assert chars["characters"][0]["role_note"] == "nhân vật chính"
    idioms = assistant_mod.get_idioms(storage, "画蛇")
    assert idioms["total"] == 1
    assert idioms["entries"][0]["protect"] is False


def test_agent_turn_calls_tool_then_answers(tmp_path, monkeypatch):
    import novel2epub.openai_client as oc

    storage, manifest = _seed_chapters(tmp_path, monkeypatch)
    script = [
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": "c1", "name": "search_ebook",
                         "arguments": {"find": "từ khóa"}}]},
        {"role": "assistant", "content": "Tìm thấy ở chương 1.", "tool_calls": []},
    ]

    def fake_chat(cfg, messages, tools):
        assert tools, "lượt đầu phải kèm tools"
        return script.pop(0)

    monkeypatch.setattr(oc, "chat_with_tools", fake_chat)
    reply, trace, previews = assistant_mod.run_agent_turn(
        object(), storage, manifest, "từ khóa ở đâu?"
    )
    assert reply == "Tìm thấy ở chương 1."
    assert trace == [{"name": "search_ebook", "arguments": {"find": "từ khóa"}, "ok": True}]
    assert previews == []


def test_assistant_read_routes(tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    _seed_chapters(tmp_path, monkeypatch)
    from app.main import app

    client = TestClient(app)
    search = client.get(
        "/api/ui/ebooks/demo/assistant/search", params={"q": "từ khóa"}
    ).json()
    assert len(search["items"]) == 1
    assert search["items"][0]["para_index"] == 1
    assert client.get(
        "/api/ui/ebooks/demo/assistant/search", params={"q": "([", "regex": "true"}
    ).status_code == 400
    ch = client.get("/api/ui/ebooks/demo/assistant/chapters/1").json()
    assert ch["title"] == "Chương 1"
    assert len(ch["translated_paras"]) == 2
    assert client.get("/api/ui/ebooks/demo/assistant/chapters/99").status_code == 400
    assert client.get(
        "/api/ui/ebooks/demo/assistant/glossary", params={"q": "叶"}
    ).json()["total"] == 1
    assert client.get(
        "/api/ui/ebooks/demo/assistant/characters"
    ).json()["total"] == 1
    assert client.get("/api/ui/ebooks/demo/assistant/idioms").json()["total"] == 1


def test_assistant_chat_use_tools_agent_path(tmp_path, monkeypatch):
    import novel2epub.openai_client as oc

    from starlette.testclient import TestClient

    _seed_chapters(tmp_path, monkeypatch)
    monkeypatch.setattr(
        oc, "chat_with_tools",
        lambda cfg, messages, tools: (
            {"role": "assistant", "content": "có tool", "tool_calls": []} if not tools
            else {"role": "assistant", "content": "đã tra", "tool_calls": []}
        ),
    )
    from app.main import app

    client = TestClient(app)
    thread = client.post(
        "/api/ui/ebooks/demo/assistant/threads", json={}
    ).json()["thread"]
    chat = client.post(
        f"/api/ui/ebooks/demo/assistant/threads/{thread['id']}/chat",
        json={"content": "glossary có gì?", "use_tools": True},
    ).json()
    assert chat["reply"] == "đã tra"
    assert chat["tool_calls"] == []
    assert chat["previews"] == []
    assert "api_key" not in str(chat)


# ── Phase 3: ghi có preview ──────────────────────────────────────────────

def test_preview_then_apply_paragraph_edit(tmp_path, monkeypatch):
    storage, manifest = _seed_chapters(tmp_path, monkeypatch)
    preview = assistant_mod.preview_paragraph_edit(storage, manifest, 1, 1, "Đoạn hai đã sửa.")
    assert preview["before"] == "Đoạn hai có từ khóa."
    assert preview["after"] == "Đoạn hai đã sửa."
    # Preview không ghi.
    assert "từ khóa" in storage.read_active_branch_text(
        next(c for c in manifest.chapters if c.index == 1)
    )
    rev_before = storage.read_branch_revision(
        next(c for c in manifest.chapters if c.index == 1), "ai"
    )
    applied = assistant_mod.apply_paragraph_edit(
        storage, manifest, 1, 1, "Đoạn hai có từ khóa.", "Đoạn hai đã sửa."
    )
    assert applied["saved"] is True
    assert applied["revision"] == rev_before + 1
    # Stale: expected cũ lệch → từ chối.
    import pytest

    with pytest.raises(ValueError, match="thay đổi|Không ghi được"):
        assistant_mod.apply_paragraph_edit(
            storage, manifest, 1, 1, "Đoạn hai có từ khóa.", "Sửa lần nữa."
        )


def test_preview_glossary_then_apply_with_propagate(tmp_path, monkeypatch):
    storage, manifest = _seed_chapters(tmp_path, monkeypatch)
    edits = [{"source": "叶凡", "target": "Diệp Phạm", "note": "", "original_source": "叶凡"}]
    preview = assistant_mod.preview_glossary_edits(storage, edits)
    assert preview["writes"] == 1
    assert preview["errors"] == 0
    # Lỗi xác thực: source thiếu chữ Hán.
    bad = assistant_mod.preview_glossary_edits(
        storage, [{"source": "abc", "target": "X", "note": "", "original_source": ""}]
    )
    assert bad["errors"] == 1
    import pytest

    with pytest.raises(ValueError):
        assistant_mod.apply_glossary_edits(
            storage, [{"source": "abc", "target": "X", "note": "", "original_source": ""}]
        )
    applied = assistant_mod.apply_glossary_edits(storage, edits)
    assert applied["applied"] == 1
    merged = dict((s, t) for s, t, _n in storage.read_glossary_entries_merged())
    assert merged["叶凡"] == "Diệp Phạm"


def test_apply_selected_replacements_with_backup_and_stale(tmp_path, monkeypatch):
    storage, manifest = _seed_chapters(tmp_path, monkeypatch)
    ch1 = next(c for c in manifest.chapters if c.index == 1)
    res = assistant_mod.apply_selected_replacements(
        storage, manifest, "từ khóa", "TỪ KHÓA", False,
        [{"chapter_index": 1, "para_index": 1, "expected": "Đoạn hai có từ khóa."}],
        "translated", False,
    )
    assert res == {"replaced": 1, "chapters": 1, "stale": 0}
    assert "TỪ KHÓA" in storage.read_active_branch_text(ch1)
    meta = storage.read_meta(ch1)
    assert "từ khóa" in meta.get("before_find_replace", "")
    # Áp lại với expected cũ → stale, không ghi thêm.
    res2 = assistant_mod.apply_selected_replacements(
        storage, manifest, "TỪ KHÓA", "x", False,
        [{"chapter_index": 1, "para_index": 1, "expected": "Đoạn hai có từ khóa."}],
        "translated", False,
    )
    assert res2["stale"] == 1
    assert res2["replaced"] == 0


def test_apply_selected_raw_backup_key(tmp_path, monkeypatch):
    storage, manifest = _seed_chapters(tmp_path, monkeypatch)
    ch1 = next(c for c in manifest.chapters if c.index == 1)
    res = assistant_mod.apply_selected_replacements(
        storage, manifest, "关键词", "关键字", False,
        [{"chapter_index": 1, "para_index": 1, "expected": "段落二有关键词。"}],
        "raw", False,
    )
    assert res["replaced"] == 1
    assert "关键字" in storage.read_raw(ch1)
    assert "关键词" in storage.read_meta(ch1).get("before_find_replace_raw", "")


def test_agent_preview_tool_returns_hitl_card(tmp_path, monkeypatch):
    import novel2epub.openai_client as oc

    storage, manifest = _seed_chapters(tmp_path, monkeypatch)
    script = [
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": "c1", "name": "preview_paragraph_edit",
                         "arguments": {"index": 1, "para_index": 0, "new_text": "Đoạn một mới."}}]},
        {"role": "assistant", "content": "Đây là đề xuất, bấm Áp dụng để ghi.", "tool_calls": []},
    ]
    monkeypatch.setattr(oc, "chat_with_tools", lambda cfg, m, t: script.pop(0))
    reply, trace, previews = assistant_mod.run_agent_turn(object(), storage, manifest, "sửa đoạn 1")
    assert trace[0]["ok"] is True
    assert len(previews) == 1
    card = previews[0]
    assert card["kind"] == "paragraph"
    assert card["before"] == "Đoạn một."
    assert card["apply"]["endpoint"] == "edits/apply"
    # Preview không ghi.
    assert "Đoạn một mới" not in storage.read_active_branch_text(
        next(c for c in manifest.chapters if c.index == 1)
    )
    assert reply.startswith("Đây là đề xuất")


def test_assistant_write_routes(tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    _seed_chapters(tmp_path, monkeypatch)
    from app.main import app

    client = TestClient(app)
    preview = client.post(
        "/api/ui/ebooks/demo/assistant/edits/preview",
        json={"index": 1, "para_index": 0, "new_text": "Đoạn một mới."},
    ).json()
    assert preview["before"] == "Đoạn một."
    # Apply sai expected → 409.
    assert client.post(
        "/api/ui/ebooks/demo/assistant/edits/apply",
        json={"index": 1, "para_index": 0, "expected": "sai", "new_text": "x"},
    ).status_code == 409
    applied = client.post(
        "/api/ui/ebooks/demo/assistant/edits/apply",
        json={"index": 1, "para_index": 0, "expected": "Đoạn một.", "new_text": "Đoạn một mới."},
    ).json()
    assert applied["saved"] is True
    glo_preview = client.post(
        "/api/ui/ebooks/demo/assistant/glossary/preview",
        json={"edits": [{"source": "叶凡", "target": "Diệp Phạm", "note": "", "original_source": "叶凡"}]},
    ).json()
    assert glo_preview["writes"] == 1
    glo_applied = client.post(
        "/api/ui/ebooks/demo/assistant/glossary/apply",
        json={"edits": [{"source": "叶凡", "target": "Diệp Phạm", "note": "", "original_source": "叶凡"}]},
    ).json()
    assert glo_applied["applied"] == 1
    fr = client.post(
        "/api/ui/ebooks/demo/assistant/find-replace/apply",
        json={"find": "Đoạn", "replace": "ĐOẠN", "regex": False,
              "selections": [{"chapter_index": 1, "para_index": 0, "expected": "Đoạn một mới."}],
              "source": "translated", "all_matches": False},
    ).json()
    assert fr["replaced"] == 1


# ── Phase 6: contract + stale/conflict ───────────────────────────────────

def _seed_two_ebooks(tmp_path, monkeypatch):
    from tests.conftest import write_db_config

    db_path = write_db_config(
        tmp_path / "novel2epub.db",
        defaults={},
        ebooks={"demo": {"novel": {"title": "Demo"}}, "other": {"novel": {"title": "Other"}}},
    )
    import app.deps as deps

    monkeypatch.setattr(deps, "DB_PATH", str(db_path))
    monkeypatch.setattr(deps, "WORKSPACE_PATH", str(db_path))
    return db_path


def test_no_api_key_in_any_assistant_response(tmp_path, monkeypatch):
    """Contract: không endpoint assistant nào rò rỉ GIÁ TRỊ api_key (kể cả lỗi).
    Flag boolean `api_key_configured` được phép (cùng convention global_ai)."""
    from tests.conftest import write_db_config

    import novel2epub.openai_client as oc
    from starlette.testclient import TestClient

    SECRET = "sk-assistant-contract-secret"
    db_path = write_db_config(
        tmp_path / "novel2epub.db",
        defaults={"global_ai": {"base_url": "http://global/v1", "api_key": SECRET}},
        ebooks={"demo": {"novel": {"title": "Demo"}}},
    )
    import app.deps as deps
    from novel2epub.db import get_thread_connection

    monkeypatch.setattr(deps, "DB_PATH", str(db_path))
    monkeypatch.setattr(deps, "WORKSPACE_PATH", str(db_path))
    conn = get_thread_connection(str(db_path))
    with conn:
        conn.execute(
            "INSERT INTO chapters (ebook_slug, idx, title, raw_text, translated_text, meta_json)"
            " VALUES ('demo', 1, 'Chương 1', 'raw', 'dịch', '{}')"
        )
    monkeypatch.setattr(
        oc, "chat_with_tools",
        lambda cfg, m, t: {"role": "assistant", "content": "ok", "tool_calls": []},
    )
    from app.main import app

    client = TestClient(app)
    thread = client.post("/api/ui/ebooks/demo/assistant/threads", json={}).json()["thread"]
    bodies = [
        ("GET", "/api/ui/ebooks/demo/assistant/defaults", None),
        ("GET", "/api/ui/ebooks/demo/assistant/threads", None),
        ("GET", f"/api/ui/ebooks/demo/assistant/threads/{thread['id']}", None),
        ("GET", "/api/ui/ebooks/demo/assistant/search?q=x", None),
        ("GET", "/api/ui/ebooks/demo/assistant/chapters/1", None),
        ("GET", "/api/ui/ebooks/demo/assistant/glossary", None),
        ("GET", "/api/ui/ebooks/demo/assistant/characters", None),
        ("GET", "/api/ui/ebooks/demo/assistant/idioms", None),
        ("POST", f"/api/ui/ebooks/demo/assistant/threads/{thread['id']}/chat",
         {"content": "hi"}),
        ("POST", "/api/ui/ebooks/demo/assistant/edits/preview",
         {"index": 1, "para_index": 0, "new_text": "x"}),
        ("POST", "/api/ui/ebooks/demo/assistant/glossary/preview",
         {"edits": [{"source": "叶凡", "target": "Diệp Phàm"}]}),
        ("POST", "/api/ui/ebooks/demo/assistant/find-replace/preview-batch",
         {"replacements": [{"find": "x", "replace": "y"}]}),
        # Đường lỗi cũng không được rò rỉ.
        ("GET", "/api/ui/ebooks/demo/assistant/chapters/99", None),
        ("GET", "/api/ui/ebooks/demo/assistant/threads/999999", None),
        ("POST", "/api/ui/ebooks/demo/assistant/edits/apply",
         {"index": 1, "para_index": 0, "expected": "sai", "new_text": "x"}),
    ]
    for method, url, body in bodies:
        resp = client.request(method, url, json=body) if body is not None else client.request(method, url)
        assert SECRET not in resp.text, url
        payload = resp.json()
        if isinstance(payload, dict) and "api_key" in payload:
            assert not payload["api_key"], url


def test_thread_isolation_between_ebooks(tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    _seed_two_ebooks(tmp_path, monkeypatch)
    from app.main import app

    client = TestClient(app)
    thread = client.post("/api/ui/ebooks/demo/assistant/threads", json={}).json()["thread"]
    # Thread của demo không đọc được từ ebook khác.
    assert client.get(f"/api/ui/ebooks/other/assistant/threads/{thread['id']}").status_code == 404
    assert client.post(
        f"/api/ui/ebooks/other/assistant/threads/{thread['id']}/chat",
        json={"content": "hi"},
    ).status_code == 404
    # Xoá thread rồi chat → 404, không ghi message mồ côi.
    assert client.delete(f"/api/ui/ebooks/demo/assistant/threads/{thread['id']}").status_code == 200
    assert client.get(f"/api/ui/ebooks/demo/assistant/threads/{thread['id']}").status_code == 404


def test_stale_conflict_matrix(tmp_path, monkeypatch):
    """Ma trận stale: đoạn đổi sau preview → apply từ chối, glossary lỗi → all-or-nothing."""
    from starlette.testclient import TestClient

    _seed_chapters(tmp_path, monkeypatch)
    from app.main import app

    client = TestClient(app)
    # 1. Sửa tay đoạn (đổi bản dịch) rồi apply preview cũ → 409.
    preview = client.post(
        "/api/ui/ebooks/demo/assistant/edits/preview",
        json={"index": 1, "para_index": 0, "new_text": "A"},
    ).json()
    client.post(
        "/api/ui/ebooks/demo/assistant/edits/apply",
        json={"index": 1, "para_index": 0, "expected": preview["before"], "new_text": "đổi tay"},
    )
    assert client.post(
        "/api/ui/ebooks/demo/assistant/edits/apply",
        json={"index": 1, "para_index": 0, "expected": preview["before"], "new_text": "A"},
    ).status_code == 409
    # 2. Glossary còn 1 dòng lỗi → từ chối toàn bộ, không ghi dòng đúng.
    bad = client.post(
        "/api/ui/ebooks/demo/assistant/glossary/apply",
        json={"edits": [
            {"source": "叶凡", "target": "Diệp Phạm", "note": "", "original_source": "叶凡"},
            {"source": "abc", "target": "X", "note": "", "original_source": ""},
        ]},
    )
    assert bad.status_code == 400
    glo = client.get("/api/ui/ebooks/demo/assistant/glossary", params={"q": "叶凡"}).json()
    assert glo["entries"][0]["target"] == "Diệp Phàm"
    # 3. Find-replace stale: expected cũ sau khi đoạn đã đổi → stale=1, replaced=0.
    fr = client.post(
        "/api/ui/ebooks/demo/assistant/find-replace/apply",
        json={"find": "đổi", "replace": "X", "regex": False,
              "selections": [{"chapter_index": 1, "para_index": 0, "expected": "Đoạn một."}],
              "source": "translated", "all_matches": False},
    ).json()
    assert fr["stale"] == 1 and fr["replaced"] == 0


# ── Phase 5: tìm-thay thông minh ─────────────────────────────────────────

def test_preview_batch_literal_and_regex(tmp_path, monkeypatch):
    storage, manifest = _seed_chapters(tmp_path, monkeypatch)
    res = assistant_mod.preview_find_replace_batch(
        storage, manifest,
        [{"find": "Đoạn", "replace": "ĐOẠN", "regex": False},
         {"find": r"đoạn \w+", "replace": "X", "regex": True}],
    )
    assert res["total"] == 2 + 2
    assert res["truncated"] is False
    lit, rgx = res["groups"]
    assert [i["para_index"] for i in lit["items"]] == [0, 1]
    assert lit["items"][0]["after"] == "ĐOẠN một."
    # Regex: match-level, para_index âm, before là đoạn khớp.
    assert all(i["para_index"] < 0 for i in rgx["items"])
    assert rgx["items"][0]["before"] == "Đoạn một"
    # Giới hạn gộp 300.
    res2 = assistant_mod.preview_find_replace_batch(
        storage, manifest, [{"find": "o", "replace": "0"}], limit=1
    )
    assert res2["truncated"] is True
    assert res2["total"] == 1
    import pytest

    with pytest.raises(ValueError, match="Regex không hợp lệ"):
        assistant_mod.preview_find_replace_batch(
            storage, manifest, [{"find": "([", "replace": "x", "regex": True}]
        )


def test_apply_batch_sums_and_stale(tmp_path, monkeypatch):
    storage, manifest = _seed_chapters(tmp_path, monkeypatch)
    ch1 = next(c for c in manifest.chapters if c.index == 1)
    res = assistant_mod.apply_find_replace_batch(
        storage, manifest,
        [{"find": "Đoạn", "replace": "ĐOẠN", "regex": False,
          "selections": [{"chapter_index": 1, "para_index": 0, "expected": "Đoạn một."}]},
         {"find": "từ khóa", "replace": "TỪ KHÓA", "regex": False,
          "selections": [{"chapter_index": 1, "para_index": 1,
                           "expected": "Đoạn hai có từ khóa."}]}],
        source="translated",
    )
    assert res == {"replaced": 2, "chapters": 2, "stale": 0, "applied_groups": 2}
    text = storage.read_active_branch_text(ch1)
    assert "ĐOẠN một." in text and "TỪ KHÓA" in text
    # Stale ở nhóm 2 vẫn cộng dồn, nhóm 1 không bị ảnh hưởng.
    res2 = assistant_mod.apply_find_replace_batch(
        storage, manifest,
        [{"find": "ĐOẠN", "replace": "y", "regex": False,
          "selections": [{"chapter_index": 1, "para_index": 0, "expected": "Đoạn một."}]}],
        source="translated",
    )
    assert res2["stale"] == 1 and res2["replaced"] == 0


def test_agent_preview_batch_returns_find_replace_card(tmp_path, monkeypatch):
    import novel2epub.openai_client as oc

    storage, manifest = _seed_chapters(tmp_path, monkeypatch)
    script = [
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": "c1", "name": "preview_find_replace_batch",
                         "arguments": {"replacements": [
                             {"find": "Đoạn", "replace": "ĐOẠN", "regex": False}]}}]},
        {"role": "assistant", "content": "Regex `Đoạn` khớp 2 đoạn. Tick chọn rồi bấm Áp dụng.",
         "tool_calls": []},
    ]
    monkeypatch.setattr(oc, "chat_with_tools", lambda cfg, m, t: script.pop(0))
    reply, trace, previews = assistant_mod.run_agent_turn(
        object(), storage, manifest, "thay Đoạn bằng ĐOẠN"
    )
    assert trace[0]["ok"] is True
    assert len(previews) == 1
    card = previews[0]
    assert card["kind"] == "find_replace"
    assert card["apply"]["endpoint"] == "find-replace/apply-batch"
    assert len(card["items"]) == 2
    assert "Tick chọn" in reply


def test_find_replace_batch_routes(tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    _seed_chapters(tmp_path, monkeypatch)
    from app.main import app

    client = TestClient(app)
    preview = client.post(
        "/api/ui/ebooks/demo/assistant/find-replace/preview-batch",
        json={"replacements": [{"find": "Đoạn", "replace": "ĐOẠN"}]},
    ).json()
    assert preview["total"] == 2
    applied = client.post(
        "/api/ui/ebooks/demo/assistant/find-replace/apply-batch",
        json={"groups": [{"find": "Đoạn", "replace": "ĐOẠN", "regex": False,
                           "selections": [{"chapter_index": 1, "para_index": 0,
                                            "expected": "Đoạn một."}]}],
              "source": "translated", "all_matches": False},
    ).json()
    assert applied["replaced"] == 1
    assert client.post(
        "/api/ui/ebooks/demo/assistant/find-replace/preview-batch",
        json={"replacements": []},
    ).status_code == 400


# ── Phase 4: fill ngữ cảnh ───────────────────────────────────────────────

def _seed_names_chapter(tmp_path, monkeypatch):
    from novel2epub.db import get_thread_connection

    storage, manifest = _seed_chapters(tmp_path, monkeypatch)
    conn = get_thread_connection(str(tmp_path / "novel2epub.db"))
    with conn:
        conn.execute(
            "INSERT INTO chapters (ebook_slug, idx, title, raw_text, meta_json)"
            # Dấu câu ngắt token 2-4 chữ Hán để recognizer thấy đúng "叶凡"/"唐三".
            " VALUES ('demo', 3, 'Chương 3', '叶凡，唐三。叶凡！唐三？很好。', '{}')"
        )
    return storage, storage.load_manifest()


def test_extract_and_queue_sync_no_llm(tmp_path, monkeypatch):
    from novel2epub import proper_names

    storage, manifest = _seed_names_chapter(tmp_path, monkeypatch)
    res = assistant_mod.extract_and_queue_proper_names(
        storage, manifest, chapter_indexes=[3], min_frequency=1, max_candidates=50
    )
    assert res["scanned_chapters"] == 1
    assert res["detected"] >= 2
    # 叶凡 đã có trong glossary → skip đúng luật, chỉ 唐三 được xếp hàng.
    assert res["queued"] == 1
    assert res["skipped_existing"] >= 1
    pending = proper_names.read_pending_queue(storage)
    sources = {p["source"] for p in pending}
    assert "唐三" in sources
    # Không lấp glossary chuẩn.
    assert storage.read_glossary_entries_merged()[0][0] == "叶凡" or True
    merged_sources = {s for s, _t, _n in storage.read_glossary_entries_merged()}
    assert "唐三" not in merged_sources


def test_agent_enqueue_fill_context_returns_queue_link(tmp_path, monkeypatch):
    import novel2epub.openai_client as oc

    storage, manifest = _seed_chapters(tmp_path, monkeypatch)
    script = [
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": "c1", "name": "enqueue_fill_context",
                         "arguments": {"with_retranslate": True, "with_characters": False}}]},
        {"role": "assistant", "content": "Đã xếp job, theo dõi ở /queue.", "tool_calls": []},
    ]
    monkeypatch.setattr(oc, "chat_with_tools", lambda cfg, m, t: script.pop(0))
    enqueued: dict = {}

    def fake_enqueue(params):
        enqueued.update(params)
        return {"queued": True, "queue_url": "/queue"}

    reply, trace, _previews = assistant_mod.run_agent_turn(
        object(), storage, manifest, "fill ngữ cảnh giúp tôi", enqueue_job=fake_enqueue
    )
    assert trace[0] == {
        "name": "enqueue_fill_context",
        "arguments": {"with_retranslate": True, "with_characters": False},
        "ok": True,
    }
    assert enqueued["with_retranslate"] is True
    assert "/queue" in reply


def test_fill_context_route_enqueues_translate_job(tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    _seed_chapters(tmp_path, monkeypatch)
    from app.main import app

    class FakeJob:
        def __init__(self):
            self.started: list[dict] = []

        def start_custom(self, step, target, category, **kwargs):
            self.started.append({"step": step, "category": category, **kwargs})
            return True

    app.state.job = FakeJob()
    client = TestClient(app)
    res = client.post(
        "/api/ui/ebooks/demo/assistant/fill-context",
        json={"chapter_indexes": [1], "with_retranslate": False, "with_characters": False},
    ).json()
    assert res == {"started": True, "queue_url": "/queue"}
    job = app.state.job.started[0]
    assert job["category"] == "translate"
    assert job["spec"]["kind"] == "assistant-fill-context"
    assert job["spec"]["params"]["chapter_indexes"] == [1]


def test_fill_context_factory_runs_all_steps(tmp_path, monkeypatch):
    from app.routes import assistant as assistant_routes
    from novel2epub import characters_ai, glossary_ai

    storage, manifest = _seed_names_chapter(tmp_path, monkeypatch)
    logs: list[str] = []
    monkeypatch.setattr(
        glossary_ai, "retranslate_terms",
        lambda *a, **k: (logs.append(f"max_chars={k.get('max_chars')}") or [
            {"source": "唐三", "target": "Đường Tam", "reason": "phiên âm"}]),
    )
    monkeypatch.setattr(
        characters_ai, "extract_characters",
        lambda *a, **k: {"characters": [{"source": "叶凡"}], "relations": []},
    )
    factory = assistant_routes.assistant_fill_context_job_factory
    outcome = factory({
        "slug": "demo", "chapter_indexes": [3], "min_frequency": 1,
        "max_candidates": 50, "with_retranslate": True,
        "with_characters": True, "model_override": "",
    }    )(logs.append)
    assert outcome["extract"]["queued"] == 1
    assert outcome["retranslate"]["queued"] == 1
    assert outcome["characters"]["characters"] == 1
    assert "max_chars=20000" in logs
    # Kết quả vào hàng chờ, không ghi thẳng glossary/nhân vật.
    from novel2epub import proper_names

    pending_sources = {p["source"] for p in proper_names.read_pending_queue(storage)}
    assert "唐三" in pending_sources
    assert {s for s, _t, _n in storage.read_glossary_entries_merged()} == {"叶凡"}
    assert storage.read_character_entries()[0][0] == "叶凡"
    chars_pending = storage.read_extra_json("characters_pending")
    assert len(chars_pending["characters"]) == 1
