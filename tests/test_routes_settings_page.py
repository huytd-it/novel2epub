"""Regression: trang settings render được cho ebook có source preset
(trước đây 500 vì import `config_writer._load` đã bị xóa khi chuyển sang SQLite)."""
from fastapi.testclient import TestClient

from app import deps
import app.routes.settings as settings_route
from novel2epub.config import load_config
from tests.conftest import write_db_config


def _fake_job():
    class Job:
        def status(self):
            return {
                "crawl": {"running": False, "step": "", "error": "", "log": []},
                "translate": {"running": False, "step": "", "error": "", "log": [], "running_ebooks": []},
                "build": {"running": False, "step": "", "error": "", "log": []},
            }
    return Job()


def test_settings_page_renders_with_source_preset(monkeypatch, tmp_path):
    db = write_db_config(
        tmp_path / "novel2epub.db",
        defaults={"translate": {"type": "none"}},
        sources={"shuhaige": {"content_selector": "#content", "delay_seconds": 1.0}},
        ebooks={
            "chua-biet-ten-2": {
                "source": "shuhaige",
                "novel": {"slug": "chua-biet-ten-2", "title": "Chưa Biết Tên"},
                "crawl": {
                    "toc_url": "https://www.shuhaige.net/372421/",
                    "content_selector": ".override",  # 1 field bị override
                },
            },
        },
    )
    db = str(db)
    monkeypatch.setattr(deps, "WORKSPACE_PATH", db)
    monkeypatch.setattr(deps, "SOURCES_PATH", db)
    monkeypatch.setattr(settings_route, "load_presets", lambda path: __import__(
        "novel2epub.sources", fromlist=["load_presets"]).load_presets(db))
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: load_config(db, slug))

    from app.main import app
    app.state.job = _fake_job()
    client = TestClient(app)

    res = client.get("/ebooks/chua-biet-ten-2/settings")
    assert res.status_code == 200
    assert "Chưa Biết Tên" in res.text
