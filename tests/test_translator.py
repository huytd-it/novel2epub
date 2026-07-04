import pytest
import requests

from novel2epub import openai_client
from novel2epub.translator import _apply_glossary, _clean_output, _parse_title_response, load_glossary_dict
from novel2epub.config import OpenAIConfig, TranslateConfig, GlossaryFilesConfig


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text

    def json(self):
        return self._json_data


def _chat_response(content):
    return _FakeResponse(200, {"choices": [{"message": {"content": content}}]})


def test_run_chat_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: _FakeResponse(401, text="auth failed"))
    cfg = OpenAIConfig(base_url="https://api.test/v1")
    with pytest.raises(RuntimeError, match="auth failed"):
        openai_client.run_chat(cfg, "xin chào")


def test_run_chat_raises_when_content_empty(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: _chat_response("   "))
    cfg = OpenAIConfig(base_url="https://api.test/v1")
    with pytest.raises(RuntimeError, match="rỗng"):
        openai_client.run_chat(cfg, "xin chào")


def test_run_chat_returns_content_on_success(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: _chat_response("Xin chào"))
    cfg = OpenAIConfig(base_url="https://api.test/v1")
    assert openai_client.run_chat(cfg, "hi") == "Xin chào"


def test_clean_output_strips_code_fence():
    assert _clean_output("```\nXin chào\n```") == "Xin chào"


def test_clean_output_strips_preamble_line():
    assert _clean_output("Đây là bản dịch:\nXin chào") == "Xin chào"


def test_clean_output_passthrough_plain_text():
    assert _clean_output("Xin chào thế giới") == "Xin chào thế giới"


def test_apply_glossary_replaces_all_occurrences():
    text = "庄国 đại chiến 庄国"
    out = _apply_glossary(text, {"庄国": "Trang Quốc"})
    assert out == "Trang Quốc đại chiến Trang Quốc"


def test_load_glossary_dict_merges_inline_and_files(tmp_path):
    names = tmp_path / "names.txt"
    names.write_text("庄国 = Trang Quốc\n", encoding="utf-8")
    vietphrase = tmp_path / "vietphrase.txt"
    vietphrase.write_text("元气 = nguyên khí\n", encoding="utf-8")

    cfg = TranslateConfig(
        glossary={"元宵": "Nguyên Tiêu"},
        glossary_files=GlossaryFilesConfig(names=str(names), vietphrase=str(vietphrase)),
    )

    result = load_glossary_dict(cfg)

    assert result == {
        "元宵": "Nguyên Tiêu",
        "庄国": "Trang Quốc",
        "元气": "nguyên khí",
    }


def test_load_glossary_dict_strips_note(tmp_path):
    names = tmp_path / "names.txt"
    names.write_text("庄国 = Trang Quốc | nước hư cấu\n", encoding="utf-8")

    cfg = TranslateConfig(
        glossary_files=GlossaryFilesConfig(names=str(names), vietphrase=""),
    )
    result = load_glossary_dict(cfg)
    # Note KHÔNG được lọt vào target (tránh thay thế literal sai khi dịch).
    assert result == {"庄国": "Trang Quốc"}


def test_load_glossary_dict_ignores_missing_files():
    cfg = TranslateConfig(
        glossary={"元宵": "Nguyên Tiêu"},
        glossary_files=GlossaryFilesConfig(names="/khong/ton/tai.txt", vietphrase=""),
    )
    assert load_glossary_dict(cfg) == {"元宵": "Nguyên Tiêu"}


def test_parse_title_response_standard_format():
    raw = "TIÊU ĐỀ: Tay nắm tay, cùng nhau cất bước\nGIẢI THÍCH: "
    title, note = _parse_title_response(raw)
    assert title == "Tay nắm tay, cùng nhau cất bước"
    assert note == ""


def test_parse_title_response_with_note():
    raw = "TIÊU ĐỀ: Mở đầu\nGIẢI THÍCH: Nghĩa gốc là 'lời nói đầu', dịch thoát ý cho gọn."
    title, note = _parse_title_response(raw)
    assert title == "Mở đầu"
    assert note == "Nghĩa gốc là 'lời nói đầu', dịch thoát ý cho gọn."


def test_parse_title_response_missing_note_line():
    raw = "TIÊU ĐỀ: Chỉ có tiêu đề"
    title, note = _parse_title_response(raw)
    assert title == "Chỉ có tiêu đề"
    assert note == ""


def test_parse_title_response_fallback_when_no_format():
    raw = "Tên truyện không theo format"
    title, note = _parse_title_response(raw)
    assert title == "Tên truyện không theo format"
    assert note == ""


def test_go_preset_chapter_translation_uses_openai(monkeypatch):
    from novel2epub.translator import make_translator

    cfg = TranslateConfig(
        type="openai",
        preset="go",
        openai=OpenAIConfig(
            base_url="https://api.test/v1",
            model="test-model",
            prompt_template="",
            title_prompt_template="",
            timeout_seconds=300,
        ),
    )
    captured = {}

    def _mock_run_chat(cfg_, prompt):
        captured["base_url"] = cfg_.base_url
        captured["model"] = cfg_.model
        return "Bản dịch tiếng Việt."

    monkeypatch.setattr("novel2epub.translator.openai_client.run_chat", _mock_run_chat)
    translator = make_translator(cfg)
    result = translator.translate("你好世界")
    assert result == "Bản dịch tiếng Việt."
    assert captured["base_url"] == "https://api.test/v1"
    assert captured["model"] == "test-model"


def test_translate_retries_when_output_has_residual_chinese(monkeypatch):
    from novel2epub.translator import make_translator

    cfg = TranslateConfig(
        type="openai",
        openai=OpenAIConfig(
            base_url="https://api.test/v1",
            prompt_template="{text}",
            title_prompt_template="{text}",
        ),
    )
    calls = []

    def _mock_run_chat(cfg_, prompt):
        calls.append(prompt)
        if len(calls) == 1:
            return "Xin chào 世界"
        return "Xin chào thế giới"

    monkeypatch.setattr("novel2epub.translator.openai_client.run_chat", _mock_run_chat)
    translator = make_translator(cfg)
    result = translator.translate("你好世界")
    assert result == "Xin chào thế giới"
    assert len(calls) == 2
    assert "LƯU Ý QUAN TRỌNG" in calls[1]


def test_translate_stops_retrying_when_chinese_does_not_improve(monkeypatch):
    from novel2epub.translator import make_translator

    cfg = TranslateConfig(
        type="openai",
        openai=OpenAIConfig(
            base_url="https://api.test/v1",
            prompt_template="{text}",
            title_prompt_template="{text}",
        ),
    )
    calls = []

    def _mock_run_chat(cfg_, prompt):
        calls.append(prompt)
        return "Xin chào 世界"

    monkeypatch.setattr("novel2epub.translator.openai_client.run_chat", _mock_run_chat)
    translator = make_translator(cfg)
    result = translator.translate("你好世界")
    assert result == "Xin chào 世界"
    assert len(calls) == 2


def test_go_preset_title_translation_uses_openai(monkeypatch):
    from novel2epub.translator import make_translator

    cfg = TranslateConfig(
        type="openai",
        preset="go",
        openai=OpenAIConfig(
            base_url="https://api.test/v1",
            model="test-model",
            prompt_template="",
            title_prompt_template="",
            timeout_seconds=300,
        ),
    )
    captured = {}

    def _mock_run_chat(cfg_, prompt):
        captured["base_url"] = cfg_.base_url
        captured["prompt"] = prompt
        return "TIÊU ĐỀ: Chương Một\nGIẢI THÍCH: "

    monkeypatch.setattr("novel2epub.translator.openai_client.run_chat", _mock_run_chat)
    translator = make_translator(cfg)
    title, note = translator.translate_title("第一章", kind="tên chương")
    assert title == "Chương Một"
    assert captured["base_url"] == "https://api.test/v1"


def test_translate_raises_when_ai_call_fails(monkeypatch):
    from novel2epub.translator import make_translator

    cfg = TranslateConfig(
        type="openai",
        openai=OpenAIConfig(
            base_url="https://api.test/v1",
            prompt_template="{text}",
            title_prompt_template="",
        ),
    )

    def _mock_run_chat(cfg_, prompt):
        raise RuntimeError("AI trả về mã lỗi HTTP 401")

    monkeypatch.setattr("novel2epub.translator.openai_client.run_chat", _mock_run_chat)
    translator = make_translator(cfg)
    with pytest.raises(RuntimeError, match="401"):
        translator.translate("test")


# ── Tests cho Auto-Glossary (extend_glossary) ──────────────────────


class _MockStorage:
    """Ghi lại các lần gọi append_glossary_line."""
    def __init__(self):
        self.written: list[tuple[str, str]] = []

    def append_glossary_line(self, name: str, line: str) -> None:
        self.written.append((name, line))

    def glossary_path(self, name: str):
        from pathlib import Path
        return Path(name)


def _make_openai_translator(**kwargs) -> "OpenAITranslator":
    cfg = TranslateConfig(
        type="openai",
        openai=OpenAIConfig(
            base_url="https://api.test/v1",
            model="test-model",
            api_key="test-key",
            prompt_template="",
            title_prompt_template="",
        ),
        **kwargs,
    )
    from novel2epub.translator import OpenAITranslator
    return OpenAITranslator(cfg)


def test_extend_glossary_added():
    """Entry mới → add vào in-memory + ghi file."""
    t = _make_openai_translator()
    storage = _MockStorage()
    result = t.extend_glossary({"叶凡": "Diệp Phàm"}, "names.txt", storage)

    assert len(result["added"]) == 1
    assert len(result["conflicts"]) == 0
    assert t.glossary["叶凡"] == "Diệp Phàm"
    assert storage.written == [("names.txt", "叶凡 = Diệp Phàm")]


def test_extend_glossary_unchanged():
    """Source đã có cùng value → skip, không ghi file."""
    t = _make_openai_translator()
    t.glossary["叶凡"] = "Diệp Phàm"
    storage = _MockStorage()
    result = t.extend_glossary({"叶凡": "Diệp Phàm"}, "names.txt", storage)

    assert len(result["added"]) == 0
    assert len(result["conflicts"]) == 0
    assert storage.written == []


def test_extend_glossary_conflict_existing_wins():
    """Source đã có khác value → existing wins, conflict báo lại."""
    t = _make_openai_translator()
    t.glossary["叶凡"] = "Diệp Phàm"
    storage = _MockStorage()
    result = t.extend_glossary({"叶凡": "Diệp Phà (cũ)"}, "names.txt", storage)

    assert len(result["added"]) == 0
    assert len(result["conflicts"]) == 1
    c = result["conflicts"][0]
    assert c["source"] == "叶凡"
    assert c["existing"] == "Diệp Phàm"
    assert c["new"] == "Diệp Phà (cũ)"
    assert c["target_file"] == "names.txt"
    # In-memory vẫn giữ giá trị cũ
    assert t.glossary["叶凡"] == "Diệp Phàm"
    # File không được ghi
    assert storage.written == []


def test_extend_glossary_accumulates_conflicts():
    """Nhiều conflict tích lũy trong _auto_glossary_conflicts, drain_conflicts trả hết."""
    t = _make_openai_translator()
    t.glossary["叶凡"] = "Diệp Phàm"
    t.glossary["林动"] = "Lâm Động"
    storage = _MockStorage()
    t.extend_glossary({"叶凡": "Diệp Phà (cũ)"}, "names.txt", storage)
    t.extend_glossary({"林动": "Lâm Động (khác)"}, "names.txt", storage)

    drained = t.drain_conflicts()
    assert len(drained) == 2
    # drain xong list rỗng
    assert t.drain_conflicts() == []


def test_extend_glossary_skips_empty_source():
    """Entry với source/suggested rỗng bị bỏ qua."""
    t = _make_openai_translator()
    storage = _MockStorage()
    result = t.extend_glossary({"": "something", "valid": ""}, "names.txt", storage)
    assert len(result["added"]) == 0
    assert len(result["conflicts"]) == 0
