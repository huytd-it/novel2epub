"""Route `/api/ui/sources/inspect` phải fetch DOM ĐÚNG cấu hình nâng cao mà
người dùng đang soạn trong modal nguồn (proxy, Cloudflare, DoH, headless,
impersonate). Nếu không, DOM xem trong "phòng thí nghiệm" khác DOM lúc crawl
thật — selector chọn xong vẫn hỏng, hoặc nguồn chỉ vào được qua proxy thì
không tải nổi DOM để chọn selector."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import write_db_config

HTML = "<html><body><a href='/c/1.html'>1</a></body></html>"


class _FakePage:
    def css(self, _selector):
        return []


@pytest.fixture()
def client(monkeypatch, tmp_path):
    db = write_db_config(tmp_path / "novel2epub.db")
    from app import deps

    monkeypatch.setattr(deps, "DB_PATH", db)
    monkeypatch.setattr(deps, "WORKSPACE_PATH", str(db))
    monkeypatch.setattr(deps, "SOURCES_PATH", str(db))
    from app.main import app

    return TestClient(app, follow_redirects=False)


@pytest.fixture()
def seen(monkeypatch):
    """Thay ScraplingCrawler bằng bản giả để bắt CrawlConfig route dựng ra."""
    import novel2epub.crawler as crawler_mod

    captured: dict = {}

    class FakeCrawler:
        def __init__(self, cfg):
            captured["cfg"] = cfg
            self._last_response_html = HTML

        def _fetch_page(self, url):
            captured["url"] = url
            return _FakePage()

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr(crawler_mod, "ScraplingCrawler", FakeCrawler)
    return captured


def test_advanced_config_di_vao_crawl_config(client, seen):
    res = client.post(
        "/api/ui/sources/inspect",
        json={
            "url": "https://example.com/toc",
            "scrapling_mode": "stealthy",
            "advanced": {
                "headless": False,
                "network_idle": False,
                "solve_cloudflare": True,
                "dns_over_https": True,
                "impersonate": "chrome120",
                "proxy": "socks5://user:pass@10.0.0.1:1080",
            },
        },
    )
    assert res.status_code == 200, res.text
    cfg = seen["cfg"]
    assert cfg.headless is False
    assert cfg.scrapling.mode == "stealthy"
    assert cfg.scrapling.network_idle is False
    assert cfg.scrapling.solve_cloudflare is True
    assert cfg.scrapling.dns_over_https is True
    assert cfg.scrapling.impersonate == "chrome120"
    assert cfg.scrapling.proxy == "socks5://user:pass@10.0.0.1:1080"
    assert seen["closed"] is True

    applied = res.json()["applied"]
    assert applied["mode"] == "stealthy"
    assert applied["solve_cloudflare"] is True
    # Proxy có thể chứa user:pass — chỉ trả cờ có/không, không trả chuỗi.
    assert applied["proxy"] is True
    assert "10.0.0.1" not in res.text


def test_khong_co_advanced_thi_giu_mac_dinh(client, seen):
    res = client.post(
        "/api/ui/sources/inspect",
        json={"url": "https://example.com/toc", "scrapling_mode": "fetcher"},
    )
    assert res.status_code == 200, res.text
    cfg = seen["cfg"]
    assert cfg.headless is True
    assert cfg.scrapling.mode == "fetcher"
    assert cfg.scrapling.network_idle is True
    assert cfg.scrapling.solve_cloudflare is False
    assert cfg.scrapling.dns_over_https is False
    assert cfg.scrapling.proxy == ""
    assert res.json()["applied"]["proxy"] is False


def test_mode_la_khong_hop_le_thi_ve_stealthy(client, seen):
    res = client.post(
        "/api/ui/sources/inspect",
        json={"url": "https://example.com/toc", "scrapling_mode": "khong-co-that"},
    )
    assert res.status_code == 200, res.text
    assert seen["cfg"].scrapling.mode == "stealthy"
    assert res.json()["applied"]["mode"] == "stealthy"


def test_thieu_url_thi_400(client, seen):
    res = client.post("/api/ui/sources/inspect", json={"url": "  "})
    assert res.status_code == 400
    assert "cfg" not in seen
