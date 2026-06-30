"""Test module novel2epub.bulk_transfer (xuất/nhập biên tập hàng loạt, định dạng Markdown)."""
from __future__ import annotations

from novel2epub import bulk_transfer as b


def test_round_trip_build_then_parse():
    items = [(2, "Tiêu đề 2", "Nội dung chương hai."), (1, "", "Nội dung chương một.")]
    text = b.build_export(items, names={"萧炎": "Tiêu Viêm"}, vietphrase={})
    parsed = b.parse_import(text)
    # Sắp theo index và giữ đúng nội dung.
    assert parsed == [(1, "Nội dung chương một."), (2, "Nội dung chương hai.")]


def test_export_includes_prompt_and_glossary_as_markdown():
    text = b.build_export([(1, "", "x")], names={"萧炎": "Tiêu Viêm"}, vietphrase={"斗气": "Đấu khí"})
    assert "biên tập" in text.lower()
    assert "## GLOSSARY" in text
    assert "### Tên riêng" in text
    assert "### Thuật ngữ" in text
    assert "萧炎 = Tiêu Viêm" in text
    assert "斗气 = Đấu khí" in text
    assert "## Chương 1" in text


def test_export_without_glossary_omits_block():
    text = b.build_export([(1, "", "x")])
    # Không có glossary tham khảo thì không render mục glossary tham khảo
    # (prompt tĩnh có nhắc tới cụm "Glossary tham khảo" nên check heading riêng).
    assert "## Glossary tham khảo" not in text


def test_translate_prompt_used_for_raw_export():
    text = b.build_export([(1, "Tiêu đề Hán", "原文内容")], prompt=b.TRANSLATE_PROMPT)
    assert "dịch" in text.lower()
    assert "Yêu cầu dịch truyện" in text
    assert "## Chương 1: Tiêu đề Hán" in text
    assert "原文内容" in text
    # Vẫn yêu cầu AI xuất GLOSSARY giống prompt biên tập, để round-trip nhất quán.
    assert "## GLOSSARY" in text


def test_translate_prompt_distinct_from_edit_prompt():
    assert b.TRANSLATE_PROMPT != b.EDIT_PROMPT
    assert "BIÊN TẬP LẠI" not in b.TRANSLATE_PROMPT
    assert "DỊCH" in b.TRANSLATE_PROMPT


def test_parse_import_markdown_headers():
    text = "## Chương 1: Khởi đầu\nNội dung 1\n\n## Chương 2\nNội dung 2"
    assert b.parse_import(text) == [(1, "Nội dung 1"), (2, "Nội dung 2")]


def test_parse_import_markdown_heading_level_and_case_tolerant():
    # AI có thể đổi cấp tiêu đề (#, ###) hoặc viết thường — vẫn parse được index.
    text = "### chương 12: Một tiêu đề dài\nnội dung"
    assert b.parse_import(text) == [(12, "nội dung")]


def test_parse_import_legacy_equals_marker_still_works():
    # Tương thích ngược với bản xuất cũ dùng marker "=====".
    text = "===== CHƯƠNG 12: Một tiêu đề dài =====\nnội dung"
    assert b.parse_import(text) == [(12, "nội dung")]


def test_parse_import_ignores_text_before_first_marker():
    text = "Lời dẫn linh tinh\n\n## Chương 5\nNội dung 5"
    assert b.parse_import(text) == [(5, "Nội dung 5")]


def test_parse_import_truncates_at_glossary():
    text = "## Chương 1\nABC\n\n## GLOSSARY\n### NAMES\n- 林动 = Lâm Động\n"
    assert b.parse_import(text) == [(1, "ABC")]


def test_parse_import_no_marker_returns_empty():
    assert b.parse_import("Chỉ là văn bản thường, không có marker.") == []


def test_parse_glossary_groups_markdown():
    text = (
        "## GLOSSARY\n\n"
        "### NAMES\n- 林动 = Lâm Động\n- 萧炎 = Tiêu Viêm\n\n"
        "### VIETPHRASE\n- 斗气 = Đấu khí\n"
    )
    g = b.parse_glossary(text)
    assert g["names"] == {"林动": "Lâm Động", "萧炎": "Tiêu Viêm"}
    assert g["vietphrase"] == {"斗气": "Đấu khí"}


def test_parse_glossary_legacy_bracket_headers_still_work():
    text = (
        "## GLOSSARY\n"
        "[NAMES]\n林动 = Lâm Động\n"
        "[VIETPHRASE]\n斗气 = Đấu khí\n"
    )
    g = b.parse_glossary(text)
    assert g["names"] == {"林动": "Lâm Động"}
    assert g["vietphrase"] == {"斗气": "Đấu khí"}


def test_parse_glossary_skips_placeholder_lines_from_prompt():
    # Khi user dán cả prompt mẫu (chứa "<chữ Hán> = <Hán Việt>") thì không nạp nhầm.
    text = b.build_export([(1, "", "x")]) + "\n## GLOSSARY\n### NAMES\n- 林动 = Lâm Động\n"
    g = b.parse_glossary(text)
    assert g["names"] == {"林动": "Lâm Động"}


def test_parse_glossary_no_block():
    assert b.parse_glossary("## Chương 1\nnội dung") == {"names": {}, "vietphrase": {}}


def test_validate_import_matched_missing_extra_unknown():
    # parse: 1,2,9 ; đã xuất: 1,2,3 ; manifest: 1,2,4,5
    report = b.validate_import([1, 2, 9], [1, 2, 3], [1, 2, 4, 5])
    assert report["matched"] == [1, 2]   # có trong text và thuộc manifest
    assert report["unknown"] == [9]      # trong text nhưng không thuộc manifest
    assert report["missing"] == [3]      # đã xuất nhưng AI bỏ sót
    assert report["extra"] == []         # không có chương ngoài tập đã chọn


def test_validate_import_extra():
    # parse 1,2 (thuộc manifest) nhưng chỉ xuất 1 → 2 là extra
    report = b.validate_import([1, 2], [1], [1, 2, 3])
    assert report["extra"] == [2]


def test_chapter_marker_is_markdown_heading():
    assert b.chapter_marker(7) == "## Chương 7"
    assert b.chapter_marker(7, "Khởi đầu") == "## Chương 7: Khởi đầu"
