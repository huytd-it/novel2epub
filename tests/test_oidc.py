import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from novel2epub.auth_core import Role
from novel2epub.oidc import OIDCConfig, OIDCError, OIDCValidator, config_from_mapping


ISSUER = "https://id.example"
DISCOVERY = ISSUER + "/.well-known/openid-configuration"
JWKS = ISSUER + "/jwks"


def _key(kid="key-1"):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    public_jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return private, public_jwk


def _config(**overrides):
    values = dict(
        discovery_url=DISCOVERY,
        issuer=ISSUER,
        audience="novel2epub-api",
        role_claim="groups",
        role_map={"readers": "viewer", "editors": "editor", "admins": "admin"},
        cache_ttl_seconds=60,
        clock_skew_seconds=0,
    )
    values.update(overrides)
    return OIDCConfig(**values)


def _token(private, **overrides):
    now = int(time.time())
    claims = dict(
        iss=ISSUER,
        sub="user-1",
        aud="novel2epub-api",
        iat=now,
        exp=now + 300,
        groups=["editors"],
    )
    claims.update(overrides)
    return jwt.encode(claims, private, algorithm="RS256", headers={"kid": "key-1"})


def test_discovery_and_jwks_are_cached():
    private, jwk = _key()
    calls = []

    def fetch(url):
        calls.append(url)
        return {"issuer": ISSUER, "jwks_uri": JWKS} if url == DISCOVERY else {"keys": [jwk]}

    validator = OIDCValidator(_config(), fetch_json=fetch)
    assert validator.validate(_token(private)).role is Role.EDITOR
    assert validator.validate(_token(private)).subject == "user-1"
    assert calls == [DISCOVERY, JWKS]


def test_unknown_kid_forces_one_jwks_refresh():
    private, jwk = _key()
    calls = []

    def fetch(url):
        calls.append(url)
        return {"issuer": ISSUER, "jwks_uri": JWKS} if url == DISCOVERY else {"keys": [jwk]}

    validator = OIDCValidator(_config(), fetch_json=fetch)
    bad = jwt.encode(
        {"iss": ISSUER, "sub": "x", "aud": "novel2epub-api", "iat": int(time.time()), "exp": int(time.time()) + 60, "groups": ["readers"]},
        private,
        algorithm="RS256",
        headers={"kid": "missing"},
    )
    with pytest.raises(OIDCError, match="not found"):
        validator.validate(bad)
    assert calls.count(JWKS) == 2


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://wrong.example"},
        {"aud": "wrong-api"},
        {"exp": 1},
        {"sub": ""},
        {"groups": ["unmapped"]},
    ],
)
def test_invalid_claims_fail_closed(overrides):
    private, jwk = _key()
    validator = OIDCValidator(
        _config(),
        fetch_json=lambda url: {"issuer": ISSUER, "jwks_uri": JWKS} if url == DISCOVERY else {"keys": [jwk]},
    )
    with pytest.raises(OIDCError, match="invalid"):
        validator.validate(_token(private, **overrides))


def test_discovery_issuer_mismatch_is_rejected():
    validator = OIDCValidator(
        _config(), fetch_json=lambda _: {"issuer": "https://wrong.example", "jwks_uri": JWKS}
    )
    with pytest.raises(OIDCError, match="issuer mismatch"):
        validator.discovery()


def test_insecure_or_symmetric_configuration_is_rejected():
    with pytest.raises(OIDCError, match="HTTPS"):
        _config(discovery_url="http://id.example/discovery")
    with pytest.raises(OIDCError, match="asymmetric"):
        _config(algorithms=("HS256",))


def test_config_mapping_empty_is_disabled_and_complete_mapping_parses():
    assert config_from_mapping({}) is None
    parsed = config_from_mapping(
        {
            "discovery_url": DISCOVERY,
            "issuer": ISSUER,
            "audience": "novel2epub-api",
            "role_claim": "realm.roles",
            "role_map": {"reader": "viewer"},
        }
    )
    assert parsed is not None
    assert parsed.role_claim == "realm.roles"
    assert parsed.role_map == {"reader": "viewer"}
