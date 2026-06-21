from novel2epub.glossary_ai import _parse_evaluation, _parse_suggestions, format_evaluation_text


def test_parse_plain_json_array():
    text = '[{"source": "庄国", "suggested": "Trang Quốc", "type": "place", "reason": "x", "target_file": "names.txt"}]'
    result = _parse_suggestions(text)
    assert result == [
        {
            "source": "庄国",
            "suggested": "Trang Quốc",
            "type": "place",
            "reason": "x",
            "target_file": "names.txt",
        }
    ]


def test_parse_json_wrapped_in_code_fence():
    text = '```json\n[{"source": "a", "suggested": "b"}]\n```'
    result = _parse_suggestions(text)
    assert result == [
        {"source": "a", "suggested": "b", "type": "term", "reason": "", "target_file": "vietphrase.txt"}
    ]


def test_parse_json_embedded_in_explanation_text():
    text = 'Đây là kết quả:\n[{"source": "a", "suggested": "b"}]\nHết.'
    result = _parse_suggestions(text)
    assert len(result) == 1
    assert result[0]["source"] == "a"


def test_invalid_type_and_target_file_fall_back_to_defaults():
    text = '[{"source": "a", "suggested": "b", "type": "bogus", "target_file": "bogus.txt"}]'
    result = _parse_suggestions(text)
    assert result[0]["type"] == "term"
    assert result[0]["target_file"] == "vietphrase.txt"


def test_missing_source_or_suggested_is_dropped():
    text = '[{"source": "a"}, {"suggested": "b"}, {"source": "a", "suggested": "b"}]'
    result = _parse_suggestions(text)
    assert len(result) == 1


def test_non_list_json_returns_empty():
    assert _parse_suggestions('{"not": "a list"}') == []


def test_unparseable_text_returns_empty():
    assert _parse_suggestions("hoàn toàn không phải JSON") == []


def test_empty_array_returns_empty():
    assert _parse_suggestions("[]") == []


def test_parse_evaluation_valid_object():
    text = (
        '{"summary": "Tạm ổn", "score": 8, "issues": ['
        '{"category": "glossary", "severity": "high", "chapter": "1", "source": "庄国",'
        ' "current": "Trang quốc", "suggestion": "Trang Quốc", "reason": "viết hoa"}]}'
    )
    report = _parse_evaluation(text)
    assert report["summary"] == "Tạm ổn"
    assert report["score"] == 8
    assert len(report["issues"]) == 1
    assert report["issues"][0]["category"] == "glossary"
    assert report["issues"][0]["severity"] == "high"


def test_parse_evaluation_embedded_in_text_uses_fallback_regex():
    text = 'Đây là báo cáo:\n{"summary": "x", "score": null, "issues": []}\nHết.'
    report = _parse_evaluation(text)
    assert report["summary"] == "x"
    assert report["score"] is None
    assert report["issues"] == []


def test_parse_evaluation_invalid_category_and_severity_fall_back():
    text = '{"summary": "", "issues": [{"category": "bogus", "severity": "huge"}]}'
    report = _parse_evaluation(text)
    assert report["issues"][0]["category"] == "other"
    assert report["issues"][0]["severity"] == "low"


def test_parse_evaluation_non_numeric_score_becomes_none():
    report = _parse_evaluation('{"summary": "x", "score": "tốt", "issues": []}')
    assert report["score"] is None


def test_parse_evaluation_garbage_returns_empty_report():
    report = _parse_evaluation("hoàn toàn không phải JSON")
    assert report == {"summary": "", "score": None, "issues": []}


def test_format_evaluation_text_no_issues():
    out = format_evaluation_text({"summary": "ổn", "score": 9, "issues": []})
    assert "9/10" in out
    assert "Không phát hiện vấn đề" in out


def test_format_evaluation_text_lists_issues():
    report = {
        "summary": "có lỗi",
        "score": None,
        "issues": [
            {
                "category": "mistranslation",
                "severity": "high",
                "chapter": "2",
                "source": "金丹",
                "current": "đan vàng",
                "suggestion": "Kim Đan",
                "reason": "thuật ngữ",
            }
        ],
    }
    out = format_evaluation_text(report)
    assert "Vấn đề (1)" in out
    assert "đan vàng -> Kim Đan" in out
