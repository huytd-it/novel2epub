"""Test route CRUD bảng nhân vật (app/routes/characters.py).

Fixture/client style copy từ tests/test_routes_idioms.py — repo không có fixture
chung `client`/`slug`, mỗi file test tự dựng `_cfg`/`_client` cục bộ.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import deps
from novel2epub.config import Config, CrawlConfig, NovelConfig, OutputConfig, TranslateConfig

SLUG = "t"


def _cfg(tmp_path):
    return Config(
        novel=NovelConfig(slug=SLUG),
        crawl=CrawlConfig(toc_url="http://x/book/", delay_seconds=0),
        translate=TranslateConfig(type="openai", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


class _FakeJob:
    def status(self):
        return {
            "crawl": {"running": False, "step": "", "error": "", "log": []},
            "translate": {"running": False, "step": "", "error": "", "log": [], "running_ebooks": []},
        }


def _client(cfg, monkeypatch):
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    from app.main import app

    app.state.job = _FakeJob()
    return TestClient(app)


def test_characters_page_renders(tmp_path, monkeypatch):
    client = _client(_cfg(tmp_path), monkeypatch)
    resp = client.get(f"/ebook/{SLUG}/characters")
    assert resp.status_code == 200
    assert "Nhân vật" in resp.text


def test_upsert_and_list_character(tmp_path, monkeypatch):
    client = _client(_cfg(tmp_path), monkeypatch)
    resp = client.post(
        f"/api/ebook/{SLUG}/characters/entry",
        data={"source": "林凡", "target": "Lâm Phàm", "aliases": "凡儿",
              "gender": "nam", "self_pronoun": "ta", "narrator_ref": "hắn",
              "role_note": "đồ đệ", "importance": "main"},
    )
    assert resp.status_code == 200

    entries = client.get(f"/api/ebook/{SLUG}/characters/list").json()["entries"]
    assert len(entries) == 1
    assert entries[0]["target"] == "Lâm Phàm"
    assert entries[0]["importance"] == "main"


def test_relation_crud(tmp_path, monkeypatch):
    client = _client(_cfg(tmp_path), monkeypatch)
    client.post(f"/api/ebook/{SLUG}/characters/entry",
                data={"source": "林凡", "target": "Lâm Phàm"})
    client.post(f"/api/ebook/{SLUG}/characters/entry",
                data={"source": "苏清雪", "target": "Tô Thanh Tuyết"})
    client.post(f"/api/ebook/{SLUG}/characters/relation",
                data={"a_source": "林凡", "b_source": "苏清雪",
                      "from_chapter": "120", "a_calls_b": "em", "a_self": "anh"})

    entries = client.get(f"/api/ebook/{SLUG}/characters/list").json()["entries"]
    lam = next(e for e in entries if e["source"] == "林凡")
    assert lam["relations"] == [
        {"b_source": "苏清雪", "b_target": "Tô Thanh Tuyết", "from_chapter": 120,
         "a_calls_b": "em", "a_self": "anh", "note": "",
         "to_chapter": None, "a_calls_b_raw": "", "a_self_raw": "",
         "evidence": "", "inferred": False, "confidence": ""}
    ]

    client.post(f"/api/ebook/{SLUG}/characters/relation/delete",
                data={"a_source": "林凡", "b_source": "苏清雪", "from_chapter": "120"})
    entries = client.get(f"/api/ebook/{SLUG}/characters/list").json()["entries"]
    assert next(e for e in entries if e["source"] == "林凡")["relations"] == []


def test_rename_character_migrates_relations(tmp_path, monkeypatch):
    """Đổi tên gốc KHÔNG được làm mất quan hệ — cả 2 mốc mà nhân vật là
    a_source lẫn mốc mà nó là b_source (người khác trỏ vào) phải sống sót,
    với tên MỚI ở đúng phía đã xuất hiện tên cũ."""
    client = _client(_cfg(tmp_path), monkeypatch)
    client.post(f"/api/ebook/{SLUG}/characters/entry",
                data={"source": "林凡", "target": "Lâm Phàm"})
    client.post(f"/api/ebook/{SLUG}/characters/entry",
                data={"source": "苏清雪", "target": "Tô Thanh Tuyết"})
    # Hai mốc quan hệ nơi 林凡 là a_source.
    client.post(f"/api/ebook/{SLUG}/characters/relation",
                data={"a_source": "林凡", "b_source": "苏清雪",
                      "from_chapter": "0", "a_calls_b": "nàng", "a_self": "ta"})
    client.post(f"/api/ebook/{SLUG}/characters/relation",
                data={"a_source": "林凡", "b_source": "苏清雪",
                      "from_chapter": "120", "a_calls_b": "em", "a_self": "anh"})
    # Một quan hệ nơi 林凡 là b_source (nhân vật kia trỏ vào nó).
    client.post(f"/api/ebook/{SLUG}/characters/relation",
                data={"a_source": "苏清雪", "b_source": "林凡",
                      "from_chapter": "0", "a_calls_b": "chàng", "a_self": "ta"})

    resp = client.post(
        f"/api/ebook/{SLUG}/characters/entry",
        data={"source": "林凡新", "target": "Lâm Phàm", "original_source": "林凡"},
    )
    assert resp.status_code == 200

    entries = client.get(f"/api/ebook/{SLUG}/characters/list").json()["entries"]
    assert {e["source"] for e in entries} == {"林凡新", "苏清雪"}

    lam = next(e for e in entries if e["source"] == "林凡新")
    assert len(lam["relations"]) == 2
    by_chapter = {r["from_chapter"]: r for r in lam["relations"]}
    assert set(by_chapter) == {0, 120}
    assert all(r["b_source"] == "苏清雪" for r in lam["relations"])
    assert by_chapter[0]["a_calls_b"] == "nàng"
    assert by_chapter[120]["a_calls_b"] == "em"

    su = next(e for e in entries if e["source"] == "苏清雪")
    assert len(su["relations"]) == 1
    assert su["relations"][0]["b_source"] == "林凡新"
    assert su["relations"][0]["a_calls_b"] == "chàng"


def test_delete_character_removes_its_relations(tmp_path, monkeypatch):
    client = _client(_cfg(tmp_path), monkeypatch)
    client.post(f"/api/ebook/{SLUG}/characters/entry", data={"source": "林凡"})
    client.post(f"/api/ebook/{SLUG}/characters/entry", data={"source": "苏清雪"})
    client.post(f"/api/ebook/{SLUG}/characters/relation",
                data={"a_source": "林凡", "b_source": "苏清雪", "a_calls_b": "nàng"})

    client.post(f"/api/ebook/{SLUG}/characters/delete", data={"sources": "林凡"})
    entries = client.get(f"/api/ebook/{SLUG}/characters/list").json()["entries"]
    assert [e["source"] for e in entries] == ["苏清雪"]
    assert entries[0]["relations"] == []
