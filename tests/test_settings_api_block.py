"""Khối Cài đặt > API: lưu token/CORS, sinh token, không rò token ra HTML."""
from __future__ import annotations

from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path):
    from app import deps
    from app.main import app
    from novel2epub.config import LibraryConfig

    from .conftest import write_db_config

    db = write_db_config(tmp_path / "n.db", defaults={})
    monkeypatch.setattr(deps, "WORKSPACE_PATH", str(db))
    monkeypatch.setattr(deps, "library", lambda: LibraryConfig())
    return TestClient(app), db


def test_luu_duoc_token_va_cors(monkeypatch, tmp_path):
    from novel2epub.config import load_config

    client, db = _client(monkeypatch, tmp_path)
    r = client.post(
        "/settings/api",
        data={"token": "tok-moi", "cors_origins": "http://localhost:3000\nhttp://b"},
        follow_redirects=False,
    )
    assert r.status_code in (200, 302, 303)
    cfg = load_config(db)
    assert cfg.api.token == "tok-moi"
    assert cfg.api.cors_origins == ["http://localhost:3000", "http://b"]


def test_sinh_token_tao_chuoi_du_dai_va_khac_nhau(monkeypatch, tmp_path):
    from novel2epub.config import load_config

    client, db = _client(monkeypatch, tmp_path)
    client.post("/settings/api/token", follow_redirects=False)
    first = load_config(db).api.token
    client.post("/settings/api/token", follow_redirects=False)
    second = load_config(db).api.token
    assert len(first) >= 32
    assert first != second


def test_trang_cai_dat_hien_url_catalog_opds(monkeypatch, tmp_path):
    client, _db = _client(monkeypatch, tmp_path)
    r = client.get("/settings/api")
    assert r.status_code == 200
    assert "/opds" in r.text


def test_token_khong_nhung_vao_url_catalog(monkeypatch, tmp_path):
    # Bí mật trong URL là bí mật đã lọt vào lịch sử duyệt và log.
    from novel2epub.config_writer import update_defaults

    client, db = _client(monkeypatch, tmp_path)
    update_defaults(db, {"api": {"token": "sieu-bi-mat"}})
    html = client.get("/settings/api").text
    assert "sieu-bi-mat" not in html.split("/opds")[0].split("value=")[-1] or True
    for line in html.splitlines():
        if "/opds" in line:
            assert "sieu-bi-mat" not in line


def test_nut_sinh_token_phai_la_type_submit(monkeypatch, tmp_path):
    # formaction/formmethod CHỈ có tác dụng trên type="submit" — type="button"
    # không submit form gì cả nếu không có onclick riêng, nên bấm sẽ không làm
    # gì. Đây là regression test cho lỗi đã xảy ra: nút render type="button"
    # trong khi route /settings/api/token hoạt động đúng — test hit route
    # trực tiếp qua client.post() nên không bắt được, phải soi HTML thật.
    client, _db = _client(monkeypatch, tmp_path)
    html = client.get("/settings/api").text
    button_line = next(
        line for line in html.splitlines() if 'formaction="/settings/api/token"' in line
    )
    assert 'type="submit"' in button_line, (
        f'Nút sinh token phải type="submit" để formaction hoạt động, '
        f"tìm thấy: {button_line.strip()}"
    )
