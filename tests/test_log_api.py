"""Tests cho API quản lý nhật ký (`/api/ui/logs*` và legacy `/api/logs*`).

Route phải mỏng — mọi semantics lọc/xoá đã test ở test_logstore.py; ở đây chỉ
kiểm tra hợp đồng HTTP: shape response, filter param, export, xoá.
"""
from __future__ import annotations

import pytest

from novel2epub.db import get_connection, init_schema
from novel2epub.logstore import insert_log


@pytest.fixture
def client(tmp_path, monkeypatch):
    import app.deps as deps
    from app.main import app

    db_path = tmp_path / "logs-api.db"
    conn = get_connection(str(db_path))
    init_schema(conn)
    conn.close()
    monkeypatch.setattr(deps, "DB_PATH", db_path)

    from starlette.testclient import TestClient

    return TestClient(app)


def _seed(conn, n=3):
    for i in range(n):
        insert_log(
            conn,
            ts=1_700_000_000.0 + i,
            level="INFO",
            logger="novel2epub.crawler",
            message=f"dòng {i}",
        )


@pytest.fixture
def log_conn(client, monkeypatch):
    """Kết nối vào CÙNG file DB mà route đang dùng (deps.DB_PATH đã patch)."""
    import app.deps as deps

    return get_connection(str(deps.DB_PATH))


def test_logs_page_returns_entries_and_total(client, log_conn):
    _seed(log_conn)
    resp = client.get("/api/ui/logs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert [e["message"] for e in data["entries"]] == ["dòng 2", "dòng 1", "dòng 0"]
    entry = data["entries"][0]
    assert set(entry) == {"id", "ts", "level", "logger", "message", "job_id"}


def test_logs_filter_by_level_param(client, log_conn):
    _seed(log_conn)
    insert_log(log_conn, ts=99, level="ERROR", logger="x", message="hỏng rồi")
    data = client.get("/api/ui/logs?levels=ERROR").json()
    assert data["total"] == 1
    assert data["entries"][0]["message"] == "hỏng rồi"


def test_logs_filter_by_q_and_source(client, log_conn):
    _seed(log_conn)
    insert_log(log_conn, ts=98, level="WARNING", logger="novel2epub.web", message="chậm")
    assert client.get("/api/ui/logs?q=chậm").json()["total"] == 1
    assert client.get("/api/ui/logs?source=novel2epub.crawler").json()["total"] == 3


def test_logs_pagination_with_before_id(client, log_conn):
    _seed(log_conn, 4)
    page1 = client.get("/api/ui/logs?limit=2").json()
    cursor = page1["entries"][-1]["id"]
    page2 = client.get(f"/api/ui/logs?limit=2&before_id={cursor}").json()
    ids = {e["id"] for e in page1["entries"]} | {e["id"] for e in page2["entries"]}
    assert len(ids) == 4
    assert page1["total"] == page2["total"] == 4


def test_logs_stats_shape(client, log_conn):
    _seed(log_conn, 2)
    stats = client.get("/api/ui/logs/stats").json()
    assert stats["total"] == 2
    assert stats["by_level"]["INFO"] == 2
    assert stats["newest_ts"] is not None


def test_logs_sources_lists_loggers(client, log_conn):
    _seed(log_conn, 2)
    sources = client.get("/api/ui/logs/sources").json()["sources"]
    assert sources == [{"logger": "novel2epub.crawler", "count": 2}]


def test_logs_clear_all_and_filtered(client, log_conn):
    _seed(log_conn, 2)
    insert_log(log_conn, ts=99, level="ERROR", logger="x", message="giữ")

    resp = client.delete("/api/ui/logs?levels=INFO")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "deleted": 2}
    assert client.get("/api/ui/logs").json()["total"] == 1

    resp = client.delete("/api/ui/logs")
    assert resp.json()["deleted"] == 1
    assert client.get("/api/ui/logs").json()["total"] == 0


def test_logs_clear_older_than_days(client, log_conn):
    _seed(log_conn)  # quá khứ xa
    import time

    insert_log(log_conn, ts=time.time(), level="INFO", logger="x", message="mới")
    assert client.delete("/api/ui/logs?older_than_days=7").json()["deleted"] == 3
    assert client.get("/api/ui/logs").json()["total"] == 1


def test_logs_export_returns_text_attachment(client, log_conn):
    _seed(log_conn, 2)
    resp = client.get("/api/ui/logs/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert "attachment" in resp.headers["content-disposition"]
    body = resp.text.strip().splitlines()
    assert len(body) == 2
    assert "] novel2epub.crawler: dòng" in body[0]


def test_legacy_api_logs_keeps_lines_contract(client, log_conn):
    _seed(log_conn, 2)
    resp = client.get("/api/logs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert all(isinstance(ln, str) for ln in data["lines"])
    assert len(data["lines"]) == 2


def test_legacy_api_logs_source_filter(client, log_conn):
    _seed(log_conn, 2)
    insert_log(log_conn, ts=50, level="ERROR", logger="novel2epub.web", message="khác nguồn")
    # source=app là alias cũ của "toàn bộ nhật ký"
    assert client.get("/api/logs?source=app").json()["total"] == 3
    data = client.get("/api/logs/novel2epub.web").json()
    assert data["total"] == 1
    assert "khác nguồn" in data["lines"][0]


def test_legacy_delete_api_logs_by_source(client, log_conn):
    _seed(log_conn, 2)
    insert_log(log_conn, ts=50, level="ERROR", logger="novel2epub.web", message="x")
    resp = client.delete("/api/logs/novel2epub.web")
    assert resp.json()["deleted"] == 1
    assert client.get("/api/logs").json()["total"] == 2


def test_logs_entry_detail_and_404(client, log_conn):
    _seed(log_conn)
    first_id = client.get("/api/ui/logs?limit=1").json()["entries"][0]["id"]
    detail = client.get(f"/api/ui/logs/{first_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == first_id
    assert "message" in detail.json()
    assert client.get("/api/ui/logs/999999").status_code == 404


def test_logs_export_not_swallowed_by_entry_route(client, log_conn):
    """Route động /logs/{entry_id} đăng ký sau cùng — không được nuốt /export."""
    assert client.get("/api/ui/logs/export").status_code == 200


def test_logs_delete_single_line(client, log_conn):
    _seed(log_conn, 3)
    ids = [e["id"] for e in client.get("/api/ui/logs?limit=10").json()["entries"]]
    target = ids[1]
    resp = client.delete(f"/api/ui/logs/{target}")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    remaining = {e["id"] for e in client.get("/api/ui/logs?limit=10").json()["entries"]}
    assert target not in remaining
    assert len(remaining) == 2
    # Xoá lại → 404.
    assert client.delete(f"/api/ui/logs/{target}").status_code == 404
