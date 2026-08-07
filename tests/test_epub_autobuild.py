"""Logic thuần quyết định ebook nào cần build lại EPUB cho catalog OPDS."""
from __future__ import annotations

from novel2epub.epub_autobuild import (
    FRESH,
    MISSING,
    STALE,
    UNTRANSLATED,
    BuildState,
    decide,
    due_for_trigger,
    needs_build,
    pending_builds,
)


def _state(**kw) -> BuildState:
    base = dict(slug="a", translated_count=10, latest_translated_at=100.0, epub_mtime=200.0)
    base.update(kw)
    return BuildState(**base)


def test_chua_co_file_epub_thi_missing():
    assert decide(_state(epub_mtime=None)) == MISSING
    assert needs_build(_state(epub_mtime=None))


def test_ban_dich_moi_hon_file_thi_stale():
    assert decide(_state(latest_translated_at=300.0, epub_mtime=200.0)) == STALE
    assert needs_build(_state(latest_translated_at=300.0, epub_mtime=200.0))


def test_file_moi_hon_ban_dich_thi_fresh():
    assert decide(_state(latest_translated_at=100.0, epub_mtime=200.0)) == FRESH
    assert not needs_build(_state(latest_translated_at=100.0, epub_mtime=200.0))


def test_chua_dich_chuong_nao_thi_khong_build_du_chua_co_file():
    """Không có bản dịch thì build ra EPUB rỗng — `step_build_selected` sẽ ném
    lỗi. Phải chặn từ đây chứ không đẩy job để rồi job chết."""
    state = _state(translated_count=0, epub_mtime=None)
    assert decide(state) == UNTRANSLATED
    assert not needs_build(state)


def test_lech_duoi_mot_giay_van_tinh_la_stale():
    """`translated_updated_at` chỉ có độ phân giải 1 giây (unixepoch), mtime
    của file thì chính xác tới micro giây. Dịch lúc 5.9 lưu thành 5.0, build
    xong lúc 5.2 — so sánh trần trụi sẽ kết luận nhầm là FRESH và bản sửa
    vĩnh viễn không lên EPUB."""
    assert decide(_state(latest_translated_at=5.0, epub_mtime=5.2)) == STALE


def test_qua_moc_noi_mot_giay_thi_thoi_stale():
    """Nới 1 giây chỉ được đẻ ra ĐÚNG một lần build dư, không phải build mãi."""
    assert decide(_state(latest_translated_at=5.0, epub_mtime=6.5)) == FRESH


def test_pending_builds_uu_tien_sach_chua_tung_build():
    states = [
        _state(slug="cu", latest_translated_at=300.0, epub_mtime=200.0),  # STALE
        _state(slug="tuoi", latest_translated_at=100.0, epub_mtime=200.0),  # FRESH
        _state(slug="thieu", epub_mtime=None),  # MISSING
        _state(slug="chua-dich", translated_count=0, epub_mtime=None),  # UNTRANSLATED
    ]
    assert [s.slug for s in pending_builds(states)] == ["thieu", "cu"]


def test_pending_builds_rong_khi_moi_thu_deu_tuoi():
    assert pending_builds([_state(latest_translated_at=1.0, epub_mtime=999.0)]) == []


def test_chua_tung_kich_hoat_thi_duoc_chay_ngay():
    assert due_for_trigger(0.0, now=1000.0, cooldown_seconds=300.0)


def test_trong_thoi_gian_nghi_thi_khong_kich_hoat_lai():
    assert not due_for_trigger(1000.0, now=1100.0, cooldown_seconds=300.0)


def test_het_thoi_gian_nghi_thi_kich_hoat_lai():
    assert due_for_trigger(1000.0, now=1300.0, cooldown_seconds=300.0)


def test_dong_ho_bi_chinh_lui_khong_khoa_cung_viec_build():
    """now < last_trigger_at chỉ xảy ra khi đồng hồ hệ thống nhảy lùi. Trả
    False ở đây sẽ khoá việc build cho tới khi đồng hồ đuổi kịp."""
    assert due_for_trigger(5000.0, now=1000.0, cooldown_seconds=300.0)
