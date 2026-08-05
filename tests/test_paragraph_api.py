"""API đọc/sửa đoạn văn — nền cho việc sửa từ readest ở giai đoạn 2."""
from __future__ import annotations

from novel2epub.storage import Chapter, Manifest, Storage

from .test_opds_routes import _client

MD = "# Chương 1\n\nĐoạn một.\n\nĐoạn hai.\n\nĐoạn ba."


def _seed(tmp_path, slug: str = "a", *, translated: str = MD):
    storage = Storage(tmp_path, slug)
    ch = Chapter(index=1, url="http://x/1", title="C1")
    storage.save_manifest(Manifest(slug=slug, title=f"Tên {slug}", chapters=[ch]))
    if translated:
        storage.write_translated(ch, translated)
        storage.mark_translated_complete(ch)
    return storage, ch


def test_get_tra_ve_danh_sach_doan_kem_chi_so(monkeypatch, tmp_path):
    _seed(tmp_path)
    r = _client(monkeypatch, tmp_path, ["a"]).get("/api/v1/ebooks/a/chapters/1")
    assert r.status_code == 200
    data = r.json()
    assert data["index"] == 1
    assert [p["index"] for p in data["paragraphs"]] == [0, 1, 2, 3]
    assert data["paragraphs"][1]["text"] == "Đoạn một."


def test_get_chuong_khong_ton_tai_tra_404(monkeypatch, tmp_path):
    _seed(tmp_path)
    assert _client(monkeypatch, tmp_path, ["a"]).get(
        "/api/v1/ebooks/a/chapters/99"
    ).status_code == 404


def test_patch_sua_dung_doan_va_khong_dong_doan_khac(monkeypatch, tmp_path):
    storage, ch = _seed(tmp_path)
    r = _client(monkeypatch, tmp_path, ["a"]).patch(
        "/api/v1/ebooks/a/chapters/1/paragraphs/2",
        json={"text": "Đoạn hai đã sửa.", "expected": "Đoạn hai."},
    )
    assert r.status_code == 200
    from novel2epub.notes import split_paras

    paras = split_paras(storage.read_translated(ch))
    assert paras == ["# Chương 1", "Đoạn một.", "Đoạn hai đã sửa.", "Đoạn ba."]


def test_patch_sai_expected_tra_409_kem_noi_dung_hien_tai(monkeypatch, tmp_path):
    storage, ch = _seed(tmp_path)
    r = _client(monkeypatch, tmp_path, ["a"]).patch(
        "/api/v1/ebooks/a/chapters/1/paragraphs/2",
        json={"text": "X", "expected": "Nội dung cũ đã lỗi thời."},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["current"] == "Đoạn hai."
    # KHÔNG được ghi gì
    assert "Đoạn hai." in storage.read_translated(ch)


def test_patch_chi_so_vuot_pham_vi_tra_409(monkeypatch, tmp_path):
    _seed(tmp_path)
    r = _client(monkeypatch, tmp_path, ["a"]).patch(
        "/api/v1/ebooks/a/chapters/1/paragraphs/99",
        json={"text": "X", "expected": "Y"},
    )
    assert r.status_code == 409


def test_patch_text_rong_tra_400_va_khong_xoa_doan(monkeypatch, tmp_path):
    # replace_para khi nhận rỗng sẽ XOÁ dòng rồi đánh lại chỉ số các đoạn sau —
    # client giữ chỉ số cũ sẽ sửa nhầm ở lần gọi kế tiếp.
    storage, ch = _seed(tmp_path)
    for payload in ({"text": "", "expected": "Đoạn hai."},
                    {"text": "   ", "expected": "Đoạn hai."}):
        r = _client(monkeypatch, tmp_path, ["a"]).patch(
            "/api/v1/ebooks/a/chapters/1/paragraphs/2", json=payload
        )
        assert r.status_code == 400
    assert "Đoạn hai." in storage.read_translated(ch)


def test_patch_chuong_chua_dich_tra_404(monkeypatch, tmp_path):
    _seed(tmp_path, translated="")
    r = _client(monkeypatch, tmp_path, ["a"]).patch(
        "/api/v1/ebooks/a/chapters/1/paragraphs/0",
        json={"text": "X", "expected": "Y"},
    )
    assert r.status_code == 404


def test_api_sua_duoc_bao_ve_boi_token(monkeypatch, tmp_path):
    _seed(tmp_path)
    client = _client(monkeypatch, tmp_path, ["a"], token="tok", host="192.168.1.20")
    assert client.get("/api/v1/ebooks/a/chapters/1").status_code == 401
    assert client.patch(
        "/api/v1/ebooks/a/chapters/1/paragraphs/1",
        json={"text": "X", "expected": "Y"},
    ).status_code == 401


def test_bearer_token_dung_thi_sua_duoc(monkeypatch, tmp_path):
    storage, ch = _seed(tmp_path)
    client = _client(monkeypatch, tmp_path, ["a"], token="tok", host="192.168.1.20")
    r = client.patch(
        "/api/v1/ebooks/a/chapters/1/paragraphs/1",
        json={"text": "Đoạn một đã sửa.", "expected": "Đoạn một."},
        headers={"Authorization": "Bearer tok"},
    )
    assert r.status_code == 200
    assert "Đoạn một đã sửa." in storage.read_translated(ch)
