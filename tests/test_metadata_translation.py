from __future__ import annotations

import pytest

from novel2epub.config import Config, CrawlConfig, NovelConfig, OutputConfig, TranslateConfig
from novel2epub.metadata_translation import translate_ebook_metadata


def _cfg() -> Config:
    return Config(
        novel=NovelConfig(), crawl=CrawlConfig(),
        translate=TranslateConfig(), output=OutputConfig(),
    )


def test_local_mt_translates_structured_metadata_and_preserves_subject_boundaries(monkeypatch):
    class FakeTranslator:
        def translate_title(self, text, kind):
            assert kind == "tên sách"
            return "Tên Việt", ""

        def translate(self, text):
            return {
                "作者": "Tác giả Việt",
                "中文简介": "Mô tả Việt",
                "玄幻": "Huyền huyễn",
                "冒险": "Phiêu lưu",
            }[text]

    monkeypatch.setattr(
        "novel2epub.metadata_translation._local_mt_translator",
        lambda cfg: FakeTranslator(),
    )

    result = translate_ebook_metadata(
        _cfg(), title="中文书名", author="作者", description="中文简介",
        subjects=["玄幻", "冒险"], engine="localmt",
    )

    assert result["draft"] == {
        "title": "Tên Việt",
        "author": "Tác giả Việt",
        "description": "Mô tả Việt",
        "subjects": ["Huyền huyễn", "Phiêu lưu"],
    }
    assert result["title"] == "Tên Việt"
    assert result["engine"] == "localmt"
    assert result["model"] == "HachimiMT-60"
    assert result["errors"] == {}


def test_ai_parses_structured_json_and_uses_assistant_model(monkeypatch):
    monkeypatch.setattr(
        "novel2epub.metadata_translation.openai_client.run_chat",
        lambda cfg, prompt: '{"title":"Tên Việt","description":"Dòng một\\nDòng hai"}',
    )

    result = translate_ebook_metadata(
        _cfg(), title="中文书名", description="中文简介", engine="ai",
    )

    assert result["title"] == "Tên Việt"
    assert result["description"] == "Dòng một\nDòng hai"
    assert result["model"] == _cfg().ai.openai.model


def test_vietnamese_metadata_is_passthrough(monkeypatch):
    monkeypatch.setattr(
        "novel2epub.metadata_translation._local_mt_translator",
        lambda cfg: pytest.fail("Local MT must not be loaded for Vietnamese metadata"),
    )
    result = translate_ebook_metadata(
        _cfg(), title="Tên Việt", author="Tác giả", subjects=["Phiêu lưu"],
        source_language="vi",
    )
    assert result["draft"] == {
        "title": "Tên Việt", "author": "Tác giả", "description": "",
        "subjects": ["Phiêu lưu"],
    }
    assert result["model"] == "passthrough"


def test_rejects_empty_metadata():
    with pytest.raises(ValueError, match="metadata"):
        translate_ebook_metadata(_cfg())


def test_ai_reports_field_error_without_losing_other_fields(monkeypatch):
    monkeypatch.setattr(
        "novel2epub.metadata_translation.openai_client.run_chat",
        lambda cfg, prompt: '{"title":"Tên Việt"}',
    )

    result = translate_ebook_metadata(
        _cfg(), title="中文书名", description="中文简介", engine="ai",
    )
    assert result["title"] == "Tên Việt"
    assert result["description"] == "中文简介"
    assert "description" in result["errors"]


def test_ai_rejects_subject_boundary_change(monkeypatch):
    monkeypatch.setattr(
        "novel2epub.metadata_translation.openai_client.run_chat",
        lambda cfg, prompt: '{"subjects":["gộp"]}',
    )
    result = translate_ebook_metadata(
        _cfg(), subjects=["玄幻", "冒险"], engine="ai",
    )
    assert result["subjects"] == ["玄幻", "冒险"]
    assert "subjects" in result["errors"]


def test_rejects_overlong_field():
    with pytest.raises(ValueError, match="description quá dài"):
        translate_ebook_metadata(_cfg(), description="x" * 20001)
