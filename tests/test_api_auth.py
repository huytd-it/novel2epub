"""Logic xác thực thuần cho API/OPDS — không đụng HTTP."""
from __future__ import annotations

import base64

from novel2epub.api_auth import (
    WWW_AUTHENTICATE,
    is_local_client,
    token_from_header,
    token_matches,
)


def _basic(user: str, password: str) -> str:
    raw = f"{user}:{password}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def test_bearer_tra_ve_token():
    assert token_from_header("Bearer abc123") == "abc123"


def test_scheme_khong_phan_biet_hoa_thuong():
    assert token_from_header("bearer abc123") == "abc123"
    assert token_from_header("BASIC " + _basic("u", "p").split(" ", 1)[1]) == "p"


def test_basic_lay_password_bo_qua_username():
    # readest gửi username/password; ta chỉ quan tâm password.
    assert token_from_header(_basic("bat-ky-ai", "tok")) == "tok"


def test_basic_password_chua_dau_hai_cham_khong_bi_cat():
    assert token_from_header(_basic("u", "a:b:c")) == "a:b:c"


def test_basic_username_rong_van_lay_duoc_password():
    assert token_from_header(_basic("", "tok")) == "tok"


def test_header_rong_hoac_rac_tra_chuoi_rong():
    assert token_from_header("") == ""
    assert token_from_header("Basic") == ""
    assert token_from_header("Digest xyz") == ""
    assert token_from_header("Basic !!!khong-phai-base64!!!") == ""


def test_basic_khong_co_dau_hai_cham_tra_rong():
    raw = base64.b64encode(b"khongcodauhaicham").decode("ascii")
    assert token_from_header("Basic " + raw) == ""


def test_token_matches_dung_va_sai():
    assert token_matches("tok", "tok") is True
    assert token_matches("tok", "khac") is False


def test_token_matches_tu_choi_chuoi_rong():
    # Token chưa cấu hình KHÔNG được biến thành "ai cũng vào được".
    assert token_matches("", "") is False
    assert token_matches("", "bat-ky") is False
    assert token_matches("tok", "") is False


def test_is_local_client():
    assert is_local_client("127.0.0.1") is True
    assert is_local_client("::1") is True
    assert is_local_client("localhost") is True
    assert is_local_client("192.168.1.20") is False
    assert is_local_client("") is False
    assert is_local_client("127.0.0.1, 10.0.0.5") is False


def test_www_authenticate_la_basic_realm():
    assert WWW_AUTHENTICATE == {"WWW-Authenticate": 'Basic realm="novel2epub"'}
