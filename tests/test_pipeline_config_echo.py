"""Tests cho phần echo config CRAWL ra job log (`_emit_crawl_config`).

Job log là thứ duy nhất user thấy trên web UI khi crawl fail, nên các dòng
[config] phải phản ánh ĐÚNG những gì đang bật/tắt — thiếu một dòng là user
đi tìm nhầm chỗ.
"""
from __future__ import annotations

from novel2epub.config import (
    Config,
    CrawlConfig,
    NovelConfig,
    OutputConfig,
    TranslateConfig,
)
from novel2epub.pipeline import _emit_crawl_config


def _cfg(**crawl_kwargs) -> Config:
    crawl = CrawlConfig(toc_url="https://example.com/book/", **crawl_kwargs)
    return Config(
        novel=NovelConfig(slug="my-novel"),
        crawl=crawl,
        translate=TranslateConfig(type="none"),
        output=OutputConfig(),
    )


def _lines(cfg: Config) -> list[str]:
    out: list[str] = []
    _emit_crawl_config(cfg, out.append)
    return out


def test_toc_pagination_reported_when_configured():
    """toc_next_page_selector bật thì phải có dòng TOC pagination riêng.

    Trước đây chỉ có '[config] CRAWL pagination: off' (nói về pagination
    CHƯƠNG) khiến user tưởng TOC pagination bị bỏ qua.
    """
    lines = _lines(_cfg(toc_next_page_selector="a.next", toc_max_pages=5))

    toc_lines = [ln for ln in lines if "TOC pagination" in ln]
    assert toc_lines, f"thiếu dòng TOC pagination; log={lines}"
    assert "a.next" in toc_lines[0]
    assert "5" in toc_lines[0]


def test_toc_pagination_reported_off_when_not_configured():
    lines = _lines(_cfg())

    toc_lines = [ln for ln in lines if "TOC pagination" in ln]
    assert toc_lines, f"thiếu dòng TOC pagination; log={lines}"
    assert "off" in toc_lines[0]


def test_chapter_pagination_line_is_distinct_from_toc():
    """Hai dòng pagination phải phân biệt được — không lẫn chương với mục lục."""
    lines = _lines(_cfg(next_page_selector="a#pg", toc_next_page_selector="a.next"))

    chapter_lines = [
        ln for ln in lines if "pagination" in ln and "TOC" not in ln
    ]
    toc_lines = [ln for ln in lines if "TOC pagination" in ln]
    assert len(chapter_lines) == 1, f"log={lines}"
    assert len(toc_lines) == 1, f"log={lines}"
    assert "a#pg" in chapter_lines[0]
    assert "a.next" in toc_lines[0]
