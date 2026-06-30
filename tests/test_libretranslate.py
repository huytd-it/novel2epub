"""Unit tests cho LibreTranslateTranslator."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from novel2epub.config import LibreTranslateConfig, TranslateConfig
from novel2epub.translator import LibreTranslateTranslator


def _make_lt_config(**overrides) -> TranslateConfig:
    lt = LibreTranslateConfig(**overrides)
    return TranslateConfig(type="libretranslate", libretranslate=lt)


class TestLibreTranslateTranslator:
    @patch("requests.post")
    def test_translate_calls_api(self, mock_post):
        resp = MagicMock()
        resp.json.return_value = {"translatedText": "Xin chào"}
        resp.raise_for_status = MagicMock()
        mock_post.return_value = resp

        cfg = _make_lt_config(base_url="http://localhost:5000")
        translator = LibreTranslateTranslator(cfg)
        result = translator.translate("你好")

        assert result == "Xin chào"
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "http://localhost:5000/translate"
        assert call_args[1]["json"]["q"] == "你好"
        assert call_args[1]["json"]["source"] == ""
        assert call_args[1]["json"]["target"] == "vi"

    @patch("requests.post")
    def test_translate_with_api_key(self, mock_post):
        resp = MagicMock()
        resp.json.return_value = {"translatedText": "Xin chào"}
        resp.raise_for_status = MagicMock()
        mock_post.return_value = resp

        cfg = _make_lt_config(api_key="test-key-123")
        translator = LibreTranslateTranslator(cfg)
        translator.translate("你好")

        call_args = mock_post.call_args
        headers = call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer test-key-123"

    def test_translate_empty_text(self):
        cfg = _make_lt_config()
        translator = LibreTranslateTranslator(cfg)
        result = translator.translate("")

        assert result == ""

    @patch("requests.post")
    def test_translate_title(self, mock_post):
        resp = MagicMock()
        resp.json.return_value = {"translatedText": "Trường Ca Hành"}
        resp.raise_for_status = MagicMock()
        mock_post.return_value = resp

        cfg = _make_lt_config()
        translator = LibreTranslateTranslator(cfg)
        title, note = translator.translate_title("长歌行")

        assert title == "Trường Ca Hành"
        assert note == ""

    @patch("requests.post")
    def test_translate_applies_glossary(self, mock_post):
        resp = MagicMock()
        resp.json.return_value = {"translatedText": "Diệp Phàm là nhân vật chính"}
        resp.raise_for_status = MagicMock()
        mock_post.return_value = resp

        cfg = _make_lt_config()
        cfg.glossary = {"叶凡": "Diệp Phàm"}
        translator = LibreTranslateTranslator(cfg)
        result = translator.translate("叶凡是主角")

        assert "Diệp Phàm" in result
