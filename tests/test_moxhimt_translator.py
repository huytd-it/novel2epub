"""Test backend dịch cục bộ MoxhiMT (translate.type=moxhimt).

Không tải model thật: inject module giả `ctranslate2`/`sentencepiece`/
`huggingface_hub` vào sys.modules + tạo thư mục model giả (model.bin + *.spm) để
kiểm tra logic chia chunk, glossary, on_chunk, và các đường lỗi.
"""
from __future__ import annotations

import sys
import types

import pytest

from novel2epub.config import MoxhiMTConfig, TranslateConfig
from novel2epub.translator import (
    MoxhiMTTranslator,
    _hard_split,
    _split_into_sentences,
    make_translator,
)


# --- module giả ---


class _FakeSP:
    def __init__(self, model_file=None):
        self.model_file = model_file

    def encode(self, text, out_type=str):
        # 1 token / ký tự — đủ để logic ngân sách token hoạt động xác định.
        return list(text)

    def decode(self, tokens):
        return "".join(tokens)


class _FakeResult:
    def __init__(self, hyp):
        self.hypotheses = [hyp]


class _FakeCT2Translator:
    # Ghi lại kích thước mỗi batch để test khẳng định cách chia chunk.
    batch_calls: list[int] = []

    def __init__(self, path, device="cpu", inter_threads=1, intra_threads=1):
        self.path = path
        self.device = device
        self.inter_threads = inter_threads
        self.intra_threads = intra_threads

    def translate_batch(self, batch, beam_size=1, max_decoding_length=512):
        _FakeCT2Translator.batch_calls.append(len(batch))
        # Echo: trả lại đúng token nguồn (decode → text gốc) để dễ assert.
        return [_FakeResult(list(toks)) for toks in batch]


@pytest.fixture
def fake_model_env(tmp_path, monkeypatch):
    """Inject module giả + thư mục model giả; trả factory tạo translator."""
    _FakeCT2Translator.batch_calls = []

    fake_ct2 = types.ModuleType("ctranslate2")
    fake_ct2.Translator = _FakeCT2Translator
    fake_spm = types.ModuleType("sentencepiece")
    fake_spm.SentencePieceProcessor = _FakeSP
    fake_hub = types.ModuleType("huggingface_hub")

    # Thư mục model giả: ưu tiên ct2-int8/model.bin + tokenizer.model.
    ct2_dir = tmp_path / "model" / "ct2-int8"
    ct2_dir.mkdir(parents=True)
    (ct2_dir / "model.bin").write_bytes(b"\x00")
    (tmp_path / "model" / "tokenizer.model").write_bytes(b"\x00")
    fake_hub.snapshot_download = lambda model_id, cache_dir=None: str(tmp_path / "model")

    monkeypatch.setitem(sys.modules, "ctranslate2", fake_ct2)
    monkeypatch.setitem(sys.modules, "sentencepiece", fake_spm)
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)

    def _make(**mox_kwargs):
        cfg = TranslateConfig(type="moxhimt", moxhimt=MoxhiMTConfig(**mox_kwargs))
        return MoxhiMTTranslator(cfg)

    return _make


# --- helper thuần (không cần model) ---


def test_split_into_sentences_basic():
    assert _split_into_sentences("第一句。第二句！第三句？") == ["第一句。", "第二句！", "第三句？"]
    # ký tự đuôi không có dấu kết câu vẫn thành 1 phần
    assert _split_into_sentences("không dấu cuối") == ["không dấu cuối"]
    # dòng trắng → rỗng
    assert _split_into_sentences("   ") == []


def test_hard_split_chunks_by_chars():
    assert _hard_split("abcdefg", 3) == ["abc", "def", "g"]
    assert _hard_split("ab", 10) == ["ab"]


# --- make_translator ---


def test_make_translator_returns_moxhimt(fake_model_env):
    t = make_translator(TranslateConfig(type="moxhimt"))
    assert isinstance(t, MoxhiMTTranslator)


def test_make_translator_invalid_type_raises():
    with pytest.raises(ValueError, match="moxhimt"):
        make_translator(TranslateConfig(type="khong-hop-le"))


# --- chunking & dịch (model giả) ---


def test_paragraph_mode_short_line_single_call(fake_model_env):
    t = fake_model_env()  # mặc định paragraph, max_length=512
    calls: list[tuple] = []
    out = t.translate("第一句。第二句。", on_chunk=lambda i, n, txt, f: calls.append((i, n, f)))
    assert out == "第一句。第二句。"  # echo, cả đoạn 1 lượt
    assert calls == [(1, 1, True)]
    # 1 dòng → đúng 1 batch, batch chứa nguyên cả đoạn (1 segment)
    assert _FakeCT2Translator.batch_calls == [1]


def test_multiline_calls_on_chunk_per_line(fake_model_env):
    t = fake_model_env()
    calls: list[tuple] = []
    out = t.translate("dòng A\ndòng B\ndòng C", on_chunk=lambda i, n, txt, f: calls.append((i, n, f)))
    assert out == "dòng A\ndòng B\ndòng C"
    assert [c[0] for c in calls] == [1, 2, 3]
    assert all(c[1] == 3 for c in calls)
    assert [c[2] for c in calls] == [False, False, True]


def test_blank_lines_preserved(fake_model_env):
    t = fake_model_env()
    out = t.translate("a\n\nb")
    assert out == "a\n\nb"


def test_multiline_translates_in_one_batch_call(fake_model_env):
    # 3 dòng vừa token -> gom CẢ 3 vào 1 lần gọi translate_batch (batch=3),
    # không gọi translate_batch riêng cho mỗi dòng.
    t = fake_model_env()
    t.translate("dòng A\ndòng B\ndòng C")
    assert _FakeCT2Translator.batch_calls == [3]


def test_batched_result_equals_sequential_result(fake_model_env):
    t = fake_model_env(max_length=48)
    text = "AAAA。BBBB。\nCCCC。DDDD。EEEE。"
    batched = t.translate(text)
    sequential = "\n".join(t._translate_line(line) if line.strip() else line for line in text.split("\n"))
    assert batched == sequential


def test_resolved_threads_respects_core_count(monkeypatch):
    monkeypatch.setattr("os.cpu_count", lambda: 8)
    cfg = MoxhiMTConfig()
    inter, intra = cfg.resolved_threads()
    assert inter * intra <= 8
    assert inter >= 1 and intra >= 1


def test_resolved_threads_uses_explicit_override(monkeypatch):
    monkeypatch.setattr("os.cpu_count", lambda: 8)
    cfg = MoxhiMTConfig(inter_threads=4, intra_threads=4)
    assert cfg.resolved_threads() == (4, 4)


def test_ct2_translator_receives_resolved_threads(fake_model_env, monkeypatch):
    monkeypatch.setattr("os.cpu_count", lambda: 8)
    t = fake_model_env(inter_threads=2, intra_threads=2)
    t.translate("第一句。")
    assert t._ct2.inter_threads == 2
    assert t._ct2.intra_threads == 2


def test_long_paragraph_falls_back_to_sentences(fake_model_env):
    # max_length=48 → budget = 48-32 = 16. Đoạn 20 ký tự > 16 → chia câu.
    t = fake_model_env(max_length=48)
    out = t.translate("AAAA。BBBB。CCCC。DDDD。")
    # 4 câu mỗi cái 5 ký tự (<=16) → 1 batch 4 segment, nối bằng khoảng trắng
    assert _FakeCT2Translator.batch_calls == [4]
    assert out == "AAAA。 BBBB。 CCCC。 DDDD。"


def test_oversized_sentence_hard_split(fake_model_env):
    # budget 16; 1 câu 20 ký tự không dấu kết → cắt cứng theo ký tự (16 + 4)
    t = fake_model_env(max_length=48)
    t.translate("X" * 20)
    assert _FakeCT2Translator.batch_calls == [2]


def test_sentence_mode_splits_immediately(fake_model_env):
    # chunk_mode=sentence: chia câu ngay cả khi đoạn vừa token
    t = fake_model_env(chunk_mode="sentence")
    t.translate("第一句。第二句。")
    assert _FakeCT2Translator.batch_calls == [2]


def test_glossary_applied_after_translate(fake_model_env, monkeypatch):
    cfg = TranslateConfig(type="moxhimt", moxhimt=MoxhiMTConfig(), glossary={"猫": "Miêu"})
    t = MoxhiMTTranslator(cfg)
    out = t.translate("黑猫")  # echo "黑猫" → glossary thay 猫 → Miêu
    assert out == "黑Miêu"


def test_translate_title_returns_empty_note(fake_model_env):
    t = fake_model_env()
    title, note = t.translate_title("第一章 标题", kind="tên chương")
    assert title == "第一章 标题"
    assert note == ""


def test_translate_empty_text_short_circuits(fake_model_env):
    t = fake_model_env()
    seen: list[bool] = []
    assert t.translate("   ", on_chunk=lambda i, n, txt, f: seen.append(f)) == "   "
    assert seen == [True]
    # không gọi model cho text rỗng
    assert _FakeCT2Translator.batch_calls == []


# --- đường lỗi ---


def test_missing_ctranslate2_raises_importerror(monkeypatch):
    def _boom():
        raise ImportError("Chưa cài ctranslate2 (cần cho translate.type=moxhimt).")

    monkeypatch.setattr(MoxhiMTTranslator, "_import_ct2", staticmethod(_boom))
    with pytest.raises(ImportError, match="ctranslate2"):
        MoxhiMTTranslator(TranslateConfig(type="moxhimt"))


def test_download_failure_raises_runtimeerror(tmp_path, monkeypatch):
    fake_ct2 = types.ModuleType("ctranslate2")
    fake_ct2.Translator = _FakeCT2Translator
    fake_spm = types.ModuleType("sentencepiece")
    fake_spm.SentencePieceProcessor = _FakeSP
    fake_hub = types.ModuleType("huggingface_hub")

    def _boom(model_id, cache_dir=None):
        raise OSError("network down")

    fake_hub.snapshot_download = _boom
    monkeypatch.setitem(sys.modules, "ctranslate2", fake_ct2)
    monkeypatch.setitem(sys.modules, "sentencepiece", fake_spm)
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)

    t = MoxhiMTTranslator(TranslateConfig(type="moxhimt"))
    with pytest.raises(RuntimeError, match="Hugging Face Hub"):
        t.translate("bất kỳ")


def test_separate_source_target_spm_detected(tmp_path, monkeypatch):
    """Model layout source.spm + target.spm → _locate_model_files trả đúng cặp."""
    fake_ct2 = types.ModuleType("ctranslate2")
    fake_ct2.Translator = _FakeCT2Translator
    fake_spm = types.ModuleType("sentencepiece")
    fake_spm.SentencePieceProcessor = _FakeSP
    fake_hub = types.ModuleType("huggingface_hub")

    model_root = tmp_path / "hachimi"
    ct2_dir = model_root / "ct2-int8_float32"
    ct2_dir.mkdir(parents=True)
    (ct2_dir / "model.bin").write_bytes(b"\x00")
    (model_root / "source.spm").write_bytes(b"\x00")
    (model_root / "target.spm").write_bytes(b"\x00")
    fake_hub.snapshot_download = lambda model_id, cache_dir=None: str(model_root)

    monkeypatch.setitem(sys.modules, "ctranslate2", fake_ct2)
    monkeypatch.setitem(sys.modules, "sentencepiece", fake_spm)
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)

    t = MoxhiMTTranslator(TranslateConfig(type="moxhimt"))
    t.translate("dịch thử")

    assert t._sp_src is not None
    assert t._sp_tgt is not None
    assert t._sp_src.model_file.endswith("source.spm")
    assert t._sp_tgt.model_file.endswith("target.spm")


def test_shared_spm_when_no_source_target(tmp_path, monkeypatch):
    """Model layout chỉ có 1 file .model → _sp_src và _sp_tgt giống nhau."""
    fake_ct2 = types.ModuleType("ctranslate2")
    fake_ct2.Translator = _FakeCT2Translator
    fake_spm = types.ModuleType("sentencepiece")
    fake_spm.SentencePieceProcessor = _FakeSP
    fake_hub = types.ModuleType("huggingface_hub")

    model_root = tmp_path / "moxhi"
    ct2_dir = model_root / "ct2-int8"
    ct2_dir.mkdir(parents=True)
    (ct2_dir / "model.bin").write_bytes(b"\x00")
    (model_root / "tokenizer.model").write_bytes(b"\x00")
    fake_hub.snapshot_download = lambda model_id, cache_dir=None: str(model_root)

    monkeypatch.setitem(sys.modules, "ctranslate2", fake_ct2)
    monkeypatch.setitem(sys.modules, "sentencepiece", fake_spm)
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)

    t = MoxhiMTTranslator(TranslateConfig(type="moxhimt"))
    t.translate("dịch thử")

    assert t._sp_src is not None
    assert t._sp_tgt is t._sp_src  # shared — cùng object


def test_model_without_ct2_format_raises(tmp_path, monkeypatch):
    """model_id trỏ tới repo không có model.bin (vd LoRA) → RuntimeError rõ ràng."""
    fake_ct2 = types.ModuleType("ctranslate2")
    fake_ct2.Translator = _FakeCT2Translator
    fake_spm = types.ModuleType("sentencepiece")
    fake_spm.SentencePieceProcessor = _FakeSP
    fake_hub = types.ModuleType("huggingface_hub")
    empty = tmp_path / "lora"
    empty.mkdir()
    (empty / "adapter_model.bin.txt").write_text("not a ct2 model")  # không có model.bin
    fake_hub.snapshot_download = lambda model_id, cache_dir=None: str(empty)
    monkeypatch.setitem(sys.modules, "ctranslate2", fake_ct2)
    monkeypatch.setitem(sys.modules, "sentencepiece", fake_spm)
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)

    t = MoxhiMTTranslator(TranslateConfig(type="moxhimt"))
    with pytest.raises(RuntimeError, match="CTranslate2"):
        t.translate("bất kỳ")


def test_translate_titles_batch_all_non_empty(fake_model_env):
    t = fake_model_env()
    titles = ["第一章 龙王出世", "第二章 凤舞九天", "第三章 剑指苍穹"]
    out = t.translate_titles(titles)
    assert len(out) == 3
    # echo: model giả trả lại token nguồn
    assert out == titles


def test_translate_titles_preserves_empty_entries(fake_model_env):
    t = fake_model_env()
    titles = ["第一章 龙王出世", "", "第三章 剑指苍穹"]
    out = t.translate_titles(titles)
    assert len(out) == 3
    assert out[1] == ""  # entry rỗng giữ nguyên


def test_translate_titles_empty_list(fake_model_env):
    t = fake_model_env()
    out = t.translate_titles([])
    assert out == []


def test_translate_titles_single_batch_call(fake_model_env):
    _FakeCT2Translator.batch_calls = []
    t = fake_model_env()
    t.translate_titles(["A", "B", "C"])
    # 3 titles → 1 batch call với batch size = 3
    assert _FakeCT2Translator.batch_calls == [3]


def test_translate_titles_all_empty_returns_original(fake_model_env):
    t = fake_model_env()
    out = t.translate_titles(["", "  "])
    assert list(out) == ["", "  "]
