"""Route `/api/ui` của hộp bản nháp AI: optimistic lock khi lưu toàn văn,
chấp nhận/bỏ candidate. Khẳng định: bản nháp không tự active, snapshot lệch
hoặc hết hạn → 409, ghi đè mù không xảy ra.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from novel2epub.storage import Chapter, Manifest, Storage

from .conftest import write_db_config

ch = Chapter(index=1, url="http://x/1")


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = write_db_config(
        tmp_path / "n.db",
        ebooks={"t": {"name": "Truyện thử", "novel": {"title": "Truyện thử"}}},
    )
    monkeypatch.setattr("app.deps.WORKSPACE_PATH", str(db))
    monkeypatch.setattr("app.deps.DB_PATH", str(db))
    from app.main import app

    # config.py ép output.data_dir = thư mục chứa DB, nên seed ngay tại đó.
    storage = Storage(str(tmp_path), "t")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    storage.write_translated(ch, "bản dịch cũ")
    return TestClient(app, client=("127.0.0.1", 12345)), storage


def _pending_revision(storage):
    """Tạo một candidate rewrite pending cho chương 1, trả (storage, id)."""
    from novel2epub import revisions

    cand = revisions.create_revision(
        engine="rewrite", idx=1, payload="bản nháp AI", base_rev=storage.read_revision(ch),
        base_translated_text="bản dịch cũ", has_raw=False,
    )
    return storage.create_ai_revision(cand)


def test_chapter_payload_co_revision_va_ai_revisions(client):
    _client, storage = client
    res = _client.get("/api/ui/ebooks/t/chapters/1")
    assert res.status_code == 200
    body = res.json()
    assert body["revision"] == storage.read_revision(
        Chapter(index=1, url="http://x/1")
    )
    assert body["ai_revisions"] == []


def test_save_toan_van_voi_expected_rev_hop_le(client):
    _client, storage = client
    res = _client.post(
        "/api/ui/ebooks/t/chapters/1/translated",
        json={"translated": "bản mới", "expected_rev": storage.read_revision(ch)},
    )
    assert res.status_code == 200
    assert res.json()["revision"] == storage.read_revision(ch)


def test_save_toan_van_stale_expected_rev_tra_409(client):
    _client, storage = client
    # Ai đó đã sửa bản dịch và bump revision sau khi client mở trang.
    storage.write_translated(ch, "người khác sửa")
    with storage.conn:
        storage.conn.execute(
            "UPDATE chapters SET revision=revision+1 WHERE ebook_slug='t' AND idx=1"
        )
    res = _client.post(
        "/api/ui/ebooks/t/chapters/1/translated",
        json={"translated": "bản mới của tôi", "expected_rev": storage.read_revision(ch) - 1},
    )
    assert res.status_code == 409
    assert storage.read_translated(ch) == "người khác sửa"


def test_confirm_candidate_ap_dung_optimistic(client):
    _client, storage = client
    rid = _pending_revision(storage)
    res = _client.post(
        "/api/ui/ebooks/t/chapters/1/ai/rewrite/confirm",
        json={"revision_id": rid},
    )
    assert res.status_code == 200
    assert storage.read_translated(ch) == "bản nháp AI"
    assert storage.read_ai_revision(ch, rid).status == "applied"


def test_confirm_candidate_stale_tra_409(client):
    _client, storage = client
    rid = _pending_revision(storage)
    storage.write_translated(ch, "ai đó sửa giữa chừng")
    with storage.conn:
        storage.conn.execute(
            "UPDATE chapters SET revision=revision+1 WHERE ebook_slug='t' AND idx=1"
        )
    res = _client.post(
        "/api/ui/ebooks/t/chapters/1/ai/rewrite/confirm",
        json={"revision_id": rid},
    )
    assert res.status_code == 409
    assert storage.read_translated(ch) == "ai đó sửa giữa chừng"
    assert storage.read_ai_revision(ch, rid).status == "pending"


def test_confirm_khong_co_revision_id_tra_400(client):
    _client, _storage = client
    res = _client.post("/api/ui/ebooks/t/chapters/1/ai/rewrite/confirm", json={})
    assert res.status_code == 400


def test_discard_candidate_khong_dong_den_ban_dich(client):
    _client, storage = client
    rid = _pending_revision(storage)
    res = _client.post(
        "/api/ui/ebooks/t/chapters/1/ai/rewrite/discard",
        json={"revision_id": rid},
    )
    assert res.status_code == 200
    assert storage.read_ai_revision(ch, rid).status == "discarded"
    assert storage.read_translated(ch) == "bản dịch cũ"