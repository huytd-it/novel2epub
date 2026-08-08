"""Khoá hợp đồng giữa API đọc cấu hình và các form lưu cấu hình.

`GET /api/ui/ebooks/{slug}/settings` trả cấu hình phẳng theo ĐÚNG tên tham số
`Form(...)` của các endpoint lưu trong `app/routes/settings.py`, vì giao diện
mới POST thẳng vào chính các endpoint cũ đó.

Đây là loại ràng buộc mục âm thầm: thêm một trường vào form mà quên thêm vào
API thì ô đó hiện rỗng rồi ghi đè giá trị thật bằng rỗng lúc người dùng bấm
Lưu — không có lỗi nào nổ ra. Test này so hai đầu và bắt lệch ngay.
"""
from __future__ import annotations

import inspect

import pytest
from fastapi.testclient import TestClient

from app.routes import settings as settings_routes

from .conftest import write_db_config

# (khoá trong JSON, hàm xử lý form tương ứng)
SECTIONS = [
    ("novel", "save_novel"),
    ("source", "save_source"),
    ("translate", "save_translate"),
    ("ai", "save_ai"),
    ("reader", "save_reader"),
    ("output", "save_output"),
]

# Tham số đường dẫn / hạ tầng, không phải trường cấu hình.
NON_FIELDS = {"request", "slug"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = write_db_config(
        tmp_path / "n.db",
        defaults={"output": {"data_dir": str(tmp_path / "data")}},
        ebooks={"t": {"name": "Truyện thử", "novel": {"title": "Truyện thử"}}},
    )
    monkeypatch.setattr("app.deps.WORKSPACE_PATH", str(db))
    monkeypatch.setattr("app.deps.DB_PATH", str(db))
    from app.main import app

    return TestClient(app, client=("127.0.0.1", 12345))


def form_fields(fn_name: str) -> set[str]:
    fn = getattr(settings_routes, fn_name)
    return {p for p in inspect.signature(fn).parameters if p not in NON_FIELDS}


@pytest.mark.parametrize(("section", "fn_name"), SECTIONS)
def test_api_tra_dung_bo_truong_ma_form_nhan(client, section, fn_name):
    payload = client.get("/api/ui/ebooks/t/settings").json()
    assert set(payload[section]) == form_fields(fn_name)


def test_moi_section_deu_co_mat(client):
    payload = client.get("/api/ui/ebooks/t/settings").json()
    for section, _ in SECTIONS:
        assert section in payload, f"thiếu section {section}"


def test_danh_sach_tra_ve_dang_van_ban_moi_dong_mot_muc(client):
    """`subjects` và `strip_patterns` là list trong config nhưng form nhận text.

    Form tự tách lại bằng `splitlines()`, nên API phải nối bằng "\\n" — trả
    mảng JSON thì ô textarea sẽ hiện "[object Object]".
    """
    payload = client.get("/api/ui/ebooks/t/settings").json()
    assert isinstance(payload["novel"]["subjects"], str)
    assert isinstance(payload["source"]["strip_patterns"], str)


def test_meta_du_de_dung_giao_dien(client):
    meta = client.get("/api/ui/ebooks/t/settings").json()["meta"]
    assert set(meta) >= {
        "source_name",
        "source_detected",
        "source_presets",
        "overridden_fields",
        "genres",
    }
    assert all({"value", "label"} <= set(g) for g in meta["genres"])


def test_slug_khong_ton_tai_tra_404_khong_phai_500(client):
    """Khớp hành vi của `resolved_cfg`/`ebook_cfg` ở các endpoint khác: thư viện
    đã có ebook thì slug lạ là 404 (not found), không phải lỗi server."""
    res = client.get("/api/ui/ebooks/khong-co-that/settings")
    assert res.status_code == 404
