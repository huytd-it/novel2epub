"""Tests cho source-ebook link: resolve preset, propagate, cleanup."""
import json
from pathlib import Path

import pytest

from novel2epub.config import load_config, _resolve_source_overrides
from novel2epub.config_writer import add_ebook, _DEPRECATED_CRAWL_FIELDS, _DEPRECATED_TRANSLATE_FIELDS
from novel2epub.db import get_connection
from novel2epub.sources import SourcePreset, save_presets, strip_preset_defaults
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


# ── Luật: preset resolve LIVE, ebook không giữ bản sao ──────────────

class TestPresetResolveLive:
    def test_sua_preset_thi_ebook_an_theo_ngay_ma_khong_ghi_gi_vao_ebook(self, tmp_path):
        db = write_db_config(
            tmp_path / "novel2epub.db",
            defaults={"translate": {"type": "none"}},
            sources={"aixdzs": {"content_selector": ".old", "delay_seconds": 1.0}},
            ebooks={"novel-a": {"name": "A", "source": "aixdzs",
                                "crawl": {"toc_url": "https://aixdzs.com/d/1"}}},
        )
        before = _read_ebook_crawl(db, "novel-a")

        save_presets(db, {"aixdzs": SourcePreset(
            name="aixdzs", content_selector=".new", delay_seconds=2.0,
        )})

        cfg = load_config(db, "novel-a")
        assert cfg.crawl.content_selector == ".new"
        assert cfg.crawl.delay_seconds == 2.0
        # Điểm mấu chốt: ebook KHÔNG bị ghi thêm gì.
        assert _read_ebook_crawl(db, "novel-a") == before

    def test_override_cua_ebook_thang_preset(self, tmp_path):
        db = write_db_config(
            tmp_path / "novel2epub.db",
            defaults={"translate": {"type": "none"}},
            sources={"aixdzs": {"content_selector": ".preset"}},
            ebooks={"novel-a": {"name": "A", "source": "aixdzs",
                                "crawl": {"toc_url": "https://aixdzs.com/d/1",
                                          "content_selector": ".rieng"}}},
        )
        cfg = load_config(db, "novel-a")
        assert cfg.crawl.content_selector == ".rieng"


# ── Proxy / DNS-over-HTTPS: preset flat fields → crawl.scrapling ────

class TestProxyResolution:
    def test_preset_proxy_and_doh_resolve_to_scrapling_config(self, tmp_path):
        config_path = write_db_config(
            tmp_path / "novel2epub.db",
            defaults={"translate": {"type": "none"}},
            sources={
                "blocked-site": {
                    "content_selector": ".content",
                    "scrapling_mode": "stealthy",
                    "proxy": "socks5://100.64.0.1:1080",
                    "dns_over_https": True,
                },
            },
            ebooks={
                "test-novel": {
                    "source": "blocked-site",
                    "novel": {"slug": "test-novel"},
                    "crawl": {"toc_url": "https://example.cn/book/1/"},
                },
            },
        )
        cfg = load_config(config_path, "test-novel")
        assert cfg.crawl.scrapling.mode == "stealthy"
        assert cfg.crawl.scrapling.proxy == "socks5://100.64.0.1:1080"
        assert cfg.crawl.scrapling.dns_over_https is True

    def test_ebook_nested_scrapling_proxy_wins_over_preset(self, tmp_path):
        config_path = write_db_config(
            tmp_path / "novel2epub.db",
            defaults={"translate": {"type": "none"}},
            sources={"blocked-site": {"proxy": "socks5://preset:1080"}},
            ebooks={
                "test-novel": {
                    "source": "blocked-site",
                    "novel": {"slug": "test-novel"},
                    "crawl": {
                        "toc_url": "https://example.cn/book/1/",
                        "scrapling": {"proxy": "socks5://ebook:1080"},
                    },
                },
            },
        )
        cfg = load_config(config_path, "test-novel")
        assert cfg.crawl.scrapling.proxy == "socks5://ebook:1080"

    def test_crawl_overrides_emits_proxy_fields(self):
        preset = SourcePreset(
            name="x", proxy="socks5://h:1080", dns_over_https=True,
        )
        overrides = preset.crawl_overrides()
        assert overrides["proxy"] == "socks5://h:1080"
        assert overrides["dns_over_https"] is True


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
    def test_create_with_source_then_update_preset(self, tmp_path):
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

        # 3. Sửa preset — không ghi gì xuống ebook
        save_presets(config_path, {
            "aixdzs": SourcePreset(
                name="aixdzs",
                content_selector=".new-article",
                delay_seconds=2.0,
            ),
        })
        assert "content_selector" not in _read_ebook_crawl(config_path, "new-novel")

        # 4. Ebook ăn theo preset mới ngay ở lần load kế tiếp
        cfg2 = load_config(config_path, "new-novel")
        assert cfg2.crawl.content_selector == ".new-article"
        assert cfg2.crawl.delay_seconds == 2.0


# ── strip_preset_defaults ───────────────────────────────────────────

class TestStripPresetDefaults:
    def _preset(self) -> SourcePreset:
        return SourcePreset(
            name="aixdzs",
            content_selector=".content",
            delay_seconds=2.0,
            scrapling_mode="stealthy",
        )

    def test_key_trung_preset_bi_bo(self):
        cleaned, removed = strip_preset_defaults(
            {"content_selector": ".content"}, self._preset()
        )
        assert cleaned == {}
        assert removed == ["content_selector"]

    def test_key_khac_preset_duoc_giu(self):
        cleaned, removed = strip_preset_defaults(
            {"content_selector": "#khac"}, self._preset()
        )
        assert cleaned == {"content_selector": "#khac"}
        assert removed == []

    def test_toc_url_luon_duoc_giu(self):
        cleaned, removed = strip_preset_defaults(
            {"toc_url": "https://example.com/book/1"}, self._preset()
        )
        assert cleaned == {"toc_url": "https://example.com/book/1"}
        assert removed == []

    def test_scrapling_long_duoc_quy_doi_ve_phang(self):
        # crawl.scrapling.mode ↔ preset.scrapling_mode — cùng nghĩa, khác tên.
        cleaned, removed = strip_preset_defaults(
            {"scrapling": {"mode": "stealthy"}}, self._preset()
        )
        assert cleaned == {}
        assert removed == ["scrapling.mode"]

    def test_scrapling_long_khac_preset_duoc_giu(self):
        cleaned, removed = strip_preset_defaults(
            {"scrapling": {"mode": "fetcher"}}, self._preset()
        )
        assert cleaned == {"scrapling": {"mode": "fetcher"}}
        assert removed == []

    def test_scrapling_giu_key_khac_bo_key_trung(self):
        cleaned, removed = strip_preset_defaults(
            {"scrapling": {"mode": "stealthy", "proxy": "http://p:1"}}, self._preset()
        )
        assert cleaned == {"scrapling": {"proxy": "http://p:1"}}
        assert removed == ["scrapling.mode"]

    def test_idempotent(self):
        preset = self._preset()
        once, _ = strip_preset_defaults({"content_selector": ".content"}, preset)
        twice, removed = strip_preset_defaults(once, preset)
        assert twice == once
        assert removed == []
