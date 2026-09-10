from novel2epub.build_validation import check_content, validate_chapter_detailed


def _codes(issues, *, content_only=False):
    if content_only:
        issues = [i for i in issues if i.get("paraIndex", 0) >= 0]
    return {i["code"] for i in issues}


def test_repeated_common_question_and_exclamation_marks_are_ignored():
    issues = check_content("Thật sao??? Không thể nào!!!")

    assert not any(issue["code"] == "repeated_punct" for issue in issues)


def test_repeated_formatting_punctuation_is_still_reported():
    issues = check_content("Sai,, rồi; ; ổn:: không--")

    repeated = [issue for issue in issues if issue["code"] == "repeated_punct"]
    assert len(repeated) == 1
    assert repeated[0]["level"] == "warning"


def test_detailed_validation_uses_same_repeated_punctuation_policy():
    result = validate_chapter_detailed("Thật sao??? Sai,, rồi!!!", title="Chương 1: Test")

    repeated = [issue for issue in result["issues"] if issue["code"] == "repeated_punct"]
    assert len(repeated) == 1
    assert "Sai,," in repeated[0]["snippet"]


def test_aggregated_and_detailed_report_the_same_codes():
    """Trang Build (gộp) và trang Chương (per-para) phải cùng một tập mã lỗi."""
    text = (
        "Đọc tiếp tại https://truyenfull.vn/chuong-1 nhé.\n"
        "## Tiêu đề sót lại,, và  double space \n"
        "中国語 còn sót ở đây.\n"
        "Đoạn này bình thường, không có gì lạ."
    )

    aggregated = _codes(check_content(text))
    detailed = _codes(validate_chapter_detailed(text, title="Chương 1: Test")["issues"], content_only=True)

    assert aggregated == detailed
    assert "url" in aggregated


def test_url_check_catches_links_and_bare_domains():
    issues = check_content(
        "Đọc tiếp tại https://truyenfull.vn/abc nhé.\nGhé thăm truyenfull.vn hoặc www.metruyenchu.com."
    )

    url = [issue for issue in issues if issue["code"] == "url"]
    assert len(url) == 1
    assert url[0]["level"] == "warning"
    assert "3" in url[0]["message"]


def test_url_check_does_not_flag_plain_vietnamese_prose():
    text = (
        "Hắn nói: “Chuyện này không đơn giản.” Rồi lặng lẽ bỏ đi.\n"
        "Từ từ thôi, cô ấy vẫn còn ở đó."
    )

    assert not any(issue["code"] == "url" for issue in check_content(text))


def test_punctuation_inside_url_is_not_reported_as_spelling_issue():
    issues = check_content("Nguồn: https://truyenfull.vn/chuong-1.html")

    assert _codes(issues) == {"url"}


def test_repeated_word_only_reported_when_unusual_in_one_paragraph():
    ok = "Từ từ thôi, xa xa có bóng người, nhè nhẹ gió thổi qua."
    assert not any(issue["code"] == "repeated_word" for issue in check_content(ok))

    noisy = "rồi rồi ạ, thôi thôi nào, đi đi mà, nhanh nhanh lên nhé."
    assert any(issue["code"] == "repeated_word" for issue in check_content(noisy))


def test_han_cluster_is_reported_once_per_cluster():
    issues = check_content("中国語 xuất hiện ở đây.")

    han = [issue for issue in issues if issue["code"] == "han_remaining"]
    assert len(han) == 1
    assert han[0]["level"] == "warning"
    assert "1 cụm" in han[0]["message"]
