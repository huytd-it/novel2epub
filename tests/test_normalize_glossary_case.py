"""Test `scripts.normalize_glossary_case` — hàm thuần + kế hoạch sửa.

Script dọn dữ liệu thật nên phần dễ sai nhất là quy tắc HOA/THƯỜNG: phải hoá
từng chữ nhưng KHÔNG được phá chữ viết tắt, tên có hoa bên trong (McDonald) và
dấu bao quanh.
"""
from __future__ import annotations

import sqlite3

import pytest

from scripts.normalize_glossary_case import (
    SKIP_NO_HAN,
    plan_changes,
    title_case_vi,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Hoá từng chữ — phần lớn glossary.
        ("Cực Địa nhân", "Cực Địa Nhân"),
        ("Lửa trại", "Lửa Trại"),
        ("tinh anh binh sĩ", "Tinh Anh Binh Sĩ"),
        ("Cha của chư thần", "Cha Của Chư Thần"),
        # Dấu bao quanh / ngăn cách phải nằm ngoài lõi từ.
        ("Giáp Tấm Hắc Thiết (Lục)", "Giáp Tấm Hắc Thiết (Lục)"),
        ("giáp tấm hắc thiết (lục)", "Giáp Tấm Hắc Thiết (Lục)"),
        ("Cơ Khí Không Chiến - Cuồng Phong", "Cơ Khí Không Chiến - Cuồng Phong"),
        ("Cơ khí không chiến - cuồng phong", "Cơ Khí Không Chiến - Cuồng Phong"),
        ("Bulun · Thiết Bích", "Bulun · Thiết Bích"),
        ("Bulun · thiết bích", "Bulun · Thiết Bích"),
        # Chữ viết tắt ALL-CAPS giữ nguyên (chỉ 3 token kiểu này trong dữ liệu
        # thật: PAC-7000, SS, IG03).
        ("NPC và mob", "NPC Và Mob"),
        # Viết tắt CHỮ THƯỜNG không giữ: không phân biệt được `hp` với `có`,
        # `mà`, `ta` — mà sai 3 từ tiếng Việt thường còn hại hơn sai 1 viết tắt.
        ("hp buff", "Hp Buff"),
        # Tên có hoa bên trong là cố ý — không hạ.
        ("McDonald", "McDonald"),
        ("O'Brien", "O'Brien"),
        ("Peggy Jamison", "Peggy Jamison"),
        # Chữ Trung trong cột Việt không có hoa/thường.
        ("残留 汉字", "残留 汉字"),
        # Số và ký hiệu không có chữ cái.
        ("Khu 174", "Khu 174"),
        ("cấp 3", "Cấp 3"),
        # Tiếng Việt có đủ dấu — str.upper() phải xử lý được.
        ("đại tráng", "Đại Tráng"),
        ("nhị tráng", "Nhị Tráng"),
        ("tứ đại khu", "Tứ Đại Khu"),
        # Rỗng / chỉ khoảng trắng.
        ("", ""),
        ("   ", "   "),
    ],
)
def test_title_case_vi(raw, expected):
    assert title_case_vi(raw) == expected


def test_title_case_vi_is_idempotent():
    """Chạy lại trên output không đổi gì — nếu không script sẽ lúc nào cũng
    báo "có mục lệch" dù bảng đã đúng."""
    once = title_case_vi("giáp tấm hắc thiết (lục) · mob hp")
    assert title_case_vi(once) == once


def test_title_case_vi_preserves_whitespace():
    assert title_case_vi("  nơi  trú  ẩn  ") == "  Nơi  Trú  Ẩn  "


def _conn(rows):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE glossary_entries ("
        " ebook_slug TEXT, list_name TEXT, source TEXT, target TEXT,"
        " note TEXT, position INTEGER)"
    )
    conn.executemany(
        "INSERT INTO glossary_entries VALUES (?,?,?,?,?,?)", rows
    )
    return conn


def test_plan_changes_only_touches_han_sources():
    """Cột Hán không có chữ Trung = nguồn đã hỏng; chuẩn hoá hoa/thường không
    cứu được nên phải bỏ qua, không tự ý sửa."""
    conn = _conn(
        [
            ("s", "names.txt", "极地人", "Cực Địa nhân", "", 0),          # đổi
            ("s", "names.txt", "曹星", "Tào Tinh", "", 1),               # giữ
            ("s", "names.txt", "Đại chủ giáo Sullivan", "Đại chủ giáo Sullivan", "", 2),  # bỏ qua
            ("s", "names.txt", "Tuyết Nguyên Cuồng Phong", "狂风雪原", "", 3),          # bỏ qua
        ]
    )
    plan = plan_changes(conn, "s")
    assert plan["total"] == 4
    assert [(c["source"], c["new_target"]) for c in plan["changes"]] == [
        ("极地人", "Cực Địa Nhân")
    ]
    assert [s["reason"] for s in plan["skipped"]] == [SKIP_NO_HAN, SKIP_NO_HAN]


def test_plan_changes_reports_every_field_needed_to_undo():
    """Backup phải đủ để `--restore` ghi đúng đúng dòng về đúng giá trị."""
    conn = _conn([("s", "names.txt", "极地人", "Cực Địa nhân", "ghi chú", 7)])
    change = plan_changes(conn, "s")["changes"][0]
    assert change["old_target"] == "Cực Địa nhân"
    assert change["list_name"] == "names.txt"
    assert change["note"] == "ghi chú"


def test_plan_changes_empty_when_already_conformant():
    conn = _conn([("s", "names.txt", "曹星", "Tào Tinh", "", 0)])
    assert plan_changes(conn, "s")["changes"] == []
