"""Test callback on_chunk của OpenAITranslator (xem spec translate-chunk-streaming)."""
from __future__ import annotations

import pytest

from novel2epub.config import OpenAIConfig, TranslationChunkConfig, TranslateConfig
from novel2epub.translator import make_translator


def _openai_cfg(
    *,
    max_chars: int = 6000,
    overlap: int = 0,
) -> TranslateConfig:
    return TranslateConfig(
        type="openai",
        openai=OpenAIConfig(
            base_url="https://api.test/v1",
            prompt_template="{text}",
            title_prompt_template="{text}",
        ),
        chunk=TranslationChunkConfig(max_chars=max_chars, overlap_paragraphs=overlap),
    )


def test_on_chunk_called_once_for_short_text(monkeypatch):
    monkeypatch.setattr(
        "novel2epub.translator.openai_client.run_chat_with_meta",
        lambda cfg, prompt: "Xin chào thế giới",
    )
    translator = make_translator(_openai_cfg())
    calls: list[tuple[int, int, str, bool]] = []

    def _cb(index, total, text, is_final):
        calls.append((index, total, text, is_final))

    out = translator.translate("Xin chào", on_chunk=_cb)
    assert out == "Xin chào thế giới"
    assert calls == [(1, 1, "Xin chào thế giới", True)]


def test_on_chunk_called_per_chunk_in_order(monkeypatch):
    # 3 paragraphs, mỗi cái dài hơn max_chars để mỗi cái nằm trong 1 chunk riêng.
    text = "đoạn dài AAAAAAAAAA\nđoạn dài BBBBBBBBBB\nđoạn dài CCCCCCCCCC"
    cfg = _openai_cfg(max_chars=10, overlap=0)

    responses = iter(["kết quả A", "kết quả B", "kết quả C"])

    def _mock_run_chat(cfg_, prompt):
        return next(responses)

    monkeypatch.setattr("novel2epub.translator.openai_client.run_chat_with_meta", _mock_run_chat)
    translator = make_translator(cfg)

    calls: list[tuple[int, int, str, bool]] = []

    def _cb(index, total, text, is_final):
        calls.append((index, total, text, is_final))

    out = translator.translate(text, on_chunk=_cb)
    # Callback phải được gọi đúng 3 lần, đúng thứ tự, is_final chỉ True ở cuối.
    assert len(calls) == 3
    assert [c[0] for c in calls] == [1, 2, 3]
    assert all(c[1] == 3 for c in calls)
    assert [c[2] for c in calls] == ["kết quả A", "kết quả B", "kết quả C"]
    assert [c[3] for c in calls] == [False, False, True]
    # Return value là concatenate các chunk bằng \n (giống cũ).
    assert out == "kết quả A\nkết quả B\nkết quả C"


def test_on_chunk_can_be_omitted(monkeypatch):
    """Backward compat: gọi không truyền on_chunk vẫn hoạt động như cũ."""
    monkeypatch.setattr(
        "novel2epub.translator.openai_client.run_chat_with_meta",
        lambda cfg, prompt: "Xin chào",
    )
    translator = make_translator(_openai_cfg())
    assert translator.translate("hi") == "Xin chào"


def test_callback_exception_propagates_and_aborts(monkeypatch):
    """Nếu callback raise, translator phải propagate và KHÔNG tiếp tục chunk sau."""
    responses = iter(["kết quả A", "kết quả B", "kết quả C"])

    def _mock_run_chat(cfg_, prompt):
        return next(responses)

    monkeypatch.setattr("novel2epub.translator.openai_client.run_chat_with_meta", _mock_run_chat)
    cfg = _openai_cfg(max_chars=10, overlap=0)
    translator = make_translator(cfg)

    def _cb(index, total, text, is_final):
        if index == 2:
            raise RuntimeError("user code error")

    with pytest.raises(RuntimeError, match="user code error"):
        translator.translate("paragraphAAAAA\nparagraphBBBBB\nparagraphCCCCC", on_chunk=_cb)
    # responses iter chỉ nên đã yield 2 phần tử (chunk 1 thành công, chunk 2 đang raise).
    # Phần tử thứ 3 chưa được yield → iterator vẫn còn 1 phần tử.
    assert next(responses) == "kết quả C"


def test_callback_for_short_text_called_with_is_final_true(monkeypatch):
    """Văn bản ngắn (1 chunk) vẫn phải gọi callback với is_final=True."""
    monkeypatch.setattr(
        "novel2epub.translator.openai_client.run_chat_with_meta",
        lambda cfg, prompt: "OK",
    )
    cfg = _openai_cfg(max_chars=6000)
    translator = make_translator(cfg)
    seen: list[bool] = []
    translator.translate("ngắn", on_chunk=lambda i, t, c, f: seen.append(f))
    assert seen == [True]


def test_prompt_max_chars_shrinks_chunk_budget(monkeypatch):
    """Tổng prompt (template + glossary + nội dung) phải <= prompt_max_chars —
    chunk budget bị thu nhỏ theo overhead của template."""
    # Template có 100 ký tự overhead cố định (không kể {text}).
    template = ("H" * 100) + "{text}"
    cfg = TranslateConfig(
        type="openai",
        prompt_max_chars=350,
        auto_glossary=False,
        openai=OpenAIConfig(
            base_url="https://api.test/v1",
            prompt_template=template,
            title_prompt_template="{text}",
        ),
        # chunk.max_chars=0 → DEFAULT_MAX_CHARS (6000), phải bị clamp còn 250.
        chunk=TranslationChunkConfig(max_chars=0, overlap_paragraphs=0),
    )
    prompts: list[str] = []

    def _mock_run_chat(cfg_, prompt):
        prompts.append(prompt)
        return "ok"

    monkeypatch.setattr("novel2epub.translator.openai_client.run_chat_with_meta", _mock_run_chat)
    translator = make_translator(cfg)
    # 3 đoạn 150 ký tự: budget còn 350-100=250 → mỗi chunk chỉ chứa 1 đoạn.
    text = "\n".join(["A" * 150, "B" * 150, "C" * 150])
    translator.translate(text)

    assert len(prompts) == 3
    for p in prompts:
        assert len(p) <= 350


def test_prompt_max_chars_zero_disables_limit(monkeypatch):
    """prompt_max_chars=0 → không giới hạn, giữ nguyên hành vi chunk cũ."""
    template = ("H" * 100) + "{text}"
    cfg = TranslateConfig(
        type="openai",
        prompt_max_chars=0,
        openai=OpenAIConfig(
            base_url="https://api.test/v1",
            prompt_template=template,
            title_prompt_template="{text}",
        ),
        chunk=TranslationChunkConfig(max_chars=6000, overlap_paragraphs=0),
    )
    prompts: list[str] = []

    def _mock_run_chat(cfg_, prompt):
        prompts.append(prompt)
        return "ok"

    monkeypatch.setattr("novel2epub.translator.openai_client.run_chat_with_meta", _mock_run_chat)
    translator = make_translator(cfg)
    translator.translate("\n".join(["A" * 40, "B" * 40, "C" * 40]))
    assert len(prompts) == 1  # cả 3 đoạn trong 1 chunk


def test_prompt_max_chars_floor_when_overhead_too_big(monkeypatch):
    """Overhead vượt cả budget → dùng sàn MIN_CHUNK_BUDGET, không chia vô hạn."""
    from novel2epub.translator import OpenAITranslator

    template = ("H" * 500) + "{text}"
    cfg = TranslateConfig(
        type="openai",
        prompt_max_chars=400,  # nhỏ hơn cả overhead 500
        openai=OpenAIConfig(
            base_url="https://api.test/v1",
            prompt_template=template,
            title_prompt_template="{text}",
        ),
        chunk=TranslationChunkConfig(max_chars=0, overlap_paragraphs=0),
    )
    monkeypatch.setattr(
        "novel2epub.translator.openai_client.run_chat_with_meta",
        lambda cfg_, prompt: "ok",
    )
    translator = make_translator(cfg)
    out = translator.translate("A" * 300)
    assert out  # không treo/chia vô hạn
    assert translator._clamp_to_prompt_budget(6000, "A" * 300) == OpenAITranslator.MIN_CHUNK_BUDGET


def test_translate_multichunk_filters_glossary_per_chunk(tmp_path, monkeypatch):
    """Mỗi chunk chỉ nhận các mục glossary SQLite xuất hiện trong chính chunk đó."""
    from novel2epub.storage import Storage

    storage = Storage(tmp_path, "t")
    storage.upsert_glossary_entry("叶凡", "Diệp Phàm")
    storage.upsert_glossary_entry("庄国", "Trang Quốc")
    cfg = TranslateConfig(
        type="openai",
        glossary_filter=True,
        openai=OpenAIConfig(
            base_url="https://api.test/v1",
            prompt_template="{glossary}\n---\n{text}",
            title_prompt_template="{text}",
        ),
        chunk=TranslationChunkConfig(max_chars=10, overlap_paragraphs=0),
    )
    prompts: list[str] = []
    responses = iter(["kết quả A", "kết quả B"])

    def _mock_run_chat(cfg_, prompt):
        prompts.append(prompt)
        return next(responses)

    monkeypatch.setattr("novel2epub.translator.openai_client.run_chat_with_meta", _mock_run_chat)
    translator = make_translator(cfg, storage=storage)
    # 2 đoạn, mỗi đoạn dài hơn max_chars → 2 chunk riêng.
    out = translator.translate("叶凡AAAAAAAAAA\n庄国BBBBBBBBBB")

    assert out == "kết quả A\nkết quả B"
    assert len(prompts) == 2
    assert "叶凡 = Diệp Phàm" in prompts[0]
    assert "庄国" not in prompts[0]
    assert "庄国 = Trang Quốc" in prompts[1]
    assert "叶凡" not in prompts[1]
