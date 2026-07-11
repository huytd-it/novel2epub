"""Test dịch tiêu đề TOC (step_translate_toc_selected / step_retranslate_title):
phải luôn dịch từ title_zh (tiêu đề gốc chữ Hán) khi đã có, KHÔNG dùng title
hiện tại (có thể đã là bản dịch tiếng Việt của lần dịch trước)."""
from __future__ import annotations

from novel2epub import pipeline
from novel2epub.config import Config, CrawlConfig, NovelConfig, OutputConfig, TranslateConfig
from novel2epub.storage import Chapter, Manifest, Storage


def _cfg(tmp_path):
    return Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/book/", delay_seconds=0),
        translate=TranslateConfig(type="cli", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


class _FakeTitleTranslator:
    """Ghi lại chính xác text nào được gửi để dịch (batch + single)."""

    def __init__(self):
        self.batch_calls: list[list[str]] = []
        self.single_calls: list[str] = []

    def translate_titles(self, titles):
        self.batch_calls.append(list(titles))
        return [f"VI:{t}" for t in titles]

    def translate_title(self, text, kind="tên chương"):
        self.single_calls.append(text)
        return f"VI:{text}", ""

    def translate(self, text, **_kw):
        self.single_calls.append(text)
        return f"VI:{text}"


def _seed(tmp_path, chapters):
    storage = Storage(tmp_path, "t")
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    return storage


def test_toc_first_time_translates_from_title_and_backfills_title_zh(tmp_path, monkeypatch):
    tr = _FakeTitleTranslator()
    monkeypatch.setattr(pipeline, "make_translator", lambda c, log=None, **kw: tr)

    ch = Chapter(index=1, url="http://x/1", title="第一章")
    storage = _seed(tmp_path, [ch])

    cfg = _cfg(tmp_path)
    pipeline.step_translate_toc_selected(cfg, lambda m: None, selected_indexes=[1])

    # Dịch đúng từ title ZH gốc (chưa từng dịch, title_zh còn rỗng).
    assert tr.batch_calls == [["第一章"]]
    ch2 = storage.load_manifest().chapters[0]
    assert ch2.title_zh == "第一章"
    assert ch2.title == "VI:第一章"


def test_toc_skips_already_translated_without_force(tmp_path, monkeypatch):
    """Chương đã có title_zh (đã dịch tiêu đề trước đó) → KHÔNG gửi lại AI khi
    không bật force."""
    tr = _FakeTitleTranslator()
    monkeypatch.setattr(pipeline, "make_translator", lambda c, log=None, **kw: tr)

    ch = Chapter(index=1, url="http://x/1", title="Chương 1: Tiêu đề cũ VI", title_zh="第一章")
    storage = _seed(tmp_path, [ch])

    cfg = _cfg(tmp_path)
    pipeline.step_translate_toc_selected(cfg, lambda m: None, selected_indexes=[1])

    assert tr.batch_calls == []
    ch2 = storage.load_manifest().chapters[0]
    assert ch2.title == "Chương 1: Tiêu đề cũ VI"
    assert ch2.title_zh == "第一章"


def test_toc_force_retranslates_from_title_zh_not_current_title(tmp_path, monkeypatch):
    """force=True dịch lại — phải lấy nguồn từ title_zh (ZH gốc), KHÔNG phải
    title hiện tại (đã là tiếng Việt), và title_zh không bị đụng vào."""
    tr = _FakeTitleTranslator()
    monkeypatch.setattr(pipeline, "make_translator", lambda c, log=None, **kw: tr)

    ch = Chapter(index=1, url="http://x/1", title="Chương 1: Tiêu đề cũ VI", title_zh="第一章")
    storage = _seed(tmp_path, [ch])

    cfg = _cfg(tmp_path)
    pipeline.step_translate_toc_selected(
        cfg, lambda m: None, selected_indexes=[1], force=True
    )

    # Nguồn gửi AI phải là title_zh (第一章), không phải "Chương 1: Tiêu đề cũ VI".
    assert tr.batch_calls == [["第一章"]]
    ch2 = storage.load_manifest().chapters[0]
    assert ch2.title == "VI:第一章"
    assert ch2.title_zh == "第一章"  # giữ nguyên, không bị ghi đè bởi title cũ


def test_retranslate_title_uses_title_zh_when_already_translated(tmp_path, monkeypatch):
    """step_retranslate_title (nút 'Dịch lại tiêu đề') phải dịch từ title_zh,
    không phải title hiện tại (tiếng Việt) khi chương đã dịch tiêu đề rồi."""
    from novel2epub import translator as translator_module

    tr = _FakeTitleTranslator()
    # step_retranslate_title import make_translator cục bộ từ novel2epub.translator
    # (không qua pipeline.make_translator) — phải patch đúng module đó.
    monkeypatch.setattr(translator_module, "make_translator", lambda c, log=None, **kw: tr)

    ch = Chapter(index=1, url="http://x/1", title="Chương 1: Tiêu đề cũ VI", title_zh="第一章")
    storage = _seed(tmp_path, [ch])
    storage.write_translated(ch, "Nội dung đã dịch.")

    cfg = _cfg(tmp_path)
    cfg.translate.type = "hachimimt"
    result = pipeline.step_retranslate_title(
        cfg, lambda m: None, slug="t", index=1, engine="hachimimt", generate_description=False
    )

    # translate() được gọi với prompt literal chứa title_zh ("第一章"), không
    # phải title hiện tại ("Chương 1: Tiêu đề cũ VI").
    assert len(tr.single_calls) == 1
    assert "第一章" in tr.single_calls[0]
    assert "Chương 1: Tiêu đề cũ VI" not in tr.single_calls[0]

    ch2 = storage.load_manifest().chapters[0]
    assert ch2.title_zh == "第一章"  # không bị đụng vào
    assert result["title"] == ch2.title
