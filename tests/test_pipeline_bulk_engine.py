from __future__ import annotations

from novel2epub import pipeline
from novel2epub.config import Config, CrawlConfig, NovelConfig, OutputConfig, TranslateConfig
from novel2epub.storage import Chapter, Manifest, Storage


def _cfg(tmp_path) -> Config:
    cfg = Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="https://example.com/toc"),
        translate=TranslateConfig(type="openai"),
        output=OutputConfig(data_dir=str(tmp_path)),
    )
    storage = Storage(tmp_path, "t")
    chapter = Chapter(index=1, url="https://example.com/1")
    storage.save_manifest(Manifest(slug="t", chapters=[chapter]))
    storage.write_raw(chapter, "第一章")
    return cfg


def test_bulk_local_mt_forces_local_engine(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    captured = {}

    def fake_translate(effective_cfg, log, **kwargs):
        captured["type"] = effective_cfg.translate.type
        captured["branch"] = kwargs["branch"]

    monkeypatch.setattr(pipeline, "step_translate_selected", fake_translate)
    result = pipeline.step_bulk_confirm(
        cfg,
        lambda message: None,
        action="local-mt",
        indexes=[1],
    )

    assert result["status"] == "done"
    assert captured == {"type": "localmt", "branch": "local_mt"}


def test_bulk_ai_translate_keeps_configured_engine(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    cfg.translate.type = "localmt"
    captured = {}

    def fake_translate(effective_cfg, log, **kwargs):
        captured["type"] = effective_cfg.translate.type
        captured["branch"] = kwargs["branch"]

    monkeypatch.setattr(pipeline, "step_translate_selected", fake_translate)
    result = pipeline.step_bulk_confirm(
        cfg,
        lambda message: None,
        action="translate",
        indexes=[1],
        branch="ai",
    )

    assert result["status"] == "done"
    assert captured == {"type": "openai", "branch": "ai"}
