"""Dependency FastAPI cho các endpoint mở ra ngoài localhost (OPDS + API sửa).

Lớp keo mỏng giữa `novel2epub.api_auth` (thuần) và HTTP. Giữ mỏng có chủ đích:
mọi quyết định đều nằm bên module thuần để test được không cần dựng app.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from novel2epub import api_auth
from novel2epub.auth_core import Principal, Role
from novel2epub.oidc import OIDCError, OIDCValidator

from . import deps


@dataclass(frozen=True)
class AuthFailure:
    status: int
    detail: str
    headers: dict[str, str]


def check_api_auth(request: Request) -> AuthFailure | None:
    """Quyết định request có được phép không. `None` = cho qua.

    Trả về giá trị thay vì raise để middleware dùng lại được: HTTPException
    ném từ middleware KHÔNG đi qua exception handler của FastAPI, nó thoát ra
    thành lỗi 500 trần.

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
        return None

    token = deps.cfg().api.token
    if not token:
        return AuthFailure(
            status=503,
            detail=(
                "Chưa cấu hình token API — vào Cài đặt > API để bật truy cập "
                "từ máy khác."
            ),
            headers={},
        )

    provided = api_auth.token_from_header(request.headers.get("authorization", ""))
    if not api_auth.token_matches(token, provided):
        return AuthFailure(
            status=401,
            detail="Token không hợp lệ.",
            headers=dict(api_auth.WWW_AUTHENTICATE),
        )

    return None


def require_api_auth(request: Request) -> None:
    """Chặn request không có token hợp lệ. Miễn trừ khi gọi từ chính máy này."""
    failure = check_api_auth(request)
    if failure is not None:
        raise HTTPException(
            status_code=failure.status,
            detail=failure.detail,
            headers=failure.headers or None,
        )


_bearer = HTTPBearer(auto_error=False)


def get_oidc_validator(request: Request) -> OIDCValidator:
    validator = getattr(request.app.state, "oidc_validator", None)
    if validator is None or not callable(getattr(validator, "validate", None)):
        raise HTTPException(status_code=503, detail="OIDC authentication is not configured.")
    return validator


def require_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    validator: OIDCValidator = Depends(get_oidc_validator),
) -> Principal:
    """Xác thực Bearer JWT cho API v2; tuyệt đối không miễn localhost."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Bearer token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return validator.validate(credentials.credentials)
    except OIDCError as exc:
        raise HTTPException(
            status_code=401,
            detail=str(exc),
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from exc


def require_role(minimum: Role):
    """Factory dependency RBAC. Authentication lỗi 401; thiếu quyền trả 403."""
    def dependency(principal: Principal = Depends(require_principal)) -> Principal:
        if not principal.allows(minimum):
            raise HTTPException(status_code=403, detail="Insufficient role.")
        return principal

    return dependency


require_viewer = require_role(Role.VIEWER)
require_editor = require_role(Role.EDITOR)
require_admin = require_role(Role.ADMIN)
