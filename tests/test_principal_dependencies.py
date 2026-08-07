from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth import require_admin, require_editor, require_viewer
from novel2epub.auth_core import Principal, Role
from novel2epub.oidc import OIDCError


class FakeValidator:
    def validate(self, token):
        if token == "bad":
            raise OIDCError("Bearer token is invalid")
        roles = {"viewer": Role.VIEWER, "editor": Role.EDITOR, "admin": Role.ADMIN}
        role = roles.get(token)
        if role is None:
            raise OIDCError("Bearer token is invalid")
        return Principal("https://id.example", token, role)


def _client(configured=True):
    app = FastAPI()
    if configured:
        app.state.oidc_validator = FakeValidator()

    @app.get("/viewer")
    def viewer(principal=Depends(require_viewer)):
        return {"subject": principal.subject}

    @app.post("/editor")
    def editor(_=Depends(require_editor)):
        return {"ok": True}

    @app.delete("/admin")
    def admin(_=Depends(require_admin)):
        return {"ok": True}

    return TestClient(app)


def test_missing_bearer_returns_401_challenge():
    response = _client().get("/viewer")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_invalid_bearer_returns_401_without_echoing_token():
    response = _client().get("/viewer", headers={"Authorization": "Bearer bad"})
    assert response.status_code == 401
    assert "bad" not in response.text
    assert "invalid_token" in response.headers["www-authenticate"]


def test_unconfigured_oidc_returns_503():
    response = _client(configured=False).get(
        "/viewer", headers={"Authorization": "Bearer viewer"}
    )
    assert response.status_code == 503


def test_viewer_can_read_but_cannot_edit():
    client = _client()
    headers = {"Authorization": "Bearer viewer"}
    assert client.get("/viewer", headers=headers).status_code == 200
    assert client.post("/editor", headers=headers).status_code == 403
    assert client.delete("/admin", headers=headers).status_code == 403


def test_editor_can_read_and_edit_but_cannot_administer():
    client = _client()
    headers = {"Authorization": "Bearer editor"}
    assert client.get("/viewer", headers=headers).status_code == 200
    assert client.post("/editor", headers=headers).status_code == 200
    assert client.delete("/admin", headers=headers).status_code == 403


def test_admin_has_all_roles_and_localhost_is_not_bypassed():
    client = _client()
    headers = {"Authorization": "Bearer admin"}
    assert client.get("/viewer", headers=headers).status_code == 200
    assert client.post("/editor", headers=headers).status_code == 200
    assert client.delete("/admin", headers=headers).status_code == 200
    assert client.get("/viewer").status_code == 401
