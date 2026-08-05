"""Dependency FastAPI cho các endpoint mở ra ngoài localhost (OPDS + API sửa).

Lớp keo mỏng giữa `novel2epub.api_auth` (thuần) và HTTP. Giữ mỏng có chủ đích:
mọi quyết định đều nằm bên module thuần để test được không cần dựng app.
"""
from __future__ import annotations

from fastapi import HTTPException, Request

from novel2epub import api_auth

from . import deps


def require_api_auth(request: Request) -> None:
    """Chặn request không có token hợp lệ. Miễn trừ khi gọi từ chính máy này.

    Ba nhánh, mã lỗi cố ý khác nhau:

    - localhost -> cho qua, không cần token (web UI + readest desktop cùng máy).
    - chưa cấu hình token -> 503: lỗi cấu hình server, KHÔNG kèm
      `WWW-Authenticate` vì không có gì để đàm phán.
    - thiếu/sai token -> 401 KÈM `WWW-Authenticate`. readest gửi Basic
      preemptive và chỉ đàm phán lại trên 401/403; trả 400 hay 403 sẽ đẩy nó
      vào nhánh phục hồi sai và người dùng chỉ thấy "Failed to load OPDS feed".
    """
    host = request.client.host if request.client else ""
    if api_auth.is_local_client(host):
        return

    token = deps.cfg().api.token
    if not token:
        raise HTTPException(
            status_code=503,
            detail=(
                "Chưa cấu hình token API — vào Cài đặt > API để bật truy cập "
                "từ máy khác."
            ),
        )

    provided = api_auth.token_from_header(request.headers.get("authorization", ""))
    if not api_auth.token_matches(token, provided):
        raise HTTPException(
            status_code=401,
            detail="Token không hợp lệ.",
            headers=api_auth.WWW_AUTHENTICATE,
        )
