from pathlib import Path

import pytest

from novel2epub.config import CrawlConfig, load_config
from tests.conftest import write_db_config


def _write_config(tmp_path: Path, extra: dict | None = None) -> Path:
    ebook = {
        "novel": {"slug": "my-novel"},
        "crawl": {"toc_url": "https://example.com"},
    }
    defaults = {"translate": {"type": "none"}, "output": {"data_dir": "data"}}
    if extra:
        for key in ("crawl",):
            if key in extra:
                ebook[key] = extra[key]
        for key in ("translate", "output"):
            if key in extra:
                defaults[key] = extra[key]
    path = tmp_path / "novel2epub.db"
    return write_db_config(path, defaults=defaults, ebooks={"my-novel": ebook})


def test_glossary_files_default_empty_for_sqlite_only(tmp_path):
    config_path = _write_config(tmp_path)
    cfg = load_config(config_path)

    assert cfg.translate.glossary_files.names == ""
    assert cfg.translate.glossary_files.vietphrase == ""


def test_glossary_files_explicit_path_is_ignored(tmp_path):
    custom = tmp_path / "custom" / "names.txt"
    custom.parent.mkdir(parents=True)
    custom.write_text("元宵 = Nguyên Tiêu\n", encoding="utf-8")
    config_path = _write_config(
        tmp_path,
        extra={"translate": {"type": "none", "glossary_files": {"names": "custom/names.txt"}}},
    )
    cfg = load_config(config_path)

    assert cfg.translate.glossary_files.names == ""
    assert cfg.translate.glossary_files.vietphrase == ""


def test_glossary_files_stale_path_is_ignored_without_warning(tmp_path):
    """glossary_files cũ không còn ảnh hưởng config; SQLite là nguồn duy nhất."""
    config_path = _write_config(
        tmp_path,
        extra={"translate": {"type": "none", "glossary_files": {"names": "khong/ton/tai.txt"}}},
    )
    cfg = load_config(config_path)

    assert cfg.translate.glossary_files.names == ""
    assert not any("glossary_files" in w for w in cfg.warnings)


def test_no_preset_backward_compat(tmp_path):
    config_path = _write_config(tmp_path, extra={"translate": {"type": "none"}})
    cfg = load_config(config_path)
    assert cfg.translate.preset == ""
    assert cfg.translate.openai.base_url == "http://localhost:20128/v1"
    assert cfg.translate.openai.model == "free-stack"


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
    """Pagination fields survive load_config round-trip qua DB."""
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


def test_solve_cloudflare_warns_when_mode_not_stealthy(tmp_path):
    """solve_cloudflare chỉ có tác dụng ở mode stealthy — mode khác phải cảnh báo.

    Không cảnh báo = user set cờ, hệ thống im lặng vứt đi, rồi crawl fail với
    lý do hoàn toàn khác (mục lục 0 chương).
    """
    config_path = _write_config(
        tmp_path,
        extra={
            "crawl": {
                "toc_url": "https://example.com/book/",
                "scrapling": {"mode": "dynamic", "solve_cloudflare": True},
            }
        },
    )
    cfg = load_config(config_path)

    assert any(
        "solve_cloudflare" in w and "dynamic" in w for w in cfg.warnings
    ), f"thiếu cảnh báo solve_cloudflare bị bỏ qua; warnings={cfg.warnings}"


def test_solve_cloudflare_no_warning_when_stealthy(tmp_path):
    """Mode stealthy dùng được solve_cloudflare — không được cảnh báo thừa."""
    config_path = _write_config(
        tmp_path,
        extra={
            "crawl": {
                "toc_url": "https://example.com/book/",
                "scrapling": {"mode": "stealthy", "solve_cloudflare": True},
            }
        },
    )
    cfg = load_config(config_path)

    assert not any("solve_cloudflare" in w for w in cfg.warnings)


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


def test_crawl_config_accepts_named_capturing_group():
    """Group đặt tên vẫn là group 1 — không được tính thành 2 group."""
    cfg = CrawlConfig(
        toc_url="https://example.com",
        next_page_url_pattern=r"(?P<page>\d+)\.html$",
    )
    assert cfg.next_page_url_pattern == r"(?P<page>\d+)\.html$"


def test_load_config_skips_broken_pattern_instead_of_raising(tmp_path):
    """Pattern hỏng đã nằm trong DB chỉ được tắt phân trang + cảnh báo.

    Ném ValueError lúc load làm chết cả trang thư viện (mọi ebook), không chỉ
    ebook có config sai — xem lỗi 500 ở /api/ui/library.
    """
    config_path = _write_config(
        tmp_path,
        extra={
            "crawl": {
                "toc_url": "https://example.com/book/",
                "next_page_url_pattern": r"\.html$",
            }
        },
    )
    cfg = load_config(config_path)

    assert cfg.crawl.next_page_url_pattern == ""
    assert any("next_page_url_pattern" in w for w in cfg.warnings), cfg.warnings


def test_unified_file_merges_defaults_with_ebook_override(tmp_path):
    """Config hiệu lực = deep_merge(defaults, ebooks[slug])."""
    path = write_db_config(
        tmp_path / "novel2epub.db",
        defaults={
            "crawl": {"engine": "scrapling", "content_selector": "#default"},
            "translate": {"type": "none", "openai": {"base_url": "https://custom.test/v1"}},
            "output": {"data_dir": "data"},
        },
        ebooks={
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
    )

    cfg_a = load_config(path, "a")
    assert cfg_a.novel.title == "A"
    assert cfg_a.crawl.scrapling.mode == "stealthy"   # override từ ebook a
    assert cfg_a.crawl.content_selector == "#default"  # kế thừa defaults
    assert cfg_a.crawl.toc_url == "https://a"
    assert cfg_a.translate.openai.base_url == "https://custom.test/v1"  # kế thừa defaults

    # Slug rỗng -> lấy ebook đầu tiên (theo thứ tự slug).
    assert load_config(path).novel.slug == "a"
    # Ebook 'b' chỉ override toc_url, mọi thứ khác từ defaults.
    cfg_b = load_config(path, "b")
    assert cfg_b.crawl.content_selector == "#default"


def test_translate_and_ai_per_ebook_override_wins(tmp_path):
    """`translate` (AI dịch) và `ai` (AI biên tập) là cấu hình RIÊNG từng ebook:
    override per-ebook đè lên defaults; ebook không có override thì rơi về
    defaults (config chung — cũng là giá trị khi Reset)."""
    path = write_db_config(
        tmp_path / "novel2epub.db",
        defaults={
            "translate": {"type": "openai", "openai": {"model": "global-model"}},
            "ai": {"openai": {"model": "global-editor"}},
        },
        ebooks={
            "a": {
                "novel": {"slug": "a"},
                "translate": {"type": "none", "openai": {"model": "per-ebook-model"}},
                "ai": {"openai": {"model": "per-ebook-editor"}},
            },
            "b": {"novel": {"slug": "b"}},  # không override — dùng config chung
        },
    )

    cfg = load_config(path, "a")
    assert cfg.translate.type == "none"
    assert cfg.translate.openai.model == "per-ebook-model"
    assert cfg.ai.openai.model == "per-ebook-editor"

    cfg_b = load_config(path, "b")
    assert cfg_b.translate.type == "openai"
    assert cfg_b.translate.openai.model == "global-model"
    assert cfg_b.ai.openai.model == "global-editor"


def test_unified_file_unknown_slug_raises(tmp_path):
    path = write_db_config(
        tmp_path / "novel2epub.db",
        ebooks={"a": {"novel": {"slug": "a"}}},
    )
    with pytest.raises(KeyError, match="nonexistent"):
        load_config(path, "nonexistent")


def test_default_translate_type_is_openai(tmp_path):
    """Không khai báo translate.type → mặc định type=openai."""
    path = write_db_config(
        tmp_path / "novel2epub.db",
        defaults={"translate": {}},
        ebooks={"test": {"novel": {"slug": "test"}, "crawl": {"toc_url": "https://example.com"}}},
    )
    cfg = load_config(path)
    assert cfg.translate.type == "openai"


def test_hachimimt_auto_preset(tmp_path):
    """model preset HachimiMT-60 → model_key được gán đúng."""
    path = write_db_config(
        tmp_path / "novel2epub.db",
        defaults={"translate": {"type": "hachimimt", "model": "hachimimt-60"}},
        ebooks={"test": {"novel": {"slug": "test"}, "crawl": {"toc_url": "https://example.com"}}},
    )
    cfg = load_config(path)
    assert cfg.translate.hachimimt.model_key == "HachimiMT-60"


def test_hachimimt_auto_preset_respects_user_override(tmp_path):
    """User override model_key → không bị preset ghi đè."""
    path = write_db_config(
        tmp_path / "novel2epub.db",
        defaults={
            "translate": {
                "type": "hachimimt",
                "model": "hachimimt-60",
                "hachimimt": {"model_key": "MoxhiMT-60", "beam_size": 4},
            },
        },
        ebooks={"test": {"novel": {"slug": "test"}, "crawl": {"toc_url": "https://example.com"}}},
    )
    cfg = load_config(path)
    assert cfg.translate.hachimimt.model_key == "MoxhiMT-60"  # user override wins
    assert cfg.translate.hachimimt.beam_size == 4


def test_glossary_filter_defaults_true(tmp_path):
    config_path = _write_config(tmp_path)
    cfg = load_config(config_path)
    assert cfg.translate.glossary_filter is True


def test_glossary_filter_always_true(tmp_path):
    """glossary_filter luôn True, bypass config (hardcode trong load_config)."""
    config_path = _write_config(
        tmp_path,
        extra={"translate": {"type": "none", "glossary_filter": False}},
    )
    cfg = load_config(config_path)
    assert cfg.translate.glossary_filter is True


def test_auto_glossary_and_batch_size_parsed_from_yaml(tmp_path):
    """auto_glossary/batch_size từng bị bỏ quên khi load config (luôn dùng default)."""
    config_path = _write_config(
        tmp_path,
        extra={"translate": {"type": "none", "auto_glossary": True, "batch_size": 5}},
    )
    cfg = load_config(config_path)
    assert cfg.translate.auto_glossary is True
    assert cfg.translate.batch_size == 5


def test_prompt_max_chars_defaults_20000(tmp_path):
    config_path = _write_config(tmp_path)
    cfg = load_config(config_path)
    assert cfg.translate.prompt_max_chars == 20000


def test_prompt_max_chars_parsed_from_yaml(tmp_path):
    config_path = _write_config(
        tmp_path,
        extra={"translate": {"type": "none", "prompt_max_chars": 12000}},
    )
    cfg = load_config(config_path)
    assert cfg.translate.prompt_max_chars == 12000


def test_translate_genre_defaults_to_auto():
    from novel2epub.config import TranslateConfig
    assert TranslateConfig().genre == "auto"


def test_genre_no_longer_deprecated():
    from novel2epub.config_writer import _DEPRECATED_TRANSLATE_FIELDS
    assert "genre" not in _DEPRECATED_TRANSLATE_FIELDS


def test_default_prompts_carry_characters_placeholder():
    from novel2epub.config import DEFAULT_PROMPT, EN_DEFAULT_PROMPT
    from novel2epub.presets.go import GO_PROMPT
    from novel2epub.presets.omniroute import OMNIPROUTE_PROMPT
    for tpl in (DEFAULT_PROMPT, EN_DEFAULT_PROMPT, GO_PROMPT, OMNIPROUTE_PROMPT):
        assert "{characters}" in tpl


def test_default_prompt_no_longer_bans_ta_nguoi_globally():
    # Vế "KHÔNG bê nguyên ta/ngươi" sai với cổ trang — đã chuyển xuống preset
    # urban/romance, nơi nó đúng.
    from novel2epub.config import DEFAULT_PROMPT
    assert "KHÔNG bê nguyên ta/ngươi" not in DEFAULT_PROMPT
    assert "[LỜI KỂ NGÔI BA]" in DEFAULT_PROMPT


def test_default_zh_and_en_prompts_allow_contextual_pronouns():
    from novel2epub.config import DEFAULT_PROMPT, EN_DEFAULT_PROMPT
    for prompt in (DEFAULT_PROMPT, EN_DEFAULT_PROMPT):
        assert '"hắn"' in prompt
        assert '"ta/ngươi"' in prompt
        assert "BẢNG NHÂN VẬT" in prompt or "CHARACTER TABLE" in prompt
        assert "máy móc" in prompt or "mechanically" in prompt


def test_epub_path_default_nam_trong_data_slug(tmp_path):
    """Mặc định `epub_path` = `<data_dir>/data/<slug>/<tựa đề> - <tác giả>.epub`,
    và đặt `output.epub_path` thủ công sẽ thắng mặc định."""
    path = write_db_config(
        tmp_path / "novel2epub.db",
        defaults={"translate": {"type": "none"}, "output": {"data_dir": "data"}},
        ebooks={
            "a": {
                "novel": {"slug": "a", "title": "Truyện A", "author": "Tác giả"},
                "crawl": {"toc_url": "https://a"},
            },
        },
    )
    cfg = load_config(path, "a")
    assert cfg.epub_path == str(tmp_path / "data" / "a" / "Truyện A - Tác giả.epub")

    cfg.output.epub_path = str(tmp_path / "tu-dat.epub")
    assert cfg.epub_path == str(tmp_path / "tu-dat.epub")


def test_epub_path_default_thieu_tac_gia_va_ky_tu_khong_hop_le(tmp_path):
    path = write_db_config(
        tmp_path / "novel2epub.db",
        defaults={"translate": {"type": "none"}, "output": {"data_dir": "data"}},
        ebooks={
            "a": {
                "novel": {"slug": "a", "title": 'Truyện: A/B', "author": ""},
                "crawl": {"toc_url": "https://a"},
            },
        },
    )
    cfg = load_config(path, "a")
    assert cfg.epub_path == str(tmp_path / "data" / "a" / "Truyện AB.epub")


def test_default_prompts_define_pronoun_priority_and_avoid_overuse():
    from novel2epub.config import DEFAULT_PROMPT, EN_DEFAULT_PROMPT
    assert "BẢNG NHÂN VẬT > ngôi kể thực tế của đoạn > quan hệ/ngữ cảnh > gợi ý thể loại" in DEFAULT_PROMPT
    assert 'không thay mọi 他 bằng "hắn"' in DEFAULT_PROMPT
    assert "tránh lặp đại từ dày đặc" in DEFAULT_PROMPT
    assert "CHARACTER TABLE > the passage's actual narrative person > relationship/context > genre suggestions" in EN_DEFAULT_PROMPT
    assert 'Do not translate every he/him as "hắn"' in EN_DEFAULT_PROMPT
    assert "Write in uppercase" not in EN_DEFAULT_PROMPT
