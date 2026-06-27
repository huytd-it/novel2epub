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
    assert cfg.translate.openai.base_url == "https://api.openai.com/v1"
    assert cfg.translate.openai.model == "gpt-4o-mini"


def test_go_preset_resolution(tmp_path):
    config_path = _write_config(
        tmp_path,
        extra={"translate": {"preset": "go"}},
    )
    cfg = load_config(config_path)
    assert cfg.translate.preset == "go"
    assert "Dịch đoạn văn" in cfg.translate.openai.prompt_template


def test_go_preset_override(tmp_path):
    config_path = _write_config(
        tmp_path,
        extra={
            "translate": {
                "preset": "go",
                "openai": {
                    "model": "custom-model",
                    "timeout_seconds": 600,
                },
            }
        },
    )
    cfg = load_config(config_path)
    assert cfg.translate.preset == "go"
    assert cfg.translate.openai.model == "custom-model"
    assert cfg.translate.openai.timeout_seconds == 600
    assert "Dịch đoạn văn" in cfg.translate.openai.prompt_template


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
                    "crawl": {"engine": "scrapling", "content_selector": "#default"},
                    "translate": {"type": "none", "openai": {"base_url": "https://custom.test/v1"}},
                    "output": {"data_dir": "data"},
                },
                "ebooks": {
                    "a": {
                        "name": "Truyện A",
                        "novel": {"slug": "a", "title": "A"},
                        "crawl": {"toc_url": "https://a", "scrapling": {"mode": "stealthy"}},
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
    assert cfg_a.crawl.engine == "scrapling"          # từ defaults (không override)
    assert cfg_a.crawl.scrapling.mode == "stealthy"   # override từ ebook a
    assert cfg_a.crawl.content_selector == "#default"  # kế thừa defaults
    assert cfg_a.crawl.toc_url == "https://a"
    assert cfg_a.translate.openai.base_url == "https://custom.test/v1"  # kế thừa defaults

    # Slug rỗng -> lấy ebook đầu tiên.
    assert load_config(path).novel.slug == "a"
    # Ebook 'b' chỉ override toc_url, mọi thứ khác từ defaults.
    cfg_b = load_config(path, "b")
    assert cfg_b.crawl.engine == "scrapling"
    assert cfg_b.crawl.content_selector == "#default"


def test_unified_file_unknown_slug_raises(tmp_path):
    path = tmp_path / "novel2epub.yaml"
    path.write_text(
        yaml.safe_dump({"defaults": {}, "ebooks": {"a": {"novel": {"slug": "a"}}}}),
        encoding="utf-8",
    )
    with pytest.raises(KeyError, match="nonexistent"):
        load_config(path, "nonexistent")


def test_default_translate_type_is_hachimimt(tmp_path):
    """Không khai báo translate.type → mặc định type=hachimimt."""
    path = tmp_path / "novel2epub.yaml"
    path.write_text(
        yaml.safe_dump({
            "novel": {"slug": "test"},
            "crawl": {"toc_url": "https://example.com"},
            "translate": {},
            "output": {"data_dir": "data"},
        }),
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.translate.type == "hachimimt"


def test_hachimimt_auto_preset(tmp_path):
    """model preset HachimiMT-60 → model_key được gán đúng."""
    path = tmp_path / "novel2epub.yaml"
    path.write_text(
        yaml.safe_dump({
            "novel": {"slug": "test"},
            "crawl": {"toc_url": "https://example.com"},
            "translate": {
                "type": "hachimimt",
                "model": "hachimimt-60",
            },
            "output": {"data_dir": "data"},
        }),
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.translate.hachimimt.model_key == "HachimiMT-60"


def test_hachimimt_auto_preset_respects_user_override(tmp_path):
    """User override model_key → không bị preset ghi đè."""
    path = tmp_path / "novel2epub.yaml"
    path.write_text(
        yaml.safe_dump({
            "novel": {"slug": "test"},
            "crawl": {"toc_url": "https://example.com"},
            "translate": {
                "type": "hachimimt",
                "model": "hachimimt-60",
                "hachimimt": {
                    "model_key": "MoxhiMT-60",
                    "beam_size": 4,
                },
            },
            "output": {"data_dir": "data"},
        }),
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.translate.hachimimt.model_key == "MoxhiMT-60"  # user override wins
    assert cfg.translate.hachimimt.beam_size == 4
