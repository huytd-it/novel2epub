"""Clone/delete-block/export/import/dry-run test cho site preset (xem spec
source-management)."""
from __future__ import annotations

import io

from fastapi.testclient import TestClient

from novel2epub.config import LibraryConfig, LibraryEntry
from novel2epub.sources import SourcePreset


def _preset(name="sto9"):
    return SourcePreset(name=name, engine="http", content_selector="#content",
                         chapter_link_pattern=r"/book/demo/\d+\.html", delay_seconds=1.0)


class _FakeJob:
    def status(self):
        return {"crawl": {"running": False, "step": "", "error": "", "log": []},
                "translate": {"running": False, "step": "", "error": "", "log": []}}

    def start_custom(self, step, target_fn, category):
        target_fn(lambda m: None)
        return True


def _client(monkeypatch, tmp_path, presets=None, library=None):
    from app import deps
    from app.main import app

    presets = presets if presets is not None else {"sto9": _preset()}
    monkeypatch.setattr(deps, "presets", lambda: presets)
    monkeypatch.setattr(deps, "library", lambda: library or LibraryConfig())
    monkeypatch.setattr(deps, "SOURCES_PATH", str(tmp_path / "novel2epub.yaml"))

    from app.routes import sources as sources_mod

    monkeypatch.setattr(sources_mod, "VALIDATION_PATH", tmp_path / "source_validation.json")
    app.state.job = _FakeJob()
    return app, TestClient(app)


def test_clone_preset_creates_copy_with_new_name(monkeypatch, tmp_path):
    app, client = _client(monkeypatch, tmp_path)
    res = client.post("/sources/sto9/clone", data={"new_name": "sto9-clone"}, follow_redirects=False)
    assert res.status_code == 303

    from novel2epub.sources import load_presets

    presets = load_presets(tmp_path / "novel2epub.yaml")
    assert "sto9-clone" in presets
    assert presets["sto9-clone"].content_selector == "#content"


def test_clone_preset_auto_renames_on_collision(monkeypatch, tmp_path):
    presets = {"sto9": _preset(), "sto9-copy": _preset("sto9-copy")}
    app, client = _client(monkeypatch, tmp_path, presets=presets)
    res = client.post("/sources/sto9/clone", data={}, follow_redirects=False)
    assert res.status_code == 303

    from novel2epub.sources import load_presets

    saved = load_presets(tmp_path / "novel2epub.yaml")
    assert "sto9-copy-2" in saved


def test_delete_blocked_when_preset_in_use(monkeypatch, tmp_path):
    library = LibraryConfig(ebooks={"demo": LibraryEntry(slug="demo", name="Demo")})
    app, client = _client(monkeypatch, tmp_path, library=library)

    from app import deps
    from novel2epub.config import CrawlConfig, Config, NovelConfig, OutputConfig, TranslateConfig

    crawl = CrawlConfig(toc_url="http://x/", **_preset().crawl_overrides())
    cfg = Config(novel=NovelConfig(slug="demo"), crawl=crawl, translate=TranslateConfig(), output=OutputConfig())
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)

    res = client.post("/sources/sto9/delete")
    assert res.status_code == 409
    assert "demo" in res.json()["detail"]


def test_export_presets_returns_yaml(monkeypatch, tmp_path):
    app, client = _client(monkeypatch, tmp_path)
    res = client.get("/sources/export")
    assert res.status_code == 200
    assert "sources" in res.text
    assert "sto9" in res.text


def test_import_presets_merge_by_name_rename_on_collision(monkeypatch, tmp_path):
    app, client = _client(monkeypatch, tmp_path)
    yaml_content = b"sources:\n  sto9:\n    engine: http\n    content_selector: '#new'\n"
    res = client.post(
        "/sources/import",
        files={"file": ("import.yaml", io.BytesIO(yaml_content), "application/x-yaml")},
        data={"on_collision": "rename"},
        follow_redirects=False,
    )
    assert res.status_code == 303

    from novel2epub.sources import load_presets

    saved = load_presets(tmp_path / "novel2epub.yaml")
    assert "sto9" in saved  # bản gốc giữ nguyên
    assert "sto9-2" in saved
    assert saved["sto9-2"].content_selector == "#new"


def test_import_presets_overwrite_on_collision(monkeypatch, tmp_path):
    app, client = _client(monkeypatch, tmp_path)
    yaml_content = b"sources:\n  sto9:\n    engine: http\n    content_selector: '#new'\n"
    res = client.post(
        "/sources/import",
        files={"file": ("import.yaml", io.BytesIO(yaml_content), "application/x-yaml")},
        data={"on_collision": "overwrite"},
        follow_redirects=False,
    )
    assert res.status_code == 303

    from novel2epub.sources import load_presets

    saved = load_presets(tmp_path / "novel2epub.yaml")
    assert saved["sto9"].content_selector == "#new"


def test_dry_run_test_records_validation_outcome(monkeypatch, tmp_path):
    app, client = _client(monkeypatch, tmp_path)

    from novel2epub.crawler import TocResult
    from novel2epub.storage import Chapter

    class _FakeCrawler:
        def fetch_toc(self):
            return TocResult(title="Tên Truyện", chapters=[Chapter(index=1, url="http://x/1")])

        def fetch_chapter(self, ch):
            return "nội dung mẫu"

        def close(self):
            pass

    from app.routes import sources as sources_mod

    monkeypatch.setattr(sources_mod, "make_crawler", lambda cfg: _FakeCrawler())

    res = client.post("/sources/sto9/test", data={"toc_url": "http://x/toc"}, follow_redirects=False)
    assert res.status_code == 303

    import json

    data = json.loads((tmp_path / "source_validation.json").read_text(encoding="utf-8"))
    assert data["sto9"]["ok"] is True
    assert "Tên Truyện" in data["sto9"]["message"]


def test_dry_run_test_records_failure_reason(monkeypatch, tmp_path):
    app, client = _client(monkeypatch, tmp_path)

    from app.routes import sources as sources_mod

    def _boom(cfg):
        raise RuntimeError("không kết nối được")

    monkeypatch.setattr(sources_mod, "make_crawler", _boom)

    res = client.post("/sources/sto9/test", data={"toc_url": "http://x/toc"}, follow_redirects=False)
    assert res.status_code == 303

    import json

    data = json.loads((tmp_path / "source_validation.json").read_text(encoding="utf-8"))
    assert data["sto9"]["ok"] is False
    assert "không kết nối được" in data["sto9"]["message"]
