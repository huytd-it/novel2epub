"""Nối dây neo đoạn vào payload đẩy lên Supabase.

Cột `chapter_contents.para_anchors` chưa tồn tại bên Supabase cho tới khi chạy
migration, nên `reader.push_anchors` mặc định TẮT. Test ở đây canh hai việc:
payload sạch tuyệt đối khi tắt, và neo đi CÙNG payload với content khi bật.
"""
from __future__ import annotations

from novel2epub import reader_client
from novel2epub.config import ReaderConfig
from novel2epub.reader_sync import classify_chapters


def _cfg(**kw) -> ReaderConfig:
    return ReaderConfig(url="https://x.supabase.co", service_key="k", **kw)


class _Bat:
    """Chặn `_request` để soi payload thay vì gọi mạng thật."""

    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, cfg, method, path, *, params=None, json_body=None, prefer="", log=None):
        self.calls.append({"path": path, "json_body": json_body})
        return []


def test_tat_co_thi_payload_khong_co_para_anchors(monkeypatch):
    bat = _Bat()
    monkeypatch.setattr(reader_client, "_request", bat)
    reader_client.upsert_contents(_cfg(), [("id-1", "Đoạn một.")], anchors_by_id=None)
    assert bat.calls[0]["json_body"] == [{"chapter_id": "id-1", "content": "Đoạn một."}]


def test_bat_thi_neo_nam_cung_payload_voi_content(monkeypatch):
    bat = _Bat()
    monkeypatch.setattr(reader_client, "_request", bat)
    reader_client.upsert_contents(
        _cfg(push_anchors=True),
        [("id-1", "Đoạn một.\n\nĐoạn hai.")],
        anchors_by_id={"id-1": [1, 2]},
    )
    assert bat.calls[0]["json_body"] == [
        {"chapter_id": "id-1", "content": "Đoạn một.\n\nĐoạn hai.", "para_anchors": [1, 2]}
    ]


def test_chapter_id_khong_co_neo_thi_khong_kem_khoa(monkeypatch):
    """Thiếu neo phải là VẮNG MẶT khoá, không phải `para_anchors: []` — mảng
    rỗng sẽ ghi đè neo đúng đang có trên Supabase bằng một mảng vô nghĩa."""
    bat = _Bat()
    monkeypatch.setattr(reader_client, "_request", bat)
    reader_client.upsert_contents(
        _cfg(push_anchors=True),
        [("id-1", "A"), ("id-2", "B")],
        anchors_by_id={"id-1": [0]},
    )
    body = bat.calls[0]["json_body"]
    assert body[0]["para_anchors"] == [0]
    assert "para_anchors" not in body[1]


def test_khong_co_row_thi_khong_goi_mang(monkeypatch):
    bat = _Bat()
    monkeypatch.setattr(reader_client, "_request", bat)
    reader_client.upsert_contents(_cfg(push_anchors=True), [], anchors_by_id={"id": [0]})
    assert bat.calls == []


def test_push_anchors_mac_dinh_tat():
    """Bật nhầm khi Supabase chưa có cột sẽ làm PostgREST trả 400 và hỏng cả
    lần đẩy — mặc định phải là tắt."""
    assert ReaderConfig().push_anchors is False


def test_classify_chapters_tinh_san_neo():
    md = "# Chương 1\n\nĐoạn một.\n\nDòng dẫn:\n— Lời thoại."
    plan = classify_chapters([(1, "Chương 1", md, {})], remote_ids={})
    push = plan.new[0]
    assert push.anchors == [1, 2, 3]
    assert len(push.anchors) == len([ln for ln in push.content.split("\n") if ln.strip()])
