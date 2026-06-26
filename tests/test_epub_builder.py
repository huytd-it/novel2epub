import zipfile

from novel2epub import footnotes
from novel2epub.config import NovelConfig
from novel2epub.epub_builder import _md_to_xhtml_body, _render_footnotes, build_epub
from novel2epub.storage import Chapter, Manifest


def test_md_to_xhtml_renders_footnote_marker_as_sup():
    md = "Trang Quốc" + footnotes.make_marker(1) + " rộng lớn."
    html = _md_to_xhtml_body(md)
    assert '<sup class="fn" data-num="1">' in html
    assert 'id="fnref1"' in html
    assert 'href="#fn1"' in html
    assert "(1)" in html
    # Placeholder PUA không còn sót lại trong output.
    assert footnotes.MARK_OPEN not in html
    assert footnotes.MARK_CLOSE not in html


def test_render_footnotes_builds_ordered_list_with_backlinks():
    items = [
        {"num": 1, "term": "Trang Quốc", "note": "nước hư cấu"},
        {"num": 2, "term": "miêu hổ", "note": "tàn nhẫn"},
    ]
    html = _render_footnotes(items)
    assert '<div class="footnotes">' in html
    assert '<li id="fn1" data-num="1">' in html and '<li id="fn2" data-num="2">' in html
    assert "<strong>Trang Quốc:</strong> nước hư cấu" in html
    assert 'href="#fnref1"' in html


def test_render_footnotes_empty_returns_empty():
    assert _render_footnotes([]) == ""


def test_render_footnotes_escapes_html():
    items = [{"num": 1, "term": "<b>", "note": "a & b"}]
    html = _render_footnotes(items)
    assert "&lt;b&gt;" in html
    assert "a &amp; b" in html


def _manifest():
    return Manifest(slug="t", title="Truyện", chapters=[Chapter(index=1, url="http://x/1")])


def _opf_text(epub_path) -> str:
    with zipfile.ZipFile(epub_path) as zf:
        opf_name = next(n for n in zf.namelist() if n.endswith(".opf"))
        return zf.read(opf_name).decode("utf-8")


def test_populated_metadata_fields_appear_in_epub(tmp_path):
    metadata = NovelConfig(
        title="Truyện",
        author="A",
        publisher="NXB Kim Đồng",
        pubdate="2024-01-01",
        subjects=["Tiên hiệp", "Huyền huyễn"],
        series="Bộ truyện X",
        series_index="2",
        identifier="urn:uuid:1234",
        date_added="2024-06-01",
    )
    out = build_epub(
        _manifest(),
        [(Chapter(index=1, url="http://x/1"), "Chương 1", "Nội dung.")],
        tmp_path / "out.epub",
        metadata=metadata,
    )
    opf = _opf_text(out)
    assert "urn:uuid:1234" in opf
    assert "NXB Kim Đồng" in opf
    assert "2024-01-01" in opf
    assert "Tiên hiệp" in opf and "Huyền huyễn" in opf
    assert "calibre:series" in opf and "Bộ truyện X" in opf
    assert 'content="2"' in opf
    assert "calibre:timestamp" in opf and "2024-06-01" in opf


def test_identifier_stable_across_rebuilds(tmp_path):
    metadata = NovelConfig(identifier="urn:uuid:stable-id")
    out1 = build_epub(_manifest(), [], tmp_path / "a.epub", metadata=metadata)
    out2 = build_epub(_manifest(), [], tmp_path / "b.epub", metadata=metadata)
    assert "urn:uuid:stable-id" in _opf_text(out1)
    assert "urn:uuid:stable-id" in _opf_text(out2)


def test_empty_metadata_fields_omitted(tmp_path):
    metadata = NovelConfig()  # mọi field publishing đều rỗng
    out = build_epub(_manifest(), [], tmp_path / "out.epub", metadata=metadata)
    opf = _opf_text(out)
    assert "calibre:series" not in opf
    assert "calibre:timestamp" not in opf
    assert "dc:publisher" not in opf
    assert "dc:subject" not in opf
