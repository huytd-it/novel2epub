"""Tests cho novel2epub/preset_builder.py"""
from __future__ import annotations

from bs4 import BeautifulSoup

from novel2epub.preset_builder import (
    PresetBuilderResult,
    build_preset,
    preview_toc,
    refine_pattern_with_ai,
    save_preset,
    select_engine_heuristic,
    validate_pattern,
)
from novel2epub.sources import SourcePreset


def _static_soup() -> BeautifulSoup:
    html = """
    <html><body>
      <div id="list">
        <a href="/book/1/1.html">Chương 1</a>
        <a href="/book/1/2.html">Chương 2</a>
        <a href="/book/1/3.html">Chương 3</a>
        <a href="/book/1/4.html">Chương 4</a>
        <a href="/book/1/5.html">Chương 5</a>
        <a href="/book/1/6.html">Chương 6</a>
      </div>
      <footer><a href="/about">About</a><a href="/contact">Contact</a></footer>
    </body></html>
    """
    return BeautifulSoup(html, "html.parser")


def test_engine_heuristic_picks_http_for_static_site():
    soup = _static_soup()
    assert select_engine_heuristic(soup) == "http"


def test_engine_heuristic_picks_crawl4ai_for_empty_body():
    soup = BeautifulSoup("<html><body></body></html>", "html.parser")
    assert select_engine_heuristic(soup) == "crawl4ai"


def test_validate_pattern_too_broad():
    # Build soup with 7321 matching links inside #list.
    anchors = "\n".join(f'<a href="/book/1/{i}.html">C{i}</a>' for i in range(7321))
    html = f"<html><body><div id='list'>{anchors}</div></body></html>"
    soup = BeautifulSoup(html, "html.parser")
    result = validate_pattern(".*", soup, "#list")
    assert result["status"] == "too_broad"
    assert result["count"] == 7321


def test_validate_pattern_too_narrow():
    soup = _static_soup()
    result = validate_pattern(r"/book/1/1\.html", soup, "#list")
    assert result["status"] == "too_narrow"
    assert result["count"] == 1


def test_refine_pattern_loop_terminates_within_budget():
    expected = r"/book/1/\d+\.html"

    def ai_call(_prompt: str) -> str:
        return '{"chapter_link_pattern": "' + expected.replace("\\", "\\\\") + '"}'

    initial_validation = {"status": "too_broad", "count": 10000, "sample": []}
    pattern, _, rounds = refine_pattern_with_ai(
        ".*", initial_validation, ai_call, "http://site.com/book/1/", max_rounds=3
    )
    assert rounds == 1
    assert pattern == expected


def test_build_preset_returns_clear_error_when_no_ai_cli(monkeypatch):
    import novel2epub.preset_builder as pb

    monkeypatch.setattr(pb, "_get_openai_config", lambda config_path=None: None)

    result = build_preset("http://site.com/book/1/", timeout_seconds=10)
    assert result.error is not None
    assert "Chưa cấu hình AI" in result.error


def test_build_preset_applies_overrides(monkeypatch):
    import novel2epub.preset_builder as pb
    from novel2epub import openai_client

    # Mock AI to return a deterministic JSON.
    def fake_ai(prompt: str) -> str:
        return '{"toc_selector": "#list", "chapter_link_pattern": "/book/1/\\\\d+\\\\.html", "content_selector": "#content", "engine": "http"}'

    from novel2epub.config import OpenAIConfig

    monkeypatch.setattr(
        pb, "_get_openai_config", lambda config_path=None: OpenAIConfig(base_url="https://api.test/v1", timeout_seconds=10)
    )
    monkeypatch.setattr(openai_client, "run_chat", lambda _cfg, prompt: fake_ai(prompt))

    result = build_preset(
        "http://site.com/book/1/",
        novel_title="赤心巡天",
        overrides={"encoding": "gbk"},
        timeout_seconds=10,
    )
    assert result.error is None
    assert result.preset is not None
    assert result.preset.encoding == "gbk"
    assert "encoding" in result.overrides_applied


def test_preview_toc_runs_non_mutating(tmp_path, monkeypatch):
    from novel2epub import crawler as crawler_mod

    sources_path = tmp_path / "sources.yaml"
    sources_path.write_text("""
sources:
  demo:
    domains: site.com
    engine: http
    toc_selector: '#list'
    chapter_link_pattern: '/book/1/\\d+\\.html'
""", encoding="utf-8")

    html = """
    <html><body>
      <div id="list">
        <a href="/book/1/1.html">C1</a>
        <a href="/book/1/2.html">C2</a>
      </div>
    </body></html>
    """
    monkeypatch.setattr(crawler_mod.HttpCrawler, "_get_soup", lambda self, url: BeautifulSoup(html, "html.parser"))

    before = sources_path.read_text(encoding="utf-8")
    result = preview_toc("http://site.com/book/1/", "demo", sources_path)
    after = sources_path.read_text(encoding="utf-8")

    assert result.error is None
    assert result.preview is not None
    assert len(result.preview.chapters) == 2
    assert before == after


def test_save_preset_round_trips(tmp_path):
    sources_path = tmp_path / "sources.yaml"
    sources_path.write_text("sources:\n", encoding="utf-8")
    preset = SourcePreset(name="test", engine="http", domains="example.com")
    save_preset(preset, sources_path)
    from novel2epub.sources import load_presets
    presets = load_presets(sources_path)
    assert "test" in presets
    assert presets["test"].engine == "http"
    assert presets["test"].domains == "example.com"
