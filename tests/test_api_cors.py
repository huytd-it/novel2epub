"""CORS chỉ bật khi được cấu hình, và không bao giờ là '*'.

Ba test cuối là bài kiểm tra "final review" cho lỗ hổng lộ token: middleware
CORS chỉ được thêm header cho /opds/* và /api/v1/*, KHÔNG BAO GIỜ cho các
route web UI khác (đại diện: /settings/api, nơi token hiện cleartext trong
HTML) — nếu không, một origin đã cấu hình có thể fetch() token từ trang cài
đặt rồi giả mạo API. Cũng xác nhận allow_credentials không bật ở đâu."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import _cors_origins, app


def test_khong_cau_hinh_thi_khong_co_origin_nao(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.WORKSPACE_PATH", str(tmp_path / "khong-ton-tai.db"))
    assert _cors_origins() == []


def test_doc_duoc_origin_tu_config(tmp_path):
    from novel2epub.config_writer import update_defaults

    from .conftest import write_db_config

    db = write_db_config(tmp_path / "n.db", defaults={})
    update_defaults(db, {"api": {"cors_origins": ["http://localhost:3000"]}})
    from app import main

    assert main._cors_origins(str(db)) == ["http://localhost:3000"]


def test_sao_bi_loai_bo(tmp_path):
    from novel2epub.config_writer import update_defaults

    from .conftest import write_db_config

    db = write_db_config(tmp_path / "n.db", defaults={})
    update_defaults(db, {"api": {"cors_origins": ["*", "http://a"]}})
    from app import main

    assert main._cors_origins(str(db)) == ["http://a"]


ORIGIN = "http://localhost:3000"


def _client_with_origin_allowed(monkeypatch):
    """Giả lập origin đã được cấu hình trong Cài đặt > API, không đụng DB thật."""
    monkeypatch.setattr("app.main._cors_origins", lambda *a, **k: [ORIGIN])
    return TestClient(app, client=("127.0.0.1", 12345))


def test_opds_books_co_header_cors_khi_origin_duoc_cau_hinh(monkeypatch):
    client = _client_with_origin_allowed(monkeypatch)
    r = client.get("/opds/books", headers={"Origin": ORIGIN})
    assert r.headers.get("access-control-allow-origin") == ORIGIN


def test_settings_api_khong_bao_gio_co_header_cors(monkeypatch):
    """Route web UI (không phải /opds hay /api/v1) không được nhận CORS dù
    origin đã được cấu hình — đây chính là finding bị khai thác: token hiện
    cleartext ở trang này, lộ ra ngoài nếu route này có CORS."""
    client = _client_with_origin_allowed(monkeypatch)
    r = client.get("/settings/api", headers={"Origin": ORIGIN})
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


def test_preflight_opds_co_cors_settings_khong(monkeypatch):
    client = _client_with_origin_allowed(monkeypatch)

    preflight_opds = client.options(
        "/opds/books",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert preflight_opds.headers.get("access-control-allow-origin") == ORIGIN

    preflight_settings = client.options(
        "/settings/api",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in {k.lower() for k in preflight_settings.headers}


def test_khong_bao_gio_bat_allow_credentials(monkeypatch):
    client = _client_with_origin_allowed(monkeypatch)
    r = client.get("/opds/books", headers={"Origin": ORIGIN})
    assert "access-control-allow-credentials" not in {k.lower() for k in r.headers}
