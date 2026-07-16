"""Test logic thuần của việc đẩy chương lên app đọc novel-reader."""
from __future__ import annotations

from novel2epub import footnotes
from novel2epub import reader_sync as rs


# ───────────────────────────── md_to_plaintext ──────────────────────────────


def test_bo_heading_dau_vi_trung_voi_cot_title():
    md = "# Chương 1: Khởi đầu\n\nĐoạn một.\n\nĐoạn hai."
    assert rs.md_to_plaintext(md) == "Đoạn một.\n\nĐoạn hai."


def test_giu_heading_giua_bai_nhung_bo_dau_thang():
    md = "Mở đầu.\n\n## Phần hai\n\nNội dung."
    assert rs.md_to_plaintext(md) == "Mở đầu.\n\nPhần hai\n\nNội dung."


def test_gop_dong_trong_cung_doan_va_ngat_doan_bang_dong_trong():
    md = "Dòng một\nDòng hai\n\nĐoạn sau."
    assert rs.md_to_plaintext(md) == "Dòng một\nDòng hai\n\nĐoạn sau."


def test_xoa_marker_footnote_vi_reader_khong_co_ui_footnote():
    text, notes = footnotes.annotate("Tiêu Viêm bước tới.", {"Tiêu Viêm": "nhân vật chính"})
    assert notes  # annotate thật sự có chèn marker
    assert footnotes.MARK_OPEN in text
    assert rs.md_to_plaintext(text) == "Tiêu Viêm bước tới."


def test_nhieu_dong_trong_lien_tiep_van_ra_mot_ngat_doan():
    assert rs.md_to_plaintext("A.\n\n\n\nB.") == "A.\n\nB."


def test_chuong_chi_co_moi_heading_thi_ra_rong():
    assert rs.md_to_plaintext("# Chương 1") == ""


# ─────────────────────────────── content_hash ───────────────────────────────


def test_hash_on_dinh_va_doi_khi_noi_dung_doi():
    assert rs.content_hash("T", "A") == rs.content_hash("T", "A")
    assert rs.content_hash("T", "A") != rs.content_hash("T", "B")


def test_hash_doi_khi_chi_sua_moi_tieu_de():
    """Sửa mỗi title cũng phải tính là thay đổi — nếu không, đổi tên chương sẽ
    không bao giờ được đẩy lên Reader."""
    assert rs.content_hash("Cũ", "A") != rs.content_hash("Mới", "A")


# ────────────────────────────── classify_chapters ───────────────────────────


def _meta(title: str, md: str, remote_id: str) -> dict:
    """Meta của một chương ĐÃ đẩy đúng trạng thái hiện tại."""
    return {"reader": {
        "hash": rs.content_hash(title, rs.md_to_plaintext(md)),
        "remote_id": remote_id,
        "pushed_at": 1.0,
    }}


def test_chuong_chua_tung_day_la_moi():
    plan = rs.classify_chapters([(1, "Chương 1", "Nội dung.", {})], {})
    assert plan.counts() == {"new": 1, "edited": 0, "unchanged": 0, "skipped": 0}
    assert plan.new[0].index == 1
    assert plan.new[0].content == "Nội dung."
    assert plan.new[0].remote_id == ""


def test_chuong_da_day_va_khong_doi_thi_bo_qua():
    md = "Nội dung."
    items = [(1, "Chương 1", md, _meta("Chương 1", md, "uuid-1"))]
    plan = rs.classify_chapters(items, {1: "uuid-1"})
    assert plan.counts() == {"new": 0, "edited": 0, "unchanged": 1, "skipped": 0}


def test_chuong_sua_noi_dung_thi_la_edited_va_giu_remote_id():
    items = [(1, "Chương 1", "Nội dung MỚI.", _meta("Chương 1", "Nội dung cũ.", "uuid-1"))]
    plan = rs.classify_chapters(items, {1: "uuid-1"})
    assert plan.counts() == {"new": 0, "edited": 1, "unchanged": 0, "skipped": 0}
    assert plan.edited[0].remote_id == "uuid-1"
    assert plan.edited[0].content == "Nội dung MỚI."


def test_local_noi_da_day_nhung_remote_mat_thi_coi_la_moi():
    """Tự phục hồi khi Reader từng bị ingest-epub.ts/admin-import xoá sạch
    chapters — state local nói 'đã đẩy' nhưng remote không còn gì."""
    md = "Nội dung."
    items = [(1, "Chương 1", md, _meta("Chương 1", md, "uuid-cu"))]
    plan = rs.classify_chapters(items, {})  # remote rỗng
    assert plan.counts() == {"new": 1, "edited": 0, "unchanged": 0, "skipped": 0}


def test_local_noi_chua_day_nhung_remote_da_co_thi_nhan_id_va_coi_la_sua():
    """Tránh tạo trùng khi state local mất mà Reader vẫn còn chương."""
    plan = rs.classify_chapters([(1, "Chương 1", "Nội dung.", {})], {1: "uuid-co-san"})
    assert plan.counts() == {"new": 0, "edited": 1, "unchanged": 0, "skipped": 0}
    assert plan.edited[0].remote_id == "uuid-co-san"


def test_remote_id_lech_voi_state_local_thi_coi_la_sua():
    """Chương bị tạo lại bên Reader (id mới) -> phải đẩy lại nội dung cho id đó."""
    md = "Nội dung."
    items = [(1, "Chương 1", md, _meta("Chương 1", md, "uuid-cu"))]
    plan = rs.classify_chapters(items, {1: "uuid-moi"})
    assert plan.counts() == {"new": 0, "edited": 1, "unchanged": 0, "skipped": 0}
    assert plan.edited[0].remote_id == "uuid-moi"


def test_chuong_rong_sau_khi_chuyen_doi_thi_bi_bo_qua():
    plan = rs.classify_chapters([(1, "Chương 1", "# Chương 1", {})], {})
    assert plan.counts() == {"new": 0, "edited": 0, "unchanged": 0, "skipped": 1}


def test_meta_reader_hong_kieu_du_lieu_thi_coi_nhu_chua_day():
    items = [(1, "Chương 1", "Nội dung.", {"reader": "không phải dict"})]
    plan = rs.classify_chapters(items, {})
    assert plan.counts()["new"] == 1


def test_phan_loai_hon_hop_nhieu_chuong():
    md = "Giữ nguyên."
    items = [
        (1, "C1", md, _meta("C1", md, "u1")),        # không đổi
        (2, "C2", "Đã sửa.", _meta("C2", "Cũ.", "u2")),  # sửa
        (3, "C3", "Chương mới.", {}),                 # mới
    ]
    plan = rs.classify_chapters(items, {1: "u1", 2: "u2"})
    assert plan.counts() == {"new": 1, "edited": 1, "unchanged": 1, "skipped": 0}
    assert plan.total_changed == 2


# ──────────────────────────────── is_free ───────────────────────────────────


def test_is_free_chi_ap_cho_n_chuong_dau():
    assert rs.is_free(1, 5) is True
    assert rs.is_free(5, 5) is True
    assert rs.is_free(6, 5) is False


def test_free_chapters_bang_0_thi_khong_chuong_nao_mien_phi():
    assert rs.is_free(1, 0) is False


def test_word_count_dem_tu_cua_noi_dung_plain_text():
    push = rs.ChapterPush(index=1, title="T", content="một hai ba", hash="x")
    assert push.word_count == 3
