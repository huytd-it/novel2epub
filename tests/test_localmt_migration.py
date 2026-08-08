"""Tách bạch Local MT ↔ OpenAI: đổi tên engine, gỡ google/libretranslate,
clear Hán mặc định Local MT, và dọn từ rác TOC."""
from __future__ import annotations

import pytest

from novel2epub.config import (
    CleanupHanConfig,
    TranslateConfig,
    _normalize_translate_type,
    load_config,
)
from novel2epub.db import _rewrite_translate_type
from novel2epub.toc import strip_toc_junk
from novel2epub.translator import LocalMTTranslator, make_translator
from tests.conftest import write_db_config


# ── Đổi tên type + gỡ engine ──────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("hachimimt", "localmt"),
        ("moxhimt", "localmt"),
        ("google", "openai"),
        ("libretranslate", "openai"),
        ("openai", "openai"),
        ("localmt", "localmt"),
        ("none", "none"),
    ],
)
def test_normalize_translate_type(raw, expected):
    assert _normalize_translate_type(raw) == expected


def test_make_translator_localmt_returns_local_mt():
    assert isinstance(make_translator(TranslateConfig(type="localmt")), LocalMTTranslator)


def test_make_translator_legacy_hachimimt_alias():
    # Alias phòng thủ cho config chưa migrate.
    assert isinstance(make_translator(TranslateConfig(type="hachimimt")), LocalMTTranslator)


def test_make_translator_rejects_removed_engine():
    with pytest.raises(ValueError):
        make_translator(TranslateConfig(type="google"))


def test_load_config_migrates_type_and_warns(tmp_path):
    path = write_db_config(
        tmp_path / "novel2epub.db",
        defaults={"translate": {"type": "google"}},
        ebooks={"t": {"novel": {"slug": "t"}, "crawl": {"toc_url": "https://e.com"},
                      "translate": {"type": "libretranslate"}}},
    )
    cfg = load_config(path, "t")
    assert cfg.translate.type == "openai"
    assert any("libretranslate" in w for w in cfg.warnings)


def test_load_config_migrates_hachimimt_to_localmt(tmp_path):
    path = write_db_config(
        tmp_path / "novel2epub.db",
        defaults={"translate": {"type": "hachimimt"}},
        ebooks={"t": {"novel": {"slug": "t"}, "crawl": {"toc_url": "https://e.com"}}},
    )
    cfg = load_config(path, "t")
    assert cfg.translate.type == "localmt"


# ── DB migration v12 (rewrite JSON đã lưu) ────────────────────────────────

def test_migration_v12_rewrites_stored_json(tmp_path):
    """_migration_v12 rewrite `type` đã lưu trong settings + ebooks."""
    import json

    from novel2epub.db import _migration_v12, get_connection, init_schema

    conn = get_connection(str(tmp_path / "m.db"))
    init_schema(conn)
    with conn:
        conn.execute(
            "INSERT INTO settings (id, translate_json) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET translate_json = excluded.translate_json",
            (json.dumps({"type": "google"}),),
        )
        conn.execute(
            "INSERT INTO ebooks (slug, translate_overrides_json) VALUES ('e', ?)",
            (json.dumps({"type": "hachimimt"}),),
        )
        _migration_v12(conn)

    s = json.loads(conn.execute("SELECT translate_json FROM settings WHERE id=1").fetchone()["translate_json"])
    e = json.loads(conn.execute("SELECT translate_overrides_json FROM ebooks WHERE slug='e'").fetchone()["translate_overrides_json"])
    assert s["type"] == "openai"
    assert e["type"] == "localmt"


def test_rewrite_translate_type_pure():
    assert '"type": "openai"' in _rewrite_translate_type('{"type": "google"}')
    assert '"type": "localmt"' in _rewrite_translate_type('{"type": "moxhimt"}')
    # Đã đúng → None (không ghi thừa).
    assert _rewrite_translate_type('{"type": "openai"}') is None
    assert _rewrite_translate_type(None) is None
    # Dọn luôn sub-block libretranslate đã gỡ.
    out = _rewrite_translate_type('{"type": "openai", "libretranslate": {"base_url": "x"}}')
    assert out is not None and "libretranslate" not in out


# ── Clear Hán mặc định Local MT ───────────────────────────────────────────

def test_cleanup_han_engine_defaults_local_mt():
    assert CleanupHanConfig().engine == "local_mt"


def test_cleanup_han_engine_parsed_from_config(tmp_path):
    path = write_db_config(
        tmp_path / "novel2epub.db",
        defaults={"translate": {"cleanup_han": {"engine": "openai"}}},
        ebooks={"t": {"novel": {"slug": "t"}, "crawl": {"toc_url": "https://e.com"}}},
    )
    cfg = load_config(path, "t")
    assert cfg.translate.cleanup_han.engine == "openai"


# ── Dọn từ rác TOC ────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "title,expected",
    [
        ("Chương 5: Đại chiến (Cầu nguyệt phiếu)", "Chương 5: Đại chiến"),
        ("Chương 12: Về nhà cầu vé tháng", "Chương 12: Về nhà"),
        ("Đại kết cục 求月票", "Đại kết cục"),
        ("Bí mật （求订阅）", "Bí mật"),
        ("Thức tỉnh 跪求月票推荐票", "Thức tỉnh"),
        ("Trùng sinh cầu phiếu！", "Trùng sinh"),
        # KHÔNG được cắt nhầm tiêu đề thường:
        ("Xin một vé về tuổi thơ", "Xin một vé về tuổi thơ"),
        ("Chương 3: Khởi đầu", "Chương 3: Khởi đầu"),
    ],
)
def test_strip_toc_junk(title, expected):
    assert strip_toc_junk(title) == expected
