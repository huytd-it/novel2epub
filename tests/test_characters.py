"""Tests cho bảng nhân vật & ngôi xưng (logic thuần, không cần DB)."""
from novel2epub import characters as C
from novel2epub.characters import Character, Relation


def test_characters_from_rows_parses_aliases():
    rows = [
        ("林凡", "Lâm Phàm", "凡儿|林少爷", "nam", "ta", "hắn", "đồ đệ của Huyền Trần Tử", "main"),
        ("苏清雪", "Tô Thanh Tuyết", "", "nu", "ta", "nàng", "", "side"),
    ]
    out = C.characters_from_rows(rows)
    assert len(out) == 2
    assert out[0] == Character(
        source="林凡", target="Lâm Phàm", aliases=("凡儿", "林少爷"),
        gender="nam", self_pronoun="ta", narrator_ref="hắn",
        role_note="đồ đệ của Huyền Trần Tử", importance="main",
    )
    assert out[1].aliases == ()


def test_characters_from_rows_skips_missing_source():
    rows = [("", "Bỏ", "", "", "", "", "", "side")]
    assert C.characters_from_rows(rows) == []


def test_relations_from_rows_skips_missing_endpoint():
    rows = [
        ("林凡", "苏清雪", 120, "em", "anh", ""),
        ("林凡", "", 0, "x", "y", ""),
    ]
    out = C.relations_from_rows(rows)
    assert out == [Relation("林凡", "苏清雪", 120, "em", "anh", "")]
