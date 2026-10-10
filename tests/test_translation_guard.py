"""Guard bắt buộc khi dịch chương: bản dịch không hợp lệ không được lưu DB.

- Trung → Việt: số từ bản Việt phải >= số từ bản Trung.
- Bản dịch dài bất thường, hoặc dính prompt dịch mà không tách ra được.
"""
from __future__ import annotations

import pytest

from novel2epub import openai_client, pipeline
from novel2epub import translation_guard as guard
from novel2epub.config import (
    Config,
    CrawlConfig,
    NovelConfig,
    OpenAIConfig,
    OutputConfig,
    TranslateConfig,
)
from novel2epub.storage import Chapter, Manifest, Storage
from novel2epub.translation_guard import TranslationGuardError
from novel2epub.translator import OpenAITranslator

RAW = "他走进了房间。\n\n她没有说话。"  # 11 chữ Hán
GOOD = "Hắn bước vào trong căn phòng.\n\nNàng không hề nói một lời nào."  # 13 từ
SHORT = "Hắn vào phòng."  # 3 từ


# ---------- đếm từ ----------

def test_count_words_han_chars_and_other_tokens():
    assert guard.count_words("他走进了房间。") == 6
    assert guard.count_words("第12章 起风") == 5  # 4 chữ Hán + "12"
    assert guard.count_words("Hắn bước vào phòng.", han=False) == 4


def test_count_words_vi_side_ignores_leftover_han():
    """Chữ Hán còn sót là phần CHƯA dịch — không được tính là từ tiếng Việt."""
    assert guard.count_words("Hắn 走进了 phòng", han=False) == 2


def test_count_words_handles_decomposed_vietnamese():
    import unicodedata

    assert guard.count_words(unicodedata.normalize("NFD", "tiếng Việt"), han=False) == 2


@pytest.mark.parametrize("source,target,expected", [
    ("", "vi", True), ("zh", "vi", True), (" ZH-CN ", "", True),
    ("en", "vi", False), ("vi", "vi", False), ("zh", "en", False),
])
def test_is_zh_to_vi(source, target, expected):
    assert guard.is_zh_to_vi(source, target) is expected


# ---------- guard số từ ----------

def test_zh_to_vi_requires_at_least_as_many_words():
    guard.check_word_counts(RAW, GOOD, zh_to_vi=True)
    guard.check_word_counts("他走了。", "Hắn đi rồi.", zh_to_vi=True)  # bằng nhau: hợp lệ
    with pytest.raises(TranslationGuardError, match="thiếu"):
        guard.check_word_counts(RAW, SHORT, zh_to_vi=True)


def test_untranslated_echo_of_source_is_rejected():
    with pytest.raises(TranslationGuardError, match="thiếu"):
        guard.check_word_counts(RAW, RAW, zh_to_vi=True)


def test_lower_bound_only_applies_to_zh_to_vi():
    guard.check_word_counts("one two three four five six", "một hai", zh_to_vi=False)


def test_abnormally_long_translation_is_rejected_for_any_language():
    bloated = "từ " * (11 * 3 + guard.MAX_WORD_SLACK + 1)
    with pytest.raises(TranslationGuardError, match="dài bất thường"):
        guard.check_word_counts(RAW, bloated, zh_to_vi=True)
    with pytest.raises(TranslationGuardError, match="dài bất thường"):
        guard.check_word_counts("eleven words " * 5 + "x", bloated, zh_to_vi=False)


# ---------- tách prompt bị lặp ----------

PROMPT = (
    "Bạn là dịch giả tiểu thuyết mạng Trung Quốc sang tiếng Việt.\n"
    "- Dịch đầy đủ nội dung, không tự ý thêm, bớt hoặc giải thích.\n"
    "林凡的宗门长老之名 = Trưởng lão tông môn của Lâm Phàm\n"
    "--- Nội dung cần dịch ---\n"
    f"{RAW}"
)


def test_output_without_prompt_is_untouched():
    assert guard.strip_prompt_echo(GOOD, PROMPT, RAW) == GOOD


def test_echoed_prompt_and_source_are_stripped():
    out = f"{PROMPT}\n\n{GOOD}"
    assert guard.strip_prompt_echo(out, PROMPT, RAW) == GOOD


def test_text_before_echoed_prompt_is_kept():
    out = f"{GOOD}\n\n{PROMPT}"
    assert guard.strip_prompt_echo(out, PROMPT, RAW) == GOOD


def test_only_prompt_cannot_be_separated():
    with pytest.raises(TranslationGuardError, match="không tách ra được"):
        guard.strip_prompt_echo(PROMPT, PROMPT, RAW)


def test_glossary_line_repeated_in_response_is_not_an_echo():
    """Phần GLOSSARY hợp lệ có thể lặp y nguyên một mục đã có trong prompt."""
    out = f"{GOOD}\nGLOSSARY:\n林凡的宗门长老之名 = Trưởng lão tông môn của Lâm Phàm"
    assert guard.strip_prompt_echo(out, PROMPT, RAW) == out


def _openai_translator(monkeypatch, response: str) -> OpenAITranslator:
    cfg = TranslateConfig(type="openai", auto_glossary=False)
    cfg.openai.prompt_template = (
        "Bạn là dịch giả tiểu thuyết mạng Trung Quốc sang tiếng Việt.\n"
        "--- Nội dung cần dịch ---\n{text}"
    )
    translator = OpenAITranslator(cfg)
    monkeypatch.setattr(
        openai_client, "run_chat_with_meta",
        lambda openai_cfg, prompt: (response.replace("{prompt}", prompt), {}),
    )
    return translator


def test_translator_strips_echoed_prompt_from_chunk(monkeypatch):
    translator = _openai_translator(monkeypatch, "{prompt}\n\n" + GOOD)
    assert translator.translate(RAW) == GOOD


def test_translator_fails_when_response_is_only_the_prompt(monkeypatch):
    translator = _openai_translator(monkeypatch, "{prompt}")
    streamed: list[str] = []
    with pytest.raises(TranslationGuardError):
        translator.translate(RAW, on_chunk=lambda *a: streamed.append(a[2]))
    assert streamed == []


# ---------- pipeline: bản bị từ chối không nằm lại trong DB ----------

def _cfg(tmp_path, **translate):
    return Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/book/1/", delay_seconds=0),
        translate=TranslateConfig(
            type="openai",
            delay_seconds=0,
            openai=OpenAIConfig(base_url="https://api.test/v1", prompt_template="{text}"),
            **translate,
        ),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


def _seed(tmp_path, raw=RAW):
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=1, url="http://x/1", title=""), Chapter(index=2, url="http://x/2", title="")]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    for ch in chapters:
        storage.write_raw(ch, raw)
    return storage, chapters


class _ByChapter:
    """Translator giả: mỗi chương trả một danh sách chunk định sẵn."""

    def __init__(self, outputs: dict[int, list[str]]):
        self.outputs = outputs

    def translate(self, text, *, chapter_idx=None, on_chunk=None, on_glossary=None):
        parts = self.outputs[chapter_idx]
        for i, part in enumerate(parts, 1):
            on_chunk(i, len(parts), part, i == len(parts))
        return "\n".join(parts)

    def translate_title(self, text, kind="tên chương"):
        return text, ""


def _translate(tmp_path, monkeypatch, outputs, cfg=None, **kwargs):
    monkeypatch.setattr(pipeline, "make_translator", lambda c, log=None, **kw: _ByChapter(outputs))
    logs: list[str] = []
    pipeline.step_translate_selected(cfg or _cfg(tmp_path), logs.append, **kwargs)
    return logs


def test_short_translation_is_not_saved(tmp_path, monkeypatch):
    storage, (ch1, _ch2) = _seed(tmp_path)

    logs = _translate(tmp_path, monkeypatch, {1: ["Hắn", "vào phòng."]}, selected_indexes=[1])

    # Chunk đã stream bị bỏ: không còn chữ nào của bản dịch lỗi trong DB.
    assert storage.read_translated(ch1) == ""
    assert storage.has_translated(ch1) is False
    assert storage.read_translated_mt(ch1) == ""
    assert "thiếu" in storage.read_meta(ch1)["last_error"]
    assert storage.load_manifest().chapters[0].last_action_status == "failed"
    assert any("Guard từ chối" in line for line in logs)


def test_abnormally_long_translation_is_not_saved(tmp_path, monkeypatch):
    storage, (ch1, _ch2) = _seed(tmp_path)

    _translate(tmp_path, monkeypatch, {1: ["từ " * 200]}, selected_indexes=[1])

    assert storage.read_translated(ch1) == ""
    assert "dài bất thường" in storage.read_meta(ch1)["last_error"]


def test_rejected_retranslation_keeps_previous_complete_translation(tmp_path, monkeypatch):
    storage, (ch1, _ch2) = _seed(tmp_path)
    _translate(tmp_path, monkeypatch, {1: [GOOD]}, selected_indexes=[1])
    revision = storage.read_branch_revision(ch1, "ai")

    _translate(tmp_path, monkeypatch, {1: [SHORT]}, selected_indexes=[1], force=True)

    assert storage.read_translated(ch1) == GOOD
    assert storage.has_translated(ch1) is True
    assert storage.read_branch_revision(ch1, "ai") == revision
    assert storage.load_manifest().chapters[0].last_action_status == "failed"


def test_guard_failure_on_first_chapter_does_not_stop_batch(tmp_path, monkeypatch):
    """Guard từ chối là lỗi nội dung của riêng chương đó, không phải lỗi cấu
    hình — batch tuần tự vẫn dịch tiếp chương sau."""
    storage, (ch1, ch2) = _seed(tmp_path)

    logs = _translate(tmp_path, monkeypatch, {1: [SHORT], 2: [GOOD]})

    assert storage.has_translated(ch1) is False
    assert storage.read_translated(ch2) == GOOD
    assert any("Đã dịch 1 chương" in line and "lỗi 1" in line for line in logs)


def test_lower_bound_skipped_for_english_source(tmp_path, monkeypatch):
    storage, (ch1, _ch2) = _seed(tmp_path, raw="He walked into the room and said nothing at all.")

    _translate(
        tmp_path, monkeypatch, {1: ["Hắn vào phòng, im lặng."]},
        cfg=_cfg(tmp_path, source_language="en"), selected_indexes=[1],
    )

    assert storage.read_translated(ch1) == "Hắn vào phòng, im lặng."
    assert storage.has_translated(ch1) is True
