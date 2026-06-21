import re

from novel2epub import footnotes

_MARK_RE = re.compile(
    re.escape(footnotes.MARK_OPEN) + r"\d+" + re.escape(footnotes.MARK_CLOSE)
)


def _strip_marks(text: str) -> str:
    return _MARK_RE.sub("", text)


def test_annotate_numbers_by_first_occurrence_order():
    text = "Trang Quốc rộng lớn. Đạo Nguyên bước vào Trang Quốc lần nữa."
    notes = {"Đạo Nguyên": "tên nhân vật", "Trang Quốc": "nước hư cấu"}
    marked, fns = footnotes.annotate(text, notes)

    # Đánh số theo thứ tự xuất hiện: Trang Quốc (pos 0) = 1, Đạo Nguyên = 2
    assert [f["num"] for f in fns] == [1, 2]
    assert fns[0]["term"] == "Trang Quốc"
    assert fns[1]["term"] == "Đạo Nguyên"

    # Marker chèn ngay sau lần xuất hiện đầu tiên; lần thứ 2 của Trang Quốc không có.
    assert _strip_marks(marked) == text
    assert marked.count(footnotes.make_marker(1)) == 1
    assert marked.count(footnotes.make_marker(2)) == 1
    # Marker (1) đứng ngay sau cụm "Trang Quốc" đầu tiên
    assert marked.startswith("Trang Quốc" + footnotes.make_marker(1))


def test_annotate_skips_terms_not_present():
    text = "Chỉ có Trang Quốc ở đây."
    notes = {"Trang Quốc": "nước", "Đạo Nguyên": "người"}
    marked, fns = footnotes.annotate(text, notes)
    assert [f["term"] for f in fns] == ["Trang Quốc"]
    assert marked.count(footnotes.MARK_OPEN) == 1


def test_annotate_prefers_longer_term():
    text = "Trang Quốc là một nước."
    notes = {"Trang": "họ", "Trang Quốc": "nước hư cấu"}
    marked, fns = footnotes.annotate(text, notes)
    terms = {f["term"] for f in fns}
    # "Trang Quốc" được khớp trước, "Trang" (con của nó) bị bỏ vì nằm giữa từ.
    assert "Trang Quốc" in terms
    assert "Trang" not in terms


def test_annotate_no_notes_returns_unchanged():
    text = "Không có gì."
    marked, fns = footnotes.annotate(text, {})
    assert marked == text
    assert fns == []
