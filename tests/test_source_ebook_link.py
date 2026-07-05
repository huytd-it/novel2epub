"""Tests cho source-ebook link: resolve preset, propagate, cleanup."""
from pathlib import Path

import pytest
import yaml
from ruamel.yaml import YAML

from novel2epub.config import load_config, _resolve_source_overrides
from novel2epub.config_writer import add_ebook, _DEPRECATED_CRAWL_FIELDS, _DEPRECATED_TRANSLATE_FIELDS
from novel2epub.sources import SourcePreset, propagate_preset_update, save_presets


def _write_yaml(path: Path, data: dict) -> None:
    y = YAML()
    y.preserve_quotes = True
    path.write_text("", encoding="utf-8")
    with path.open("w", encoding="utf-8") as f:
        y.dump(data, f)


def _read_yaml(path: Path) -> dict:
    y = YAML()
    return y.load(path.read_text(encoding="utf-8")) or {}


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
        data = {
            "defaults": {"translate": {"type": "none"}, "output": {"data_dir": "data"}},
            "ebooks": {
                "old-ebook": {
                    "novel": {"slug": "old-ebook"},
                    "crawl": {
                        "toc_url": "https://example.com",
                        "content_selector": ".content",
                        "delay_seconds": 2.0,
                    },
                },
            },
        }
        config_path = tmp_path / "config.yaml"
        _write_yaml(config_path, data)
        cfg = load_config(config_path, "old-ebook")
        assert cfg.source == ""
        assert cfg.crawl.content_selector == ".content"
        assert cfg.crawl.delay_seconds == 2.0

    def test_ebook_with_source_resolves_preset(self, tmp_path):
        data = {
            "defaults": {"translate": {"type": "none"}, "output": {"data_dir": "data"}},
            "sources": {
                "aixdzs": {
                    "content_selector": ".article-content",
                    "delay_seconds": 1.5,
                    "headless": True,
                },
            },
            "ebooks": {
                "test-novel": {
                    "source": "aixdzs",
                    "novel": {"slug": "test-novel"},
                    "crawl": {"toc_url": "https://aixdzs.com/novel/test/"},
                },
            },
        }
        config_path = tmp_path / "config.yaml"
        _write_yaml(config_path, data)
        cfg = load_config(config_path, "test-novel")
        assert cfg.source == "aixdzs"
        assert cfg.crawl.content_selector == ".article-content"
        assert cfg.crawl.delay_seconds == 1.5
        assert cfg.crawl.toc_url == "https://aixdzs.com/novel/test/"

    def test_ebook_override_takes_priority_over_preset(self, tmp_path):
        data = {
            "defaults": {"translate": {"type": "none"}, "output": {"data_dir": "data"}},
            "sources": {
                "aixdzs": {
                    "content_selector": ".article-content",
                    "delay_seconds": 1.5,
                },
            },
            "ebooks": {
                "test-novel": {
                    "source": "aixdzs",
                    "novel": {"slug": "test-novel"},
                    "crawl": {
                        "toc_url": "https://aixdzs.com/novel/test/",
                        "content_selector": ".custom-css",
                    },
                },
            },
        }
        config_path = tmp_path / "config.yaml"
        _write_yaml(config_path, data)
        cfg = load_config(config_path, "test-novel")
        # Override wins
        assert cfg.crawl.content_selector == ".custom-css"
        # Preset fills non-overridden
        assert cfg.crawl.delay_seconds == 1.5


# ── Task 7.2: source preset bị xóa ─────────────────────────────────

class TestMissingSourcePreset:
    def test_deleted_preset_falls_back_to_ebook_fields(self, tmp_path):
        data = {
            "defaults": {"translate": {"type": "none"}, "output": {"data_dir": "data"}},
            "ebooks": {
                "test-novel": {
                    "source": "deleted-preset",
                    "novel": {"slug": "test-novel"},
                    "crawl": {
                        "toc_url": "https://example.com",
                        "content_selector": ".fallback",
                    },
                },
            },
        }
        config_path = tmp_path / "config.yaml"
        _write_yaml(config_path, data)
        cfg = load_config(config_path, "test-novel")
        assert cfg.source == "deleted-preset"
        assert cfg.crawl.content_selector == ".fallback"
        assert len(cfg.warnings) == 1
        assert "không tồn tại" in cfg.warnings[0]


# ── Task 9.2: propagate_preset_update ──────────────────────────────

class TestPropagatePresetUpdate:
    def _make_config(self, tmp_path) -> Path:
        data = {
            "defaults": {"translate": {"type": "none"}, "output": {"data_dir": "data"}},
            "sources": {
                "aixdzs": {
                    "content_selector": ".old-content",
                    "delay_seconds": 1.0,
                },
            },
            "ebooks": {
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
        }
        config_path = tmp_path / "config.yaml"
        _write_yaml(config_path, data)
        return config_path

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

        # Verify novel-a got the new values
        result = _read_yaml(config_path)
        novel_a_crawl = result["ebooks"]["novel-a"]["crawl"]
        assert novel_a_crawl["content_selector"] == ".new-content"
        assert novel_a_crawl["delay_seconds"] == 2.0

        # Verify novel-b kept its override for content_selector but got new delay_seconds
        novel_b_crawl = result["ebooks"]["novel-b"]["crawl"]
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
        # Tạo ebook crawl block chứa đầy đủ field từ preset
        full_crawl_a = {"toc_url": "https://aixdzs.com/a/"}
        full_crawl_a.update(overrides)
        full_crawl_b = {"toc_url": "https://aixdzs.com/b/", "content_selector": ".custom"}
        full_crawl_b.update({k: v for k, v in overrides.items() if k != "content_selector"})

        data = {
            "defaults": {"translate": {"type": "none"}, "output": {"data_dir": "data"}},
            "sources": {"aixdzs": {"content_selector": ".old-content", "delay_seconds": 1.0}},
            "ebooks": {
                "novel-a": {"source": "aixdzs", "novel": {"slug": "novel-a"}, "crawl": full_crawl_a},
                "novel-b": {"source": "aixdzs", "novel": {"slug": "novel-b"}, "crawl": full_crawl_b},
            },
        }
        config_path = tmp_path / "config.yaml"
        _write_yaml(config_path, data)

        presets = {"aixdzs": preset}
        affected = propagate_preset_update(config_path, "aixdzs", presets)
        assert affected == []


# ── Task 9.3: _preset_usage with source field ──────────────────────

class TestPresetUsageSourceField:
    def test_usage_reads_source_field(self, tmp_path):
        data = {
            "defaults": {"translate": {"type": "none"}, "output": {"data_dir": "data"}},
            "sources": {
                "aixdzs": {"content_selector": ".content"},
            },
            "ebooks": {
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
        }
        config_path = tmp_path / "config.yaml"
        _write_yaml(config_path, data)

        # load_config should return source for novel-a
        cfg_a = load_config(config_path, "novel-a")
        assert cfg_a.source == "aixdzs"

        cfg_b = load_config(config_path, "novel-b")
        assert cfg_b.source == ""


# ── Task 9.4: YAML cleanup — deprecated fields ─────────────────────

class TestYamlCleanup:
    def test_add_ebook_no_deprecated_fields(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        _write_yaml(config_path, {"defaults": {}, "ebooks": {}})
        add_ebook(config_path, "new-slug", toc_url="https://example.com", source_name="aixdzs")
        result = _read_yaml(config_path)
        ebook = result["ebooks"]["new-slug"]
        crawl = ebook.get("crawl", {})
        for field in _DEPRECATED_CRAWL_FIELDS:
            assert field not in crawl, f"deprecated field {field!r} should not be in crawl"

    def test_deprecated_field_lists_not_empty(self):
        assert len(_DEPRECATED_CRAWL_FIELDS) > 0
        assert len(_DEPRECATED_TRANSLATE_FIELDS) > 0
        assert "auto_glossary" in _DEPRECATED_TRANSLATE_FIELDS
        assert "ai_fallback" in _DEPRECATED_CRAWL_FIELDS


# ── Task 9.5: Integration — create ebook → update preset → verify ──

class TestIntegration:
    def test_create_with_source_then_propagate(self, tmp_path):
        data = {
            "defaults": {"translate": {"type": "none"}, "output": {"data_dir": "data"}},
            "sources": {
                "aixdzs": {
                    "content_selector": ".article",
                    "delay_seconds": 1.0,
                },
            },
            "ebooks": {},
        }
        config_path = tmp_path / "config.yaml"
        _write_yaml(config_path, data)

        # 1. Create ebook with source
        add_ebook(
            config_path,
            "new-novel",
            title="Test Novel",
            toc_url="https://aixdzs.com/novel/test/",
            source_name="aixdzs",
        )

        # Verify ebook has source, not copied fields
        result = _read_yaml(config_path)
        ebook = result["ebooks"]["new-novel"]
        assert ebook["source"] == "aixdzs"
        crawl = ebook.get("crawl", {})
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
