"""Regression: `preview_plan` ước lượng token cho `ai-edit-draft`.

Nhánh ước lượng dùng `revisions.BRANCH_LOCAL_MT` nhưng `revisions` chỉ được
import cục bộ trong `chapter_eligibility`/`chapter_fingerprint`, nên mỗi chương
ĐỦ ĐIỀU KIỆN đều ném `NameError` → `/bulk-preview` trả 500 và nút "Biên tập AI"
không bao giờ tạo được job. Chương chưa có Local MT thì `ok=False` nên nhánh
`else 0` che mất lỗi — vì vậy test phải có cả hai loại chương.
"""
from __future__ import annotations

from novel2epub import bulk_contract, revisions
from novel2epub.storage import Chapter, Manifest, Storage


def _seed(tmp_path):
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=i, url=f"http://x/{i}", title=f"Chương {i}") for i in (1, 2)]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    storage.write_branch_text(chapters[0], revisions.BRANCH_LOCAL_MT, "x" * 40)
    return storage, storage.load_manifest()


def test_preview_plan_ai_edit_draft_uoc_luong_duoc_token(tmp_path):
    storage, manifest = _seed(tmp_path)

    plan = bulk_contract.preview_plan(
        storage, manifest, action="ai-edit-draft", indexes=[1, 2],
    )

    assert plan["eligible"] == 1
    assert plan["blocked"] == 1
    # 40 ký tự Local MT → (40 + 3) // 4 = 10 token đầu vào.
    assert plan["estimates"]["input_tokens"] == 10
    assert plan["estimates"]["blocked_indexes"] == [2]


def test_preview_plan_translate_van_uoc_luong_tu_ban_goc(tmp_path):
    storage = Storage(tmp_path, "t")
    chapters = [Chapter(index=1, url="http://x/1", title="Chương 1")]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    storage.write_raw(chapters[0], "y" * 80)

    plan = bulk_contract.preview_plan(
        storage, storage.load_manifest(), action="translate", indexes=[1], branch="ai",
    )

    assert plan["eligible"] == 1
    assert plan["estimates"]["input_tokens"] == 20


def test_preview_plan_local_mt_khong_nham_toc_da_dich_la_noi_dung_da_dich(tmp_path):
    storage = Storage(tmp_path, "t")
    chapter = Chapter(
        index=1,
        url="http://x/1",
        title="Chương 1: Khởi đầu",
        title_zh="第一章 开始",
    )
    storage.save_manifest(Manifest(slug="t", chapters=[chapter]))
    storage.write_raw(chapter, "Nội dung gốc" * 10)
    storage.write_branch_titles(
        chapter,
        revisions.BRANCH_LOCAL_MT,
        "Chương 1: Khởi đầu",
        "第一章 开始",
    )

    plan = bulk_contract.preview_plan(
        storage, storage.load_manifest(), action="local-mt", indexes=[1],
    )

    assert plan["eligible"] == 1
    assert plan["blocked"] == 0
    assert storage.has_branch_text(chapter, revisions.BRANCH_LOCAL_MT) is False


def test_preview_plan_local_mt_neu_chi_co_toc_thi_bao_thieu_noi_dung_goc(tmp_path):
    storage = Storage(tmp_path, "t")
    chapter = Chapter(
        index=1,
        url="http://x/1",
        title="Chương 1: Khởi đầu",
        title_zh="第一章 开始",
    )
    storage.save_manifest(Manifest(slug="t", chapters=[chapter]))

    plan = bulk_contract.preview_plan(
        storage, storage.load_manifest(), action="local-mt", indexes=[1],
    )

    assert plan["eligible"] == 0
    assert plan["blocked"] == 1
    assert plan["chapters"][0]["reason"] == (
        "Chưa crawl nội dung gốc của chương — TOC/tiêu đề không phải nội dung để dịch."
    )
