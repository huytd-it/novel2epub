"""Test luật sở hữu source↔ebook ở route settings: lưu source và sync-to-source
không được để lại override thừa."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from novel2epub.db import get_connection
from novel2epub.sources import load_presets
from tests.conftest import write_db_config


def _crawl(path: Path, slug: str) -> dict:
    conn = get_connection(str(path))
    row = conn.execute(
        "SELECT crawl_overrides_json FROM ebooks WHERE slug=?", (slug,)
    ).fetchone()
    return json.loads(row["crawl_overrides_json"] or "{}") if row else {}


def _fake_job():
    class Job:
        def status(self):
            return {
                "crawl": {"running": False, "step": "", "error": "", "log": []},
                "translate": {"running": False, "step": "", "error": "", "log": []},
            }

    return Job()


def _client(monkeypatch, tmp_path):
    db = write_db_config(
        tmp_path / "novel2epub.db",
        defaults={"translate": {"type": "none"}},
        sources={"aixdzs": {"content_selector": ".preset", "delay_seconds": 2.0,
                            "scrapling_mode": "stealthy",
                            "domains": "aixdzs.com"}},
        ebooks={
            "a": {"name": "A", "source": "aixdzs",
                  "crawl": {"toc_url": "https://aixdzs.com/d/1"}},
            # Ebook thứ hai cùng preset — dùng để khẳng định không ai ghi vào nó.
            "b": {"name": "B", "source": "aixdzs",
                  "crawl": {"toc_url": "https://aixdzs.com/d/2"}},
        },
    )
    from app import deps

    # Trong production mọi alias này trỏ CÙNG 1 file DB (xem app/deps.py) —
    # patch hết để route chạy thật trên DB tạm: resolved_cfg/library() đọc
    # WORKSPACE_PATH, code mới đọc DB_PATH. Không stub resolved_cfg để test đi
    # qua load_config thật.
    monkeypatch.setattr(deps, "DB_PATH", db)
    monkeypatch.setattr(deps, "WORKSPACE_PATH", str(db))
    monkeypatch.setattr(deps, "SOURCES_PATH", str(db))
    from app.main import app

    app.state.job = _fake_job()
    return db, TestClient(app, follow_redirects=False)


def _form(**over) -> dict:
    base = {
        "toc_url": "https://aixdzs.com/d/1",
        "chapter_link_pattern": ".*",
        "max_chapters": 0,
        "delay_seconds": 2.0,
        "max_workers": 1,
        "content_selector": ".preset",
        "scrapling_mode": "stealthy",
        # Checkbox không tick thì trình duyệt KHÔNG gửi field → Form(False).
        # Preset mặc định headless/network_idle = True, nên phải gửi "true"
        # mới đúng ý "form trùng khít preset"; thiếu chúng là form thật sự
        # KHÁC preset và override sinh ra là chính đáng.
        "headless": "true",
        "network_idle": "true",
        "max_pages_per_chapter": 10,
        "toc_max_pages": 5,
        "retry_attempts": 3,
        "retry_delay_seconds": 5.0,
        "retry_backoff": 2.0,
        "retry_max_delay_seconds": 120.0,
    }
    base.update(over)
    return base


def test_luu_source_trung_preset_khong_sinh_override(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    r = client.post("/ebooks/a/settings/source", data=_form())
    assert r.status_code == 303
    crawl = _crawl(db, "a")
    # Chỉ còn toc_url + retry (retry không đến từ preset). Không có
    # content_selector/delay_seconds/scrapling vì chúng trùng preset.
    assert "content_selector" not in crawl
    assert "delay_seconds" not in crawl
    assert "scrapling" not in crawl
    assert crawl["toc_url"] == "https://aixdzs.com/d/1"


def test_luu_source_khac_preset_thi_giu_override(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    r = client.post("/ebooks/a/settings/source", data=_form(content_selector="#rieng"))
    assert r.status_code == 303
    assert _crawl(db, "a")["content_selector"] == "#rieng"


def test_luu_source_scrapling_khac_preset_giu_override_dang_long(monkeypatch, tmp_path):
    """Override scrapling KHÁC preset được giữ, và giữ đúng dạng LỒNG.

    Chốt tiền đề của strip_preset_defaults: dạng `{"scrapling": {...}}` mà nó
    xử lý đúng là dạng `update_ebook` thật sự ghi xuống DB (preset lưu tên
    phẳng `scrapling_mode` — chính chỗ bug cũ so trượt).
    """
    db, client = _client(monkeypatch, tmp_path)
    r = client.post("/ebooks/a/settings/source", data=_form(scrapling_mode="dynamic"))
    assert r.status_code == 303

    crawl = _crawl(db, "a")
    assert crawl["scrapling"] == {"mode": "dynamic"}
    # Chỉ `mode` khác preset — 5 field scrapling còn lại trùng nên bị lọc sạch.
    from novel2epub.config import load_config
    assert load_config(db, "a").crawl.scrapling.mode == "dynamic"


def test_sync_to_source_day_field_scrapling_long_va_don_override(monkeypatch, tmp_path):
    """sync-to-source quy đổi tên lồng → phẳng qua SCRAPLING_FIELD_MAP, rồi dọn.

    Round-trip thật: route → update_ebook → DB, với override dạng lồng.
    """
    db, client = _client(monkeypatch, tmp_path)
    client.post("/ebooks/a/settings/source", data=_form(scrapling_mode="dynamic"))
    assert _crawl(db, "a")["scrapling"] == {"mode": "dynamic"}

    r = client.post("/ebooks/a/settings/sync-to-source")
    assert r.status_code == 303

    # Preset nhận giá trị mới ở tên PHẲNG.
    assert load_presets(db)["aixdzs"].scrapling_mode == "dynamic"
    # Ebook về tham chiếu thuần — không còn khối scrapling thừa.
    assert "scrapling" not in _crawl(db, "a")


def test_sync_to_source_day_len_preset_va_don_override_cua_ebook(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    # Ebook override khác preset.
    client.post("/ebooks/a/settings/source", data=_form(content_selector="#rieng"))
    assert _crawl(db, "a")["content_selector"] == "#rieng"

    r = client.post("/ebooks/a/settings/sync-to-source")
    assert r.status_code == 303

    # Preset nhận giá trị mới.
    assert load_presets(db)["aixdzs"].content_selector == "#rieng"
    # Ebook về tham chiếu thuần — không giữ bản sao thừa.
    assert "content_selector" not in _crawl(db, "a")


def test_sync_to_source_khong_ghi_vao_ebook_khac(monkeypatch, tmp_path):
    """Ebook khác cùng preset ăn theo lúc load, KHÔNG bị ghi vào DB.

    Đây là thứ propagate_preset_update từng làm sai: nó ghi giá trị preset vào
    từng ebook, biến chúng thành override cứng rồi tự khoá.
    """
    from novel2epub.config import load_config

    db, client = _client(monkeypatch, tmp_path)
    before_b = _crawl(db, "b")

    client.post("/ebooks/a/settings/source", data=_form(content_selector="#rieng"))
    client.post("/ebooks/a/settings/sync-to-source")

    # b không bị ghi thêm gì...
    assert _crawl(db, "b") == before_b
    # ...nhưng vẫn thấy giá trị mới nhờ resolve live lúc load.
    assert load_config(db, "b").crawl.content_selector == "#rieng"
