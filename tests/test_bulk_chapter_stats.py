import json
import pytest
from novel2epub.storage import Storage, Chapter


@pytest.fixture
def tmp_storage(tmp_path):
    s = Storage(tmp_path, "test-slug")
    s.ensure_dirs()
    return s


def _ch(idx):
    return Chapter(index=idx, url=f"http://example.com/{idx}", title=f"Ch {idx}")


def test_bulk_chapter_stats_empty(tmp_storage):
    result = tmp_storage.bulk_chapter_stats()
    assert result == {}


def test_bulk_chapter_stats_flags(tmp_storage):
    s = tmp_storage
    ch1 = _ch(1)
    ch2 = _ch(2)
    ch3 = _ch(3)

    s.write_raw(ch1, "你好世界")
    s.write_raw(ch2, "再见")
    s.write_translated(ch2, "Xin chào thế giới")
    s.mark_translated_complete(ch2)
    s.write_translated(ch3, "partial")
    s.write_meta(ch3, {"complete": False})

    result = s.bulk_chapter_stats()

    assert result[1]["has_raw"] is True
    assert result[1]["has_translated"] is False

    assert result[2]["has_raw"] is True
    assert result[2]["has_translated"] is True
    assert result[2]["translated_len"] > 0
    assert result[2]["raw_len"] > 0

    assert result[3]["has_translated"] is False


def test_bulk_chapter_stats_meta_json(tmp_storage):
    s = tmp_storage
    ch = _ch(10)
    s.write_translated(ch, "Xin chào")
    s.write_meta(ch, {"complete": True, "ai_rewrite": {"text": "draft", "generated_at": "2026-01-01"}})
    s.mark_translated_complete(ch)
    result = s.bulk_chapter_stats()
    assert result[10]["meta_json"] is not None
    meta = json.loads(result[10]["meta_json"])
    assert meta.get("ai_rewrite") is not None


def test_bulk_chapter_stats_uses_active_local_mt_branch(tmp_storage):
    s = tmp_storage
    ch = _ch(11)
    s.write_branch_text(ch, "local_mt", "Bản dịch Local MT")
    s.mark_branch_complete(ch, "local_mt")
    s.set_active_branch(ch, "local_mt")

    result = s.bulk_chapter_stats()[11]

    assert result["active_branch"] == "local_mt"
    assert result["has_translated"] is True
    assert result["has_ai_translation"] is False
    assert result["has_local_mt_translation"] is True
    assert result["translated_len"] == len("Bản dịch Local MT")
    assert s.translated_stats()[0] == 1


def test_bulk_chapter_stats_exposes_inactive_local_mt_branch(tmp_storage):
    s = tmp_storage
    ch = _ch(12)
    s.write_raw(ch, "原文")
    s.write_branch_text(ch, "local_mt", "Bản dịch Local MT")
    s.mark_branch_complete(ch, "local_mt")

    result = s.bulk_chapter_stats()[12]

    assert result["active_branch"] == "ai"
    assert result["has_translated"] is False
    assert result["has_ai_translation"] is False
    assert result["has_local_mt_translation"] is True


from novel2epub.toc import chapter_rows, ChapterRow


def test_chapter_rows_with_stats_map(tmp_storage):
    s = tmp_storage
    ch1 = _ch(1)
    ch2 = _ch(2)
    s.write_raw(ch1, "你好世界再见朋友")
    s.write_raw(ch2, "再见")
    s.write_translated(ch2, "Xin chao the gioi")
    s.mark_translated_complete(ch2)

    stats_map = s.bulk_chapter_stats()
    rows = chapter_rows([ch1, ch2], s, stats_map=stats_map)

    assert len(rows) == 2
    r1 = next(r for r in rows if r.index == 1)
    r2 = next(r for r in rows if r.index == 2)

    assert r1.has_raw is True
    assert r1.has_translated is False
    assert r1.word_count == 0
    assert r1.zh_char_count > 0

    assert r2.has_translated is True
    assert r2.word_count > 0


def test_chapter_rows_without_stats_map_still_works(tmp_storage):
    s = tmp_storage
    ch = _ch(5)
    s.write_raw(ch, "你好")
    rows = chapter_rows([ch], s)
    assert rows[0].has_raw is True
    assert rows[0].active_branch == "ai"
    assert rows[0].has_ai_translation is False
    assert rows[0].has_local_mt_translation is False


def test_chapter_rows_expose_translation_state_of_each_branch(tmp_storage):
    s = tmp_storage
    ch = _ch(6)
    s.write_raw(ch, "原文")
    s.write_branch_text(ch, "local_mt", "Bản dịch Local MT")
    s.mark_branch_complete(ch, "local_mt")

    row = chapter_rows([ch], s, stats_map=s.bulk_chapter_stats())[0]

    assert row.active_branch == "ai"
    assert row.has_translated is False
    assert row.has_ai_translation is False
    assert row.has_local_mt_translation is True


def test_chapter_rows_use_active_branch_title(tmp_storage):
    s = tmp_storage
    ch = Chapter(index=5, url="http://example.com/5", title="第5章 仪式")
    s.write_branch_titles(ch, "local_mt", "Chương 5: Nghi thức", "第5章 仪式")
    s.set_active_branch(ch, "local_mt")

    row = chapter_rows([ch], s)[0]

    assert row.title == "Chương 5: Nghi thức"
    assert row.visible_title == "Chương 5: Nghi thức"
