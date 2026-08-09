"""Test API sửa đoạn tại chỗ trên trang đọc (app/routes/chapters.py)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import deps
from novel2epub.config import (
    Config,
    CrawlConfig,
    NovelConfig,
    OutputConfig,
    TranslateConfig,
)
from novel2epub.storage import Chapter, Manifest, Storage


def _cfg(tmp_path):
    return Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/book/", delay_seconds=0),
        translate=TranslateConfig(type="none", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


def _seed(tmp_path, *, translated="A.\n\nB.\n\nC.", raw=None, mt=None):
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=7, url="http://x/7")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    if translated is not None:
        storage.write_translated(ch, translated)
    if raw is not None:
        storage.write_raw(ch, raw)
    if mt is not None:
        storage.write_translated_mt(ch, mt)
    return storage, ch


def _client(tmp_path, monkeypatch, cfg):
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    from app.main import app
    return TestClient(app)


def test_para_save_happy_path_keeps_mt_snapshot(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage, ch = _seed(tmp_path, mt="A.\n\nB.\n\nC.")
    client = _client(tmp_path, monkeypatch, cfg)

    res = client.post(
        "/api/ebooks/t/chapters/7/para/save",
        data={"para_index": 1, "para_text": "B.", "new_text": "B đã sửa."},
    )
    assert res.status_code == 200, res.text
    assert res.json()["saved"] is True
    assert storage.read_translated(ch) == "A.\n\nB đã sửa.\n\nC."
    # Snapshot MT KHÔNG đổi
    assert storage.read_translated_mt(ch) == "A.\n\nB.\n\nC."


def test_para_save_writes_active_local_mt_branch(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage, ch = _seed(tmp_path, translated="AI giữ nguyên.")
    storage.write_branch_text(ch, "local_mt", "A.\n\nB.\n\nC.")
    storage.mark_branch_complete(ch, "local_mt")
    storage.set_active_branch(ch, "local_mt")
    revision = storage.read_branch_revision(ch, "local_mt")
    client = _client(tmp_path, monkeypatch, cfg)

    res = client.post(
        "/api/ebooks/t/chapters/7/para/save",
        data={"para_index": 1, "para_text": "B.", "new_text": "B local."},
    )

    assert res.status_code == 200, res.text
    assert storage.read_branch_text(ch, "local_mt") == "A.\n\nB local.\n\nC."
    assert storage.read_branch_revision(ch, "local_mt") == revision + 1
    assert storage.read_branch_text(ch, "ai") == "AI giữ nguyên."


def test_para_save_stale_conflict(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _storage, _ch = _seed(tmp_path)
    client = _client(tmp_path, monkeypatch, cfg)

    res = client.post(
        "/api/ebooks/t/chapters/7/para/save",
        data={"para_index": 1, "para_text": "Đoạn cũ khác.", "new_text": "x"},
    )
    assert res.status_code == 409
    assert "thay đổi" in res.json()["detail"]


def test_para_save_empty_deletes_paragraph(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _storage, _ch = _seed(tmp_path)
    client = _client(tmp_path, monkeypatch, cfg)

    res = client.post(
        "/api/ebooks/t/chapters/7/para/save",
        data={"para_index": 1, "para_text": "B.", "new_text": "   "},
    )
    assert res.status_code == 200, res.text
    assert res.json()["deleted"] is True
    assert _storage.read_translated(_ch) == "A.\n\nC."


def test_para_save_unknown_chapter_404(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path)
    client = _client(tmp_path, monkeypatch, cfg)

    res = client.post(
        "/api/ebooks/t/chapters/999/para/save",
        data={"para_index": 0, "para_text": "A.", "new_text": "x"},
    )
    assert res.status_code == 404


from app.routes import chapters as chapters_route


def _cfg_ai(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.ai.openai.base_url = "http://ai.local/v1"  # bật guard "đã cấu hình AI"
    return cfg


def test_para_ai_edit_uses_ai_backend_and_zh_context(tmp_path, monkeypatch):
    cfg = _cfg_ai(tmp_path)
    # raw có CÙNG số đoạn với translated (3) → ZH đoạn 1 được đính kèm
    _seed(tmp_path, translated="A.\n\nB.\n\nC.", raw="甲。\n\n乙。\n\n丙。")
    client = _client(tmp_path, monkeypatch, cfg)

    captured = {}

    def fake_run_chat(openai_cfg, prompt):
        captured["cfg"] = openai_cfg
        captured["prompt"] = prompt
        return "B đã biên tập."

    monkeypatch.setattr(chapters_route, "openai_run_chat", fake_run_chat)

    res = client.post(
        "/api/ebooks/t/chapters/7/para/ai-edit",
        data={"para_index": 1, "text": "B.", "instruction": "xưng anh/em"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["edited"] == "B đã biên tập."
    # Dùng ĐÚNG backend AI biên tập, không phải translate
    assert captured["cfg"] is cfg.ai.openai
    # ZH đoạn tương ứng + chỉ dẫn có trong prompt
    assert "乙。" in captured["prompt"]
    assert "xưng anh/em" in captured["prompt"]


def test_para_ai_edit_no_zh_when_para_count_differs(tmp_path, monkeypatch):
    cfg = _cfg_ai(tmp_path)
    # raw 2 đoạn ≠ translated 3 đoạn → bỏ ZH
    _seed(tmp_path, translated="A.\n\nB.\n\nC.", raw="甲。\n\n乙。")
    client = _client(tmp_path, monkeypatch, cfg)

    captured = {}

    def fake_run_chat(openai_cfg, prompt):
        captured["prompt"] = prompt
        return "sửa"

    monkeypatch.setattr(chapters_route, "openai_run_chat", fake_run_chat)
    res = client.post(
        "/api/ebooks/t/chapters/7/para/ai-edit",
        data={"para_index": 1, "text": "B."},
    )
    assert res.status_code == 200
    assert "乙。" not in captured["prompt"]
    assert "(không có)" in captured["prompt"]


def test_para_ai_edit_requires_ai_config(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    # OpenAIConfig.base_url mặc định trỏ localhost — xoá để AI thực sự chưa cấu hình.
    cfg.ai.openai.base_url = ""
    cfg.ai.openai.api_key = ""
    _seed(tmp_path)
    client = _client(tmp_path, monkeypatch, cfg)
    res = client.post(
        "/api/ebooks/t/chapters/7/para/ai-edit",
        data={"para_index": 1, "text": "B."},
    )
    assert res.status_code == 400
    assert "AI" in res.json()["detail"]
