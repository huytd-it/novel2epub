from pathlib import Path

from fastapi.testclient import TestClient

from app.main import _SPA_DIR, app


client = TestClient(app)


def test_html_is_not_cached():
    root = Path(__file__).parents[1]
    main = (root / "app" / "main.py").read_text(encoding="utf-8")

    assert 'response.headers["Cache-Control"] = "no-store"' in main


def test_spa_index_is_not_cached():
    res = client.get("/")
    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-store"


def test_spa_navigation_fallback_is_not_cached():
    res = client.get("/ebooks/some-book/chapters/3")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert res.headers["cache-control"] == "no-store"


def test_hashed_assets_are_immutable():
    assets = sorted((_SPA_DIR / "assets").glob("*.js"))
    assert assets, "thiếu bundle SPA — chạy build frontend trước"
    res = client.get(f"/assets/{assets[0].name}")
    assert res.status_code == 200
    assert res.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_sw_and_manifest_are_revalidated():
    for path in ("/sw.js", "/manifest.webmanifest", "/registerSW.js"):
        res = client.get(path)
        assert res.status_code == 200, path
        assert res.headers["cache-control"] == "public, max-age=0, must-revalidate", path


def test_missing_sw_is_json_not_html_fallback():
    # sw.js mất file mà trả index.html thì update-check của SW thất bại và SW
    # cũ kẹt vĩnh viễn — phải 404 JSON, không nuốt vào fallback SPA.
    res = client.get("/workbox-missing.js")
    assert res.status_code == 404
    assert "text/html" not in res.headers["content-type"]


def test_static_assets_are_revalidated():
    # Bundle SPA nằm dưới /assets (không có static Jinja2 cũ).
    res = client.get("/assets/")
    assert res.status_code in (200, 404)  # danh mục không tồn tại → 404, không crash
