import subprocess

import pytest

from novel2epub import cli_runner
from novel2epub.translator import _apply_glossary, _clean_output, _parse_title_response, load_glossary_dict
from novel2epub.config import CliTranslatorConfig, TranslateConfig, GlossaryFilesConfig


def _fake_completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=["x"], returncode=returncode, stdout=stdout, stderr=stderr)


def test_run_cli_raises_on_nonzero_with_stderr(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake_completed(returncode=1, stderr="auth failed"))
    cli = CliTranslatorConfig(command="dummy", mode="stdin")
    with pytest.raises(RuntimeError, match="auth failed"):
        cli_runner.run_cli(cli, "xin chào", argv=["dummy"])


def test_run_cli_raises_when_exit0_but_empty_output(monkeypatch):
    # AI CLI hay thoát mã 0 mà vẫn lỗi (rate-limit) -> stdout rỗng, stderr có lỗi.
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake_completed(returncode=0, stdout="  \n", stderr="rate limited"))
    cli = CliTranslatorConfig(command="dummy", mode="stdin")
    with pytest.raises(RuntimeError, match="rate limited"):
        cli_runner.run_cli(cli, "xin chào", argv=["dummy"])


def test_run_cli_returns_stdout_on_success(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake_completed(returncode=0, stdout="Xin chào"))
    cli = CliTranslatorConfig(command="dummy", mode="stdin")
    assert cli_runner.run_cli(cli, "hi", argv=["dummy"]) == "Xin chào"


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


def test_go_preset_chapter_translation_uses_opencode(monkeypatch):
    from novel2epub.translator import CLITranslator, make_translator

    cfg = TranslateConfig(
        type="cli",
        preset="go",
        cli=CliTranslatorConfig(
            command="opencode run",
            model="opencode-go/deepseek-v4-flash",
            prompt_template="",
            title_prompt_template="",
            mode="stdin",
            timeout_seconds=300,
        ),
    )
    captured = {}

    def _mock_run_cli(cli, prompt, argv=None):
        captured["command"] = cli.command
        captured["model"] = cli.model
        return "Bản dịch tiếng Việt."

    monkeypatch.setattr("novel2epub.translator.cli_runner.run_cli", _mock_run_cli)
    translator = make_translator(cfg)
    result = translator.translate("你好世界")
    assert result == "Bản dịch tiếng Việt."
    assert captured["command"] == "opencode run"
    assert captured["model"] == "opencode-go/deepseek-v4-flash"


def test_go_preset_title_translation_uses_opencode(monkeypatch):
    from novel2epub.translator import make_translator

    cfg = TranslateConfig(
        type="cli",
        preset="go",
        cli=CliTranslatorConfig(
            command="opencode run",
            model="opencode-go/deepseek-v4-flash",
            prompt_template="",
            title_prompt_template="",
            mode="stdin",
            timeout_seconds=300,
        ),
    )
    captured = {}

    def _mock_run_cli(cli, prompt, argv=None):
        captured["command"] = cli.command
        captured["prompt"] = prompt
        return "TIÊU ĐỀ: Chương Một\nGIẢI THÍCH: "

    monkeypatch.setattr("novel2epub.translator.cli_runner.run_cli", _mock_run_cli)
    translator = make_translator(cfg)
    title, note = translator.translate_title("第一章", kind="tên chương")
    assert title == "Chương Một"
    assert captured["command"] == "opencode run"


def test_go_preset_error_guides_auth(monkeypatch):
    from novel2epub.translator import make_translator

    cfg = TranslateConfig(
        type="cli",
        preset="go",
        cli=CliTranslatorConfig(
            command="opencode run",
            model="opencode-go/deepseek-v4-flash",
            prompt_template="{text}",
            title_prompt_template="",
            mode="stdin",
            timeout_seconds=300,
        ),
    )

    def _mock_run_cli(cli, prompt, argv=None):
        raise FileNotFoundError("opencode not found")

    monkeypatch.setattr("novel2epub.translator.cli_runner.run_cli", _mock_run_cli)
    translator = make_translator(cfg)
    with pytest.raises(RuntimeError) as exc:
        translator.translate("test")
    msg = str(exc.value)
    assert "opencode" in msg.lower() or "opencode" in msg
