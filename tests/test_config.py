from pathlib import Path

import pytest
import yaml

from novel2epub.config import CrawlConfig, load_config


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
    with pytest.raises(ValueError, match="nonexistent"):
        load_config(config_path)


def test_crawl_config_pagination_defaults():
    """Pagination fields default to safe values; existing configs still load."""
    cfg = CrawlConfig(toc_url="https://example.com/book/")
    assert cfg.next_page_selector == ""
    assert cfg.next_page_url_pattern == ""
    assert cfg.max_pages_per_chapter == 10


def test_crawl_config_pagination_fields_round_trip(tmp_path):
    """Pagination fields survive load_config / YAML round-trip."""
    config_path = _write_config(
        tmp_path,
        extra={
            "crawl": {
                "toc_url": "https://example.com/book/",
                "next_page_selector": "a#pager_next",
                "next_page_url_pattern": r"(\d+)\.html$",
                "max_pages_per_chapter": 4,
            }
        },
    )
    cfg = load_config(config_path)
    assert cfg.crawl.next_page_selector == "a#pager_next"
    assert cfg.crawl.next_page_url_pattern == r"(\d+)\.html$"
    assert cfg.crawl.max_pages_per_chapter == 4


def test_crawl_config_rejects_pattern_with_zero_capturing_groups():
    with pytest.raises(ValueError, match="capturing group"):
        CrawlConfig(toc_url="https://example.com", next_page_url_pattern=r"\.html$")


def test_crawl_config_rejects_pattern_with_two_capturing_groups():
    with pytest.raises(ValueError, match="capturing group"):
        CrawlConfig(
            toc_url="https://example.com",
            next_page_url_pattern=r"(\d+)_(\d+)\.html$",
        )


def test_crawl_config_rejects_invalid_regex():
    with pytest.raises(ValueError, match="regex"):
        CrawlConfig(
            toc_url="https://example.com",
            next_page_url_pattern=r"(unclosed",
        )


def test_unified_file_merges_defaults_with_ebook_override(tmp_path):
    """File gộp: config hiệu lực = deep_merge(defaults, ebooks[slug])."""
    path = tmp_path / "novel2epub.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "defaults": {
                    "crawl": {"engine": "http", "content_selector": "#default"},
                    "translate": {"type": "none", "cli": {"command": "claude -p"}},
                    "output": {"data_dir": "data"},
                },
                "ebooks": {
                    "a": {
                        "name": "Truyện A",
                        "novel": {"slug": "a", "title": "A"},
                        "crawl": {"toc_url": "https://a", "engine": "crawl4ai"},
                    },
                    "b": {
                        "novel": {"slug": "b"},
                        "crawl": {"toc_url": "https://b"},
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    cfg_a = load_config(path, "a")
    assert cfg_a.novel.title == "A"
    assert cfg_a.crawl.engine == "crawl4ai"          # override
    assert cfg_a.crawl.content_selector == "#default"  # kế thừa defaults
    assert cfg_a.crawl.toc_url == "https://a"
    assert cfg_a.translate.cli.command == "claude -p"  # kế thừa defaults

    # Slug rỗng -> lấy ebook đầu tiên.
    assert load_config(path).novel.slug == "a"
    # Ebook 'b' chỉ override toc_url, mọi thứ khác từ defaults.
    cfg_b = load_config(path, "b")
    assert cfg_b.crawl.engine == "http"
    assert cfg_b.crawl.content_selector == "#default"


def test_unified_file_unknown_slug_raises(tmp_path):
    path = tmp_path / "novel2epub.yaml"
    path.write_text(
        yaml.safe_dump({"defaults": {}, "ebooks": {"a": {"novel": {"slug": "a"}}}}),
        encoding="utf-8",
    )
    with pytest.raises(KeyError, match="nonexistent"):
        load_config(path, "nonexistent")
