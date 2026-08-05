"""Cấu hình `api` — token và CORS cho OPDS/API ngoài localhost."""
from __future__ import annotations

from novel2epub.config import ApiConfig, load_config
from novel2epub.config_writer import reset_defaults, update_defaults

from .conftest import write_db_config


def test_api_mac_dinh_rong(tmp_path):
    db = write_db_config(tmp_path / "n.db", defaults={})
    cfg = load_config(db)
    assert cfg.api == ApiConfig()
    assert cfg.api.token == ""
    assert cfg.api.cors_origins == []


def test_api_doc_duoc_tu_defaults(tmp_path):
    db = write_db_config(
        tmp_path / "n.db",
        defaults={"api": {"token": "abc123", "cors_origins": ["http://localhost:3000"]}},
    )
    cfg = load_config(db)
    assert cfg.api.token == "abc123"
    assert cfg.api.cors_origins == ["http://localhost:3000"]


def test_token_bi_strip_khoang_trang(tmp_path):
    db = write_db_config(tmp_path / "n.db", defaults={"api": {"token": "  abc  "}})
    assert load_config(db).api.token == "abc"


def test_cors_origins_bo_phan_tu_rong_va_strip(tmp_path):
    db = write_db_config(
        tmp_path / "n.db",
        defaults={"api": {"cors_origins": [" http://a ", "", "   ", "http://b"]}},
    )
    assert load_config(db).api.cors_origins == ["http://a", "http://b"]


def test_cors_origins_khong_phai_list_thi_bo_qua(tmp_path):
    db = write_db_config(tmp_path / "n.db", defaults={"api": {"cors_origins": "http://a"}})
    assert load_config(db).api.cors_origins == []


def test_update_defaults_ghi_duoc_section_api(tmp_path):
    db = write_db_config(tmp_path / "n.db", defaults={})
    update_defaults(db, {"api": {"token": "tok"}})
    assert load_config(db).api.token == "tok"


def test_reset_defaults_xoa_duoc_section_api(tmp_path):
    db = write_db_config(tmp_path / "n.db", defaults={"api": {"token": "tok"}})
    assert reset_defaults(db, ["api"]) == ["api"]
    assert load_config(db).api.token == ""
