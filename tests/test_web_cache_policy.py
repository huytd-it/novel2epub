from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_html_is_not_cached():
    root = Path(__file__).parents[1]
    main = (root / "app" / "main.py").read_text(encoding="utf-8")
    base = (root / "app" / "templates" / "base.html").read_text(encoding="utf-8")

    assert 'response.headers["Cache-Control"] = "no-store"' in main
    assert "/static/app.js?v={{ static_version('app.js') }}" in base
    assert "/static/tailwind.js?v={{ static_version('tailwind.js') }}" in base
    assert "20260731-3" not in base


def test_static_assets_are_revalidated():
    response = client.get("/static/app.js")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
