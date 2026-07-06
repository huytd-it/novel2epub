"""Tests cho source-ebook link: resolve preset, propagate, cleanup."""
import json
from pathlib import Path

import pytest

from novel2epub.config import load_config, _resolve_source_overrides
from novel2epub.config_writer import add_ebook, _DEPRECATED_CRAWL_FIELDS, _DEPRECATED_TRANSLATE_FIELDS
from novel2epub.db import get_connection
from novel2epub.sources import SourcePreset, propagate_preset_update, save_presets
from tests.conftest import write_db_config


def _read_ebook_crawl(path: Path, slug: str) -> dict:
    conn = get_connection(str(path))
    row = conn.execute("SELECT crawl_overrides_json FROM ebooks WHERE slug=?", (slug,)).fetchone()
    return json.loads(row["crawl_overrides_json"] or "{}") if row else {}


def _read_settings_translate(path: Path) -> dict:
    conn = get_connection(str(path))
    row = conn.execute("SELECT translate_json FROM settings WHERE id=1").fetchone()
    return json.loads(row["translate_json"] or "{}") if row else {}


# ── Task 9.1: resolve_source_overrides ──────────────────────────────

class TestResolveSourceOverrides:
    def test_no_source_returns_empty(self):
        ebook = {"crawl": {"toc_url": "https://example.com"}}
        result, name, warnings = _resolve_source_overrides(ebook, {})
        assert result == {}
        assert name == ""
        assert warnings == []

    def test_source_found_returns_overrides(self):
        ebook = {"source": "test-preset", "crawl": {"toc_url": "https://example.com"}}
        sources = {
            "test-preset": {
                "content_selector": ".content",
                "delay_seconds": 2.0,
                "headless": True,
            }
        }
        result, name, warnings = _resolve_source_overrides(ebook, sources)
        assert name == "test-preset"
        assert "content_selector" in result
        assert result["content_selector"] == ".content"
        assert warnings == []

    def test_source_not_found_returns_warning(self):
        ebook = {"source": "missing-preset", "crawl": {}}
        result, name, warnings = _resolve_source_overrides(ebook, {})
        assert result == {}
        assert name == "missing-preset"
        assert len(warnings) == 1
        assert "không tồn tại" in warnings[0]


# ── Task 7.1: backward compat — ebook cũ không có source ────────────

class TestBackwardCompat:
    def test_old_ebook_without_source_loads_normally(self, tmp_path):
        config_path = write_db_config(
            tmp_path / "novel2epub.db",
            defaults={"translate": {"type": "none"}},
            ebooks={
                "old-ebook": {
                    "novel": {"slug": "old-ebook"},
                    "crawl": {
                        "toc_url": "https://example.com",
                        "content_selector": ".content",
                        "delay_seconds": 2.0,
                    },
                },
            },
        )
        cfg = load_config(config_path, "old-ebook")
        assert cfg.source == ""
        assert cfg.crawl.content_selector == ".content"
        assert cfg.crawl.delay_seconds == 2.0

    def test_ebook_with_source_resolves_preset(self, tmp_path):
        config_path = write_db_config(
            tmp_path / "novel2epub.db",
            defaults={"translate": {"type": "none"}},
            sources={
                "aixdzs": {
                    "content_selector": ".article-content",
                    "delay_seconds": 1.5,
                    "headless": True,
                },
            },
            ebooks={
                "test-novel": {
                    "source": "aixdzs",
                    "novel": {"slug": "test-novel"},
                    "crawl": {"toc_url": "https://aixdzs.com/novel/test/"},
                },
            },
        )
        cfg = load_config(config_path, "test-novel")
        assert cfg.source == "aixdzs"
        assert cfg.crawl.content_selector == ".article-content"
        assert cfg.crawl.delay_seconds == 1.5
        assert cfg.crawl.toc_url == "https://aixdzs.com/novel/test/"

    def test_ebook_override_takes_priority_over_preset(self, tmp_path):
        config_path = write_db_config(
            tmp_path / "novel2epub.db",
            defaults={"translate": {"type": "none"}},
            sources={
                "aixdzs": {"content_selector": ".article-content", "delay_seconds": 1.5},
            },
            ebooks={
                "test-novel": {
                    "source": "aixdzs",
                    "novel": {"slug": "test-novel"},
                    "crawl": {
                        "toc_url": "https://aixdzs.com/novel/test/",
                        "content_selector": ".custom-css",
                    },
                },
            },
        )
        cfg = load_config(config_path, "test-novel")
        # Override wins
        assert cfg.crawl.content_selector == ".custom-css"
        # Preset fills non-overridden
        assert cfg.crawl.delay_seconds == 1.5


# ── Task 7.2: source preset bị xóa ─────────────────────────────────

class TestMissingSourcePreset:
    def test_deleted_preset_falls_back_to_ebook_fields(self, tmp_path):
        config_path = write_db_config(
            tmp_path / "novel2epub.db",
            defaults={"translate": {"type": "none"}},
            ebooks={
                "test-novel": {
                    "source": "deleted-preset",
                    "novel": {"slug": "test-novel"},
                    "crawl": {
                        "toc_url": "https://example.com",
                        "content_selector": ".fallback",
                    },
                },
            },
        )
        cfg = load_config(config_path, "test-novel")
        assert cfg.source == "deleted-preset"
        assert cfg.crawl.content_selector == ".fallback"
        assert len(cfg.warnings) == 1
        assert "không tồn tại" in cfg.warnings[0]


# ── Task 9.2: propagate_preset_update ──────────────────────────────

class TestPropagatePresetUpdate:
    def _make_config(self, tmp_path) -> Path:
        return write_db_config(
            tmp_path / "novel2epub.db",
            defaults={"translate": {"type": "none"}},
            sources={"aixdzs": {"content_selector": ".old-content", "delay_seconds": 1.0}},
            ebooks={
                "novel-a": {
                    "source": "aixdzs",
                    "novel": {"slug": "novel-a"},
                    "crawl": {"toc_url": "https://aixdzs.com/a/"},
                },
                "novel-b": {
                    "source": "aixdzs",
                    "novel": {"slug": "novel-b"},
                    "crawl": {
                        "toc_url": "https://aixdzs.com/b/",
                        "content_selector": ".custom",
                    },
                },
                "novel-c": {
                    "novel": {"slug": "novel-c"},
                    "crawl": {"toc_url": "https://other.com/c/"},
                },
            },
        )

    def test_propagate_updates_non_overridden_ebooks(self, tmp_path):
        config_path = self._make_config(tmp_path)
        presets = {
            "aixdzs": SourcePreset(
                name="aixdzs",
                content_selector=".new-content",
                delay_seconds=2.0,
            ),
        }
        affected = propagate_preset_update(config_path, "aixdzs", presets)
        assert "novel-a" in affected
        # novel-b has override for content_selector, should NOT be in affected
        # (but delay_seconds is not overridden, so it should be affected)
        assert "novel-b" in affected
        assert "novel-c" not in affected

        novel_a_crawl = _read_ebook_crawl(config_path, "novel-a")
        assert novel_a_crawl["content_selector"] == ".new-content"
        assert novel_a_crawl["delay_seconds"] == 2.0

        # Verify novel-b kept its override for content_selector but got new delay_seconds
        novel_b_crawl = _read_ebook_crawl(config_path, "novel-b")
        assert novel_b_crawl["content_selector"] == ".custom"  # preserved
        assert novel_b_crawl["delay_seconds"] == 2.0  # updated

    def test_propagate_no_affected_returns_empty(self, tmp_path):
        """Khi ebook đã có TẤT CẢ field từ crawl_overrides với giá trị đúng,
        propagate không thay đổi gì."""
        preset = SourcePreset(
            name="aixdzs",
            content_selector=".old-content",
            delay_seconds=1.0,
        )
        overrides = preset.crawl_overrides()
        full_crawl_a = {"toc_url": "https://aixdzs.com/a/"}
        full_crawl_a.update(overrides)
        full_crawl_b = {"toc_url": "https://aixdzs.com/b/", "content_selector": ".custom"}
        full_crawl_b.update({k: v for k, v in overrides.items() if k != "content_selector"})

        config_path = write_db_config(
            tmp_path / "novel2epub.db",
            defaults={"translate": {"type": "none"}},
            sources={"aixdzs": {"content_selector": ".old-content", "delay_seconds": 1.0}},
            ebooks={
                "novel-a": {"source": "aixdzs", "novel": {"slug": "novel-a"}, "crawl": full_crawl_a},
                "novel-b": {"source": "aixdzs", "novel": {"slug": "novel-b"}, "crawl": full_crawl_b},
            },
        )

        presets = {"aixdzs": preset}
        affected = propagate_preset_update(config_path, "aixdzs", presets)
        assert affected == []


# ── Task 9.3: _preset_usage with source field ──────────────────────

class TestPresetUsageSourceField:
    def test_usage_reads_source_field(self, tmp_path):
        config_path = write_db_config(
            tmp_path / "novel2epub.db",
            defaults={"translate": {"type": "none"}},
            sources={"aixdzs": {"content_selector": ".content"}},
            ebooks={
                "novel-a": {
                    "source": "aixdzs",
                    "novel": {"slug": "novel-a"},
                    "crawl": {"toc_url": "https://aixdzs.com/a/"},
                },
                "novel-b": {
                    "novel": {"slug": "novel-b"},
                    "crawl": {"toc_url": "https://other.com/b/"},
                },
            },
        )

        cfg_a = load_config(config_path, "novel-a")
        assert cfg_a.source == "aixdzs"

        cfg_b = load_config(config_path, "novel-b")
        assert cfg_b.source == ""


# ── Task 9.4: cleanup — deprecated fields ─────────────────────

class TestDbCleanup:
    def test_add_ebook_no_deprecated_fields(self, tmp_path):
        config_path = write_db_config(tmp_path / "novel2epub.db")
        add_ebook(config_path, "new-slug", toc_url="https://example.com", source_name="aixdzs")
        crawl = _read_ebook_crawl(config_path, "new-slug")
        for field in _DEPRECATED_CRAWL_FIELDS:
            assert field not in crawl, f"deprecated field {field!r} should not be in crawl"

    def test_deprecated_field_lists_not_empty(self):
        assert len(_DEPRECATED_CRAWL_FIELDS) > 0
        assert len(_DEPRECATED_TRANSLATE_FIELDS) > 0
        assert "glossary" in _DEPRECATED_TRANSLATE_FIELDS
        assert "ai_fallback" in _DEPRECATED_CRAWL_FIELDS
        # Các field này có UI trong tab Dịch — không được strip khi ghi config.
        for field in ("auto_glossary", "glossary_filter", "batch_size",
                      "prompt_max_chars", "auto_cleanup_han", "cleanup_han"):
            assert field not in _DEPRECATED_TRANSLATE_FIELDS

    def test_update_defaults_persists_translate_ui_fields(self, tmp_path):
        """Regression: các field tab Dịch từng bị strip như deprecated khi lưu."""
        from novel2epub.config_writer import update_defaults

        config_path = write_db_config(tmp_path / "novel2epub.db")
        update_defaults(config_path, {"translate": {
            "auto_glossary": True,
            "glossary_filter": False,
            "batch_size": 5,
            "prompt_max_chars": 9000,
            "auto_cleanup_han": True,
            "cleanup_han": {"max_chars": 4000, "retries": 2},
        }})
        tr = _read_settings_translate(config_path)
        assert tr["auto_glossary"] is True
        assert tr["glossary_filter"] is False
        assert tr["batch_size"] == 5
        assert tr["prompt_max_chars"] == 9000
        assert tr["auto_cleanup_han"] is True
        assert tr["cleanup_han"]["max_chars"] == 4000
        assert tr["cleanup_han"]["retries"] == 2

    def test_update_defaults_still_strips_deprecated(self, tmp_path):
        from novel2epub.config_writer import update_defaults

        config_path = write_db_config(tmp_path / "novel2epub.db")
        update_defaults(config_path, {"translate": {
            "batch_size": 3,
            "profile": "x",
            "genre": "y",
            "glossary": {"a": "b"},
        }})
        tr = _read_settings_translate(config_path)
        assert tr["batch_size"] == 3
        for field in ("profile", "genre", "glossary"):
            assert field not in tr


# ── Task 9.5: Integration — create ebook → update preset → verify ──

class TestIntegration:
    def test_create_with_source_then_propagate(self, tmp_path):
        config_path = write_db_config(
            tmp_path / "novel2epub.db",
            defaults={"translate": {"type": "none"}},
            sources={"aixdzs": {"content_selector": ".article", "delay_seconds": 1.0}},
        )

        # 1. Create ebook with source
        add_ebook(
            config_path,
            "new-novel",
            title="Test Novel",
            toc_url="https://aixdzs.com/novel/test/",
            source_name="aixdzs",
        )

        # Verify ebook has source, not copied fields
        crawl = _read_ebook_crawl(config_path, "new-novel")
        assert "content_selector" not in crawl  # not copied
        assert crawl["toc_url"] == "https://aixdzs.com/novel/test/"

        # 2. Load config — should resolve from preset
        cfg = load_config(config_path, "new-novel")
        assert cfg.source == "aixdzs"
        assert cfg.crawl.content_selector == ".article"
        assert cfg.crawl.delay_seconds == 1.0

        # 3. Update preset and propagate
        presets = {
            "aixdzs": SourcePreset(
                name="aixdzs",
                content_selector=".new-article",
                delay_seconds=2.0,
            ),
        }
        affected = propagate_preset_update(config_path, "aixdzs", presets)
        assert "new-novel" in affected

        # 4. Verify ebook got updated
        cfg2 = load_config(config_path, "new-novel")
        assert cfg2.crawl.content_selector == ".new-article"
        assert cfg2.crawl.delay_seconds == 2.0
