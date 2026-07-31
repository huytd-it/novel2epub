from novel2epub.glossary_ai import (
    EDIT_HAY_GUIDELINES,
    _parse_evaluation,
    _parse_suggestions,
    format_evaluation_text,
)


def test_edit_guidelines_preserve_valid_contextual_pronouns():
    assert 'Giữ "hắn"' in EDIT_HAY_GUIDELINES
    assert '"Ta/ngươi" hợp lệ' in EDIT_HAY_GUIDELINES
    assert "không lạm dụng ta/ngươi" not in EDIT_HAY_GUIDELINES


def test_parse_plain_json_array():
    text = '[{"source": "庄国", "suggested": "Trang Quốc", "type": "place", "reason": "x"}]'
    result = _parse_suggestions(text)
    assert result == [
        {
            "source": "庄国",
            "suggested": "Trang Quốc",
            "type": "place",
            "reason": "x",
        }
    ]


def test_parse_json_wrapped_in_code_fence():
    text = '```json\n[{"source": "a", "suggested": "b"}]\n```'
    result = _parse_suggestions(text)
    assert result == [
        {"source": "a", "suggested": "b", "type": "term", "reason": ""}
    ]


def test_parse_json_embedded_in_explanation_text():
    text = 'Đây là kết quả:\n[{"source": "a", "suggested": "b"}]\nHết.'
    result = _parse_suggestions(text)
    assert len(result) == 1
    assert result[0]["source"] == "a"


def test_invalid_type_falls_back_to_term_and_target_file_dropped():
    """type sai → fallback "term"; target_file (đã bỏ phân loại) không còn
    trong output kể cả khi AI cũ vẫn emit."""
    text = '[{"source": "a", "suggested": "b", "type": "bogus", "target_file": "bogus.txt"}]'
    result = _parse_suggestions(text)
    assert result[0]["type"] == "term"
    assert "target_file" not in result[0]


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


# ---------------------------------------------------------------------------
# Lọc glossary theo text khi build prompt (glossary_filter)
# ---------------------------------------------------------------------------

def _capture_run_chat(monkeypatch, response):
    from novel2epub import glossary_ai

    captured = {}

    def _mock(cfg, prompt):
        captured["prompt"] = prompt
        return response

    monkeypatch.setattr(glossary_ai.openai_client, "run_chat", _mock)
    return captured


def _ai_cfg():
    from novel2epub.config import OpenAIConfig

    return OpenAIConfig(base_url="https://api.test/v1")


def test_rewrite_chapter_prompt_filters_but_apply_uses_full_glossary(monkeypatch):
    from novel2epub.glossary_ai import rewrite_chapter

    glossary = {"叶凡": "Diệp Phàm", "庄国": "Trang Quốc"}
    # Output AI chứa 庄国 (mục KHÔNG có trong prompt) → _apply_glossary
    # hậu xử lý vẫn phải thay bằng full glossary.
    captured = _capture_run_chat(monkeypatch, "Bản sửa nhắc tới 庄国.")
    out = rewrite_chapter(_ai_cfg(), raw="叶凡出场", current_translation="Diệp Phàm xuất hiện", glossary=glossary)

    assert "叶凡 = Diệp Phàm" in captured["prompt"]
    assert "庄国" not in captured["prompt"]
    assert out == "Bản sửa nhắc tới Trang Quốc."


def test_rewrite_chapter_unfiltered_when_disabled(monkeypatch):
    from novel2epub.glossary_ai import rewrite_chapter

    glossary = {"叶凡": "Diệp Phàm", "庄国": "Trang Quốc"}
    captured = _capture_run_chat(monkeypatch, "OK")
    rewrite_chapter(
        _ai_cfg(), raw="叶凡出场", current_translation="Diệp Phàm xuất hiện",
        glossary=glossary, filter_glossary=False,
    )
    assert "叶凡 = Diệp Phàm" in captured["prompt"]
    assert "庄国 = Trang Quốc" in captured["prompt"]


def test_fix_passages_filters_on_vi_text_when_raw_empty(monkeypatch):
    from novel2epub.glossary_ai import fix_passages

    glossary = {"叶凡": "Diệp Phàm", "庄国": "Trang Quốc"}
    captured = _capture_run_chat(monkeypatch, "[]")
    fix_passages(
        _ai_cfg(), raw="", translated="Diệp Phàm bước ra",
        notes=[{"id": "n1", "para_index": 0, "selected_text": "x", "para_text": "y", "note": "z"}],
        glossary=glossary,
    )
    assert "叶凡 = Diệp Phàm" in captured["prompt"]
    assert "庄国" not in captured["prompt"]


def test_suggest_glossary_filters_existing_block(monkeypatch):
    from novel2epub.glossary_ai import suggest_glossary

    existing = {"叶凡": "Diệp Phàm", "庄国": "Trang Quốc"}
    captured = _capture_run_chat(monkeypatch, "[]")
    suggest_glossary(_ai_cfg(), [("叶凡出场", "Diệp Phàm xuất hiện")], existing)
    assert "叶凡 = Diệp Phàm" in captured["prompt"]
    assert "庄国" not in captured["prompt"]


def test_evaluate_translation_uses_full_glossary(monkeypatch):
    from novel2epub.glossary_ai import evaluate_translation

    glossary = {"叶凡": "Diệp Phàm", "庄国": "Trang Quốc"}
    captured = _capture_run_chat(monkeypatch, '{"summary": "ok", "score": 8, "issues": []}')
    evaluate_translation(_ai_cfg(), [("叶凡出场", "Diệp Phàm xuất hiện")], glossary)
    # evaluate audit TOÀN BỘ glossary (tìm mục thừa/trùng/mâu thuẫn) → không lọc.
    assert "叶凡 = Diệp Phàm" in captured["prompt"]
    assert "庄国 = Trang Quốc" in captured["prompt"]
