from novel2epub import footnotes
from novel2epub.epub_builder import _md_to_xhtml_body, _render_footnotes


def test_md_to_xhtml_renders_footnote_marker_as_sup():
    md = "Trang Quốc" + footnotes.make_marker(1) + " rộng lớn."
    html = _md_to_xhtml_body(md)
    assert '<sup class="fn">' in html
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
    assert '<li id="fn1">' in html and '<li id="fn2">' in html
    assert "<strong>Trang Quốc:</strong> nước hư cấu" in html
    assert 'href="#fnref1"' in html


def test_render_footnotes_empty_returns_empty():
    assert _render_footnotes([]) == ""


def test_render_footnotes_escapes_html():
    items = [{"num": 1, "term": "<b>", "note": "a & b"}]
    html = _render_footnotes(items)
    assert "&lt;b&gt;" in html
    assert "a &amp; b" in html
