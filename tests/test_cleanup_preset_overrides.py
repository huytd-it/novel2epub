"""Test script dọn override thừa mà propagate_preset_update để lại."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from novel2epub.db import get_connection
from tests.conftest import write_db_config

from scripts.cleanup_preset_overrides import cleanup_overrides, main


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
    db = _db(tmp_path, {"a": {"source": "aixdzs", "crawl": {
        "toc_url": "https://aixdzs.com/d/1",
        "content_selector": ".content",   # trùng preset → bỏ
        "delay_seconds": 2.0,             # trùng preset → bỏ
    }}})
    report = cleanup_overrides(db)
    assert sorted(report["a"]) == ["content_selector", "delay_seconds"]
    assert _crawl(db, "a") == {"toc_url": "https://aixdzs.com/d/1"}


def test_giu_override_khac_preset(tmp_path):
    db = _db(tmp_path, {"a": {"source": "aixdzs", "crawl": {
        "toc_url": "https://aixdzs.com/d/1",
        "content_selector": ".rieng",     # khác preset → giữ
    }}})
    report = cleanup_overrides(db)
    assert "a" not in report
    assert _crawl(db, "a")["content_selector"] == ".rieng"


def test_ebook_khong_co_source_khong_bi_dung(tmp_path):
    db = _db(tmp_path, {"a": {"crawl": {
        "content_selector": ".content",
    }}})
    report = cleanup_overrides(db)
    assert report == {}
    assert _crawl(db, "a")["content_selector"] == ".content"


def test_source_khong_ton_tai_thi_bo_qua(tmp_path):
    db = _db(tmp_path, {"a": {"source": "khong-co", "crawl": {
        "content_selector": ".content",
    }}})
    report = cleanup_overrides(db)
    assert report == {}
    assert _crawl(db, "a")["content_selector"] == ".content"


def test_dry_run_khong_ghi_gi(tmp_path):
    db = _db(tmp_path, {"a": {"source": "aixdzs", "crawl": {
        "toc_url": "https://aixdzs.com/d/1",
        "content_selector": ".content",
    }}})
    before = _crawl(db, "a")
    report = cleanup_overrides(db, dry_run=True)
    assert report["a"] == ["content_selector"]
    assert _crawl(db, "a") == before


def test_idempotent(tmp_path):
    db = _db(tmp_path, {"a": {"source": "aixdzs", "crawl": {
        "toc_url": "https://aixdzs.com/d/1",
        "content_selector": ".content",
    }}})
    cleanup_overrides(db)
    after_first = _crawl(db, "a")
    report = cleanup_overrides(db)
    assert report == {}
    assert _crawl(db, "a") == after_first


def test_main_db_khong_ton_tai_thi_bao_loi_va_exit_khac_0(tmp_path, capsys):
    """DB không tồn tại KHÔNG được báo thành công như DB sạch — script chỉ chạy
    một lần, operator gõ sai -c mà thấy "không cần làm gì" là mất DB thật."""
    missing = tmp_path / "khong-co.db"
    with pytest.raises(SystemExit) as exc:
        main(["-c", str(missing)])
    assert exc.value.code != 0
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "Không tìm thấy DB" in out
    assert str(missing.resolve()) in out
    assert "Không cần làm gì" not in out
    assert not missing.exists()  # không được tạo DB rỗng


def test_main_dry_run_bao_cao_db_that(tmp_path, capsys):
    """main() với DB có thật vẫn chạy bình thường — guard mới không chặn nhầm."""
    db = _db(tmp_path, {"a": {"source": "aixdzs", "crawl": {
        "toc_url": "https://aixdzs.com/d/1",
        "content_selector": ".content",
    }}})
    main(["-c", str(db), "--dry-run"])
    out = capsys.readouterr().out
    assert "content_selector" in out
    assert _crawl(db, "a")["content_selector"] == ".content"  # dry-run: chưa ghi
