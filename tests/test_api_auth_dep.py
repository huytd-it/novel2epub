"""Dependency xác thực ở tầng HTTP: mã lỗi, header thử thách, miễn localhost."""
from __future__ import annotations

import base64

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from novel2epub.config import ApiConfig


def _app(monkeypatch, token: str):
    from app import auth, deps

    class _Cfg:
        api = ApiConfig(token=token)

    monkeypatch.setattr(deps, "cfg", lambda: _Cfg())
    api = FastAPI()

    @api.get("/protected")
    def protected(_=Depends(auth.require_api_auth)):
        return {"ok": True}

    return api


def _client(monkeypatch, token: str, host: str = "127.0.0.1"):
    # TestClient mặc định báo client host là "testclient" (không phải localhost),
    # nên dùng nó để mô phỏng máy KHÁC; truyền client=... để mô phỏng localhost.
    return TestClient(_app(monkeypatch, token), client=(host, 12345))


def _basic(password: str) -> dict[str, str]:
    raw = base64.b64encode(f"u:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": "Basic " + raw}


def test_localhost_duoc_mien_token(monkeypatch):
    r = _client(monkeypatch, token="tok", host="127.0.0.1").get("/protected")
    assert r.status_code == 200


def test_localhost_duoc_mien_ngay_ca_khi_chua_cau_hinh_token(monkeypatch):
    r = _client(monkeypatch, token="", host="127.0.0.1").get("/protected")
    assert r.status_code == 200


def test_may_khac_khong_co_token_tra_401_kem_www_authenticate(monkeypatch):
    r = _client(monkeypatch, token="tok", host="192.168.1.20").get("/protected")
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == 'Basic realm="novel2epub"'


def test_may_khac_sai_token_tra_401(monkeypatch):
    r = _client(monkeypatch, token="tok", host="192.168.1.20").get(
        "/protected", headers=_basic("sai")
    )
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == 'Basic realm="novel2epub"'


def test_may_khac_dung_token_basic_thi_qua(monkeypatch):
    r = _client(monkeypatch, token="tok", host="192.168.1.20").get(
        "/protected", headers=_basic("tok")
    )
    assert r.status_code == 200


def test_may_khac_dung_token_bearer_thi_qua(monkeypatch):
    r = _client(monkeypatch, token="tok", host="192.168.1.20").get(
        "/protected", headers={"Authorization": "Bearer tok"}
    )
    assert r.status_code == 200


def test_chua_cau_hinh_token_tra_503_khong_phai_401(monkeypatch):
    # Lỗi cấu hình phía server, KHÔNG phải thử thách xác thực — không được
    # để readest tưởng có thể đàm phán.
    r = _client(monkeypatch, token="", host="192.168.1.20").get("/protected")
    assert r.status_code == 503
    assert "WWW-Authenticate" not in r.headers


def test_x_forwarded_for_gia_mao_khong_duoc_mien_tru(monkeypatch):
    # Đây là test quan trọng nhất của file: header do client tự đặt không
    # bao giờ được biến thành quyền truy cập.
    r = _client(monkeypatch, token="tok", host="192.168.1.20").get(
        "/protected",
        headers={"X-Forwarded-For": "127.0.0.1", "X-Real-IP": "127.0.0.1"},
    )
    assert r.status_code == 401


def test_token_khong_lot_vao_than_response(monkeypatch):
    r = _client(monkeypatch, token="sieu-bi-mat", host="192.168.1.20").get("/protected")
    assert "sieu-bi-mat" not in r.text
