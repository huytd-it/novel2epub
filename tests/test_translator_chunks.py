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
        "novel2epub.translator.openai_client.run_chat",
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

    monkeypatch.setattr("novel2epub.translator.openai_client.run_chat", _mock_run_chat)
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
        "novel2epub.translator.openai_client.run_chat",
        lambda cfg, prompt: "Xin chào",
    )
    translator = make_translator(_openai_cfg())
    assert translator.translate("hi") == "Xin chào"


def test_callback_exception_propagates_and_aborts(monkeypatch):
    """Nếu callback raise, translator phải propagate và KHÔNG tiếp tục chunk sau."""
    responses = iter(["kết quả A", "kết quả B", "kết quả C"])

    def _mock_run_chat(cfg_, prompt):
        return next(responses)

    monkeypatch.setattr("novel2epub.translator.openai_client.run_chat", _mock_run_chat)
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
        "novel2epub.translator.openai_client.run_chat",
        lambda cfg, prompt: "OK",
    )
    cfg = _openai_cfg(max_chars=6000)
    translator = make_translator(cfg)
    seen: list[bool] = []
    translator.translate("ngắn", on_chunk=lambda i, t, c, f: seen.append(f))
    assert seen == [True]
