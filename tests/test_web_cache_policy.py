from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_html_is_not_cached():
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "/static/app.js?v=" in response.text
    assert "/static/tailwind.js?v=" in response.text
    assert "20260731-3" not in response.text


def test_static_assets_are_revalidated():
    response = client.get("/static/app.js")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
