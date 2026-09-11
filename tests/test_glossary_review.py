from novel2epub.glossary_review import (
    DUPLICATE_IN_BATCH_DETAIL,
    EMPTY_FIELD_DETAIL,
    INVALID_SOURCE_DETAIL,
    RENAME_COLLIDES_DETAIL,
    count_entry_flags,
    entry_flags,
    filter_by_flags,
    find_suspects,
    parse_flags,
    plan_glossary_edits,
    replacement_pairs,
)


def test_same_target_groups_case_insensitive():
    entries = [
        ("张三", "Trương Tam", ""),
        ("斗气", "Đấu khí", "note"),
        ("张叁", "trương tam ", ""),  # khác hoa thường + thừa space vẫn gộp
    ]
    out = find_suspects(entries, None)
    assert len(out["same_target"]) == 1
    group = out["same_target"][0]
    assert group["target"] == "Trương Tam"  # target của mục đầu tiên trong nhóm
    assert [e["source"] for e in group["entries"]] == ["张三", "张叁"]


def test_nested_source_pairs_detects_substring_both_directions():
    entries = [
        ("张三", "Trương Tam", ""),
        ("张三爷", "Trương Tam gia", ""),
        ("斗气", "Đấu khí", ""),
    ]
    out = find_suspects(entries, None)
    assert len(out["nested_source"]) == 1
    pair = out["nested_source"][0]
    assert pair["inner"]["source"] == "张三"
    assert pair["outer"]["source"] == "张三爷"


def test_no_suspects_when_clean():
    entries = [("张三", "Trương Tam", ""), ("斗气", "Đấu khí", "")]
    out = find_suspects(entries, None)
    assert out["same_target"] == []
    assert out["nested_source"] == []
    assert out["conflicts"] == []


def test_conflicts_mapped_and_bad_rows_skipped():
    raw = [
        {"source": "张三", "existing": "Trương Tam", "new": "Trương Tân", "target_file": "x"},
        {"source": "", "existing": "a", "new": "b"},  # thiếu source → bỏ
        "not-a-dict",
    ]
    out = find_suspects([], raw)
    assert out["conflicts"] == [
        {"source": "张三", "kept": "Trương Tam", "new": "Trương Tân"}
    ]


def test_plan_edits_classifies_new_update_rename_and_unchanged():
    existing = [("张三", "Trương Tam", "nv"), ("李四", "Lý Tứ", "")]
    planned = plan_glossary_edits(
        existing,
        [
            {"source": "张三", "target": "Trần Tam", "note": "nv", "original_source": "张三"},
            {"source": "李十四", "target": "Lý Tứ", "original_source": "李四"},
            {"source": "王五", "target": "Vương Ngũ"},
            {"source": "李四", "target": "Lý Tứ", "original_source": "李四"},
        ],
    )

    assert [row["kind"] for row in planned] == ["update", "rename", "new", "unchanged"]
    assert planned[0]["existing_target"] == "Trương Tam"
    assert planned[1]["original_source"] == "李四"
    assert planned[2]["existing_target"] == ""
    assert all(row["error"] == "" for row in planned)


def test_plan_edits_flags_blank_vietnamese_source_duplicate_and_collision():
    existing = [("张三", "Trương Tam", ""), ("李四", "Lý Tứ", "")]
    planned = plan_glossary_edits(
        existing,
        [
            {"source": "王五", "target": "  "},
            {"source": "Tiêu Viêm", "target": "Tiêu Viêm"},
            {"source": "赵六", "target": "Triệu Lục"},
            {"source": "赵六", "target": "Triệu Sáu"},
            {"source": "李四", "target": "Lý Tứ", "original_source": "张三"},
        ],
    )

    errors = [row["error"] for row in planned]
    assert errors[0] == EMPTY_FIELD_DETAIL
    assert errors[1] == INVALID_SOURCE_DETAIL
    assert errors[2] == ""
    assert errors[3] == DUPLICATE_IN_BATCH_DETAIL
    assert errors[4] == RENAME_COLLIDES_DETAIL
    assert all(row["kind"] == "unchanged" for row in planned if row["error"])


def test_replacement_pairs_skips_new_unchanged_errored_and_dedups_old():
    existing = [("张三", "Trương Tam", ""), ("张三爷", "Trương Tam", ""), ("李四", "Lý Tứ", "")]
    planned = plan_glossary_edits(
        existing,
        [
            {"source": "张三", "target": "Trần Tam", "original_source": "张三"},
            {"source": "张三爷", "target": "Trần Tam gia", "original_source": "张三爷"},
            {"source": "李四", "target": "Lý Tứ", "original_source": "李四"},
            {"source": "王五", "target": "Vương Ngũ"},
            {"source": "Tiêu Viêm", "target": "x"},
        ],
    )

    # Hai dòng đầu cùng target cũ "Trương Tam" — chỉ giữ cặp đầu để không quét
    # chồng; dòng giữ nguyên, dòng mới và dòng lỗi đều không lan truyền.
    assert replacement_pairs(planned) == [("Trương Tam", "Trần Tam")]


def test_entry_flags_catches_han_in_vietnamese_and_latin_in_source():
    assert entry_flags("李逸", "Lý Dịch") == set()
    assert entry_flags("李逸", "Lý 逸") == {"vi_han"}
    assert entry_flags("李逸", "李逸") == {"vi_han", "same"}
    # Source do người dùng gõ nhầm tiếng Việt: vừa lẫn Latin vừa không có Hán.
    assert entry_flags("Tiêu Viêm", "Tiêu Viêm") == {"han_latin", "no_han", "same"}
    assert entry_flags("斗气Lv2", "Đấu khí cấp 2") == {"han_latin"}


def test_count_and_filter_use_the_same_predicate():
    entries = [
        ("李逸", "Lý Dịch", ""),
        ("王五", "Vương 五", ""),
        ("Tiêu Viêm", "Tiêu Viêm", ""),
    ]

    counts = count_entry_flags(entries)
    assert counts["vi_han"] == 1
    assert counts["han_latin"] == 1
    assert counts["same"] == 1

    # Số trên chip lọc phải bằng số dòng lọc ra, nếu không người dùng bấm vào
    # một chip "3 mục" rồi thấy bảng trống.
    for flag, expected in counts.items():
        assert len(filter_by_flags(entries, [flag])) == expected


def test_filter_by_flags_is_or_and_empty_means_no_filter():
    entries = [("李逸", "Lý Dịch", ""), ("王五", "Vương 五", ""), ("Tiêu Viêm", "x", "")]

    both = filter_by_flags(entries, ["vi_han", "han_latin"])
    assert [e[0] for e in both] == ["王五", "Tiêu Viêm"]
    assert filter_by_flags(entries, []) == entries


def test_parse_flags_drops_unknown_names_and_duplicates():
    assert parse_flags("vi_han, same, vi_han, bogus") == ["vi_han", "same"]
    assert parse_flags("") == []
