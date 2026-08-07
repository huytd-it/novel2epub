import pytest

from novel2epub.auth_core import (
    AuthorizationError,
    Role,
    principal_from_claims,
    require_role,
    role_from_claim,
)


def test_role_claim_maps_single_and_list_to_highest_role():
    role_map = {"readers": "viewer", "writers": "editor", "owners": "admin"}
    assert role_from_claim({"groups": "readers"}, "groups", role_map) is Role.VIEWER
    assert role_from_claim({"groups": ["readers", "writers"]}, "groups", role_map) is Role.EDITOR
    assert role_from_claim({"realm": {"groups": ["owners"]}}, "realm.groups", role_map) is Role.ADMIN


@pytest.mark.parametrize("claims", [{}, {"groups": "unknown"}, {"groups": 123}, {"groups": []}])
def test_role_claim_fails_closed(claims):
    with pytest.raises(AuthorizationError, match="no mapped role"):
        role_from_claim(claims, "groups", {"readers": "viewer"})


def test_principal_identity_is_issuer_and_subject():
    principal = principal_from_claims(
        {"iss": "https://id.example", "sub": "user-1", "roles": "editors", "name": "Editor"},
        claim_name="roles",
        role_map={"editors": "editor"},
    )
    assert principal.identity == ("https://id.example", "user-1")
    assert principal.role is Role.EDITOR
    assert require_role(principal, Role.VIEWER) is principal
    with pytest.raises(AuthorizationError, match="insufficient"):
        require_role(principal, Role.ADMIN)


@pytest.mark.parametrize("claims", [{"sub": "x", "role": "admin"}, {"iss": "x", "role": "admin"}])
def test_principal_requires_issuer_and_subject(claims):
    with pytest.raises(AuthorizationError, match="issuer and subject"):
        principal_from_claims(claims, claim_name="role", role_map={"admin": "admin"})
