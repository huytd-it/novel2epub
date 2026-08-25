"""Khoá hợp đồng giữa API đọc cấu hình và các form lưu cấu hình.

`GET /api/ui/ebooks/{slug}/settings` trả cấu hình phẳng theo ĐÚNG tên tham số
`Form(...)` của các endpoint lưu trong `app/routes/settings.py`, vì giao diện
mới POST thẳng vào chính các endpoint cũ đó.

Đây là loại ràng buộc mục âm thầm: thêm một trường vào form mà quên thêm vào
API thì ô đó hiện rỗng rồi ghi đè giá trị thật bằng rỗng lúc người dùng bấm
Lưu — không có lỗi nào nổ ra. Test này so hai đầu và bắt lệch ngay.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.routes import settings as settings_routes

from .conftest import write_db_config

# (khoá trong JSON, hàm xử lý form tương ứng)
SECTIONS = [
    ("novel", "save_novel"),
    ("source", "save_source"),
    ("translate", "save_translate"),
    ("ai", "save_ai"),
    ("reader", "save_reader"),
    ("output", "save_output"),
]

# Tham số đường dẫn / hạ tầng, không phải trường cấu hình.
NON_FIELDS = {"request", "slug"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = write_db_config(
        tmp_path / "n.db",
        defaults={"output": {"data_dir": str(tmp_path / "data")}},
        sources={"test-source": {"headless": False}},
        ebooks={"t": {"source": "test-source", "novel": {"title": "Truyện thử"}}},
    )
    monkeypatch.setattr("app.deps.WORKSPACE_PATH", str(db))
    monkeypatch.setattr("app.deps.DB_PATH", str(db))
    from app.main import app

    return TestClient(app, client=("127.0.0.1", 12345))


def form_fields(fn_name: str) -> set[str]:
    fn = getattr(settings_routes, fn_name)
    return {p for p in inspect.signature(fn).parameters if p not in NON_FIELDS}


@pytest.mark.parametrize(("section", "fn_name"), SECTIONS)
def test_api_tra_dung_bo_truong_ma_form_nhan(client, section, fn_name):
    payload = client.get("/api/ui/ebooks/t/settings").json()
    assert set(payload[section]) == form_fields(fn_name)


def test_moi_section_deu_co_mat(client):
    payload = client.get("/api/ui/ebooks/t/settings").json()
    for section, _ in SECTIONS:
        assert section in payload, f"thiếu section {section}"


def test_source_checkbox_false_xoa_override_true_cu(client):
    """SPA gửi boolean false rõ ràng; lần lưu sau phải xóa override true cũ."""
    current = client.get("/api/ui/ebooks/t/settings").json()["source"]

    enabled = client.post(
        "/api/ui/ebooks/t/settings/source",
        json={**current, "headless": True},
    )
    assert enabled.status_code == 200
    assert client.get("/api/ui/ebooks/t/settings").json()["source"]["headless"] is True

    disabled = client.post(
        "/api/ui/ebooks/t/settings/source",
        json={**current, "headless": False},
    )
    assert disabled.status_code == 200
    assert client.get("/api/ui/ebooks/t/settings").json()["source"]["headless"] is False


def test_default_prompts_tra_prompt_moi_theo_ngon_ngu(client):
    from novel2epub.config import DEFAULT_PROMPT, EN_DEFAULT_PROMPT, EN_TITLE_PROMPT, TITLE_PROMPT

    settings_page = (Path(__file__).parents[1] / "frontend/src/routes/SettingsPage.tsx").read_text(encoding="utf-8")
    assert "Nạp lại prompt" in settings_page
    assert "Xem prompt toàn màn hình" in settings_page
    assert "/settings/translate/default-prompts?source_language=" in settings_page

    chinese = client.get("/settings/translate/default-prompts")
    assert chinese.status_code == 200
    assert chinese.json() == {
        "prompt_template": DEFAULT_PROMPT,
        "title_prompt_template": TITLE_PROMPT,
    }

    english = client.get("/settings/translate/default-prompts?source_language=en")
    assert english.status_code == 200
    assert english.json() == {
        "prompt_template": EN_DEFAULT_PROMPT,
        "title_prompt_template": EN_TITLE_PROMPT,
    }


def test_danh_sach_tra_ve_dang_van_ban_moi_dong_mot_muc(client):
    """`subjects` và `strip_patterns` là list trong config nhưng form nhận text.

    Form tự tách lại bằng `splitlines()`, nên API phải nối bằng "\\n" — trả
    mảng JSON thì ô textarea sẽ hiện "[object Object]".
    """
    payload = client.get("/api/ui/ebooks/t/settings").json()
    assert isinstance(payload["novel"]["subjects"], str)
    assert isinstance(payload["source"]["strip_patterns"], str)


def test_meta_du_de_dung_giao_dien(client):
    meta = client.get("/api/ui/ebooks/t/settings").json()["meta"]
    assert set(meta) >= {
        "source_name",
        "source_detected",
        "source_presets",
        "overridden_fields",
        "genres",
    }
    assert all({"value", "label"} <= set(g) for g in meta["genres"])


def test_settings_response_never_exposes_global_api_key(client):
    from novel2epub.config_writer import update_defaults
    from app import deps

    update_defaults(deps.WORKSPACE_PATH, {"global_ai": {
        "base_url": "https://provider.example/v1",
        "api_key": "super-secret-key",
        "translation_model": "translation-model",
        "assistant_model": "assistant-model",
    }})

    payload = client.get("/api/ui/ebooks/t/settings").json()
    assert "super-secret-key" not in client.get("/api/ui/ebooks/t/settings").text
    assert payload["translate"]["api_key"] == ""
    assert payload["ai"]["api_key"] == ""
    assert payload["global_ai"]["api_key"] == ""
    assert payload["global_ai"]["api_key_configured"] is True


def test_global_ai_save_blank_key_keeps_secret_and_explicit_clear_removes_it(client):
    from novel2epub.config_writer import update_defaults
    from app import deps

    update_defaults(deps.WORKSPACE_PATH, {"global_ai": {
        "base_url": "https://provider.example/v1",
        "api_key": "keep-me",
        "translation_model": "old-translation",
        "assistant_model": "old-assistant",
    }})
    response = client.post("/api/ui/settings/global-ai", json={
        "base_url": "https://new.example/v1",
        "api_key": "",
        "translation_model": "new-translation",
        "assistant_model": "new-assistant",
        "timeout_seconds": 60,
        "temperature": 0.3,
    })
    assert response.status_code == 200
    assert "keep-me" not in response.text
    assert client.get("/api/ui/settings/global-ai").json()["api_key_configured"] is True

    cleared = client.post("/api/ui/settings/global-ai", json={"clear_api_key": True})
    assert cleared.status_code == 200
    assert client.get("/api/ui/settings/global-ai").json()["api_key_configured"] is False


def test_model_discovery_accepts_key_in_body_not_query(client, monkeypatch):
    captured = {}

    def fake_list_models(base_url, api_key="", timeout_seconds=30):
        captured.update(base_url=base_url, api_key=api_key, timeout=timeout_seconds)
        return ["model-a"]

    monkeypatch.setattr("app.routes.settings.openai_client.list_models", fake_list_models)
    response = client.post("/settings/ai/models", json={
        "base_url": "https://provider.example/v1",
        "api_key": "body-secret",
        "timeout_seconds": 12,
    })
    assert response.status_code == 200
    assert response.json() == {"models": ["model-a"]}
    assert captured == {
        "base_url": "https://provider.example/v1",
        "api_key": "body-secret",
        "timeout": 12,
    }
    assert client.get(
        "/settings/ai/models?base_url=https://provider.example/v1&api_key=query-secret"
    ).status_code == 405


def test_model_override_can_use_global_without_losing_other_translate_settings(client):
    from app import deps
    from novel2epub.config_writer import update_ebook

    update_ebook(deps.WORKSPACE_PATH, "t", {
        "translate": {"translation_model": "ebook-translation", "genre": "xianxia"},
        "ai": {"assistant_model": "ebook-assistant"},
    })
    current = client.get("/api/ui/ebooks/t/settings/model-overrides")
    assert current.json() == {
        "translation_model": "ebook-translation",
        "assistant_model": "ebook-assistant",
    }

    saved = client.post("/api/ui/ebooks/t/settings/model-overrides", json={
        "translation_model": "",
        "assistant_model": "new-assistant",
    })
    assert saved.status_code == 200
    assert saved.json()["model_overrides"] == {
        "translation_model": "",
        "assistant_model": "new-assistant",
    }
    assert client.get("/api/ui/ebooks/t/settings").json()["translate"]["genre"] == "xianxia"


def test_slug_khong_ton_tai_tra_404_khong_phai_500(client):
    """Khớp hành vi của `resolved_cfg`/`ebook_cfg` ở các endpoint khác: thư viện
    đã có ebook thì slug lạ là 404 (not found), không phải lỗi server."""
    res = client.get("/api/ui/ebooks/khong-co-that/settings")
    assert res.status_code == 404
