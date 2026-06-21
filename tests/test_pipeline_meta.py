from novel2epub import pipeline
from novel2epub.config import (
    Config,
    CrawlConfig,
    NovelConfig,
    OutputConfig,
    TranslateConfig,
)
from novel2epub.crawler import TocResult
from novel2epub.storage import Chapter, Storage


def _cfg(tmp_path, translate_type="cli"):
    return Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/book/1/", delay_seconds=0),
        translate=TranslateConfig(type=translate_type, delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


class _FakeCrawler:
    def __init__(self, toc):
        self._toc = toc

    def fetch_toc(self):
        return self._toc

    def fetch_chapter(self, ch):  # pragma: no cover - không dùng trong test này
        return "noi dung"

    def sleep(self):
        pass

    def close(self):
        pass


class _UpperTranslator:
    """Translator giả: 'dịch' = thêm tiền tố để kiểm tra giá trị được ghi."""

    def translate(self, text):
        return f"VI:{text}"

    def translate_title(self, text, kind="tên chương"):
        return f"VI:{text}", f"note:{kind}"


def test_step_fetch_toc_saves_metadata_no_content(tmp_path, monkeypatch):
    toc = TocResult(
        title="原书名",
        author="某作者",
        description="简介",
        cover_url="",  # để trống tránh tải ảnh thật
        chapters=[Chapter(index=1, url="http://x/1"), Chapter(index=2, url="http://x/2")],
    )
    monkeypatch.setattr(pipeline, "make_crawler", lambda c: _FakeCrawler(toc))

    cfg = _cfg(tmp_path)
    pipeline.step_fetch_toc(cfg, lambda m: None)

    storage = Storage(tmp_path, "t")
    manifest = storage.load_manifest()
    assert manifest.title == "原书名"
    assert manifest.description == "简介"
    assert len(manifest.chapters) == 2
    # fetch_toc KHÔNG tải nội dung chương
    assert not storage.has_raw(manifest.chapters[0])


def test_step_translate_meta_fills_vi(tmp_path, monkeypatch):
    toc = TocResult(title="书名", author="作者", description="简介", chapters=[Chapter(index=1, url="http://x/1")])
    monkeypatch.setattr(pipeline, "make_crawler", lambda c: _FakeCrawler(toc))
    monkeypatch.setattr(pipeline, "make_translator", lambda c: _UpperTranslator())

    cfg = _cfg(tmp_path)
    pipeline.step_fetch_toc(cfg, lambda m: None)
    pipeline.step_translate_meta(cfg, lambda m: None)

    manifest = Storage(tmp_path, "t").load_manifest()
    assert manifest.title_vi == "VI:书名"
    assert manifest.title_note == "note:tên truyện"
    assert manifest.author_vi == "VI:作者"
    assert manifest.description_vi == "VI:简介"


def test_step_translate_meta_noop_skips(tmp_path, monkeypatch):
    toc = TocResult(title="书名", description="简介", chapters=[Chapter(index=1, url="http://x/1")])
    monkeypatch.setattr(pipeline, "make_crawler", lambda c: _FakeCrawler(toc))

    cfg = _cfg(tmp_path, translate_type="none")
    pipeline.step_fetch_toc(cfg, lambda m: None)
    pipeline.step_translate_meta(cfg, lambda m: None)

    manifest = Storage(tmp_path, "t").load_manifest()
    assert manifest.title_vi == ""
    assert manifest.description_vi == ""


def test_translate_meta_inplace_respects_force(tmp_path):
    from novel2epub.storage import Manifest

    manifest = Manifest(slug="t", title="书名", title_vi="đã có")
    tr = _UpperTranslator()

    # không force + đã có -> không đổi
    assert pipeline._translate_meta_inplace(manifest, tr, is_noop=False, log=lambda m: None, force=False) is False
    assert manifest.title_vi == "đã có"

    # force -> dịch lại
    assert pipeline._translate_meta_inplace(manifest, tr, is_noop=False, log=lambda m: None, force=True) is True
    assert manifest.title_vi == "VI:书名"
    assert manifest.title_note == "note:tên truyện"


class _FlakyTranslator:
    """Dịch OK trừ những chương có index nằm trong `fail_on` thì ném lỗi."""

    def __init__(self, fail_on):
        self.fail_on = set(fail_on)
        self.calls = 0

    def translate(self, text):
        self.calls += 1
        if text in self.fail_on:
            raise RuntimeError("CLI thoát mã 0 nhưng không trả về nội dung")
        return f"VI:{text}"


def test_translate_selected_reports_per_chapter_error_and_continues(tmp_path, monkeypatch):
    from novel2epub.storage import Manifest

    storage = Storage(tmp_path, "t")
    chs = [Chapter(index=i, url=f"http://x/{i}") for i in (1, 2, 3)]
    storage.save_manifest(Manifest(slug="t", chapters=chs))
    for ch in chs:
        storage.write_raw(ch, f"raw{ch.index}")

    # Chương 1 dịch được (nên không fail-fast), chương 2 lỗi, chương 3 dịch được.
    tr = _FlakyTranslator(fail_on={"raw2"})
    monkeypatch.setattr(pipeline, "make_translator", lambda c: tr)

    logs = []
    cfg = _cfg(tmp_path)
    pipeline.step_translate_selected(cfg, logs.append)

    assert storage.has_translated(chs[0]) and storage.has_translated(chs[2])
    assert not storage.has_translated(chs[1])
    assert any("Lỗi chương" in m for m in logs)
    assert any("lỗi 1" in m for m in logs)  # dòng tổng kết


def test_translate_selected_fails_fast_on_first_chapter(tmp_path, monkeypatch):
    from novel2epub.storage import Manifest

    storage = Storage(tmp_path, "t")
    chs = [Chapter(index=i, url=f"http://x/{i}") for i in (1, 2)]
    storage.save_manifest(Manifest(slug="t", chapters=chs))
    for ch in chs:
        storage.write_raw(ch, f"raw{ch.index}")

    tr = _FlakyTranslator(fail_on={"raw1", "raw2"})
    monkeypatch.setattr(pipeline, "make_translator", lambda c: tr)

    cfg = _cfg(tmp_path)
    import pytest

    with pytest.raises(RuntimeError, match="ngay chương đầu"):
        pipeline.step_translate_selected(cfg, lambda m: None)
    # Dừng sớm: không thử dịch chương 2 (1 lần gọi cho chương 1).
    assert tr.calls == 1


def test_step_find_replace_replaces_and_backs_up(tmp_path):
    from novel2epub.storage import Manifest

    storage = Storage(tmp_path, "t")
    chs = [Chapter(index=i, url=f"http://x/{i}") for i in (1, 2)]
    storage.save_manifest(Manifest(slug="t", chapters=chs))
    storage.write_translated(chs[0], "Trang Quốc và Trang Quốc.")
    storage.write_translated(chs[1], "Không có gì.")

    cfg = _cfg(tmp_path)
    logs = []
    pipeline.step_find_replace(cfg, logs.append, find="Trang Quốc", replace="Trang quốc")

    assert storage.read_translated(chs[0]) == "Trang quốc và Trang quốc."
    assert storage.read_translated(chs[1]) == "Không có gì."
    # Bản trước khi thay được lưu để khôi phục.
    assert storage.read_meta(chs[0])["before_find_replace"] == "Trang Quốc và Trang Quốc."
    assert not storage.has_meta(chs[1])
    assert any("tổng 2 lần thay" in m for m in logs)


def test_step_find_replace_empty_find_is_noop(tmp_path):
    from novel2epub.storage import Manifest

    storage = Storage(tmp_path, "t")
    ch = Chapter(index=1, url="http://x/1")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    storage.write_translated(ch, "nguyên văn")

    cfg = _cfg(tmp_path)
    pipeline.step_find_replace(cfg, lambda m: None, find="", replace="x")
    assert storage.read_translated(ch) == "nguyên văn"


def test_step_build_inserts_glossary_footnotes(tmp_path):
    from novel2epub.storage import Manifest

    storage = Storage(tmp_path, "t")
    ch = Chapter(index=1, url="http://x/1", title_vi="Chương 1")
    storage.save_manifest(Manifest(slug="t", title_vi="Truyện", chapters=[ch]))
    storage.write_translated(ch, "Trang Quốc rộng lớn.")
    storage.write_glossary_file("names.txt", "庄国 = Trang Quốc | nước hư cấu\n")

    cfg = _cfg(tmp_path)
    cfg.output.epub_path = str(tmp_path / "out.epub")
    out = pipeline.step_build(cfg, lambda m: None)

    from pathlib import Path

    assert Path(out).exists() and Path(out).stat().st_size > 0


def test_build_epub_uses_vi_meta_and_cover(tmp_path):
    from novel2epub.epub_builder import build_epub
    from novel2epub.storage import Manifest

    cover = tmp_path / "cover.png"
    cover.write_bytes(b"\x89PNG\r\n\x1a\n")  # header PNG tối thiểu
    manifest = Manifest(
        slug="t",
        title="书名",
        title_vi="Tên Việt",
        author_vi="Tác giả Việt",
        description_vi="Mô tả Việt",
        chapters=[Chapter(index=1, url="http://x/1", title_vi="Chương 1")],
    )
    out = build_epub(
        manifest,
        [(manifest.chapters[0], "Chương 1", "Nội dung.")],
        tmp_path / "out.epub",
        cover_path=cover,
    )
    assert out.exists() and out.stat().st_size > 0
