"""Test hộp bản nháp AI (candidate revisions): engine registry, snapshot,
expiry, optimistic apply — logic thuần trong novel2epub.revisions + Storage.
"""
from __future__ import annotations

import pytest

from novel2epub import revisions
from novel2epub.storage import Chapter, Manifest, Storage


def _rev(**kw):
    base = dict(
        engine="rewrite", idx=1, payload="bản mới", base_rev=1,
        base_translated_text="", has_raw=False,
    )
    base.update(kw)
    return base


# ---------- Registry engine: độc lập + quyền raw ----------


def test_rewrite_khong_duoc_dung_raw():
    assert revisions.ENGINES.allows_raw("rewrite") is False
    assert revisions.ENGINES.allows_raw("han-cleanup") is False


def test_review_suggest_duoc_dung_raw_de_doi_chieu():
    assert revisions.ENGINES.allows_raw("review") is True
    assert revisions.ENGINES.allows_raw("suggest") is True


def test_chi_candidate_ap_duoc_len_ban_dich():
    assert revisions.ENGINES.applies_to_translation("rewrite") is True
    assert revisions.ENGINES.applies_to_translation("han-cleanup") is True
    assert revisions.ENGINES.applies_to_translation("review") is False
    assert revisions.ENGINES.applies_to_translation("suggest") is False


def test_engine_khong_dang_ky():
    assert revisions.ENGINES.exists("bogus") is False


# ---------- CreateRevision: candidate không tự áp ----------


def test_create_candidate_mac_dinh_pending():
    cand = revisions.create_revision(**_rev())
    assert cand.status == revisions.STATUS_PENDING
    assert cand.created_at
    assert cand.expires_at
    assert cand.base_translated_text == ""


def test_create_candidate_engine_la_thi_loi():
    with pytest.raises(ValueError):
        revisions.create_revision(**_rev(engine="nonexistent"))


def test_candidate_luu_snapshot_goc_va_has_raw():
    cand = revisions.create_revision(**_rev(base_rev=7, base_translated_text="cũ", has_raw=False))
    assert cand.base_rev == 7
    assert cand.base_translated_text == "cũ"
    assert cand.has_raw is False


# ---------- check_still_valid: snapshot expiry + exact base ----------


def test_still_valid_khi_dung_snapshot_trong_han():
    cand = revisions.create_revision(**_rev(base_rev=1, base_translated_text="cũ"))
    reason = revisions.check_still_valid(cand, current_rev=1, current_translated_text="cũ")
    assert reason is None


def test_stale_khi_ban_dich_doi_khoi_snapshot():
    cand = revisions.create_revision(**_rev(base_rev=1, base_translated_text="cũ"))
    reason = revisions.check_still_valid(cand, current_rev=1, current_translated_text="khác")
    assert reason is not None
    assert "thay đổi" in reason


def test_stale_khi_revision_doi():
    cand = revisions.create_revision(**_rev(base_rev=1, base_translated_text="cũ"))
    reason = revisions.check_still_valid(cand, current_rev=2, current_translated_text="cũ")
    assert reason is not None


def test_stale_khi_het_han():
    cand = revisions.create_revision(**_rev(base_rev=1, base_translated_text="cũ"))
    cand.expires_at = "2000-01-01T00:00:00.000000Z"
    reason = revisions.check_still_valid(cand, current_rev=1, current_translated_text="cũ")
    assert reason is not None
    assert "hết hạn" in reason


def test_stale_khi_khong_con_pending():
    cand = revisions.create_revision(**_rev(base_rev=1, base_translated_text="cũ"))
    cand.status = revisions.STATUS_APPLIED
    reason = revisions.check_still_valid(cand, current_rev=1, current_translated_text="cũ")
    assert reason is not None


# ---------- Storage: optimistic compare-and-swap trên `revision` ----------


def _storage(tmp_path) -> tuple[Storage, Chapter]:
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=1, url="http://x/1")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    storage.write_translated(ch, "cũ")
    return storage, ch


def test_compare_and_swap_thanh_cong_bump_revision(tmp_path):
    storage, ch = _storage(tmp_path)
    rev = storage.read_revision(ch)
    assert storage.compare_and_swap_translation(ch, expected_rev=rev, new_text="mới") is True
    assert storage.read_translated(ch) == "mới"
    assert storage.read_revision(ch) == rev + 1


def test_compare_and_swap_tu_choi_khi_revision_doi(tmp_path):
    storage, ch = _storage(tmp_path)
    # Ai đó (đồng thời) đã bump revision lên 5 sau khi bản nháp sinh từ rev=1.
    with storage.conn:
        storage.conn.execute(
            "UPDATE chapters SET revision=5 WHERE ebook_slug='t' AND idx=?",
            (ch.index,),
        )
    assert storage.read_revision(ch) == 5
    assert storage.compare_and_swap_translation(ch, expected_rev=1, new_text="mới") is False
    # Bản dịch không bị đè.
    assert storage.read_translated(ch) == "cũ"
    assert storage.read_revision(ch) == 5


def test_compare_and_swap_khong_ghi_khi_revision_khong_khop(tmp_path):
    storage, ch = _storage(tmp_path)
    # Giả lập hai bản nháp sinh từ cùng bản cũ (rev=1); một bản áp trước bump → 2.
    assert storage.compare_and_swap_translation(ch, expected_rev=1, new_text="bản A") is True
    # Bản B vẫn giữ expected_rev=1 (cũ) → phải từ chối, KHÔNG ghi đè bản A.
    assert storage.compare_and_swap_translation(ch, expected_rev=1, new_text="bản B") is False
    assert storage.read_translated(ch) == "bản A"


def test_create_read_mark_revision_vong_doi(tmp_path):
    storage, ch = _storage(tmp_path)
    cand = revisions.create_revision(
        engine="rewrite", idx=1, payload="bản nháp", base_rev=1,
        base_translated_text="cũ", has_raw=False,
    )
    rid = storage.create_ai_revision(cand)
    stored = storage.read_ai_revision(ch, rid)
    assert stored.engine == "rewrite"
    assert stored.payload == "bản nháp"
    assert stored.status == revisions.STATUS_PENDING

    storage.mark_ai_revision(ch, rid, status=revisions.STATUS_APPLIED)
    assert storage.read_ai_revision(ch, rid).status == revisions.STATUS_APPLIED
    listed = storage.list_ai_revisions(ch)
    assert listed[0]["id"] == rid
    assert storage.revision_chapter(rid) == 1


def test_expire_stale_revisions_only_pending_qua_han(tmp_path):
    storage, ch = _storage(tmp_path)
    fresh = revisions.create_revision(
        engine="rewrite", idx=1, payload="mới", base_rev=1, base_translated_text="cũ", has_raw=False
    )
    stale = revisions.create_revision(
        engine="rewrite", idx=1, payload="hết hạn", base_rev=1, base_translated_text="cũ", has_raw=False
    )
    stale.expires_at = "2000-01-01T00:00:00.000000Z"
    fresh_id = storage.create_ai_revision(fresh)
    stale_id = storage.create_ai_revision(stale)

    assert storage.expire_stale_revisions(ch) == 1
    assert storage.read_ai_revision(ch, stale_id).status == revisions.STATUS_EXPIRED
    assert storage.read_ai_revision(ch, fresh_id).status == revisions.STATUS_PENDING