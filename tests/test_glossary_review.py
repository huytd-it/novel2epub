from novel2epub.glossary_review import find_suspects


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
