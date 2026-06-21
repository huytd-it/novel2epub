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
