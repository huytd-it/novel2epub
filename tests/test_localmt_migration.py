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


def test_cleanup_han_default_delegates_to_local_mt(tmp_path, monkeypatch):
    """step_cleanup_han_selected mặc định (engine=local_mt) ủy quyền cho bản
    Local MT, KHÔNG cần ai.openai."""
    from novel2epub import pipeline
    from novel2epub.config import Config, CrawlConfig, NovelConfig, OutputConfig

    cfg = Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/", delay_seconds=0),
        translate=TranslateConfig(type="openai", delay_seconds=0),  # backend dịch là AI
        output=OutputConfig(data_dir=str(tmp_path)),
    )
    # ai.openai để trống → nếu đi nhánh openai sẽ bị bỏ qua; phải đi nhánh local_mt.
    cfg.ai.openai.base_url = ""
    cfg.ai.openai.api_key = ""

    called = {"local_mt": False}

    def _fake_local(cfg2, log=None, **kw):
        called["local_mt"] = True
        return None

    monkeypatch.setattr(pipeline, "step_cleanup_han_local_mt_selected", _fake_local)
    pipeline.step_cleanup_han_selected(cfg, lambda m: None, selected_indexes=[1])
    assert called["local_mt"] is True

def test_cleanup_han_engine_parsed_from_config(tmp_path):
    path = write_db_config(
        tmp_path / "novel2epub.db",
        defaults={"translate": {"cleanup_han": {"engine": "openai"}}},
        ebooks={"t": {"novel": {"slug": "t"}, "crawl": {"toc_url": "https://e.com"}}},
    )
    cfg = load_config(path, "t")
    assert cfg.translate.cleanup_han.engine == "openai"


# ── Dọn từ rác TOC ────────────────────────────────────────────────────────

def test_step_clean_toc_titles_preview_and_apply(tmp_path):
    from novel2epub.config import Config, CrawlConfig, NovelConfig, OutputConfig
    from novel2epub.pipeline import step_clean_toc_titles
    from novel2epub.storage import Chapter, Manifest, Storage

    cfg = Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/", delay_seconds=0),
        translate=TranslateConfig(type="localmt", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )
    storage = Storage(str(tmp_path), "t")
    storage.save_manifest(Manifest(slug="t", chapters=[
        Chapter(
            index=1,
            url="http://x/1",
            title="Chương 1: Khởi đầu (Cầu nguyệt phiếu)",
            title_zh="1.第1章 绯红（第一更求推荐票）",
        ),
        Chapter(index=2, url="http://x/2", title="Chương 2: Bình thường"),
        Chapter(index=3, url="http://x/3", title="Chương 3", title_zh="3.第3章 梅丽莎（上）"),
    ]))

    # Preview mặc định chỉ dọn bản dịch, KHÔNG ghi và giữ nguyên title_zh dùng
    # trong khóa nhận diện chương mới.
    preview = step_clean_toc_titles(cfg, lambda m: None, apply=False)
    assert preview["changed"] == 1
    assert preview["applied"] == 0
    assert preview["include_translated"] is True
    assert preview["include_zh"] is False
    assert preview["changes"][0]["changed_fields"] == ["title"]
    assert storage.load_manifest().chapters[0].title.endswith("(Cầu nguyệt phiếu)")

    result = step_clean_toc_titles(cfg, lambda m: None, apply=True)
    assert result["applied"] == 1
    first = storage.load_manifest().chapters[0]
    assert first.title == "Chương 1: Khởi đầu"
    assert first.title_zh == "1.第1章 绯红（第一更求推荐票）"
    assert storage.load_manifest().chapters[2].title_zh == "3.第3章 梅丽莎（上）"

    # Chỉ khi opt-in mới dọn tiêu đề nguồn.
    source = step_clean_toc_titles(cfg, lambda m: None, apply=True, include_zh=True)
    assert source["applied"] == 2
    assert source["include_zh"] is True
    first = storage.load_manifest().chapters[0]
    assert first.title == "Chương 1: Khởi đầu"
    assert first.title_zh == "第1章 绯红"
    assert storage.load_manifest().chapters[2].title_zh == "第3章 梅丽莎（上）"


def test_step_clean_toc_titles_cleans_title_when_source_has_not_been_backfilled(tmp_path):
    from novel2epub.config import Config, CrawlConfig, NovelConfig, OutputConfig
    from novel2epub.pipeline import step_clean_toc_titles
    from novel2epub.storage import Chapter, Manifest, Storage

    cfg = Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/", delay_seconds=0),
        translate=TranslateConfig(type="localmt", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )
    storage = Storage(str(tmp_path), "t")
    storage.save_manifest(Manifest(slug="t", chapters=[
        Chapter(index=1, url="http://x/1", title="1.第1章 开始 求月票"),
    ]))

    # Không có title_zh thì title đang là nguồn; mặc định phải giữ nguyên để
    # chapter_title_key() không đổi giữa hai lần fetch TOC.
    result = step_clean_toc_titles(cfg, lambda m: None, apply=True)
    assert result["changed"] == 0
    assert storage.load_manifest().chapters[0].title == "1.第1章 开始 求月票"

    source = step_clean_toc_titles(cfg, lambda m: None, apply=True, include_zh=True)
    assert source["changes"][0]["changed_fields"] == ["title"]
    assert storage.load_manifest().chapters[0].title == "第1章 开始"


def test_step_clean_toc_titles_also_cleans_branch_titles(tmp_path):
    """Chuẩn hóa TOC phải chạm cả tiêu đề theo NHÁNH (Local MT/AI) — bản dịch
    máy tự dịch lại tiêu đề nên thường còn nguyên từ rác dù manifest đã sạch."""
    from novel2epub.config import Config, CrawlConfig, NovelConfig, OutputConfig
    from novel2epub.pipeline import step_clean_toc_titles
    from novel2epub.storage import Chapter, Manifest, Storage
    from novel2epub import revisions

    cfg = Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/", delay_seconds=0),
        translate=TranslateConfig(type="localmt", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )
    storage = Storage(str(tmp_path), "t")
    ch = Chapter(index=1, url="http://x/1", title="第1章 绯红", title_zh="第1章 绯红")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))

    storage.write_branch_titles(ch, revisions.BRANCH_LOCAL_MT,
                                title="Chương 1: Hồng (Cầu nguyệt phiếu)", title_zh="第1章 绯红")
    storage.write_branch_titles(ch, revisions.BRANCH_AI,
                                title="Chương 1: Hồng", title_zh="第1章 绯红")

    preview = step_clean_toc_titles(cfg, lambda m: None, apply=False, include_translated=True)
    change = preview["changes"][0]
    # Preview trả diff cho từng nhánh nhưng CHƯA ghi.
    assert change["branches"]["local_mt"]["title"] == (
        "Chương 1: Hồng (Cầu nguyệt phiếu)", "Chương 1: Hồng",
    )
    assert storage.read_branch_title(ch, revisions.BRANCH_LOCAL_MT).endswith("(Cầu nguyệt phiếu)")

    result = step_clean_toc_titles(cfg, lambda m: None, apply=True, include_translated=True)
    assert result["applied"] == 1
    assert storage.read_branch_title(ch, revisions.BRANCH_LOCAL_MT) == "Chương 1: Hồng"
    assert storage.read_branch_title_zh(ch, revisions.BRANCH_LOCAL_MT) == "第1章 绯红"
    # Nhánh AI không có gì phải dọn → giữ nguyên.
    assert storage.read_branch_title(ch, revisions.BRANCH_AI) == "Chương 1: Hồng"


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Chương 5: Đại chiến (Cầu nguyệt phiếu)", "Chương 5: Đại chiến"),
        ("Chương 12: Về nhà cầu vé tháng", "Chương 12: Về nhà"),
        ("Đại kết cục 求月票", "Đại kết cục"),
        ("Bí mật （求订阅）", "Bí mật"),
        ("Thức tỉnh 跪求月票推荐票", "Thức tỉnh"),
        ("Trùng sinh cầu phiếu！", "Trùng sinh"),
        ("Chương 75: Nhà họ Bì (Chương thêm", "Chương 75: Nhà họ Bì"),
        ("Chương 125: Đại bại (thêm chương, cầu đặt mua)", "Chương 125: Đại bại"),
        ("Chương 196: Giết chóc (Thêm chương cầu duyệt)", "Chương 196: Giết chóc"),
        (
            "Chương 75: Nhà họ Bì (Chương thêm cầu nguyệt phiếu)",
            "Chương 75: Nhà họ Bì",
        ),
        # KHÔNG được cắt nhầm tiêu đề thường:
        ("Xin một vé về tuổi thơ", "Xin một vé về tuổi thơ"),
        ("Chương 3: Khởi đầu", "Chương 3: Khởi đầu"),
    ],
)
def test_strip_toc_junk(title, expected):
    assert strip_toc_junk(title) == expected
