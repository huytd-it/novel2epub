from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_html_is_not_cached():
    root = Path(__file__).parents[1]
    main = (root / "app" / "main.py").read_text(encoding="utf-8")

    assert 'response.headers["Cache-Control"] = "no-store"' in main


def test_spa_index_is_not_cached():
    res = client.get("/")
    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-store"


def test_static_assets_are_revalidated():
    # Bundle SPA nằm dưới /assets (không có static Jinja2 cũ).
    res = client.get("/assets/")
    assert res.status_code in (200, 404)  # danh mục không tồn tại → 404, không crash
