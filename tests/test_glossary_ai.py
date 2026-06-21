from novel2epub.glossary_ai import _parse_suggestions


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
