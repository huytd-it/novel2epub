"""Test các hàm AI hỗ trợ trong editor 1 chương: review / suggest / rewrite-preview.

Mock glossary_ai để không gọi CLI thật; chỉ kiểm tra kết quả được ghi đúng vào
meta của chương và preview KHÔNG ghi đè bản dịch hiện tại.
"""
import pytest

from novel2epub import glossary_ai, pipeline
from novel2epub.config import (
    Config,
    CrawlConfig,
    NovelConfig,
    OutputConfig,
    TranslateConfig,
)
from novel2epub.storage import Chapter, Manifest, Storage


def _cfg(tmp_path):
    return Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/book/1/", delay_seconds=0),
        translate=TranslateConfig(type="cli", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


def _seed(tmp_path, *, translated="bản dịch cũ"):
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=1, url="http://x/1", title="第一章")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    storage.write_raw(ch, "原文")
    if translated is not None:
        storage.write_translated(ch, translated)
    return storage, ch


def test_review_chapter_writes_report_to_meta(tmp_path, monkeypatch):
    storage, ch = _seed(tmp_path)
    report = {"summary": "ổn", "score": 7, "issues": []}
    monkeypatch.setattr(glossary_ai, "evaluate_translation", lambda *a, **k: report)
    monkeypatch.setattr(glossary_ai, "load_glossary", lambda cfg: {})

    out = pipeline.step_review_chapter(_cfg(tmp_path), lambda m: None, index=1)

    assert out == report
    meta = storage.read_meta(ch)
    assert meta["ai_review"]["report"] == report
    assert meta["ai_review"]["generated_at"]


def test_review_chapter_without_translation_is_noop(tmp_path, monkeypatch):
    storage, ch = _seed(tmp_path, translated=None)
    called = {"n": 0}
    monkeypatch.setattr(glossary_ai, "evaluate_translation", lambda *a, **k: called.__setitem__("n", 1))

    pipeline.step_review_chapter(_cfg(tmp_path), lambda m: None, index=1)

    assert called["n"] == 0
    assert "ai_review" not in storage.read_meta(ch)


def test_suggest_chapter_writes_suggestions_to_meta(tmp_path, monkeypatch):
    storage, ch = _seed(tmp_path)
    suggestions = [{"source": "原文", "suggested": "Nguyên Văn", "type": "term", "reason": "", "target_file": "vietphrase.txt"}]
    monkeypatch.setattr(glossary_ai, "suggest_glossary", lambda *a, **k: suggestions)
    monkeypatch.setattr(glossary_ai, "load_glossary", lambda cfg: {})

    pipeline.step_suggest_chapter(_cfg(tmp_path), lambda m: None, index=1)

    assert storage.read_meta(ch)["ai_suggestions"] == suggestions


def test_rewrite_preview_does_not_overwrite_translation(tmp_path, monkeypatch):
    storage, ch = _seed(tmp_path, translated="bản dịch cũ")
    monkeypatch.setattr(glossary_ai, "rewrite_chapter", lambda *a, **k: "bản nháp mới")
    monkeypatch.setattr(glossary_ai, "load_glossary", lambda cfg: {})

    pipeline.step_rewrite_preview(_cfg(tmp_path), lambda m: None, index=1)

    # Bản dịch hiện tại GIỮ NGUYÊN; bản nháp nằm trong meta để người review duyệt.
    assert storage.read_translated(ch) == "bản dịch cũ"
    assert storage.read_meta(ch)["ai_rewrite"]["text"] == "bản nháp mới"


def test_rewrite_preview_empty_result_skips(tmp_path, monkeypatch):
    storage, ch = _seed(tmp_path)
    monkeypatch.setattr(glossary_ai, "rewrite_chapter", lambda *a, **k: "   ")
    monkeypatch.setattr(glossary_ai, "load_glossary", lambda cfg: {})

    pipeline.step_rewrite_preview(_cfg(tmp_path), lambda m: None, index=1)

    assert "ai_rewrite" not in storage.read_meta(ch)


def test_require_chapter_raises_on_missing_index(tmp_path):
    _seed(tmp_path)
    with pytest.raises(RuntimeError, match="Không tìm thấy chương"):
        pipeline.step_review_chapter(_cfg(tmp_path), lambda m: None, index=99)
