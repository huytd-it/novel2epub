"""Test helper thuần của ghi chú lỗi dịch (novel2epub/notes.py) + parser đề xuất AI."""
from __future__ import annotations

from novel2epub.glossary_ai import _parse_fixes
from novel2epub.notes import apply_note_fix, locate_note_para, replace_para, split_paras


def _note(**overrides) -> dict:
    base = {
        "id": "n1",
        "chapter_index": 1,
        "para_index": 1,
        "selected_text": "hắn nói",
        "para_text": "Rồi hắn nói một câu.",
        "note": "sai ngôi xưng",
        "status": "open",
    }
    base.update(overrides)
    return base


# --- split_paras ---


def test_split_paras_drops_blank_lines():
    assert split_paras("Đoạn 1\n\nĐoạn 2\n   \nĐoạn 3") == ["Đoạn 1", "Đoạn 2", "Đoạn 3"]
    assert split_paras("") == []


# --- locate_note_para ---


def test_locate_hits_saved_para_index():
    paras = ["Mở đầu.", "Rồi hắn nói một câu.", "Kết thúc."]
    assert locate_note_para(paras, _note()) == 1


def test_locate_finds_moved_para():
    # Đoạn chứa text đã dịch chuyển (para_index cũ không còn khớp)
    paras = ["Chèn thêm.", "Mở đầu.", "Rồi hắn nói một câu."]
    assert locate_note_para(paras, _note(para_index=1)) == 2


def test_locate_disambiguates_duplicates_by_para_text():
    paras = ["hắn nói to.", "Rồi hắn nói một câu.", "hắn nói nhỏ."]
    note = _note(para_index=9)  # index sai → phải dò toàn cục
    assert locate_note_para(paras, note) == 1


def test_locate_ambiguous_or_missing_returns_none():
    # Nhiều đoạn khớp, para_text không khớp đoạn nào → None
    paras = ["hắn nói to.", "hắn nói nhỏ."]
    assert locate_note_para(paras, _note(para_index=5, para_text="không khớp")) is None
    # Không đoạn nào chứa text → None
    assert locate_note_para(["khác hẳn"], _note()) is None
    # selected_text rỗng → None
    assert locate_note_para(["hắn nói"], _note(selected_text="")) is None


# --- apply_note_fix ---


def test_apply_replaces_in_right_para_and_keeps_blank_lines():
    translated = "Mở đầu.\n\nRồi hắn nói một câu.\n\nKết thúc."
    new_text, err = apply_note_fix(translated, _note(), "anh ta nói")
    assert err == ""
    assert new_text == "Mở đầu.\n\nRồi anh ta nói một câu.\n\nKết thúc."


def test_apply_only_first_occurrence_in_target_para():
    translated = "hắn nói rồi hắn nói nữa."
    note = _note(para_index=0, para_text=translated)
    new_text, err = apply_note_fix(translated, note, "y nói")
    assert err == ""
    assert new_text == "y nói rồi hắn nói nữa."


def test_apply_stale_returns_error():
    new_text, err = apply_note_fix("Văn bản đã đổi hoàn toàn.", _note(), "y nói")
    assert new_text is None
    assert "Không tìm thấy" in err


def test_apply_empty_selection_returns_error():
    new_text, err = apply_note_fix("Bất kỳ.", _note(selected_text=""), "x")
    assert new_text is None
    assert err


# --- _parse_fixes ---


def test_parse_fixes_clean_json():
    out = '[{"id": "n1", "fixed_text": "anh ta nói", "explanation": "đúng ngôi"}]'
    assert _parse_fixes(out, {"n1"}) == [
        {"id": "n1", "fixed_text": "anh ta nói", "explanation": "đúng ngôi"}
    ]


def test_parse_fixes_code_fence_and_prose():
    out = 'Đây là kết quả:\n```json\n[{"id": "n1", "fixed_text": "sửa"}]\n```\nHết.'
    assert _parse_fixes(out, {"n1"}) == [{"id": "n1", "fixed_text": "sửa", "explanation": ""}]


def test_parse_fixes_drops_unknown_id_empty_text_and_dupes():
    out = (
        '[{"id": "n1", "fixed_text": "a"}, {"id": "lạ", "fixed_text": "b"},'
        ' {"id": "n2", "fixed_text": ""}, {"id": "n1", "fixed_text": "trùng"}]'
    )
    assert _parse_fixes(out, {"n1", "n2"}) == [{"id": "n1", "fixed_text": "a", "explanation": ""}]


def test_parse_fixes_garbage_returns_empty():
    assert _parse_fixes("không phải json", {"n1"}) == []
    assert _parse_fixes('{"id": "n1"}', {"n1"}) == []  # object, không phải array


# --- replace_para ---


def test_replace_para_middle_keeps_blank_lines():
    translated = "Mở đầu.\n\nRồi hắn nói một câu.\n\nKết thúc."
    new_text, err = replace_para(translated, 1, "Rồi hắn nói một câu.", "Rồi anh ta đáp.")
    assert err == ""
    assert new_text == "Mở đầu.\n\nRồi anh ta đáp.\n\nKết thúc."


def test_replace_para_first_and_last():
    translated = "A.\n\nB.\n\nC."
    first, err = replace_para(translated, 0, "A.", "A2.")
    assert err == "" and first == "A2.\n\nB.\n\nC."
    last, err = replace_para(translated, 2, "C.", "C2.")
    assert err == "" and last == "A.\n\nB.\n\nC2."


def test_replace_para_mismatch_expected_returns_error():
    translated = "A.\n\nB.\n\nC."
    new_text, err = replace_para(translated, 1, "Khác hẳn.", "B2.")
    assert new_text is None
    assert "đã thay đổi" in err


def test_replace_para_index_out_of_range_returns_error():
    translated = "A.\n\nB."
    new_text, err = replace_para(translated, 9, "A.", "x")
    assert new_text is None
    assert "Không tìm thấy" in err


def test_replace_para_multiline_new_text_collapsed_to_one_line():
    # Người dùng dán nhiều dòng → gộp về 1 dòng, không làm lệch đoạn sau.
    translated = "A.\n\nB.\n\nC."
    new_text, err = replace_para(translated, 1, "B.", "B dòng 1.\n\nB dòng 2.")
    assert err == ""
    assert new_text == "A.\n\nB dòng 1. B dòng 2.\n\nC."
    # Đoạn sau (C.) vẫn ở para_index 2
    assert split_paras(new_text)[2] == "C."


def test_replace_para_empty_new_text_deletes_paragraph():
    translated = "A.\n\nB.\n\nC."
    new_text, err = replace_para(translated, 1, "B.", "   \n  ")
    assert new_text == "A.\n\nC."
    assert err == ""
