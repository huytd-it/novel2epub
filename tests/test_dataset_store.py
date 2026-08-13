from novel2epub.dataset_store import backfill_dataset_store
from novel2epub.storage import Chapter, Manifest, Storage


def _seed(tmp_path):
    storage = Storage(tmp_path, "t")
    chapter = Chapter(index=1, url="https://example.test/1", title="Chương AI", title_zh="第一章")
    storage.save_manifest(Manifest(slug="t", chapters=[chapter]))
    raw = "第一段。\n\n第二段。"
    ai = "Đoạn AI một.\n\nĐoạn AI hai."
    local = "Đoạn MT một.\n\nĐoạn MT hai."
    storage.write_raw(chapter, raw)
    storage.write_branch_text(chapter, "ai", ai)
    storage.write_branch_text(chapter, "local_mt", local)
    storage.write_branch_titles(chapter, "ai", "Chương AI", "第一章")
    storage.write_branch_titles(chapter, "local_mt", "Chương MT", "第一章")
    storage.mark_branch_complete(chapter, "ai")
    storage.mark_branch_complete(chapter, "local_mt")
    return storage, chapter, raw, ai, local


def test_backfill_creates_canonical_store_without_mutating_workspace(tmp_path):
    storage, chapter, raw, ai, local = _seed(tmp_path)
    before = (
        storage.read_raw(chapter), storage.read_branch_text(chapter, "ai"),
        storage.read_branch_text(chapter, "local_mt"), storage.active_branch(chapter),
        storage.read_branch_revision(chapter, "ai"), storage.read_branch_revision(chapter, "local_mt"),
    )

    result = backfill_dataset_store(storage)

    assert result.source_revisions == 1
    assert result.translation_links == 2
    assert result.source_segments == 2
    assert result.translation_segments == 4
    assert result.alignments == 2
    assert before == (
        storage.read_raw(chapter), storage.read_branch_text(chapter, "ai"),
        storage.read_branch_text(chapter, "local_mt"), storage.active_branch(chapter),
        storage.read_branch_revision(chapter, "ai"), storage.read_branch_revision(chapter, "local_mt"),
    )
    assert storage.read_raw(chapter) == raw
    assert storage.read_branch_text(chapter, "ai") == ai
    assert storage.read_branch_text(chapter, "local_mt") == local

    source = storage.conn.execute("SELECT * FROM chapter_source_revisions").fetchone()
    assert source["source_url"] == chapter.url
    assert source["fetcher_kind"] == "legacy_unknown"
    assert len(source["content_hash"]) == 64
    assert storage.conn.execute(
        "SELECT COUNT(*) AS c FROM chapter_revisions WHERE source_revision_id=?", (source["id"],)
    ).fetchone()["c"] == 2
    alignments = storage.conn.execute("SELECT * FROM segment_alignments ORDER BY id").fetchall()
    assert [(row["method"], row["status"], row["confidence"]) for row in alignments] == [
        ("ordinal_backfill", "proposed", 0.25),
        ("ordinal_backfill", "proposed", 0.25),
    ]
    assert all('"training_eligible": false' in row["metadata_json"] for row in alignments)
    assert storage.conn.execute("SELECT COUNT(*) AS c FROM chapter_eligibility_decisions").fetchone()["c"] == 0


def test_backfill_is_idempotent_and_stable(tmp_path):
    storage, *_ = _seed(tmp_path)
    first = backfill_dataset_store(storage)
    keys = [row["stable_key"] for row in storage.conn.execute("SELECT stable_key FROM chapter_segments ORDER BY id")]

    second = backfill_dataset_store(storage)

    assert first.source_revisions == 1
    assert second.source_revisions == 0
    assert second.translation_links == 0
    assert second.source_segments == 0
    assert second.translation_segments == 0
    assert second.alignments == 0
    assert keys == [row["stable_key"] for row in storage.conn.execute("SELECT stable_key FROM chapter_segments ORDER BY id")]


def test_alignment_keeps_unpaired_segments_explicit(tmp_path):
    storage = Storage(tmp_path, "t")
    chapter = Chapter(index=1, url="u", title_zh="源")
    storage.save_manifest(Manifest(slug="t", chapters=[chapter]))
    storage.write_raw(chapter, "甲\n乙")
    storage.write_branch_text(chapter, "local_mt", "Một")
    storage.mark_branch_complete(chapter, "local_mt")

    backfill_dataset_store(storage)

    alignment = storage.conn.execute("SELECT id FROM segment_alignments").fetchone()["id"]
    members = storage.conn.execute(
        "SELECT group_ordinal, side FROM segment_alignment_members WHERE alignment_id=? "
        "ORDER BY group_ordinal, side", (alignment,),
    ).fetchall()
    assert [(row["group_ordinal"], row["side"]) for row in members] == [
        (0, "source"), (0, "translation"), (1, "source")
    ]
