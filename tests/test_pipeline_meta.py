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


def test_step_fetch_toc_saves_metadata_no_content(tmp_path, monkeypatch):
    toc = TocResult(
        title="原书名",
        author="某作者",
        description="简介",
        cover_url="",  # để trống tránh tải ảnh thật
        chapters=[Chapter(index=1, url="http://x/1"), Chapter(index=2, url="http://x/2")],
    )
    monkeypatch.setattr(pipeline, "ScraplingCrawler", lambda c: _FakeCrawler(toc))

    cfg = _cfg(tmp_path)
    pipeline.step_fetch_toc(cfg, lambda m: None)

    storage = Storage(tmp_path, "t")
    manifest = storage.load_manifest()
    assert manifest.title == "原书名"
    assert manifest.description == "简介"
    assert len(manifest.chapters) == 2
    # fetch_toc KHÔNG tải nội dung chương
    assert not storage.has_raw(manifest.chapters[0])


def test_fetch_toc_khong_de_len_metadata_user_da_sua(tmp_path, monkeypatch):
    """fetch-toc chỉ đồng bộ danh sách chương; metadata user sửa tay phải nguyên vẹn."""
    toc = TocResult(
        title="Tên do TOC",
        author="Tác giả do TOC",
        description="Mô tả do TOC",
        cover_url="",  # để trống tránh tải ảnh thật
        chapters=[Chapter(index=1, url="http://x/1"), Chapter(index=2, url="http://x/2")],
    )
    monkeypatch.setattr(pipeline, "ScraplingCrawler", lambda c: _FakeCrawler(toc))

    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")

    # Lần đầu: có manifest + metadata từ TOC.
    pipeline.step_fetch_toc(cfg, lambda m: None)
    manifest = storage.load_manifest()

    # User sửa tay metadata.
    manifest.title = "Tên do user đặt"
    manifest.author = "Tác giả do user đặt"
    manifest.description = "Mô tả do user viết"
    storage.save_manifest(manifest)

    # Lấy TOC lần nữa.
    pipeline.step_fetch_toc(cfg, lambda m: None)

    after = storage.load_manifest()
    assert after.title == "Tên do user đặt"
    assert after.author == "Tác giả do user đặt"
    assert after.description == "Mô tả do user viết"


def test_fetch_toc_khong_dien_lai_metadata_user_da_xoa(tmp_path, monkeypatch):
    """Manifest đã tồn tại => fetch-toc không đụng metadata, kể cả khi trống.

    User xoá trắng mô tả là một lựa chọn có chủ đích; TOC không được điền lại.
    Chỉ form Settings mới được ghi metadata.
    """
    toc = TocResult(
        title="Tên do TOC",
        author="Tác giả do TOC",
        description="Mô tả do TOC",
        cover_url="",
        chapters=[Chapter(index=1, url="http://x/1")],
    )
    monkeypatch.setattr(pipeline, "ScraplingCrawler", lambda c: _FakeCrawler(toc))

    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")

    pipeline.step_fetch_toc(cfg, lambda m: None)
    manifest = storage.load_manifest()

    # User xoá trắng mô tả.
    manifest.description = ""
    storage.save_manifest(manifest)

    pipeline.step_fetch_toc(cfg, lambda m: None)

    assert storage.load_manifest().description == ""


def test_fetch_toc_khong_con_tham_so_force():
    """`force` đã bị bỏ — gọi kèm nó phải là TypeError, không im lặng bỏ qua."""
    import inspect

    assert "force" not in inspect.signature(pipeline.step_fetch_toc).parameters


def test_refresh_manifest_empty_toc_keeps_cached_chapters(tmp_path, monkeypatch):
    """TOC trả về 0 chương (anti-bot trả 200, site đổi cấu trúc...) không được
    xóa chapters đã có trong manifest — dùng lại cache."""
    from novel2epub.storage import Manifest

    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=1, url="http://x/1", title="C1"), Chapter(index=2, url="http://x/2", title="C2")]
    storage.save_manifest(Manifest(slug="t", title="Truyện", chapters=chapters))

    toc = TocResult(title="", chapters=[])
    monkeypatch.setattr(pipeline, "ScraplingCrawler", lambda c: _FakeCrawler(toc))

    cfg = _cfg(tmp_path)
    pipeline.step_fetch_toc(cfg, lambda m: None)

    manifest = storage.load_manifest()
    assert len(manifest.chapters) == 2
    assert manifest.chapters[0].title == "C1"


def test_refresh_manifest_empty_toc_no_cache_raises(tmp_path, monkeypatch):
    toc = TocResult(title="", chapters=[])
    monkeypatch.setattr(pipeline, "ScraplingCrawler", lambda c: _FakeCrawler(toc))

    cfg = _cfg(tmp_path)
    import pytest

    with pytest.raises(RuntimeError):
        pipeline.step_fetch_toc(cfg, lambda m: None)


def test_refresh_manifest_partial_toc_keeps_missing_chapters(tmp_path, monkeypatch):
    """Chương cũ vắng mặt trong TOC mới (phân trang lỗi, site đổi URL...) phải
    được giữ lại — không mồ côi file raw/translated trên đĩa."""
    from novel2epub.storage import Manifest

    storage = Storage(tmp_path, "t")
    chapters = [
        Chapter(index=1, url="http://x/1", title="C1"),
        Chapter(index=2, url="http://x/2", title="C2"),
    ]
    storage.save_manifest(Manifest(slug="t", title="Truyện", chapters=chapters))

    # TOC mới chỉ còn chương 2 + thêm chương 3 mới
    toc = TocResult(
        title="",
        chapters=[
            Chapter(index=1, url="http://x/2", title="C2"),
            Chapter(index=2, url="http://x/3", title="C3"),
        ],
    )
    monkeypatch.setattr(pipeline, "ScraplingCrawler", lambda c: _FakeCrawler(toc))

    cfg = _cfg(tmp_path)
    pipeline.step_fetch_toc(cfg, lambda m: None)

    manifest = storage.load_manifest()
    urls = [ch.url for ch in manifest.chapters]
    assert urls == ["http://x/1", "http://x/2", "http://x/3"]
    # Chương cũ giữ nguyên index (file trên đĩa đặt tên theo index)
    assert manifest.chapters[0].index == 1
    assert manifest.chapters[1].index == 2
    # Chương mới nối vào cuối với index tiếp theo
    assert manifest.chapters[2].index == 3
    # Title cũ không bị TOC mới ghi đè
    assert manifest.chapters[1].title == "C2"


def test_refresh_manifest_keeps_same_url_different_titles(tmp_path, monkeypatch):
    """A new title at an existing URL is a new chapter with a new index."""
    from novel2epub.storage import Manifest

    storage = Storage(tmp_path, "t")
    storage.save_manifest(Manifest(
        slug="t",
        chapters=[Chapter(index=1, url="http://x/1", title="C1")],
    ))
    toc = TocResult(
        title="",
        chapters=[
            Chapter(index=1, url="http://x/1", title="C1"),
            Chapter(index=2, url="http://x/1", title="C1 bản khác"),
        ],
    )
    monkeypatch.setattr(pipeline, "ScraplingCrawler", lambda c: _FakeCrawler(toc))

    pipeline.step_fetch_toc(_cfg(tmp_path), lambda m: None)

    chapters = storage.load_manifest().chapters
    assert [(ch.index, ch.url, ch.title) for ch in chapters] == [
        (1, "http://x/1", "C1"),
        (2, "http://x/1", "C1 bản khác"),
    ]
    assert chapters[1].duplicate_of is None
    assert "duplicate" not in chapters[1].missing_fields


class _FlakyTranslator:
    """Dịch OK trừ những chương có index nằm trong `fail_on` thì ném lỗi."""

    def __init__(self, fail_on):
        self.fail_on = set(fail_on)
        self.calls = 0

    def translate(self, text, *, chapter_idx=None, on_chunk=None, on_glossary=None):
        self.calls += 1
        if text in self.fail_on:
            raise RuntimeError("CLI thoát mã 0 nhưng không trả về nội dung")
        out = f"VI:{text}"
        if on_chunk is not None:
            on_chunk(1, 1, out, True)
        return out


def test_translate_selected_reports_per_chapter_error_and_continues(tmp_path, monkeypatch):
    from novel2epub.storage import Manifest

    storage = Storage(tmp_path, "t")
    chs = [Chapter(index=i, url=f"http://x/{i}") for i in (1, 2, 3)]
    storage.save_manifest(Manifest(slug="t", chapters=chs))
    for ch in chs:
        storage.write_raw(ch, f"raw{ch.index}")

    # Chương 1 dịch được (nên không fail-fast), chương 2 lỗi, chương 3 dịch được.
    tr = _FlakyTranslator(fail_on={"raw2"})
    monkeypatch.setattr(pipeline, "make_translator", lambda c, log=None, **kw: tr)

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
    monkeypatch.setattr(pipeline, "make_translator", lambda c, log=None, **kw: tr)

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


def test_step_find_replace_regex_replaces_with_groups_and_backs_up(tmp_path):
    from novel2epub.storage import Manifest

    storage = Storage(tmp_path, "t")
    chs = [Chapter(index=i, url=f"http://x/{i}") for i in (1, 2)]
    storage.save_manifest(Manifest(slug="t", chapters=chs))
    storage.write_translated(chs[0], "Chương 1 và Chương 12.")
    storage.write_translated(chs[1], "Không số.")

    cfg = _cfg(tmp_path)
    logs = []
    pipeline.step_find_replace(
        cfg, logs.append, find=r"Chương (\d+)", replace=r"Hồi \1", regex=True
    )

    assert storage.read_translated(chs[0]) == "Hồi 1 và Hồi 12."
    assert storage.read_translated(chs[1]) == "Không số."
    assert storage.read_meta(chs[0])["before_find_replace"] == "Chương 1 và Chương 12."
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
    ch = Chapter(index=1, url="http://x/1", title="Chương 1")
    storage.save_manifest(Manifest(slug="t", title="Truyện", chapters=[ch]))
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
        title="Tên Việt",
        author="Tác giả Việt",
        description="Mô tả Việt",
        chapters=[Chapter(index=1, url="http://x/1", title="Chương 1")],
    )
    out = build_epub(
        manifest,
        [(manifest.chapters[0], "Chương 1", "Nội dung.")],
        tmp_path / "out.epub",
        cover_path=cover,
    )
    assert out.exists() and out.stat().st_size > 0
