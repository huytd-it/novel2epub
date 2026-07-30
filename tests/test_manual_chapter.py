from __future__ import annotations

from pathlib import Path

import pytest

from novel2epub.storage import Chapter, Manifest, Storage


def _storage(tmp_path: Path) -> Storage:
    storage = Storage(tmp_path, "t")
    storage.save_manifest(Manifest(slug="t"))
    return storage


def _chapter_row(storage: Storage, index: int):
    return storage.conn.execute(
        "SELECT * FROM chapters WHERE ebook_slug=? AND idx=?",
        ("t", index),
    ).fetchone()


def test_insert_chapter_into_empty_manifest(tmp_path):
    storage = _storage(tmp_path)

    storage.insert_chapter(Chapter(index=1, url="https://x/1", title="第一章", title_zh="第一章"))

    manifest = storage.load_manifest()
    assert [(ch.index, ch.url, ch.title, ch.title_zh) for ch in manifest.chapters] == [
        (1, "https://x/1", "第一章", "第一章")
    ]


def test_insert_chapter_appends_at_n_plus_one(tmp_path):
    storage = _storage(tmp_path)
    storage.save_manifest(Manifest(slug="t", chapters=[Chapter(1, "https://x/1", "One")]))

    storage.insert_chapter(Chapter(2, "https://x/2", "Two", "Two"))

    assert [ch.index for ch in storage.load_manifest().chapters] == [1, 2]


def test_insert_chapter_shifts_complete_rows_without_data_loss(tmp_path):
    storage = _storage(tmp_path)
    first = Chapter(1, "https://x/1", "One", "一", "note", ["author"], None, "done", True)
    second = Chapter(2, "https://x/2", "Two", "二")
    storage.save_manifest(Manifest(slug="t", chapters=[first, second]))
    storage.write_raw(second, "RAW TWO")
    storage.write_translated(second, "TRANSLATED TWO")
    storage.write_translated_mt(second, "MT TWO")
    storage.write_meta(second, {"complete": True, "warnings": ["kept"]})
    before = dict(_chapter_row(storage, 2))

    storage.insert_chapter(Chapter(2, "https://x/new", "New", "New"))

    shifted = dict(_chapter_row(storage, 3))
    assert {k: v for k, v in shifted.items() if k != "idx"} == {
        k: v for k, v in before.items() if k != "idx"
    }
    assert storage.read_raw(storage.load_manifest().chapters[2]) == "RAW TWO"
    assert storage.read_translated(storage.load_manifest().chapters[2]) == "TRANSLATED TWO"
    assert storage.read_translated_mt(storage.load_manifest().chapters[2]) == "MT TWO"
    assert storage.read_meta(storage.load_manifest().chapters[2]) == {
        "complete": True,
        "warnings": ["kept"],
    }


@pytest.mark.parametrize("index", [0, 3])
def test_insert_chapter_rejects_out_of_range_without_changes(tmp_path, index):
    storage = _storage(tmp_path)
    storage.save_manifest(Manifest(slug="t", chapters=[Chapter(1, "https://x/1", "One")]))
    before = storage.load_manifest().to_json()

    with pytest.raises(ValueError, match="Vị trí"):
        storage.insert_chapter(Chapter(index, "https://x/new", "New"))

    assert storage.load_manifest().to_json() == before


def test_insert_chapter_rejects_duplicate_url_without_changes(tmp_path):
    storage = _storage(tmp_path)
    storage.save_manifest(Manifest(slug="t", chapters=[Chapter(1, "https://x/1", "One")]))
    before = storage.load_manifest().to_json()

    with pytest.raises(ValueError, match="URL"):
        storage.insert_chapter(Chapter(1, "https://x/1", "Duplicate"))

    assert storage.load_manifest().to_json() == before
