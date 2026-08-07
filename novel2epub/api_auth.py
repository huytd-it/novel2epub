"""Xác thực token cho OPDS và API ngoài (tích hợp readest).

Logic THUẦN — không import FastAPI, không đọc config, không I/O. Lớp keo với
HTTP nằm ở `app/auth.py`.

Hỗ trợ hai cách gửi token vì hai bên gọi khác nhau:

- **Basic** — readest gửi username/password cho catalog OPDS. Username bị bỏ
  qua hoàn toàn, chỉ password được so với token.
- **Bearer** — dùng cho API sửa đoạn và cho việc thử tay bằng curl.

readest gửi Basic PREEMPTIVE (ngay từ request đầu, không đợi thử thách) và chỉ
đàm phán lại khi nhận 401/403 — nên `WWW_AUTHENTICATE` phải đi kèm mọi
response 401, và lỗi xác thực KHÔNG được trả 400 hay 403.
"""
from __future__ import annotations

import base64
import binascii
import hmac

# Địa chỉ được miễn token. So sánh với `request.client.host` (địa chỉ socket
# thật) — TUYỆT ĐỐI không so với X-Forwarded-For: client tự đặt được header đó,
# tin nó thì miễn trừ localhost thành cửa mở toang cho cả LAN.
_LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

WWW_AUTHENTICATE = {"WWW-Authenticate": 'Basic realm="novel2epub"'}


def token_from_header(header: str) -> str:
    """Token nằm trong giá trị header `Authorization`, hoặc "" nếu không đọc được."""
    if not header:
        return ""
    scheme, _, rest = header.partition(" ")
    rest = rest.strip()
    if not rest:
        return ""
    scheme = scheme.strip().lower()
    if scheme == "bearer":
        return rest
    if scheme == "basic":
        try:
            decoded = base64.b64decode(rest, validate=True).decode("utf-8")
        except (binascii.Error, ValueError, UnicodeDecodeError):
            return ""
        # `partition` chứ không phải `split`: password chứa dấu ":" là hợp lệ.
        _user, sep, password = decoded.partition(":")
        return password if sep else ""
    return ""


def token_matches(expected: str, provided: str) -> bool:
    """So khớp hằng thời gian. Chuỗi rỗng LUÔN không khớp — token chưa cấu
    hình không được biến thành "ai cũng vào được"."""
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected, provided)


def is_local_client(host: str) -> bool:
    """`host` là máy đang chạy chính novel2epub?"""
    return host in _LOCAL_HOSTS
