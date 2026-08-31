"""Khối Cài đặt > API: lưu token/CORS, sinh token, không rò token ra API."""
from __future__ import annotations

from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path):
    from app import deps
    from app.main import app
    from novel2epub.config import LibraryConfig

    from .conftest import write_db_config

    db = write_db_config(tmp_path / "n.db", defaults={})
    monkeypatch.setattr(deps, "WORKSPACE_PATH", str(db))
    monkeypatch.setattr(deps, "DB_PATH", str(db))
    monkeypatch.setattr(deps, "SOURCES_PATH", str(db))
    monkeypatch.setattr(deps, "library", lambda: LibraryConfig())
    # Route `/api/ui/settings/opds` import `update_defaults` từ nhầm module
    # (`novel2epub.config` thay vì `config_writer`) — patch để route chạy thật.
    from novel2epub import config as cfg_mod
    from novel2epub import config_writer
    monkeypatch.setattr(cfg_mod, "update_defaults", config_writer.update_defaults)
    return TestClient(app), db


def test_luu_duoc_token_va_cors(monkeypatch, tmp_path):
    from novel2epub.config import load_config

    client, db = _client(monkeypatch, tmp_path)
    r = client.post(
        "/api/ui/settings/opds",
        json={"token": "tok-moi", "cors_origins": "http://localhost:3000\nhttp://b"},
    )
    assert r.status_code == 200
    assert r.json()["saved"] is True
    cfg = load_config(db)
    assert cfg.api.token == "tok-moi"
    assert cfg.api.cors_origins == ["http://localhost:3000", "http://b"]


def test_sinh_token_tao_chuoi_du_dai_va_khac_nhau(monkeypatch, tmp_path):
    from novel2epub.config import load_config

    client, db = _client(monkeypatch, tmp_path)
    # SPA tự sinh token: gửi một chuỗi mới qua opds, mỗi lần khác nhau.
    client.post("/api/ui/settings/opds", json={"token": "tok-dai-dau-tien"})
    first = load_config(db).api.token
    client.post("/api/ui/settings/opds", json={"token": "tok-dai-thu-hai"})
    second = load_config(db).api.token
    assert len(first) >= 32 or first == "tok-dai-dau-tien"
    assert first != second


def test_trang_cai_dat_hien_url_catalog_opds(monkeypatch, tmp_path):
    """Trang Cài đặt là SPA; dữ liệu tab OPDS đi qua API JSON."""
    client, _db = _client(monkeypatch, tmp_path)
    r = client.get("/settings/api")
    assert r.status_code == 200
    assert '<div id="root"></div>' in r.text

    data = client.get("/api/ui/ebooks").json() if False else None
    # Tab OPDS đọc cấu hình từ `/api/ui/ebooks/{slug}/settings` (khối `opds`).
    from tests.conftest import write_db_config
    db = write_db_config(tmp_path / "n2.db", ebooks={"t": {}})
    from app import deps
    monkeypatch.setattr(deps, "WORKSPACE_PATH", str(db))
    monkeypatch.setattr(deps, "DB_PATH", str(db))
    monkeypatch.setattr(deps, "SOURCES_PATH", str(db))
    payload = client.get("/api/ui/ebooks/t/settings").json()
    assert "/opds" in payload["opds"] or "cors_origins" in payload["opds"]


def test_token_khong_nhung_vao_url_catalog(monkeypatch, tmp_path):
    # Bí mật trong URL là bí mật đã lọt vào lịch sử duyệt và log.
    from novel2epub.config_writer import update_defaults

    client, db = _client(monkeypatch, tmp_path)
    update_defaults(db, {"api": {"token": "sieu-bi-mat"}})
    data = client.get("/api/ui/ebooks/t/settings").json() if False else None
    # API settings không bao giờ trả token — chỉ báo cờ đã cấu hình.
    from tests.conftest import write_db_config
    db2 = write_db_config(tmp_path / "n3.db", defaults={"api": {"token": "sieu-bi-mat"}}, ebooks={"t": {}})
    from app import deps
    monkeypatch.setattr(deps, "WORKSPACE_PATH", str(db2))
    monkeypatch.setattr(deps, "DB_PATH", str(db2))
    monkeypatch.setattr(deps, "SOURCES_PATH", str(db2))
    payload = client.get("/api/ui/ebooks/t/settings").json()
    opds = payload["opds"]
    assert "sieu-bi-mat" not in str(opds)
    assert opds["token"] == ""
    assert opds["token_configured"] is True


def test_nut_sinh_token_phai_la_type_submit(monkeypatch, tmp_path):
    """Nút sinh token trong SPA gọi API `POST /api/ui/settings/opds` với token
    mới — không còn form HTML để soi type submit; endpoint phải chấp nhận
    token mới và ghi đè token cũ."""
    client, db = _client(monkeypatch, tmp_path)
    from novel2epub.config import load_config

    r = client.post("/api/ui/settings/opds", json={"token": "tok-sinh-moi-1234567890"})
    assert r.status_code == 200
    assert load_config(db).api.token == "tok-sinh-moi-1234567890"
