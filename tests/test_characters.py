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


# ---------- lọc theo chunk ----------

_LAM = Character(source="林凡", target="Lâm Phàm", aliases=("凡儿",),
                 narrator_ref="hắn", self_pronoun="ta", importance="main")
_TO = Character(source="苏清雪", target="Tô Thanh Tuyết", narrator_ref="nàng",
                importance="side")
_HUYEN = Character(source="玄尘子", target="Huyền Trần Tử", importance="side")


def test_filter_keeps_main_even_when_absent():
    # Chunk toàn đại từ, không nêu tên ai — main vẫn phải có mặt để giữ
    # narrator_ref, side thì không.
    out = C.filter_for_text([_LAM, _TO], "他看着她，沉默不语。")
    assert [c.source for c in out] == ["林凡"]


def test_filter_matches_alias():
    out = C.filter_for_text([_TO, _HUYEN], "凡儿，你回来了。玄尘子点头。")
    assert [c.source for c in out] == ["玄尘子"]

    lam_side = Character(source="林凡", aliases=("凡儿",), importance="side")
    out = C.filter_for_text([lam_side], "凡儿，你回来了。")
    assert [c.source for c in out] == ["林凡"]


def test_filter_latin_uses_word_boundary():
    lin = Character(source="Lin", importance="side")
    assert C.filter_for_text([lin], "Linda smiled.", source_language="en") == []
    assert C.filter_for_text([lin], "Lin smiled.", source_language="en") == [lin]


# ---------- chọn mốc quan hệ ----------

_R0 = Relation("林凡", "苏清雪", 0, "nàng", "ta")
_R120 = Relation("林凡", "苏清雪", 120, "em", "anh")
_R300 = Relation("林凡", "苏清雪", 300, "vợ", "anh")


def test_resolve_relations_picks_latest_at_or_before():
    assert C.resolve_relations([_R0, _R120, _R300], 200) == [_R120]
    assert C.resolve_relations([_R0, _R120, _R300], 300) == [_R300]
    assert C.resolve_relations([_R0, _R120, _R300], 50) == [_R0]


def test_resolve_relations_none_uses_chapter_zero():
    assert C.resolve_relations([_R0, _R120], None) == [_R0]


def test_resolve_relations_drops_pair_with_no_valid_milestone():
    assert C.resolve_relations([_R120], 50) == []


# ---------- render khối prompt ----------

def test_format_llm_block_empty_returns_empty_string():
    assert C.format_llm_block([], []) == ""


def test_format_llm_block_renders_attributes_and_aliases():
    block = C.format_llm_block([_LAM], [])
    assert "BẢNG NHÂN VẬT & NGÔI XƯNG" in block
    assert "林凡 = Lâm Phàm" in block
    assert "còn gọi: 凡儿" in block
    assert 'tự xưng "ta"' in block
    assert 'lời kể gọi "hắn"' in block


def test_format_llm_block_relation_needs_both_characters_present():
    # Chỉ có Lâm Phàm trong chars → dòng quan hệ tới Tô Thanh Tuyết bị bỏ.
    only_lam = C.format_llm_block([_LAM], [_R120])
    assert "với" not in only_lam

    both = C.format_llm_block([_LAM, _TO], [_R120])
    assert 'với Tô Thanh Tuyết: gọi "em", tự xưng "anh"' in both


def test_format_pin_line_lists_main_only():
    pin = C.format_pin_line([_LAM, _TO], forbid_words="anh/em/cậu/bạn")
    assert "Lâm Phàm" in pin
    assert "Tô Thanh Tuyết" not in pin   # side, không lên dòng ghim
    assert "CẤM dùng anh/em/cậu/bạn" in pin


def test_format_pin_line_empty_without_main():
    assert C.format_pin_line([_TO], forbid_words="x") == ""
