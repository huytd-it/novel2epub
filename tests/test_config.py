from pathlib import Path

import yaml

from novel2epub.config import load_config


def _write_config(tmp_path: Path, extra: dict | None = None) -> Path:
    data = {
        "novel": {"slug": "my-novel"},
        "crawl": {"toc_url": "https://example.com"},
        "translate": {"type": "none"},
        "output": {"data_dir": "data"},
    }
    if extra:
        data.update(extra)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_glossary_files_default_to_data_dir_glossary_folder(tmp_path):
    config_path = _write_config(tmp_path)
    cfg = load_config(config_path)

    expected_dir = (tmp_path / "data" / "my-novel" / "glossary").resolve()
    assert Path(cfg.translate.glossary_files.names) == expected_dir / "names.txt"
    assert Path(cfg.translate.glossary_files.vietphrase) == expected_dir / "vietphrase.txt"


def test_glossary_files_explicit_path_is_respected(tmp_path):
    config_path = _write_config(
        tmp_path,
        extra={"translate": {"type": "none", "glossary_files": {"names": "custom/names.txt"}}},
    )
    cfg = load_config(config_path)

    assert Path(cfg.translate.glossary_files.names) == (tmp_path / "custom" / "names.txt").resolve()
    # vietphrase không khai báo riêng -> vẫn rơi về default trong data_dir.
    expected_default = (tmp_path / "data" / "my-novel" / "glossary" / "vietphrase.txt").resolve()
    assert Path(cfg.translate.glossary_files.vietphrase) == expected_default


def test_no_preset_backward_compat(tmp_path):
    config_path = _write_config(tmp_path, extra={"translate": {"type": "none"}})
    cfg = load_config(config_path)
    assert cfg.translate.preset == ""
    assert cfg.translate.cli.command == "claude -p"
    assert cfg.translate.cli.model == ""


def test_go_preset_resolution(tmp_path):
    config_path = _write_config(
        tmp_path,
        extra={"translate": {"preset": "go"}},
    )
    cfg = load_config(config_path)
    assert cfg.translate.preset == "go"
    assert cfg.translate.type == "cli"
    assert cfg.translate.cli.command == "opencode run"
    assert cfg.translate.cli.model == "opencode-go/deepseek-v4-flash"
    assert "Dịch đoạn văn" in cfg.translate.cli.prompt_template
    assert cfg.translate.cli.mode == "stdin"


def test_go_preset_override(tmp_path):
    config_path = _write_config(
        tmp_path,
        extra={
            "translate": {
                "preset": "go",
                "cli": {
                    "model": "opencode-go/qwen3.7-plus",
                    "timeout_seconds": 600,
                },
            }
        },
    )
    cfg = load_config(config_path)
    assert cfg.translate.preset == "go"
    assert cfg.translate.cli.command == "opencode run"
    assert cfg.translate.cli.model == "opencode-go/qwen3.7-plus"
    assert cfg.translate.cli.timeout_seconds == 600


def test_unknown_preset_raises(tmp_path):
    config_path = _write_config(
        tmp_path,
        extra={"translate": {"preset": "nonexistent"}},
    )
    import pytest
    with pytest.raises(ValueError, match="nonexistent"):
        load_config(config_path)
