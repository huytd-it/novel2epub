"""Principal và RBAC dùng chung cho API v2, BFF và legacy guards."""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Mapping


class Role(IntEnum):
    VIEWER = 10
    EDITOR = 20
    ADMIN = 30


_ROLE_NAMES = {
    "viewer": Role.VIEWER,
    "editor": Role.EDITOR,
    "admin": Role.ADMIN,
}


class AuthorizationError(ValueError):
    """Identity không có role hợp lệ hoặc không đủ quyền."""


@dataclass(frozen=True)
class Principal:
    issuer: str
    subject: str
    role: Role
    display_name: str = ""
    email: str = ""
    auth_method: str = "oidc"

    @property
    def identity(self) -> tuple[str, str]:
        return self.issuer, self.subject

    def allows(self, minimum: Role) -> bool:
        return self.role >= minimum


def role_from_claim(claims: Mapping[str, Any], claim_name: str, role_map: Mapping[str, str]) -> Role:
    """Map claim cấu hình được sang role; thiếu/không map luôn fail closed."""
    raw: Any = claims
    for part in claim_name.split("."):
        if not isinstance(raw, Mapping) or part not in raw:
            raw = None
            break
        raw = raw[part]
    values = raw if isinstance(raw, list) else [raw]
    mapped: list[Role] = []
    for value in values:
        if not isinstance(value, str):
            continue
        role_name = role_map.get(value)
        role = _ROLE_NAMES.get(role_name or "")
        if role is not None:
            mapped.append(role)
    if not mapped:
        raise AuthorizationError("identity has no mapped role")
    return max(mapped)


def principal_from_claims(
    claims: Mapping[str, Any], *, claim_name: str, role_map: Mapping[str, str]
) -> Principal:
    issuer = claims.get("iss")
    subject = claims.get("sub")
    if not isinstance(issuer, str) or not issuer or not isinstance(subject, str) or not subject:
        raise AuthorizationError("identity requires issuer and subject")
    return Principal(
        issuer=issuer,
        subject=subject,
        role=role_from_claim(claims, claim_name, role_map),
        display_name=str(claims.get("name") or ""),
        email=str(claims.get("email") or ""),
    )


def require_role(principal: Principal, minimum: Role) -> Principal:
    if not principal.allows(minimum):
        raise AuthorizationError("insufficient role")
    return principal
