"""Test các nút Reset ở trang Settings: xoá override crawl per-ebook (về
preset/mặc định) và xoá cấu hình translate/ai RIÊNG của ebook (về config
chung trong defaults) — lối thoát khi config chồng chéo."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from novel2epub.config import load_config
from novel2epub.db import get_connection
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
        defaults={
            "translate": {
                "type": "openai",
                "openai": {"model": "custom-model", "api_key": "sk-x"},
            },
            "ai": {"openai": {"model": "custom-editor", "api_key": "sk-y"}},
            # Khối crawl còn sót trong config chung (legacy) — chính là thứ
            # từng làm Reset Nguồn "chưa chính xác": sau khi xoá override, các
            # giá trị này rò vào ebook. Reset phải trung hoà chúng.
            "crawl": {
                "content_selector": "#junk-chung",
                "next_page_selector": "a#pager_next",
                "max_chapters": 0,  # trùng mặc định — không cần trung hoà
            },
        },
        sources={"aixdzs": {"content_selector": ".preset", "delay_seconds": 2.0,
                            "scrapling_mode": "stealthy",
                            "domains": "aixdzs.com"}},
        ebooks={
            "a": {"name": "A", "source": "aixdzs",
                  "crawl": {"toc_url": "https://aixdzs.com/d/1",
                            "content_selector": "#cu-rich",
                            "delay_seconds": 9.0,
                            "scrapling": {"mode": "dynamic"}},
                  # Cấu hình AI riêng của a — reset phải xoá đúng chỗ này.
                  "translate": {"type": "none",
                                "openai": {"model": "model-rieng-a"}},
                  "ai": {"openai": {"model": "editor-rieng-a"}}},
            # Ebook không gắn nguồn — reset crawl về mặc định thuần; có
            # translate riêng để khẳng định reset của a không lây sang b.
            "b": {"name": "B",
                  "crawl": {"toc_url": "https://khac.com/d/2",
                            "content_selector": "#rieng"},
                  "translate": {"openai": {"model": "model-rieng-b"}}},
        },
    )
    from app import deps

    monkeypatch.setattr(deps, "DB_PATH", db)
    monkeypatch.setattr(deps, "WORKSPACE_PATH", str(db))
    monkeypatch.setattr(deps, "SOURCES_PATH", str(db))
    from app.main import app

    app.state.job = _fake_job()
    return db, TestClient(app, follow_redirects=False)


def test_reset_source_xoa_override_giu_toc_url_va_an_theo_preset(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    assert _crawl(db, "a")["content_selector"] == "#cu-rich"

    r = client.post("/ebooks/a/settings/source/reset")
    assert r.status_code == 303

    # Override chỉ còn toc_url (định danh) + phần trung hoà defaults.crawl
    # cho key preset KHÔNG phủ (next_page_selector có trong preset... không —
    # SourcePreset có next_page_selector nên được preset phủ; content_selector
    # cũng vậy). Với preset phủ hết key rác thì override sạch trơn.
    assert _crawl(db, "a") == {"toc_url": "https://aixdzs.com/d/1"}
    # Resolve lại ăn theo preset — KHÔNG dính giá trị rác từ config chung.
    cfg = load_config(db, "a")
    assert cfg.crawl.content_selector == ".preset"
    assert cfg.crawl.delay_seconds == 2.0
    assert cfg.crawl.scrapling.mode == "stealthy"
    assert cfg.crawl.next_page_selector == ""  # preset không đặt → mặc định


def test_reset_source_ebook_khong_nguon_ve_mac_dinh_khong_dinh_rac_defaults(monkeypatch, tmp_path):
    """Ebook không khớp nguồn nào: reset phải về MẶC ĐỊNH thật — các giá trị
    rác trong defaults.crawl (config chung cũ) phải bị trung hoà, không được
    rò vào form sau reset (bug "reset mặc định Nguồn chưa chính xác")."""
    db, client = _client(monkeypatch, tmp_path)

    r = client.post("/ebooks/b/settings/source/reset")
    assert r.status_code == 303

    cfg = load_config(db, "b")
    assert cfg.crawl.content_selector == ""      # không phải "#junk-chung"
    assert cfg.crawl.next_page_selector == ""    # không phải "a#pager_next"
    # Override = toc_url + phần trung hoà (ghi tường minh giá trị mặc định
    # cho đúng các key bị defaults.crawl làm rò).
    crawl = _crawl(db, "b")
    assert crawl["toc_url"] == "https://khac.com/d/2"
    assert crawl["content_selector"] == ""
    assert crawl["next_page_selector"] == ""
    assert "max_chapters" not in crawl  # trùng mặc định sẵn — không ghi thừa


def test_reset_source_tu_gan_lai_nguon_khop_url(monkeypatch, tmp_path):
    """Ebook tạo trước khi preset tồn tại (source_preset=None) nhưng toc_url
    khớp domain preset: reset phải gắn lại nguồn và ăn theo preset."""
    from novel2epub.db import get_connection

    db, client = _client(monkeypatch, tmp_path)
    # Ebook c: URL thuộc aixdzs.com nhưng chưa gắn nguồn, override cũ lung tung.
    conn = get_connection(str(db))
    with conn:
        conn.execute(
            "INSERT INTO ebooks (slug, name, crawl_overrides_json) VALUES (?, ?, ?)",
            ("c", "C", json.dumps({
                "toc_url": "https://aixdzs.com/d/9",
                "content_selector": "#cu-cua-c",
                "delay_seconds": 7.0,
            })),
        )

    r = client.post("/ebooks/c/settings/source/reset")
    assert r.status_code == 303

    conn = get_connection(str(db))
    row = conn.execute("SELECT source_preset FROM ebooks WHERE slug='c'").fetchone()
    assert row["source_preset"] == "aixdzs"
    cfg = load_config(db, "c")
    assert cfg.crawl.content_selector == ".preset"
    assert cfg.crawl.delay_seconds == 2.0
    assert cfg.crawl.scrapling.mode == "stealthy"


def test_reset_source_khong_dung_ebook_khac(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    before_b = _crawl(db, "b")
    client.post("/ebooks/a/settings/source/reset")
    assert _crawl(db, "b") == before_b


def test_reset_translate_xoa_override_rieng_ve_config_chung(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    # Trước reset: a dùng cấu hình riêng.
    assert load_config(db, "a").translate.openai.model == "model-rieng-a"

    r = client.post("/ebooks/a/settings/translate/reset")
    assert r.status_code == 303

    # a quay VỀ config chung (defaults) — không phải dataclass default.
    tr = load_config(db, "a").translate
    assert tr.type == "openai"
    assert tr.openai.model == "custom-model"
    # DB: override riêng của a thật sự trống.
    conn = get_connection(str(db))
    row = conn.execute(
        "SELECT translate_overrides_json FROM ebooks WHERE slug='a'"
    ).fetchone()
    assert json.loads(row["translate_overrides_json"]) == {}
    # Config chung (defaults) KHÔNG bị đụng.
    srow = conn.execute("SELECT translate_json FROM settings WHERE id = 1").fetchone()
    assert json.loads(srow["translate_json"])["openai"]["model"] == "custom-model"
    # Ebook khác giữ nguyên config riêng của nó.
    assert load_config(db, "b").translate.openai.model == "model-rieng-b"
    # Section ai riêng của a không bị đụng.
    assert load_config(db, "a").ai.openai.model == "editor-rieng-a"


def test_reset_ai_xoa_override_rieng_khong_dung_translate(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    assert load_config(db, "a").ai.openai.model == "editor-rieng-a"

    r = client.post("/ebooks/a/settings/ai/reset")
    assert r.status_code == 303

    cfg = load_config(db, "a")
    # a quay về config chung defaults.ai.
    assert cfg.ai.openai.model == "custom-editor"
    # translate riêng của a giữ nguyên.
    assert cfg.translate.openai.model == "model-rieng-a"

    conn = get_connection(str(db))
    row = conn.execute("SELECT ai_overrides_json FROM ebooks WHERE slug='a'").fetchone()
    assert json.loads(row["ai_overrides_json"]) == {}


def test_save_translate_chi_ghi_rieng_ebook(monkeypatch, tmp_path):
    """Lưu tab Dịch chỉ ghi override riêng của ebook — defaults và ebook khác
    không đổi (business logic global đã bỏ)."""
    db, client = _client(monkeypatch, tmp_path)

    r = client.post("/ebooks/a/settings/translate", data={
        "type": "openai",
        "base_url": "http://localhost:20128/v1",
        "model": "model-moi-cua-a",
        "timeout_seconds": 120000,
        "temperature": 0.7,
    })
    assert r.status_code == 303

    assert load_config(db, "a").translate.openai.model == "model-moi-cua-a"
    # b vẫn dùng config riêng của nó; defaults giữ nguyên.
    assert load_config(db, "b").translate.openai.model == "model-rieng-b"
    conn = get_connection(str(db))
    srow = conn.execute("SELECT translate_json FROM settings WHERE id = 1").fetchone()
    assert json.loads(srow["translate_json"])["openai"]["model"] == "custom-model"
