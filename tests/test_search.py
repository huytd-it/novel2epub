"""Unit tests cho novel2epub.search module."""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from novel2epub.search import SearchResult, SourceSearcher, search_all
from novel2epub.sources import SourcePreset


def _make_preset(**overrides) -> SourcePreset:
    defaults = {
        "name": "test-source",
        "engine": "scrapling",
        "url": "https://example.com",
        "domains": "example.com",
        "search_url_pattern": "https://example.com/search?q={query}",
        "search_result_selector": ".result-item",
        "search_title_selector": ".title",
        "search_link_selector": "a.link",
        "search_author_selector": ".author",
        "search_cover_selector": "img.cover",
        "max_search_results": 5,
    }
    defaults.update(overrides)
    return SourcePreset(**defaults)


class TestSourceSearcher:
    @patch("novel2epub.search._fetch_page")
    def test_search_returns_results(self, mock_fetch):
        page = MagicMock()
        item1 = MagicMock()
        item1.css.side_effect = lambda sel: {
            ".title": [MagicMock(text="Truyện A", get_all_text=lambda strip=True: "Truyện A")],
            "a.link": [MagicMock(attrib={"href": "/book/1"})],
            ".author": [MagicMock(text="Tác giả A", get_all_text=lambda strip=True: "Tác giả A")],
            "img.cover": [MagicMock(attrib={"src": "/img/1.jpg"})],
        }.get(sel, [])
        item1.attrib = {}

        page.css.return_value = [item1]
        mock_fetch.return_value = page

        preset = _make_preset()
        searcher = SourceSearcher(preset)
        results = searcher.search("truyện")

        assert len(results) == 1
        assert results[0].title == "Truyện A"
        assert results[0].author == "Tác giả A"
        assert results[0].source_name == "test-source"
        assert "book/1" in results[0].url

    @patch("novel2epub.search._fetch_page")
    def test_search_no_pattern_returns_empty(self, mock_fetch):
        preset = _make_preset(search_url_pattern="")
        searcher = SourceSearcher(preset)
        results = searcher.search("truyện")
        assert results == []
        mock_fetch.assert_not_called()

    @patch("novel2epub.search._fetch_page")
    def test_search_respects_limit(self, mock_fetch):
        page = MagicMock()
        items = []
        for i in range(10):
            item = MagicMock()
            item.css.side_effect = lambda sel, _i=i: {
                ".title": [MagicMock(text=f"Truyện {_i}", get_all_text=lambda strip=True, _i=_i: f"Truyện {_i}")],
                "a.link": [MagicMock(attrib={"href": f"/book/{_i}"})],
                ".author": [MagicMock(text="", get_all_text=lambda strip=True: "")],
                "img.cover": [],
            }.get(sel, [])
            item.attrib = {}
            items.append(item)

        page.css.return_value = items
        mock_fetch.return_value = page

        preset = _make_preset(max_search_results=3)
        searcher = SourceSearcher(preset)
        results = searcher.search("truyện")

        assert len(results) <= 3


class TestSearchAll:
    @patch("novel2epub.search.SourceSearcher.search")
    def test_search_all_multiple_sources(self, mock_search):
        mock_search.return_value = [
            SearchResult(title="Truyện A", url="https://example.com/1", source_name="src1"),
        ]

        presets = {
            "src1": _make_preset(name="src1"),
            "src2": _make_preset(name="src2", search_url_pattern="https://other.com/search?q={query}"),
        }

        response = search_all(presets, "truyện", max_workers=2)

        assert len(response.results) == 2
        assert len(response.errors) == 0

    @patch("novel2epub.search.SourceSearcher.search")
    def test_search_all_with_error(self, mock_search):
        def side_effect(query):
            raise Exception("Anti-bot blocked")

        mock_search.side_effect = side_effect

        presets = {"src1": _make_preset(name="src1")}
        response = search_all(presets, "truyện")

        assert len(response.results) == 0
        assert len(response.errors) == 1
        assert "Anti-bot" in response.errors[0].message

    def test_search_all_no_search_config(self):
        presets = {"src1": _make_preset(name="src1", search_url_pattern="")}
        response = search_all(presets, "truyện")

        assert len(response.results) == 0
        assert len(response.errors) == 1
        assert "Không có source" in response.errors[0].message

    @patch("novel2epub.search.SourceSearcher.search")
    def test_search_all_filter_by_source_names(self, mock_search):
        mock_search.return_value = [
            SearchResult(title="Truyện A", url="https://example.com/1", source_name="src1"),
        ]

        presets = {
            "src1": _make_preset(name="src1"),
            "src2": _make_preset(name="src2"),
        }

        response = search_all(presets, "truyện", source_names=["src1"])

        assert len(response.results) == 1
        mock_search.assert_called_once()
