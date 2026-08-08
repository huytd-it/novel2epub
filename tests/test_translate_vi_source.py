"""Truyện nguồn tiếng Việt (translate.source_language=vi): không cần dịch —
bước dịch chỉ copy nguyên văn raw → translated (+ snapshot translated_mt),
không gọi AI/model nào, tiêu đề giữ nguyên."""
from __future__ import annotations

import pytest

from novel2epub import pipeline
from novel2epub.config import (
    Config,
    CrawlConfig,
    NovelConfig,
    OpenAIConfig,
    OutputConfig,
    TranslateConfig,
)
from novel2epub.storage import Chapter, Manifest, Storage
from novel2epub.translator import NoopTranslator, make_translator


def _cfg(tmp_path):
    return Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/book/1/", delay_seconds=0),
        translate=TranslateConfig(
            type="openai",  # type openai nhưng nguồn vi → vẫn phải noop
            source_language="vi",
            delay_seconds=0,
            # base_url không tồn tại: nếu pipeline lỡ gọi AI thật, test sẽ fail
            openai=OpenAIConfig(base_url="http://127.0.0.1:9/v1"),
        ),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


def _seed(tmp_path, title="Chương 1: Khởi đầu"):
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=1, url="http://x/1", title=title)
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    storage.write_raw(ch, "Ngày xưa có một chàng trai.\n\nAnh ta lên núi tu tiên.")
    return storage, ch


def test_make_translator_vi_source_returns_noop():
    cfg = TranslateConfig(type="openai", source_language="vi")
    assert isinstance(make_translator(cfg), NoopTranslator)


def test_make_translator_vi_source_case_insensitive():
    cfg = TranslateConfig(type="localmt", source_language=" VI ")
    assert isinstance(make_translator(cfg), NoopTranslator)


def test_translate_vi_source_copies_raw_without_ai(tmp_path):
    storage, ch = _seed(tmp_path)
    raw = storage.read_raw(ch)

    pipeline.step_translate_selected(_cfg(tmp_path), lambda m: None, selected_indexes=[1])

    # Nội dung giữ nguyên văn, snapshot MT cũng là nguyên văn.
    assert storage.read_translated(ch) == raw
    assert storage.read_translated_mt(ch) == raw
    assert storage.read_meta(ch)["complete"] is True
    # Tiêu đề không bị đụng (noop không prepend/dịch tiêu đề).
    assert ch.title == "Chương 1: Khởi đầu"
    assert ch.title_zh == ""


def test_translate_toc_vi_source_keeps_titles(tmp_path):
    storage, ch = _seed(tmp_path)

    manifest = pipeline.step_translate_toc_selected(
        _cfg(tmp_path), lambda m: None, force=True, selected_indexes=[1]
    )

    out = manifest.chapters[0]
    assert out.title == "Chương 1: Khởi đầu"
    assert out.title_zh == ""


def test_retranslate_title_vi_source_raises(tmp_path):
    storage, ch = _seed(tmp_path)
    storage.write_translated(ch, "nội dung")

    with pytest.raises(RuntimeError, match="noop"):
        pipeline.step_retranslate_title(_cfg(tmp_path), slug="t", index=1)
