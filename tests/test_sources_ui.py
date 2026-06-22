"""Tests cho /sources page UI/UX (change: improve-sources-ui)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from novel2epub.config import Config, CrawlConfig, LibraryConfig, LibraryEntry, NovelConfig, OutputConfig, TranslateConfig
from novel2epub.sources import SourcePreset


def _cfg(tmp_path, engine="http"):
    return Config(
        novel=NovelConfig(slug="demo"),
        crawl=CrawlConfig(
            toc_url="http://x/book/demo/",
            engine=engine,
            content_selector="#content",
            chapter_link_pattern="/book/demo/\\d+\\.html",
            delay_seconds=1.0,
        ),
        translate=TranslateConfig(type="none", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


def _fake_job():
    class Job:
        def status(self):
            return {"running": False, "step": "", "error": "", "log": []}

    return Job()


def test_sources_table_shows_usage_and_data_table(tmp_path, monkeypatch):
    from app import deps
    from app.main import app

    presets = {"sto9": SourcePreset(name="sto9", engine="http", content_selector="#content",
                                     chapter_link_pattern="/book/demo/\\d+\\.html", delay_seconds=1.0)}
    monkeypatch.setattr(deps, "presets", lambda: presets)
    monkeypatch.setattr(deps, "library", lambda: LibraryConfig(
        ebooks={"demo": LibraryEntry(slug="demo", name="Demo", config="configs/demo.yaml")}))
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: _cfg(tmp_path))
    app.state.job = _fake_job()
    client = TestClient(app)

    res = client.get("/sources")
    assert res.status_code == 200
    html = res.text
    assert 'class="data-table"' in html
    assert 'class="table-wrap"' in html
    # engine badge (http -> ok)
    assert 'badge ok' in html
    # usage shows the matching slug link
    assert '<a href="/ebooks/demo">demo</a>' in html
    # row actions replaced inline text links
    assert 'class="row-actions"' in html
    assert 'class="button" href="/sources?edit=sto9"' in html


def test_sources_empty_state_renders_muted_message_no_table(monkeypatch):
    from app import deps
    from app.main import app

    monkeypatch.setattr(deps, "presets", lambda: {})
    monkeypatch.setattr(deps, "library", lambda: LibraryConfig())
    app.state.job = _fake_job()
    client = TestClient(app)

    res = client.get("/sources")
    assert res.status_code == 200
    html = res.text
    # No preset table in empty state
    assert "data-table" not in html
    assert "muted" in html
    # Action-oriented hint mentions adding preset
    assert "thêm preset" in html or "Thêm" in html


def test_sources_crawl4ai_fieldset_hidden_by_default_visible_in_edit(monkeypatch):
    from app import deps
    from app.main import app

    presets_http = {"sto9": SourcePreset(name="sto9", engine="http")}
    monkeypatch.setattr(deps, "presets", lambda: presets_http)
    monkeypatch.setattr(deps, "library", lambda: LibraryConfig())
    app.state.job = _fake_job()
    client = TestClient(app)

    # Add mode: engine defaults to http -> crawl4ai fieldset hidden
    res = client.get("/sources")
    assert res.status_code == 200
    assert 'id="crawl4ai-options"' in res.text
    assert 'style="display:none"' in res.text
    # Engine select no longer contains firecrawl
    assert '>firecrawl<' not in res.text

    # Edit a crawl4ai preset -> crawl4ai fieldset visible (no display:none on the fieldset)
    presets_c4 = {"c4": SourcePreset(name="c4", engine="crawl4ai", js_code="window.scrollTo(...)")}
    monkeypatch.setattr(deps, "presets", lambda: presets_c4)
    res = client.get("/sources?edit=c4")
    assert res.status_code == 200
    # fieldset exists and is NOT hidden (no display:none inside its opening tag)
    assert 'id="crawl4ai-options"' in res.text
    assert 'crawl4ai-options" style="display:none"' not in res.text
    assert 'crawl4ai-options"' in res.text or 'crawl4ai-options ' in res.text
    assert '>firecrawl<' not in res.text