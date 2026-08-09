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


class _FakeSingleTitleMT:
    def __init__(self):
        self.calls = []

    def translate_title(self, text, kind="tên chương"):
        self.calls.append(text)
        return f"MT:{text}", ""


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
    assert ch2.title == "Chương 1: VI:第一章"


def test_toc_formats_numbered_title_with_name(tmp_path, monkeypatch):
    tr = _FakeTitleTranslator()
    tr.translate_titles = lambda titles: ["Tên chương"]
    monkeypatch.setattr(pipeline, "make_translator", lambda c, log=None, **kw: tr)

    storage = _seed(tmp_path, [Chapter(index=1, url="http://x/1", title="第12章 原名")])

    pipeline.step_translate_toc_selected(_cfg(tmp_path), lambda m: None, selected_indexes=[1])

    assert storage.load_manifest().chapters[0].title == "Chương 12: Tên chương"


def test_toc_formats_numbered_title_without_name(tmp_path, monkeypatch):
    tr = _FakeTitleTranslator()
    tr.translate_titles = lambda titles: ["Chương 12"]
    monkeypatch.setattr(pipeline, "make_translator", lambda c, log=None, **kw: tr)

    storage = _seed(tmp_path, [Chapter(index=1, url="http://x/1", title="第12章")])

    pipeline.step_translate_toc_selected(_cfg(tmp_path), lambda m: None, selected_indexes=[1])

    assert storage.load_manifest().chapters[0].title == "Chương 12"


def test_toc_removes_vote_request_suffix(tmp_path, monkeypatch):
    tr = _FakeTitleTranslator()
    tr.translate_titles = lambda titles: ["Tên chương (Cầu phiếu tháng!)"]
    monkeypatch.setattr(pipeline, "make_translator", lambda c, log=None, **kw: tr)

    storage = _seed(tmp_path, [Chapter(index=1, url="http://x/1", title="第12章 原名 求月票")])

    pipeline.step_translate_toc_selected(_cfg(tmp_path), lambda m: None, selected_indexes=[1])

    assert storage.load_manifest().chapters[0].title == "Chương 12: Tên chương"


def test_toc_mt_without_batch_translates_raw_titles_one_by_one(tmp_path, monkeypatch):
    tr = _FakeSingleTitleMT()
    monkeypatch.setattr(pipeline, "make_translator", lambda c, log=None, **kw: tr)
    storage = _seed(tmp_path, [
        Chapter(index=1, url="http://x/1", title="第一章 开始"),
        Chapter(index=2, url="http://x/2", title="第二章 继续"),
    ])

    pipeline.step_translate_toc_selected(_cfg(tmp_path), lambda m: None, selected_indexes=[1, 2])

    assert tr.calls == ["第一章 开始", "第二章 继续"]
    assert [ch.title for ch in storage.load_manifest().chapters] == [
        "Chương 1: MT:第一章 开始",
        "Chương 2: MT:第二章 继续",
    ]


def test_clean_title_removes_common_vote_suffixes_only_at_end():
    assert pipeline._clean_title("Tên chương - xin phiếu đề cử") == "Tên chương"
    assert pipeline._clean_title("Tên chương【Cầu vé tháng】") == "Tên chương"
    assert pipeline._clean_title("Lá phiếu định mệnh") == "Lá phiếu định mệnh"


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
    assert ch2.title == "Chương 1: VI:第一章"
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

    # Local MT phải nhận đúng chuỗi nguồn, không nhận prompt/instruction như LLM.
    assert len(tr.single_calls) == 1
    assert tr.single_calls[0] == "第一章"

    ch2 = storage.load_manifest().chapters[0]
    assert ch2.title_zh == "第一章"  # không bị đụng vào
    assert ch2.title == "Chương 1: VI:第一章"
    assert result["title"] == ch2.title


def test_retranslate_title_uses_selected_mt_backend_not_global_type(tmp_path, monkeypatch):
    from novel2epub import translator as translator_module

    tr = _FakeTitleTranslator()
    seen_types = []

    def fake_make_translator(cfg, log=None, **kw):
        seen_types.append(cfg.type)
        return tr

    monkeypatch.setattr(translator_module, "make_translator", fake_make_translator)
    ch = Chapter(index=1, url="http://x/1", title="Chương 1: Cũ", title_zh="第一章 新名")
    storage = _seed(tmp_path, [ch])
    storage.write_translated(ch, "Nội dung đã dịch.")
    cfg = _cfg(tmp_path)
    cfg.translate.type = "openai"

    pipeline.step_retranslate_title(
        cfg, lambda m: None, slug="t", index=1,
        engine="hachimimt", generate_description=False,
    )

    assert seen_types == ["hachimimt"]
    assert tr.single_calls == ["第一章 新名"]


def test_retranslate_title_works_without_translation(tmp_path, monkeypatch):
    """Dịch lại tiêu đề không bắt buộc chương đã dịch — chưa dịch thì dùng raw
    làm ngữ cảnh, không báo 'chưa có bản dịch'."""
    from novel2epub import translator as translator_module

    tr = _FakeTitleTranslator()
    monkeypatch.setattr(translator_module, "make_translator", lambda c, log=None, **kw: tr)

    ch = Chapter(index=1, url="http://x/1", title="第一章")
    storage = _seed(tmp_path, [ch])
    storage.write_raw(ch, "# 第一章\n\n原nội dung chưa dịch。")

    cfg = _cfg(tmp_path)
    cfg.translate.type = "hachimimt"
    result = pipeline.step_retranslate_title(
        cfg, lambda m: None, slug="t", index=1,
        engine="hachimimt", generate_description=False,
    )

    assert tr.single_calls == ["第一章"]
    ch2 = storage.load_manifest().chapters[0]
    assert ch2.title_zh == "第一章"
    assert result["title"] == ch2.title
