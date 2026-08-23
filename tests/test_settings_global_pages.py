"""Test các endpoint cấu hình CHUNG: Local MT (`/api/ui/settings/local-mt*`)
và Dịch Chung (`/api/ui/settings/translate-defaults`)."""
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


def _cfg(tmp_path):
    return Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/book/", delay_seconds=0),
        translate=TranslateConfig(type="openai", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


def _client(cfg, monkeypatch) -> TestClient:
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    from app.main import app

    return TestClient(app)


def test_local_mt_overview_lists_catalog_and_config(tmp_path, monkeypatch):
    client = _client(_cfg(tmp_path), monkeypatch)

    res = client.get("/api/ui/settings/local-mt")
    assert res.status_code == 200
    data = res.json()
    # Catalog đọc trực tiếp từ MODELS — bổ sung model mới chỉ cần thêm backend.
    engines = data["engines"]
    assert engines and engines[0]["id"] == "hachimimt"
    models = engines[0]["models"]
    keys = {m["key"] for m in models}
    assert "HachimiMT-60" in keys
    for m in models:
        assert isinstance(m["downloaded"], bool)
        assert m["label"] == m["key"]
    assert data["config"]["model_key"] == "HachimiMT-60"
    assert data["config"]["chunk_mode"] in ("sentence", "paragraph")


def test_local_mt_config_save_writes_defaults(tmp_path, monkeypatch):
    from novel2epub.config_writer import _read_settings_sections
    from novel2epub.db import get_thread_connection

    db_path = tmp_path / "novel2epub.db"
    cfg = _cfg(db_path)
    monkeypatch.setattr(deps, "WORKSPACE_PATH", str(db_path))
    client = _client(cfg, monkeypatch)

    res = client.post(
        "/api/ui/settings/local-mt/config",
        json={"model_key": "MoxhiMT-30", "beam_size": 3, "chunk_mode": "paragraph"},
    )
    assert res.status_code == 200
    assert res.json()["saved"] is True

    conn = get_thread_connection(db_path.resolve())
    stored = _read_settings_sections(conn)
    assert stored["translate"]["hachimimt"]["model_key"] == "MoxhiMT-30"
    assert stored["translate"]["hachimimt"]["beam_size"] == 3
    assert stored["translate"]["hachimimt"]["chunk_mode"] == "paragraph"


def test_local_mt_config_rejects_unknown_model(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path / "db")
    client = _client(cfg, monkeypatch)

    res = client.post("/api/ui/settings/local-mt/config", json={"model_key": "Nope-9000"})
    assert res.status_code == 400


def test_translate_defaults_roundtrip(tmp_path, monkeypatch):
    from novel2epub.config_writer import _read_settings_sections
    from novel2epub.db import get_thread_connection

    db_path = tmp_path / "novel2epub.db"
    cfg = _cfg(db_path)
    monkeypatch.setattr(deps, "WORKSPACE_PATH", str(db_path))
    client = _client(cfg, monkeypatch)

    got = client.get("/api/ui/settings/translate-defaults")
    assert got.status_code == 200
    payload = got.json()
    assert payload["target_language"] == "vi"
    assert isinstance(payload.get("genres"), list) and payload["genres"]

    res = client.post("/api/ui/settings/translate-defaults", json={
        **payload,
        "genre": "wuxia",
        "prompt_max_chars": 12000,
        "retry_attempts": 4,
        "tone": "hào hùng",
        "prompt_template": "# Dịch\n{text}",
    })
    assert res.status_code == 200
    assert res.json()["saved"] is True

    # GET đọc từ deps.cfg() (đã patch tĩnh) — kiểm tra độ bền bằng cách nạp
    # LẠI config từ DB như một tiến trình mới.
    from novel2epub.config import load_config

    reloaded = load_config(db_path)
    assert reloaded.translate.genre == "wuxia"
    assert reloaded.translate.prompt_max_chars == 12000
    assert reloaded.translate.retry.attempts == 4
    assert reloaded.translate.style.tone == "hào hùng"
    assert "{text}" in reloaded.translate.openai.prompt_template
    # Prompt ghi vào openai.* — không đè mất credential đang có.
    conn = get_thread_connection(db_path.resolve())
    stored = _read_settings_sections(conn)["translate"]
    assert stored["retry"] == {"attempts": 4, "delay_seconds": payload["retry_delay_seconds"]}
