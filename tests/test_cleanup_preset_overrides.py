"""Test script dọn override thừa mà propagate_preset_update để lại."""
from __future__ import annotations

import json
from pathlib import Path

from novel2epub.db import get_connection
from tests.conftest import write_db_config

from scripts.cleanup_preset_overrides import cleanup_overrides


def _crawl(path: Path, slug: str) -> dict:
    conn = get_connection(str(path))
    row = conn.execute(
        "SELECT crawl_overrides_json FROM ebooks WHERE slug=?", (slug,)
    ).fetchone()
    return json.loads(row["crawl_overrides_json"] or "{}") if row else {}


def _db(tmp_path: Path, ebooks: dict) -> Path:
    return write_db_config(
        tmp_path / "novel2epub.db",
        defaults={"translate": {"type": "none"}},
        sources={"aixdzs": {"content_selector": ".content", "delay_seconds": 2.0,
                            "scrapling_mode": "stealthy"}},
        ebooks=ebooks,
    )


def test_bo_override_trung_preset(tmp_path):
    db = _db(tmp_path, {"a": {"name": "A", "source": "aixdzs", "crawl": {
        "toc_url": "https://aixdzs.com/d/1",
        "content_selector": ".content",   # trùng preset → bỏ
        "delay_seconds": 2.0,             # trùng preset → bỏ
    }}})
    report = cleanup_overrides(db)
    assert sorted(report["a"]) == ["content_selector", "delay_seconds"]
    assert _crawl(db, "a") == {"toc_url": "https://aixdzs.com/d/1"}


def test_giu_override_khac_preset(tmp_path):
    db = _db(tmp_path, {"a": {"name": "A", "source": "aixdzs", "crawl": {
        "toc_url": "https://aixdzs.com/d/1",
        "content_selector": ".rieng",     # khác preset → giữ
    }}})
    report = cleanup_overrides(db)
    assert "a" not in report
    assert _crawl(db, "a")["content_selector"] == ".rieng"


def test_ebook_khong_co_source_khong_bi_dung(tmp_path):
    db = _db(tmp_path, {"a": {"name": "A", "crawl": {
        "content_selector": ".content",
    }}})
    report = cleanup_overrides(db)
    assert report == {}
    assert _crawl(db, "a")["content_selector"] == ".content"


def test_source_khong_ton_tai_thi_bo_qua(tmp_path):
    db = _db(tmp_path, {"a": {"name": "A", "source": "khong-co", "crawl": {
        "content_selector": ".content",
    }}})
    report = cleanup_overrides(db)
    assert report == {}
    assert _crawl(db, "a")["content_selector"] == ".content"


def test_dry_run_khong_ghi_gi(tmp_path):
    db = _db(tmp_path, {"a": {"name": "A", "source": "aixdzs", "crawl": {
        "toc_url": "https://aixdzs.com/d/1",
        "content_selector": ".content",
    }}})
    before = _crawl(db, "a")
    report = cleanup_overrides(db, dry_run=True)
    assert report["a"] == ["content_selector"]
    assert _crawl(db, "a") == before


def test_idempotent(tmp_path):
    db = _db(tmp_path, {"a": {"name": "A", "source": "aixdzs", "crawl": {
        "toc_url": "https://aixdzs.com/d/1",
        "content_selector": ".content",
    }}})
    cleanup_overrides(db)
    after_first = _crawl(db, "a")
    report = cleanup_overrides(db)
    assert report == {}
    assert _crawl(db, "a") == after_first
