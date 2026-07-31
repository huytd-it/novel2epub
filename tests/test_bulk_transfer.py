"""Test module novel2epub.bulk_transfer (xuất/nhập biên tập hàng loạt, định dạng Markdown)."""
from __future__ import annotations

import pytest

from novel2epub import bulk_transfer as b
from novel2epub import config
from novel2epub.presets import go, omniroute


def test_round_trip_build_then_parse():
    items = [(2, "Tiêu đề 2", "Nội dung chương hai."), (1, "", "Nội dung chương một.")]
    text = b.build_export(items, glossary={"萧炎": "Tiêu Viêm"})
    parsed = b.parse_import(text)
    # Sắp theo index, giữ đúng tiêu đề + nội dung.
    assert parsed == [(1, "", "Nội dung chương một."), (2, "Tiêu đề 2", "Nội dung chương hai.")]


def test_export_includes_prompt_and_glossary_as_markdown():
    text = b.build_export([(1, "", "x")], glossary={"萧炎": "Tiêu Viêm", "斗气": "Đấu khí"})
    assert "biên tập" in text.lower()
    assert "## GLOSSARY" in text
    assert "## Glossary tham khảo" in text
    assert "萧炎 = Tiêu Viêm" in text
    assert "斗气 = Đấu khí" in text
    assert "## idx:1" in text


def test_export_without_glossary_omits_block():
    text = b.build_export([(1, "", "x")])
    # Không có glossary tham khảo thì không render mục glossary tham khảo
    # (prompt tĩnh có nhắc tới cụm "Glossary tham khảo" nên check heading riêng).
    assert "## Glossary tham khảo" not in text


def test_translate_prompt_used_for_raw_export():
    text = b.build_export([(1, "Tiêu đề Hán", "原文内容")], prompt=b.TRANSLATE_PROMPT)
    assert "dịch" in text.lower()
    assert "Yêu cầu dịch truyện" in text
    assert "## idx:1: Tiêu đề Hán" in text
    assert "原文内容" in text
    # Vẫn yêu cầu AI xuất GLOSSARY giống prompt biên tập, để round-trip nhất quán.
    assert "## GLOSSARY" in text


def test_translate_prompt_distinct_from_edit_prompt():
    assert b.TRANSLATE_PROMPT != b.EDIT_PROMPT
    assert "BIÊN TẬP LẠI" not in b.TRANSLATE_PROMPT
    assert "DỊCH" in b.TRANSLATE_PROMPT


@pytest.mark.parametrize(
    "prompt",
    [
        config.DEFAULT_PROMPT,
        b.TRANSLATE_PROMPT,
        b.EDIT_PROMPT,
        go.GO_PROMPT,
        omniroute.OMNIPROUTE_PROMPT,
    ],
)
def test_foreign_name_rule_present_in_every_prompt(prompt):
    """Luật "tên người nước ngoài giữ dạng Latin" phải có ở MỌI prompt dịch/biên
    tập — nếu chỉ sửa một chỗ, cùng một truyện sẽ ra 2 kiểu tên (Sherlock ở
    luồng này, Hạ Lạc Khắc ở luồng kia)."""
    assert "Sherlock" in prompt
    assert "夏洛克" in prompt


@pytest.mark.parametrize(
    "prompt",
    [
        config.DEFAULT_PROMPT,
        config.EN_DEFAULT_PROMPT,
        b.TRANSLATE_PROMPT,
        b.EDIT_PROMPT,
        go.GO_PROMPT,
        omniroute.OMNIPROUTE_PROMPT,
    ],
)
def test_contextual_pronoun_rule_present_in_every_translation_prompt(prompt):
    assert '"hắn"' in prompt
    assert '"ta/ngươi"' in prompt
    assert "KHÔNG bê nguyên ta/ngươi" not in prompt


@pytest.mark.parametrize("prompt", [b.TRANSLATE_PROMPT, b.EDIT_PROMPT])
def test_foreign_name_example_in_prompt_never_imported_as_glossary(prompt):
    """Ví dụ tên nước ngoài trong prompt KHÔNG được nạp thành entry glossary thật
    khi user dán ngược cả prompt — ví dụ dùng mũi tên `→` (không phải `=`) và
    nằm trên heading `## GLOSSARY` mẫu, nên parse_glossary bỏ qua."""
    text = b.build_export([(1, "", "x")], prompt=prompt) + "\n## GLOSSARY\n- 林动 = Lâm Động\n"
    assert b.parse_glossary(text) == {"林动": "Lâm Động"}


def test_parse_import_markdown_headers():
    text = "## Chương 1: Khởi đầu\nNội dung 1\n\n## Chương 2\nNội dung 2"
    assert b.parse_import(text) == [(1, "Khởi đầu", "Nội dung 1"), (2, "", "Nội dung 2")]


def test_parse_import_markdown_heading_level_and_case_tolerant():
    # AI có thể đổi cấp tiêu đề (#, ###) hoặc viết thường — vẫn parse được index.
    text = "### chương 12: Một tiêu đề dài\nnội dung"
    assert b.parse_import(text) == [(12, "Một tiêu đề dài", "nội dung")]


def test_parse_import_legacy_equals_marker_still_works():
    # Tương thích ngược với bản xuất cũ dùng marker "=====".
    text = "===== CHƯƠNG 12: Một tiêu đề dài =====\nnội dung"
    assert b.parse_import(text) == [(12, "Một tiêu đề dài", "nội dung")]


def test_parse_import_legacy_marker_without_title_gives_empty_title():
    # Không nuốt run "=" cuối marker legacy làm tiêu đề.
    text = "===== CHƯƠNG 12 =====\nnội dung"
    assert b.parse_import(text) == [(12, "", "nội dung")]


def test_parse_import_title_separator_variants():
    # Fullwidth "：" và gạch ngang đều được strip khỏi đầu tiêu đề.
    text = "## Chương 3： Tiêu đề A\nx\n\n## Chương 4 - Tiêu đề B\ny"
    assert b.parse_import(text) == [(3, "Tiêu đề A", "x"), (4, "Tiêu đề B", "y")]


def test_parse_import_title_number_differs_from_index():
    # N của marker là index VỊ TRÍ trong manifest; số chương thật trong tiêu đề
    # có thể khác (vd vị trí 928 nhưng truyện đánh số 918) — giữ nguyên văn.
    text = "## Chương 928: Chương 918: Thiếu niên trở về\nnội dung"
    assert b.parse_import(text) == [(928, "Chương 918: Thiếu niên trở về", "nội dung")]


def test_parse_import_ignores_text_before_first_marker():
    text = "Lời dẫn linh tinh\n\n## Chương 5\nNội dung 5"
    assert b.parse_import(text) == [(5, "", "Nội dung 5")]


def test_parse_import_truncates_at_glossary():
    text = "## Chương 1\nABC\n\n## GLOSSARY\n### NAMES\n- 林动 = Lâm Động\n"
    assert b.parse_import(text) == [(1, "", "ABC")]


def test_parse_import_no_marker_returns_empty():
    assert b.parse_import("Chỉ là văn bản thường, không có marker.") == []


def test_parse_glossary_flat_markdown():
    text = (
        "## GLOSSARY\n"
        "- 林动 = Lâm Động\n- 萧炎 = Tiêu Viêm\n- 斗气 = Đấu khí\n"
    )
    g = b.parse_glossary(text)
    assert g == {"林动": "Lâm Động", "萧炎": "Tiêu Viêm", "斗气": "Đấu khí"}


def test_parse_glossary_legacy_subheadings_still_parse_flat():
    """File .md xuất theo định dạng cũ (subheading NAMES/VIETPHRASE) vẫn parse
    được — subheading không chứa `=` nên tự bị bỏ, mọi entry vào 1 dict."""
    text = (
        "## GLOSSARY\n"
        "### NAMES\n- 林动 = Lâm Động\n"
        "[VIETPHRASE]\n斗气 = Đấu khí\n"
    )
    g = b.parse_glossary(text)
    assert g == {"林动": "Lâm Động", "斗气": "Đấu khí"}


def test_parse_glossary_skips_placeholder_lines_from_prompt():
    # Khi user dán cả prompt mẫu (chứa "<chữ Hán> = <Hán Việt>") thì không nạp nhầm.
    text = b.build_export([(1, "", "x")]) + "\n## GLOSSARY\n- 林动 = Lâm Động\n"
    g = b.parse_glossary(text)
    assert g == {"林动": "Lâm Động"}


def test_parse_glossary_no_block():
    assert b.parse_glossary("## Chương 1\nnội dung") == {}


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
    assert b.chapter_marker(7) == "## idx:7"
    assert b.chapter_marker(7, "Khởi đầu") == "## idx:7: Khởi đầu"


def test_parse_import_idx_marker():
    text = "## idx:1: Khởi đầu\nNội dung 1\n\n## idx:2\nNội dung 2"
    assert b.parse_import(text) == [(1, "Khởi đầu", "Nội dung 1"), (2, "", "Nội dung 2")]


def test_parse_import_idx_marker_case_and_heading_level_tolerant():
    text = "### IDX:12: Một tiêu đề dài\nnội dung"
    assert b.parse_import(text) == [(12, "Một tiêu đề dài", "nội dung")]


def test_idx_marker_does_not_confuse_index_with_real_chapter_number():
    # idx (vị trí manifest, 1353) khác số chương thật trong tiêu đề gốc (1338)
    # — round-trip build/parse phải giữ nguyên cả hai, không trộn lẫn.
    title = "第1338章 番外一（就是先前把完本感言发错了，直接全盘修改重写成番外了）"
    text = b.build_export([(1353, title, "正文")], prompt=b.TRANSLATE_PROMPT)
    assert f"## idx:1353: {title}" in text
    assert b.parse_import(text) == [(1353, title, "正文")]

    # AI dịch tiêu đề nhưng giữ nguyên idx — parse phải tách đúng index=1353,
    # tiêu đề đã dịch vẫn giữ số chương thật 1338 (do ensure_title_number xử lý
    # ở tầng trên, không phải ở đây — parse_import chỉ tách nguyên văn).
    ai_reply = "## idx:1353: Chương 1338: Phiên ngoại 1 (...)\nNội dung đã dịch"
    assert b.parse_import(ai_reply) == [
        (1353, "Chương 1338: Phiên ngoại 1 (...)", "Nội dung đã dịch")
    ]


# ── ensure_title_number: giữ số chương THẬT từ tiêu đề gốc ────────────


def test_ensure_title_number_prefixes_dropped_number():
    # AI dịch "gọn" làm rơi 第911章 → gắn lại số thật từ bản gốc.
    assert b.ensure_title_number(
        "第911章 我要冻结所有法条！", "Ta muốn đóng băng tất cả pháp điều!"
    ) == "Chương 911: Ta muốn đóng băng tất cả pháp điều!"


def test_ensure_title_number_keeps_correct_number():
    assert b.ensure_title_number(
        "第911章 我要冻结所有法条！", "Chương 911: Ta muốn đóng băng tất cả pháp điều!"
    ) == "Chương 911: Ta muốn đóng băng tất cả pháp điều!"


def test_ensure_title_number_fixes_wrong_number():
    # AI echo nhầm index vị trí (961) vào tiêu đề → sửa về số thật (911).
    assert b.ensure_title_number(
        "第911章 我要冻结所有法条！", "Chương 961: Ta muốn đóng băng tất cả pháp điều!"
    ) == "Chương 911: Ta muốn đóng băng tất cả pháp điều!"


def test_ensure_title_number_no_zh_prefix_returns_verbatim():
    # Tiêu đề gốc không mở đầu bằng 第M章 → không đụng vào tiêu đề dịch.
    assert b.ensure_title_number("楔子", "Mở đầu") == "Mở đầu"
    assert b.ensure_title_number("", "Tiêu đề") == "Tiêu đề"


def test_ensure_title_number_juan_and_hui_labels():
    assert b.ensure_title_number("第3卷 风起", "Gió nổi") == "Quyển 3: Gió nổi"
    assert b.ensure_title_number("第7回 大战", "Đại chiến") == "Hồi 7: Đại chiến"


def test_ensure_title_number_title_only_number():
    # Bản gốc chỉ có 第5章, AI trả "Chương 5" → giữ dạng không dấu ':'.
    assert b.ensure_title_number("第5章", "Chương 5") == "Chương 5"


def test_glossary_export_round_trip_flat():
    """build_glossary_export → parse_glossary phải nạp lại đúng bảng phẳng."""
    glossary = {"萧炎": "Tiêu Viêm", "斗气": "Đấu khí"}
    text = b.build_glossary_export(glossary)
    assert "## GLOSSARY" in text
    assert b.parse_glossary(text) == glossary


# ── Task 8: khối nhân vật trong Xuất RAW + vá {idioms} rò ──────────────


def test_build_export_includes_character_block():
    out = b.build_export(
        [(1, "Chương 1", "Nội dung")],
        glossary={"林凡": "Lâm Phàm"},
        characters="BẢNG NHÂN VẬT & NGÔI XƯNG (bắt buộc, không tự ý đổi):\n林凡 = Lâm Phàm",
    )
    assert "BẢNG NHÂN VẬT & NGÔI XƯNG" in out
    # Khối nhân vật đứng sau glossary, trước chương đầu tiên.
    assert out.index("Glossary tham khảo") < out.index("BẢNG NHÂN VẬT")
    assert out.index("BẢNG NHÂN VẬT") < out.index("## idx:1")


def test_build_export_omits_empty_character_block():
    # Chuỗi chỉ toàn khoảng trắng phải bị coi là rỗng — dùng "" không đủ để
    # bắt thiếu `.strip()` (falsy cả khi thiếu guard), nên test cũ pass giả.
    out = b.build_export([(1, "Chương 1", "Nội dung")], characters="   \n  ")
    assert "BẢNG NHÂN VẬT" not in out


def test_translate_prompt_from_cfg_leaks_no_placeholders():
    # `config.Config` (novel2epub/config.py) đòi 4 field bắt buộc (novel/crawl/
    # translate/output) không default riêng ở cấp Config, nhưng bản thân từng
    # dataclass con đều dựng rỗng được — hàm chỉ đọc cfg.translate.{openai,style,genre}.
    cfg = config.Config(
        novel=config.NovelConfig(),
        crawl=config.CrawlConfig(),
        translate=config.TranslateConfig(),
        output=config.OutputConfig(),
    )
    out = b.build_translate_prompt_from_cfg(cfg)
    for placeholder in ("{idioms}", "{characters}", "{glossary}", "{text}",
                        "{pronoun_policy}", "{tone}", "{han_viet_level}"):
        assert placeholder not in out
    # Luật thể loại phải được render ra, không phải chuỗi enum trần.
    assert "contextual" not in out
