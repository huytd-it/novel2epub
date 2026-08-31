"""Test dịch tiêu đề chương CHUNG với content trong 1 lời gọi AI.

Tiêu đề ZH (`title_zh or title`) được prepend làm dòng đầu của text gửi
translator; dòng đầu output được tách ra làm `ch.title` (số chương thật
re-prefix từ bản ZH qua `ensure_title_number`), phần thân ghi vào
`translated/` + `translated_mt/` (body-only). Xem `pipeline._translate_one`.
"""
from __future__ import annotations

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


def _cfg(tmp_path, translate_type="openai"):
    return Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/book/1/", delay_seconds=0),
        translate=TranslateConfig(
            type=translate_type,
            delay_seconds=0,
            openai=OpenAIConfig(
                base_url="https://api.test/v1",
                prompt_template="{text}",
                title_prompt_template="{text}",
            ),
        ),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


def _seed(tmp_path, *, title="第12章 起风", title_zh="", raw="正文第一段。\n\n正文第二段。"):
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=1, url="http://x/1", title=title, title_zh=title_zh)
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    storage.write_raw(ch, raw)
    return storage, ch


class _FakeTranslator:
    """Ghi lại text được gửi, trả output cố định qua on_chunk 1 lần."""

    def __init__(self, output):
        self.output = output
        self.seen: list[str] = []

    def translate(self, text, *, chapter_idx=None, on_chunk=None, on_glossary=None):
        self.seen.append(text)
        if on_chunk is not None:
            on_chunk(1, 1, self.output, True)
        return self.output

    def translate_title(self, text, kind="tên chương"):
        return f"MT:{text}", ""


def _run(tmp_path, monkeypatch, translator, *, force=False, translate_type="openai"):
    cfg = _cfg(tmp_path, translate_type)
    monkeypatch.setattr(pipeline, "make_translator", lambda c, log=None, **kw: translator)
    pipeline.step_translate_selected(cfg, lambda m: None, selected_indexes=[1], force=force)


def _reload_chapter(storage):
    return storage.load_manifest().chapters[0]


def test_title_sent_with_content_and_extracted(tmp_path, monkeypatch):
    storage, ch = _seed(tmp_path)
    tr = _FakeTranslator("Chương 99: Gió Nổi\nNội dung dịch.")

    _run(tmp_path, monkeypatch, tr)

    # Tiêu đề ZH prepend làm dòng đầu, cách thân 1 dòng trống.
    assert tr.seen[0].startswith("第12章 起风\n\n")
    ch = _reload_chapter(storage)
    # Số chương THẬT (12, từ 第12章) được gắn lại thay số AI echo nhầm (99).
    assert ch.title == "Chương 12: Gió Nổi"
    assert ch.title_zh == "第12章 起风"  # backfill 1 lần
    # File dịch + snapshot MT chỉ còn thân, không còn dòng tiêu đề.
    assert storage.read_translated(ch) == "Nội dung dịch."
    assert storage.read_translated_mt(ch) == "Nội dung dịch."


def test_retranslate_uses_title_zh_not_current_vi_title(tmp_path, monkeypatch):
    storage, ch = _seed(tmp_path, title="Chương 1: Cũ VI", title_zh="第1章")
    storage.write_translated(ch, "bản cũ")
    tr = _FakeTranslator("Chương 1: Mới VI\nThân mới.")

    _run(tmp_path, monkeypatch, tr, force=True)

    assert tr.seen[0].startswith("第1章\n\n")
    assert "Cũ VI" not in tr.seen[0]
    ch = _reload_chapter(storage)
    assert ch.title == "Chương 1: Mới VI"
    assert ch.title_zh == "第1章"  # không bị ghi đè


def test_first_line_too_long_keeps_title_and_full_body(tmp_path, monkeypatch):
    storage, ch = _seed(tmp_path)
    long_line = "câu văn xuôi rất dài " * 10  # > _MAX_TITLE_LINE ký tự
    tr = _FakeTranslator(f"{long_line}\nphần sau.")

    _run(tmp_path, monkeypatch, tr)

    ch = _reload_chapter(storage)
    assert ch.title == "第12章 起风"  # giữ nguyên
    assert storage.read_translated(ch) == f"{long_line}\nphần sau."


def test_single_line_output_keeps_title(tmp_path, monkeypatch):
    """Model gộp hết thành 1 dòng → không tách (mất thân nếu tách)."""
    storage, ch = _seed(tmp_path)
    tr = _FakeTranslator("Chỉ có đúng một dòng dịch.")

    _run(tmp_path, monkeypatch, tr)

    ch = _reload_chapter(storage)
    assert ch.title == "第12章 起风"
    assert storage.read_translated(ch) == "Chỉ có đúng một dòng dịch."


def test_no_title_no_prepend(tmp_path, monkeypatch):
    storage, ch = _seed(tmp_path, title="")
    tr = _FakeTranslator("Bản dịch.")

    _run(tmp_path, monkeypatch, tr)

    assert tr.seen[0] == "正文第一段。\n\n正文第二段。"  # nguyên raw, không prepend


def test_streamed_title_chunk_rewritten_to_body_only(tmp_path, monkeypatch):
    """Tiêu đề nằm trong chunk 1/3 đã stream vào file — file cuối phải được
    ghi đè lại body-only sau khi tách tiêu đề."""
    storage, ch = _seed(tmp_path)

    class _ThreeChunk:
        def __init__(self):
            self.seen = []

        def translate(self, text, *, chapter_idx=None, on_chunk=None, on_glossary=None):
            self.seen.append(text)
            parts = ["Chương 12: Gió Nổi\nĐoạn 1.", "Đoạn 2.", "Đoạn 3."]
            for i, p in enumerate(parts, 1):
                on_chunk(i, len(parts), p, i == len(parts))
            return "\n".join(parts)

    _run(tmp_path, monkeypatch, _ThreeChunk())

    ch = _reload_chapter(storage)
    assert ch.title == "Chương 12: Gió Nổi"
    assert storage.read_translated(ch) == "Đoạn 1.\nĐoạn 2.\nĐoạn 3."
    assert storage.read_translated_mt(ch) == "Đoạn 1.\nĐoạn 2.\nĐoạn 3."


def test_local_mt_translates_title_separately_from_body(tmp_path, monkeypatch):
    storage, _ch = _seed(tmp_path)
    tr = _FakeTranslator("Nội dung dịch Local MT.")

    cfg = _cfg(tmp_path, "localmt")
    monkeypatch.setattr(pipeline, "make_translator", lambda c, log=None, **kw: tr)
    pipeline.step_translate_selected(
        cfg, lambda m: None, selected_indexes=[1], branch="local_mt"
    )

    ch = _reload_chapter(storage)
    assert tr.seen == ["正文第一段。\n\n正文第二段。"]
    # `_translate_one` tự chuyển nhánh active sang `local_mt` sau khi dịch xong
    # (xem pipeline.py — nhánh hoàn tất trở thành bản đang đọc/biên tập).
    assert storage.active_branch(ch) == "local_mt"
    assert storage.read_branch_title(ch, "local_mt") == "Chương 12: MT:Chương 12 起风"
    assert storage.read_branch_title_zh(ch, "local_mt") == "第12章 起风"
    assert storage.read_branch_text(ch, "local_mt") == "Nội dung dịch Local MT."
    assert storage.read_branch_mt_snapshot(ch, "local_mt") == "Nội dung dịch Local MT."

    assert storage.read_active_branch_title(ch) == "Chương 12: MT:Chương 12 起风"
    storage.set_active_branch(ch, "ai")
    assert storage.read_active_branch_title(ch) == "第12章 起风"
