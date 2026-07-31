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
    # title rỗng: các test này pin chunk-streaming; dịch tiêu đề chung content
    # được cover riêng ở tests/test_translate_title_combined.py.
    ch = Chapter(index=1, url="http://x/1", title="")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    storage.write_raw(ch, "原文\n" * 50)  # đủ dài để chia chunk
    return storage, ch


class _ChunkingTranslator:
    """Translator giả: chia text thành 3 phần cố định, mỗi phần ~1/3."""

    def __init__(self):
        self.calls = 0

    def translate(self, text, *, chapter_idx=None, on_chunk=None, on_glossary=None):
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
    monkeypatch.setattr(pipeline, "make_translator", lambda c, log=None, **kw: translator)

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
        def translate(self, text, *, chapter_idx=None, on_chunk=None, on_glossary=None):
            if on_chunk is not None:
                on_chunk(1, 2, "PHẦN 1", False)  # chunk 1 OK
            raise RuntimeError("CLI lỗi giữa chừng")

        def translate_title(self, text, kind="tên chương"):
            return f"VI:{text}", ""

    storage, ch = _seed(tmp_path)
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(pipeline, "make_translator", lambda c, log=None, **kw: _FailingTranslator())

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
        def translate(self, text, *, chapter_idx=None, on_chunk=None, on_glossary=None):
            seen.append("called")
            return super().translate(text, chapter_idx=chapter_idx, on_chunk=on_chunk, on_glossary=on_glossary)

        def translate_title(self, text, kind="tên chương"):
            return text, ""

    cfg = _cfg(tmp_path)
    monkeypatch.setattr(pipeline, "make_translator", lambda c, log=None, **kw: _RecordingTranslator())
    pipeline.step_translate_selected(cfg, lambda m: None, selected_indexes=[1])
    assert seen == ["called"], "Translator phải được gọi lại vì partial không phải complete"
    # File đã được ghi đè với đầy đủ 3 chunk.
    assert storage.read_translated(ch) == "PHẦN 1\nPHẦN 2\nPHẦN 3"
    assert storage.read_meta(ch)["complete"] is True


def _translator_with_characters(tmp_path, template):
    from novel2epub.config import TranslateConfig
    from novel2epub.storage import Storage
    from novel2epub.translator import OpenAITranslator

    storage = Storage(str(tmp_path), "truyen-test")
    storage.upsert_character("林凡", "Lâm Phàm", "凡儿", "nam", "ta", "hắn", "", "main")
    storage.upsert_character("苏清雪", "Tô Thanh Tuyết", "", "nu", "", "nàng", "", "side")
    storage.upsert_relation("林凡", "苏清雪", 0, "nàng", "ta")
    storage.upsert_relation("林凡", "苏清雪", 120, "em", "anh")

    cfg = TranslateConfig()
    cfg.genre = "xianxia"
    cfg.openai.prompt_template = template
    return OpenAITranslator(cfg, storage=storage), storage


def test_prompt_contains_character_block(tmp_path):
    tr, _ = _translator_with_characters(tmp_path, "A\n{characters}\n{text}")
    prompt = tr._build_prompt("苏清雪 走了进来。", chapter_idx=200)
    assert "BẢNG NHÂN VẬT & NGÔI XƯNG" in prompt
    assert "林凡 = Lâm Phàm" in prompt          # main, luôn chèn
    assert 'với Tô Thanh Tuyết: gọi "em", tự xưng "anh"' in prompt   # mốc 120


def test_prompt_uses_chapter_zero_milestone_when_idx_missing(tmp_path):
    tr, _ = _translator_with_characters(tmp_path, "A\n{characters}\n{text}")
    prompt = tr._build_prompt("苏清雪 走了进来。", chapter_idx=None)
    assert 'gọi "nàng"' in prompt
    assert 'gọi "em"' not in prompt


def test_block_injected_when_template_lacks_placeholder(tmp_path):
    # Template pin cũ không có {characters} → vẫn phải được chèn, ngay trước nội dung.
    tr, _ = _translator_with_characters(tmp_path, "A\n{glossary}\n{text}")
    prompt = tr._build_prompt("苏清雪 走了进来。", chapter_idx=0)
    assert "BẢNG NHÂN VẬT & NGÔI XƯNG" in prompt
    assert prompt.index("BẢNG NHÂN VẬT") < prompt.index("苏清雪 走了进来。")


def test_pin_line_is_last(tmp_path):
    tr, _ = _translator_with_characters(tmp_path, "A\n{characters}\n{text}")
    prompt = tr._build_prompt("苏清雪 走了进来。", chapter_idx=0)
    assert "NHẮC LẠI:" in prompt
    assert prompt.index("NHẮC LẠI:") > prompt.index("苏清雪 走了进来。")


def test_pronoun_policy_renders_genre_rules(tmp_path):
    tr, _ = _translator_with_characters(tmp_path, "P={pronoun_policy}\n{text}")
    prompt = tr._build_prompt("走。", chapter_idx=0)
    assert "tại hạ" in prompt
    assert "contextual" not in prompt


def test_runtime_pin_protects_contextual_pronouns_without_character_table(tmp_path):
    from novel2epub.config import TranslateConfig
    from novel2epub.translator import OpenAITranslator

    cfg = TranslateConfig()
    cfg.genre = "urban"
    cfg.openai.prompt_template = "Prompt cũ cấm hắn.\n{text}"
    prompt = OpenAITranslator(cfg)._build_prompt("他发现怪物更快。")
    assert prompt.endswith(__import__("novel2epub.genre", fromlist=["RUNTIME_PRONOUN_PIN"]).RUNTIME_PRONOUN_PIN)
    assert "hắn/ta/ngươi chỉ dùng khi tự nhiên" in prompt
    assert "CẤM dùng" not in prompt


def test_character_table_pronouns_override_urban_genre_guidance(tmp_path):
    tr, _ = _translator_with_characters(tmp_path, "{pronoun_policy}\n{characters}\n{text}")
    tr.cfg.genre = "urban"
    prompt = tr._build_prompt("林凡 走了。", chapter_idx=0)
    assert 'tự xưng "ta"' in prompt
    assert 'lời kể gọi "hắn"' in prompt
    assert "CẤM:" not in prompt
    assert "CẤM dùng" not in prompt
    assert prompt.rfind("Bảng nhân vật > ngôi kể > ngữ cảnh > thể loại") > prompt.index("林凡 走了。")


def test_rate_limited_forwards_chapter_idx():
    """RateLimited là wrapper — quên chuyển tiếp chapter_idx thì mọi ebook có
    giới hạn tốc độ sẽ mất mốc quan hệ (`from_chapter`) mà không báo lỗi gì."""
    from novel2epub.translator import RateLimited

    class _Recorder:
        def __init__(self):
            self.seen_chapter_idx = "chưa gọi"

        def translate(self, text, *, chapter_idx=None, on_chunk=None, on_glossary=None):
            self.seen_chapter_idx = chapter_idx
            return text

    inner = _Recorder()
    wrapped = RateLimited(inner, delay_seconds=0)
    wrapped.translate("苏清雪 走了进来。", chapter_idx=42)
    assert inner.seen_chapter_idx == 42
