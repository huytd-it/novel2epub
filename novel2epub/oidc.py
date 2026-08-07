"""OIDC discovery, JWKS cache và Bearer JWT validation provider-agnostic."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen

import jwt
from jwt import InvalidTokenError, PyJWK

from .auth_core import Principal, principal_from_claims


class OIDCError(ValueError):
    """Token hoặc metadata OIDC không hợp lệ; thông báo không chứa token."""


@dataclass(frozen=True)
class OIDCConfig:
    discovery_url: str
    issuer: str
    audience: str
    role_claim: str
    role_map: Mapping[str, str]
    algorithms: tuple[str, ...] = ("RS256",)
    cache_ttl_seconds: int = 300
    clock_skew_seconds: int = 30

    def __post_init__(self) -> None:
        if not all((self.discovery_url, self.issuer, self.audience, self.role_claim)):
            raise OIDCError("OIDC discovery URL, issuer, audience and role claim are required")
        if not self.discovery_url.startswith("https://"):
            raise OIDCError("OIDC discovery URL must use HTTPS")
        if not self.role_map:
            raise OIDCError("OIDC role map must not be empty")
        if not self.algorithms or any(a.startswith("HS") or a == "none" for a in self.algorithms):
            raise OIDCError("OIDC algorithms must use asymmetric signatures")


@dataclass
class _CacheEntry:
    value: Mapping[str, Any]
    expires_at: float


FetchJSON = Callable[[str], Mapping[str, Any]]


def _fetch_json(url: str) -> Mapping[str, Any]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "novel2epub"})
    with urlopen(request, timeout=10) as response:  # noqa: S310 - URL is explicit admin config
        if response.status != 200:
            raise OIDCError("OIDC endpoint returned an unexpected status")
        data = json.loads(response.read())
    if not isinstance(data, dict):
        raise OIDCError("OIDC endpoint did not return an object")
    return data


def config_from_mapping(data: Mapping[str, Any]) -> OIDCConfig | None:
    """Parse settings.oidc_json; object rỗng nghĩa là OIDC chưa cấu hình."""
    if not data:
        return None
    role_map = data.get("role_map")
    algorithms = data.get("algorithms", ["RS256"])
    if not isinstance(role_map, dict) or not isinstance(algorithms, list):
        raise OIDCError("OIDC role map and algorithms have invalid types")
    return OIDCConfig(
        discovery_url=str(data.get("discovery_url") or ""),
        issuer=str(data.get("issuer") or ""),
        audience=str(data.get("audience") or ""),
        role_claim=str(data.get("role_claim") or ""),
        role_map={str(key): str(value) for key, value in role_map.items()},
        algorithms=tuple(str(value) for value in algorithms),
        cache_ttl_seconds=int(data.get("cache_ttl_seconds", 300)),
        clock_skew_seconds=int(data.get("clock_skew_seconds", 30)),
    )


@dataclass
class OIDCValidator:
    config: OIDCConfig
    fetch_json: FetchJSON = _fetch_json
    now: Callable[[], float] = time.time
    _discovery: _CacheEntry | None = field(default=None, init=False)
    _jwks: _CacheEntry | None = field(default=None, init=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)

    def _cached(self, name: str, loader: Callable[[], Mapping[str, Any]], *, force: bool = False) -> Mapping[str, Any]:
        with self._lock:
            entry: _CacheEntry | None = getattr(self, name)
            current = self.now()
            if not force and entry is not None and entry.expires_at > current:
                return entry.value
            value = loader()
            setattr(self, name, _CacheEntry(value, current + max(1, self.config.cache_ttl_seconds)))
            return value

    def discovery(self) -> Mapping[str, Any]:
        def load() -> Mapping[str, Any]:
            data = self.fetch_json(self.config.discovery_url)
            if data.get("issuer") != self.config.issuer:
                raise OIDCError("OIDC discovery issuer mismatch")
            jwks_uri = data.get("jwks_uri")
            if not isinstance(jwks_uri, str) or not jwks_uri.startswith("https://"):
                raise OIDCError("OIDC discovery has no secure JWKS URI")
            return data

        return self._cached("_discovery", load)

    def jwks(self, *, force: bool = False) -> Mapping[str, Any]:
        def load() -> Mapping[str, Any]:
            data = self.fetch_json(str(self.discovery()["jwks_uri"]))
            if not isinstance(data.get("keys"), list):
                raise OIDCError("OIDC JWKS has no keys")
            return data

        return self._cached("_jwks", load, force=force)

    def _signing_key(self, kid: str, algorithm: str) -> Any:
        if algorithm not in self.config.algorithms:
            raise OIDCError("JWT signing algorithm is not allowed")
        for force in (False, True):
            for key in self.jwks(force=force).get("keys", []):
                if isinstance(key, dict) and key.get("kid") == kid and key.get("use", "sig") == "sig":
                    try:
                        jwk = PyJWK.from_dict(key, algorithm=algorithm)
                    except (InvalidTokenError, ValueError) as exc:
                        raise OIDCError("JWT signing key is invalid") from exc
                    return jwk.key
        raise OIDCError("JWT signing key was not found")

    def validate(self, token: str) -> Principal:
        if not token:
            raise OIDCError("Bearer token is required")
        try:
            header = jwt.get_unverified_header(token)
        except InvalidTokenError as exc:
            raise OIDCError("Bearer token is malformed") from exc
        kid = header.get("kid")
        algorithm = header.get("alg")
        if not isinstance(kid, str) or not kid or not isinstance(algorithm, str):
            raise OIDCError("Bearer token has no signing key metadata")
        key = self._signing_key(kid, algorithm)
        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=list(self.config.algorithms),
                audience=self.config.audience,
                issuer=self.config.issuer,
                leeway=self.config.clock_skew_seconds,
                options={"require": ["exp", "iat", "iss", "sub", "aud"]},
            )
            return principal_from_claims(
                claims,
                claim_name=self.config.role_claim,
                role_map=self.config.role_map,
            )
        except (InvalidTokenError, ValueError) as exc:
            raise OIDCError("Bearer token is invalid") from exc
