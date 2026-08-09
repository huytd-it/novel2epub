from __future__ import annotations

import pytest

from novel2epub.config import Config, CrawlConfig, NovelConfig, OutputConfig, TranslateConfig
from novel2epub.metadata_translation import translate_ebook_metadata


def _cfg() -> Config:
    return Config(
        novel=NovelConfig(), crawl=CrawlConfig(),
        translate=TranslateConfig(), output=OutputConfig(),
    )


def test_local_mt_translates_title_and_description(monkeypatch):
    class FakeTranslator:
        def translate_title(self, text, kind):
            assert kind == "tên sách"
            return "Tên Việt", ""

        def translate(self, text):
            return "Mô tả Việt"

    monkeypatch.setattr(
        "novel2epub.metadata_translation._local_mt_translator",
        lambda cfg: FakeTranslator(),
    )

    result = translate_ebook_metadata(
        _cfg(), title="中文书名", description="中文简介", engine="localmt",
    )

    assert result == {
        "title": "Tên Việt", "description": "Mô tả Việt", "engine": "localmt",
    }


def test_ai_parses_multiline_description(monkeypatch):
    monkeypatch.setattr(
        "novel2epub.metadata_translation.openai_client.run_chat",
        lambda cfg, prompt: "TITLE: Tên Việt\nDESCRIPTION: Dòng một\nDòng hai",
    )

    result = translate_ebook_metadata(
        _cfg(), title="中文书名", description="中文简介", engine="ai",
    )

    assert result["title"] == "Tên Việt"
    assert result["description"] == "Dòng một\nDòng hai"


def test_rejects_empty_metadata():
    with pytest.raises(ValueError, match="title hoặc description"):
        translate_ebook_metadata(_cfg())


def test_ai_rejects_missing_description_marker(monkeypatch):
    monkeypatch.setattr(
        "novel2epub.metadata_translation.openai_client.run_chat",
        lambda cfg, prompt: "TITLE: Tên Việt",
    )

    with pytest.raises(RuntimeError, match="DESCRIPTION"):
        translate_ebook_metadata(
            _cfg(), title="中文书名", description="中文简介", engine="ai",
        )
