"""Test _translate_one ghi file progressive qua on_chunk (spec translate-chunk-streaming)."""
from __future__ import annotations

from novel2epub import pipeline
from novel2epub.config import (
    OpenAIConfig,
    Config,
    CrawlConfig,
    NovelConfig,
    OutputConfig,
    TranslationChunkConfig,
    TranslateConfig,
)
from novel2epub.storage import Chapter, Manifest, Storage


def _cfg(tmp_path):
    return Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/book/1/", delay_seconds=0),
        translate=TranslateConfig(
            type="openai",
            delay_seconds=0,
            openai=OpenAIConfig(
                base_url="https://api.test/v1",
                prompt_template="{text}",
                title_prompt_template="{text}",
            ),
            chunk=TranslationChunkConfig(max_chars=20, overlap_paragraphs=0),
        ),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


def _seed(tmp_path):
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=1, url="http://x/1", title="第一章")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    storage.write_raw(ch, "原文\n" * 50)  # đủ dài để chia chunk
    return storage, ch


class _ChunkingTranslator:
    """Translator giả: chia text thành 3 phần cố định, mỗi phần ~1/3."""

    def __init__(self):
        self.calls = 0

    def translate(self, text, *, on_chunk=None):
        parts = ["PHẦN 1", "PHẦN 2", "PHẦN 3"]
        if on_chunk is not None:
            for i, p in enumerate(parts, 1):
                on_chunk(i, len(parts), p, i == len(parts))
        return "\n".join(parts)

    def translate_title(self, text, kind="tên chương"):
        return f"VI:{text}", ""


def test_translate_one_writes_file_progressively(tmp_path, monkeypatch):
    storage, ch = _seed(tmp_path)
    translator = _ChunkingTranslator()
    cfg = _cfg(tmp_path)
    cfg.translate.type = "openai"  # is_noop = False

    # Patch make_translator để trả translator giả.
    monkeypatch.setattr(pipeline, "make_translator", lambda c, log=None: translator)

    pipeline.step_translate_selected(cfg, lambda m: None, selected_indexes=[1])

    # File đã ghi đầy đủ 3 chunk nối bằng \n.
    assert storage.read_translated(ch) == "PHẦN 1\nPHẦN 2\nPHẦN 3"
    # Meta có `complete: True` ở cuối.
    meta = storage.read_meta(ch)
    assert meta["complete"] is True
    assert meta["chapter"] == "0001"
    assert meta["index"] == 1


def test_translate_one_failure_does_not_mark_complete(tmp_path, monkeypatch):
    """Nếu translator raise giữa chừng, meta KHÔNG có `complete: true`."""

    class _FailingTranslator:
        def translate(self, text, *, on_chunk=None):
            if on_chunk is not None:
                on_chunk(1, 2, "PHẦN 1", False)  # chunk 1 OK
            raise RuntimeError("CLI lỗi giữa chừng")

        def translate_title(self, text, kind="tên chương"):
            return f"VI:{text}", ""

    storage, ch = _seed(tmp_path)
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(pipeline, "make_translator", lambda c, log=None: _FailingTranslator())

    with __import__("pytest").raises(RuntimeError, match="CLI lỗi"):
        pipeline.step_translate_selected(cfg, lambda m: None, selected_indexes=[1])

    # File có 1 chunk đã ghi nhưng meta KHÔNG complete.
    assert storage.read_translated(ch) == "PHẦN 1"
    meta = storage.read_meta(ch) if storage.has_meta(ch) else {}
    assert not meta.get("complete", False), f"meta không được complete khi job fail: {meta}"
    # has_translated phải trả False (sẽ bị dịch lại ở lần chạy sau).
    assert storage.has_translated(ch) is False


def test_partial_chapter_is_retried_on_next_run(tmp_path, monkeypatch):
    """Chapter có file translated/ nhưng meta có complete=False → lần chạy kế sẽ dịch lại."""
    storage, ch = _seed(tmp_path)
    # Mô phỏng job trước đã ghi 1 chunk rồi crash (đã ghi meta với complete=False).
    storage.write_translated(ch, "PHẦN 1")
    storage.write_meta(ch, {"complete": False, "warnings": [], "generated_at": "2024-01-01T00:00:00"})

    # Chạy step_translate_selected KHÔNG force: phải dịch lại (vì has_translated=False).
    seen: list[str] = []

    class _RecordingTranslator(_ChunkingTranslator):
        def translate(self, text, *, on_chunk=None):
            seen.append("called")
            return super().translate(text, on_chunk=on_chunk)

        def translate_title(self, text, kind="tên chương"):
            return text, ""

    cfg = _cfg(tmp_path)
    monkeypatch.setattr(pipeline, "make_translator", lambda c, log=None: _RecordingTranslator())
    pipeline.step_translate_selected(cfg, lambda m: None, selected_indexes=[1])
    assert seen == ["called"], "Translator phải được gọi lại vì partial không phải complete"
    # File đã được ghi đè với đầy đủ 3 chunk.
    assert storage.read_translated(ch) == "PHẦN 1\nPHẦN 2\nPHẦN 3"
    assert storage.read_meta(ch)["complete"] is True
