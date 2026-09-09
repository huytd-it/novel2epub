from novel2epub.build_validation import _check_strange_markers, validate_chapter_detailed


def test_repeated_common_question_and_exclamation_marks_are_ignored():
    issues = _check_strange_markers("Thật sao??? Không thể nào!!!")

    assert not any(issue["code"] == "repeated_punct" for issue in issues)


def test_repeated_formatting_punctuation_is_still_reported():
    issues = _check_strange_markers("Sai,, rồi; ; ổn:: không--")

    repeated = [issue for issue in issues if issue["code"] == "repeated_punct"]
    assert len(repeated) == 1
    assert repeated[0]["level"] == "warning"


def test_detailed_validation_uses_same_repeated_punctuation_policy():
    result = validate_chapter_detailed("Thật sao??? Sai,, rồi!!!", title="Chương 1: Test")

    repeated = [issue for issue in result["issues"] if issue["code"] == "repeated_punct"]
    assert len(repeated) == 1
    assert "Sai,," in repeated[0]["snippet"]
