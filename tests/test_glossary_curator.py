import json

import pytest

from novel2epub import glossary_curator as curator
from novel2epub import openai_client
from novel2epub.config import OpenAIConfig
from novel2epub.storage import Storage, Chapter, Manifest


def setup_storage(tmp_path):
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    storage.write_glossary_entries("names.txt", [
        ("张三", "Trương Sai", "Chú thích độc giả"),
        ("rác", "lỗi", "log kỹ thuật"),
        ("长生剑法", "Trường Sinh Kiếm Pháp", ""),
    ])
    return storage


def rows(storage):
    return [{"source": s, "target": t, "note": n} for s, t, n in storage.read_glossary_entries_merged()]


@pytest.mark.parametrize("selected_only", [False, True])
def test_prompt_vietnamese_with_grounded_character_notes(selected_only):
    prompt = curator.build_prompt([], [], {}, "", selected_only=selected_only)
    assert "biên tập viên glossary" in prompt
    assert "NHÂN VẬT" in prompt
    assert "tối đa 30 từ" in prompt
    assert "Thiếu bằng chứng thì bỏ trường note" in prompt
    assert "Không tạo ghi chú cho địa danh" in prompt
    assert "Bỏ trường note để giữ ghi chú cũ" in prompt
    assert "Viết target, note và reason bằng tiếng Việt" in prompt
    if selected_only:
        assert "giữ nguyên quy tắc dịch và ghi chú" in prompt


def test_crud_propagates_and_separates_reader_note(tmp_path):
    storage = setup_storage(tmp_path)
    chapter = Chapter(index=1, url="http://x/1")
    storage.save_manifest(Manifest(slug="t", chapters=[chapter]))
    storage.write_translated(chapter, "Trương Sai cầm kiếm. lỗi vẫn là nội dung.")
    result = curator.apply_operations(storage, rows(storage), [
        {"op": "update", "original_source": "张三", "source": "张三", "target": "Trương Tam", "reason": "Sửa phiên âm"},
        {"op": "delete", "original_source": "rác", "reason": "Không phải thuật ngữ"},
        {"op": "create", "original_source": "长生剑法", "source": "长生", "target": "Trường Sinh", "reason": "Thuật ngữ thành phần"},
    ])
    assert len(result["operations"]) == 3
    assert storage.read_glossary_file("names.txt")["张三"] == "Trương Tam"
    assert "rác" not in storage.read_glossary_file("names.txt")
    assert "长生" in storage.read_glossary_file("names.txt")
    assert storage.read_glossary_notes()["Trương Tam"] == "Chú thích độc giả"
    assert storage.read_translated(chapter) == "Trương Tam cầm kiếm. lỗi vẫn là nội dung."
    assert storage.read_extra_json("glossary_curator_audit")[0]["operations"][0]["reason"] == "Sửa phiên âm"


def test_rename_note_and_keep_pending(tmp_path):
    storage = setup_storage(tmp_path)
    storage.upsert_glossary_entry("李四x", "Lý Sai", "ghi chú sai")
    storage.write_extra_json("glossary_pending", [{"source": "王五", "target": "Vương Ngũ", "existing_target": "", "note": "Chú thích", "chapter_index": 0}])
    batch = rows(storage) + [{"source": "王五", "target": "Vương Ngũ", "note": "Chú thích"}]
    result = curator.apply_operations(storage, batch, [
        {"op": "update", "original_source": "李四x", "source": "李四", "target": "Lý Tứ", "note": "", "reason": "Bỏ Latin"},
        {"op": "keep", "original_source": "王五", "reason": "Đúng"},
    ])
    assert not result["held"]
    assert "李四x" not in storage.read_glossary_file("names.txt")
    assert ("李四", "Lý Tứ", "") in storage.read_glossary_entries("names.txt")
    assert storage.read_extra_json("glossary_pending") == []
    assert ("王五", "Vương Ngũ", "Chú thích") in storage.read_glossary_entries("names.txt")


def test_guard_outside_batch_duplicate_hallucination_and_stale(tmp_path):
    storage = setup_storage(tmp_path)
    batch = rows(storage)
    storage.upsert_glossary_entry("张三", "Trương Tam", "Chú thích độc giả")
    result = curator.apply_operations(storage, batch, [
        {"op": "delete", "original_source": "不存在", "reason": "x"},
        {"op": "delete", "original_source": "张三", "reason": "stale"},
        {"op": "create", "original_source": "长生剑法", "source": "天道", "target": "Thiên Đạo"},
        {"op": "update", "original_source": "长生剑法", "source": "长生剑法", "target": "剑法"},
    ])
    assert len(result["held"]) == 4
    assert result["operations"] == []


def test_propagation_failure_rolls_back_entire_batch(tmp_path, monkeypatch):
    storage = setup_storage(tmp_path)
    chapter = Chapter(index=1, url="http://x/1")
    storage.save_manifest(Manifest(slug="t", chapters=[chapter]))
    storage.write_translated(chapter, "Trương Sai đi chợ.")
    propagate = storage.apply_replacements
    def fail(*args, **kwargs):
        propagate(*args, **kwargs)
        raise RuntimeError("disk failure")
    monkeypatch.setattr(storage, "apply_replacements", fail)
    with pytest.raises(RuntimeError, match="disk failure"):
        curator.apply_operations(storage, rows(storage), [{"op": "update", "original_source": "张三", "source": "张三", "target": "Trương Tam"}])
    assert storage.read_glossary_file("names.txt")["张三"] == "Trương Sai"
    assert storage.read_extra_json("glossary_curator_audit") is None
    assert storage.read_translated(chapter) == "Trương Sai đi chợ."


def test_batches_refresh_reference_and_skip_invalid_json(tmp_path, monkeypatch):
    storage = setup_storage(tmp_path)
    storage.write_glossary_entries("names.txt", [
        ("张三", "Trương Sai", ""),
        ("张三丰", "Trương Tam Phong", ""),
        ("rác", "lỗi", ""),
    ])
    monkeypatch.setattr(curator, "BATCH_SIZE", 1)
    prompts = []
    def chat(cfg, prompt):
        prompts.append(prompt)
        if len(prompts) == 1:
            return json.dumps([{"op": "update", "original_source": "张三", "source": "张三", "target": "Trương Tam"}])
        return "truncated JSON ["
    monkeypatch.setattr(curator.openai_client, "run_chat", chat)
    result = curator.curate(storage, OpenAIConfig())
    assert result["failed_batches"] == 2
    reference = json.loads(prompts[1].split("\nREFERENCE:\n")[1])
    assert reference == [{"source": "张三", "target": "Trương Tam", "note": ""}]
    assert json.loads(prompts[2].split("\nREFERENCE:\n")[1]) == []
    assert all(curator.token_upper_bound(p) < curator.CONTEXT_TOKENS - curator.OUTPUT_RESERVE for p in prompts)
    assert "rác" in storage.read_glossary_file("names.txt")


@pytest.mark.parametrize("selected_only", [False, True])
def test_budget_bounds_reference_and_rejects_oversized_entry(selected_only):
    batch = [{"source": "张三", "target": "Trương Tam", "note": ""}]
    related = [{"source": f"张三{i}", "target": f"Trương Tam {i}", "note": ""} for i in range(20)]
    reference = batch + [
        {"source": "李四", "target": "Lý Tứ", "note": ""},
        {"source": "张三丰", "target": "Trương Tam Phong", "note": "x" * 20_000},
    ] + [related[0]] * 10 + related
    prompt = curator.build_prompt(batch, reference, {}, "", selected_only=selected_only)
    raw_reference = prompt.split("\nREFERENCE:\n")[1]
    assert json.loads(raw_reference) == related[:5]
    assert len(raw_reference) <= curator.REFERENCE_MAX_CHARS
    assert curator.token_upper_bound(prompt) <= curator.CONTEXT_TOKENS - curator.OUTPUT_RESERVE
    # Even a small number of unusually long reference notes must stay bounded.
    large_reference = [{**row, "note": "x" * 900} for row in related]
    raw_reference = curator.build_prompt(batch, large_reference, {}, "").split("\nREFERENCE:\n")[1]
    assert len(json.loads(raw_reference)) == 2
    assert len(raw_reference) <= curator.REFERENCE_MAX_CHARS
    batch[0]["note"] = "中" * 200_000
    with pytest.raises(ValueError, match="200k"):
        curator.build_prompt(batch, [], {}, "")


def test_ambiguous_old_target_is_held(tmp_path):
    storage = setup_storage(tmp_path)
    storage.upsert_glossary_entry("李四", "Trương Sai")
    result = curator.apply_operations(storage, rows(storage), [{"op": "update", "original_source": "张三", "source": "张三", "target": "Trương Tam"}])
    assert len(result["held"]) == 1
    assert storage.read_glossary_file("names.txt")["张三"] == "Trương Sai"


@pytest.mark.parametrize("batch_size", [1, 50])
@pytest.mark.parametrize("legacy_location", ["glossary", "pending"])
def test_vietnamese_keys_do_not_block_chinese_corrections(tmp_path, monkeypatch, batch_size, legacy_location):
    storage = Storage(tmp_path, "t")
    storage.write_glossary_entries("names.txt", [
        ("厉猎月", "Lệ Liệp Nguyệt", ""),
        ("素真天", "Tố Chân Thiên", ""),
        ("张硕", "Trương Sơ", ""),
    ])
    pending = [
        {"source": "厉猎月", "target": "Lệ Liệp Yuyet", "existing_target": "Lệ Liệp Nguyệt", "note": ""},
        {"source": "素真天", "target": "素真天", "existing_target": "Tố Chân Thiên", "note": ""},
    ]
    # Legacy queue rows accidentally put Vietnamese in the Chinese key column.
    legacy = [
        {"source": "Lịch Liệp Nguyệt", "target": "Lịch Liệp Nguyệt", "existing_target": "Lệ Liệp Nguyệt", "note": ""},
        {"source": "Lệ Liệp Nguyệt", "target": "厉猎月", "existing_target": "Lệ Liệp Nguyệt", "note": ""},
        {"source": "Tố Chân Thiên", "target": "素真天", "existing_target": "Tố Chân Thiên", "note": ""},
    ]
    if legacy_location == "pending":
        pending += legacy
    else:
        for row in legacy:
            storage.upsert_glossary_entry(row["source"], row["existing_target"], "Ghi chú cũ")
    storage.write_extra_json("glossary_pending", pending)
    before_legacy = [row for row in storage.read_glossary_entries_merged() if row[0] in {r["source"] for r in legacy}]
    chapter = Chapter(index=1, url="http://x/1")
    storage.save_manifest(Manifest(slug="t", chapters=[chapter]))
    storage.write_translated(chapter, "Lệ Liệp Nguyệt, Lệ Liệp Yuyet, 素真天, Tố Chân Thiên, Trương Sơ.")
    targets = {"厉猎月": "Lịch Liệp Nguyệt", "素真天": "Tố Chân Thiên", "张硕": "Trương Thạc"}
    sent = []

    def chat(cfg, prompt):
        batch = json.loads(prompt.split("\nBATCH:\n")[1].split("\nREFERENCE:\n")[0])
        sent.extend(row["source"] for row in batch)
        return json.dumps([
            {"op": "update", "original_source": row["source"], "source": row["source"], "target": targets[row["source"]]}
            for row in batch
        ])

    monkeypatch.setattr(curator.openai_client, "run_chat", chat)
    result = curator.curate(storage, OpenAIConfig(), sources=list(targets), batch_size=batch_size)
    assert sent == list(targets)
    assert len(result["operations"]) == 3
    assert result["held"] == []
    assert result["failed_batches"] == 0
    assert all(storage.read_glossary_file("names.txt")[source] == target for source, target in targets.items())
    assert all(row in storage.read_glossary_entries_merged() for row in before_legacy)
    assert storage.read_extra_json("glossary_pending") == (
        [{**row, "chapter_index": 0} for row in legacy] if legacy_location == "pending" else []
    )
    assert storage.read_translated(chapter) == "Lịch Liệp Nguyệt, Lịch Liệp Nguyệt, Tố Chân Thiên, Tố Chân Thiên, Trương Thạc."
    assert {tuple(pair) for audit in storage.read_extra_json("glossary_curator_audit") for pair in audit["replacement_pairs"]} == {
        ("Lệ Liệp Nguyệt", "Lịch Liệp Nguyệt"), ("Lệ Liệp Yuyet", "Lịch Liệp Nguyệt"),
        ("素真天", "Tố Chân Thiên"), ("Trương Sơ", "Trương Thạc"),
    }


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("broken_key", ["Lý Tứ", "Lý Tứ四"])
def test_repaired_vietnamese_key_still_requires_propagation_consensus(tmp_path, reverse, broken_key):
    storage = Storage(tmp_path, "t")
    storage.write_glossary_entries("names.txt", [("张三", "Tên chung", ""), (broken_key, "Tên chung", "")])
    before = rows(storage)
    chapter = Chapter(index=1, url="http://x/1")
    storage.save_manifest(Manifest(slug="t", chapters=[chapter]))
    storage.write_translated(chapter, "Tên chung đi chợ.")
    operations = [
        {"op": "update", "original_source": "张三", "source": "张三", "target": "Trương Tam"},
        {"op": "update", "original_source": broken_key, "source": "李四", "target": "Lý Tứ"},
    ]
    if reverse:
        operations.reverse()
    with pytest.raises(ValueError, match="chưa đồng thuận"):
        curator.apply_operations(storage, before, operations, selected_only=True)
    assert rows(storage) == before
    assert storage.read_translated(chapter) == "Tên chung đi chợ."
    assert storage.read_extra_json("glossary_curator_audit") is None


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("pending_keep", [False, True])
def test_shared_old_translation_with_batch_consensus_is_safe(tmp_path, reverse, pending_keep):
    storage = Storage(tmp_path, "t")
    storage.write_glossary_entries("names.txt", [
        ("传奇", "Truyền Kì", "ghi chú cũ"), ("传奇级", "Truyền Kì", ""),
    ])
    chapter = Chapter(index=1, url="http://x/1")
    storage.save_manifest(Manifest(slug="t", chapters=[chapter]))
    storage.write_translated(chapter, "Truyền Kì gặp Truyền Kì.")
    if pending_keep:
        storage.write_extra_json("glossary_pending", [
            {"source": source, "target": "Truyền Kỳ", "note": note,
             "existing_target": "Truyền Kì"}
            for source, _target, note in storage.read_glossary_entries_merged()
        ])
        batch = storage.read_extra_json("glossary_pending")
        operations = [{"op": "keep", "original_source": row["source"]} for row in batch]
    else:
        batch = rows(storage)
        operations = [{"op": "update", "original_source": row["source"],
                       "source": row["source"], "target": "Truyền Kỳ"} for row in batch]
    if reverse:
        operations.reverse()
    result = curator.apply_operations(storage, batch, operations, selected_only=True)
    assert result["held"] == []
    assert len(result["operations"]) == 2
    assert storage.read_translated(chapter) == "Truyền Kỳ gặp Truyền Kỳ."
    assert storage.read_glossary_file("names.txt") == {"传奇": "Truyền Kỳ", "传奇级": "Truyền Kỳ"}
    assert storage.read_extra_json("glossary_pending") == []
    assert storage.read_extra_json("glossary_curator_audit")[0]["replacement_pairs"] == [
        ["Truyền Kì", "Truyền Kỳ"],
    ]


def test_keep_shared_translation_without_changes_needs_no_propagation(tmp_path):
    storage = Storage(tmp_path, "t")
    storage.write_glossary_entries("names.txt", [("传奇", "Truyền Kỳ", ""), ("传奇级", "Truyền Kỳ", "")])
    batch = rows(storage)
    result = curator.apply_operations(storage, batch, [
        {"op": "keep", "original_source": row["source"]} for row in batch
    ], selected_only=True)
    assert not result["held"]
    assert storage.read_extra_json("glossary_curator_audit")[0]["replacement_pairs"] == []


@pytest.mark.parametrize("batch_size", [1, 2, 50])
@pytest.mark.parametrize("select_aliases", [False, True])
def test_curate_reviews_shared_aliases_before_propagating(tmp_path, monkeypatch, batch_size, select_aliases):
    storage = Storage(tmp_path, "t")
    originals = [
        ("猎魔人", "Thợ Săn Ma Quỷ", ""),
        ("巨龟岩台号", "Cự Quy Nham Đài", ""),
        ("猎 魔 人", "Thợ Săn Ma Quỷ", "Ghi chú cũ"),
        ("巨 龟 岩 台 号", "Cự Quy Nham Đài", ""),
        ("巨龟岩台", "Cự Quy Nham Đài", ""),
        ("Cự Quy Nham Đài号", "Cự Quy Nham Đài", ""),
    ]
    storage.write_glossary_entries("names.txt", originals)
    storage.write_extra_json("glossary_pending", [
        {"source": "猎魔人", "target": "Thợ Săn Ma", "existing_target": "Thợ Săn Ma Quỷ", "note": ""},
        {"source": "巨龟岩台号", "target": "Tàu Cự Quy Nhan Đài", "existing_target": "Cự Quy Nham Đài", "note": ""},
    ])
    chapter = Chapter(index=1, url="http://x/1")
    storage.save_manifest(Manifest(slug="t", chapters=[chapter]))
    storage.write_translated(chapter, "Thợ Săn Ma Quỷ trên Cự Quy Nham Đài.")
    sources = [source for source, _target, _note in originals[:5 if select_aliases else 2]]
    seen = []

    def chat(cfg, prompt):
        assert not storage.conn.in_transaction
        batch = json.loads(prompt.split("\nBATCH:\n")[1].split("\nREFERENCE:\n")[0])
        assert len(batch) <= batch_size
        seen.extend(row["source"] for row in batch)
        if "SHARED TRANSLATION REVIEW:" in prompt:
            guidance = json.loads(prompt.split("PROPOSED REPLACEMENTS:\n")[1].split("\nBATCH:\n")[0])
            assert {row["source"] for row in guidance} == {row["source"] for row in batch}
            assert "not established facts" in prompt
        return json.dumps([
            {"op": "update", "original_source": row["source"], "source": row["source"],
             "target": "Thợ Săn Ma" if "猎" in row["source"] else "Tàu Cự Quy Nhan Đài"}
            for row in batch
        ])

    monkeypatch.setattr(curator.openai_client, "run_chat", chat)
    result = curator.curate(storage, OpenAIConfig(), sources=sources, batch_size=batch_size)
    assert len(seen) == len(set(seen)) == 5
    assert "Cự Quy Nham Đài号" not in seen
    assert result["requested"] == len(sources)
    assert set(result["related_sources"]) == set(seen) - set(sources)
    assert result["held"] == []
    assert storage.read_extra_json("glossary_pending") == []
    assert storage.read_translated(chapter) == "Thợ Săn Ma trên Tàu Cự Quy Nhan Đài."
    assert ("猎 魔 人", "Thợ Săn Ma", "Ghi chú cũ") in storage.read_glossary_entries_merged()
    assert originals[-1] in storage.read_glossary_entries_merged()
    glossary = storage.read_glossary_file("names.txt")
    assert all(glossary[key] == ("Thợ Săn Ma" if "猎" in key else "Tàu Cự Quy Nhan Đài") for key in seen)
    audits = storage.read_extra_json("glossary_curator_audit")
    assert {row["source"] for audit in audits for row in audit["before"]} == set(seen)


@pytest.mark.parametrize("limit", ["batch", "timeout", "context"])
def test_related_review_follows_transitive_pending_owners_atomically(tmp_path, monkeypatch, limit):
    storage = Storage(tmp_path, "t")
    # 李四 bridges two old targets, so 王五 only becomes necessary after its review.
    storage.write_glossary_entries("names.txt", [
        ("张三", "Tên A", ""), ("李四", "Tên A", "n" * 2000),
        ("赵六", "Tên A", "n" * 2000), ("王五", "Tên B", ""),
    ])
    pending = [
        {"source": "张三", "target": "Tên mới", "existing_target": "Tên A", "note": ""},
        {"source": "李四", "target": "Tên B", "existing_target": "Tên A", "note": "n" * 2000},
    ]
    storage.write_extra_json("glossary_pending", pending)
    before = rows(storage)
    seen, sizes = [], []
    if limit == "context":
        # Để đủ một alias có note dài, nhưng buộc tách khi có hai alias;
        # tính phần dữ liệu riêng để không phụ thuộc độ dài/ngôn ngữ prompt.
        base_size = curator.token_upper_bound(curator.build_prompt([], [], {}, "", selected_only=True))
        monkeypatch.setattr(curator, "CONTEXT_TOKENS", base_size + 4500)
        monkeypatch.setattr(curator, "OUTPUT_RESERVE", 500)
    monkeypatch.setattr(curator, "AI_RETRY_DELAY_SECONDS", 0)

    def chat(cfg, prompt):
        assert rows(storage) == before
        assert storage.read_extra_json("glossary_curator_audit") is None
        assert not storage.conn.in_transaction
        assert curator.token_upper_bound(prompt) <= curator.CONTEXT_TOKENS - curator.OUTPUT_RESERVE
        batch = json.loads(prompt.split("\nBATCH:\n")[1].split("\nREFERENCE:\n")[0])
        sizes.append(len(batch))
        if limit == "timeout" and len(batch) == 2:
            raise openai_client.RetryableAIError("timeout")
        seen.extend(row["source"] for row in batch)
        return json.dumps([
            {"op": "update", "original_source": row["source"], "source": row["source"], "target": "Tên mới"}
            for row in batch
        ])

    monkeypatch.setattr(curator.openai_client, "run_chat", chat)
    result = curator.curate(storage, OpenAIConfig(), sources=["张三"], batch_size=1 if limit == "batch" else 50)
    assert len(seen) == len(set(seen)) == 4
    assert set(result["related_sources"]) == {"李四", "赵六", "王五"}
    assert all(target == "Tên mới" for _source, target, _note in storage.read_glossary_entries_merged())
    assert storage.read_extra_json("glossary_pending") == []
    audits = storage.read_extra_json("glossary_curator_audit")
    assert len(audits) == 1
    assert {tuple(pair) for pair in audits[0]["replacement_pairs"]} == {("Tên A", "Tên mới"), ("Tên B", "Tên mới")}
    if limit == "timeout":
        assert sizes[:4] == [1, 2, 2, 1]
    elif limit == "context":
        assert sizes[:2] == [1, 1]
    else:
        assert set(sizes) == {1}


@pytest.mark.parametrize("batch_size", [1, 10, 100])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("select_aliases", [False, True])
def test_reported_ship_alias_conflict_keeps_group_and_finishes_other_entries(tmp_path, monkeypatch, batch_size, reverse, select_aliases):
    storage = Storage(tmp_path, "t")
    originals = [
        ("尤恩·艾本", "Ewen Eben", ""),
        ("柯依伯站", "trạm Kuiper", ""),
        ("莫萨-莫比可", "Mạc Tát-Mạc Bỉ Khả", ""),
        ("巨龟岩台号", "Cự Quy Nham Đài", "ghi chú tàu"),
        ("丹莫斯", "Đan Mạc Tư", ""),
        ("泛银河文明共同体", "Phán Ngân Hà Văn Minh Cộng Đồng Thể", ""),
        ("人鱼", "Nhân Ngư", ""),
        ("小人鱼", "Tiểu nhân ngư", ""),
        ("布鲁谢特", "Blushet", ""),
        ("尤恩", "Ewen", ""),
        ("张三", "Trương Sai", "lô sau"),
        ("巨 龟 岩 台 号", "Cự Quy Nham Đài", "ghi chú alias"),
        ("巨龟岩台", "Cự Quy Nham Đài", "ghi chú địa danh"),
    ]
    storage.write_glossary_entries("names.txt", originals)
    pending = [{"source": key, "target": target, "existing_target": target, "note": note, "chapter_index": 0}
               for key, target, note in originals if key in {"巨龟岩台号", "张三"}]
    storage.write_extra_json("glossary_pending", pending)
    chapter = Chapter(index=1, url="http://x/1")
    storage.save_manifest(Manifest(slug="t", chapters=[chapter]))
    storage.write_translated(chapter, "Cự Quy Nham Đài gặp Trương Sai.")
    changes = {"巨龟岩台号": "Tàu Cự Quy Nham Đài", "巨 龟 岩 台 号": "Tàu Cự Quy Nham Đài",
               "泛银河文明共同体": "Cộng đồng Văn minh Ngân Hà", "张三": "Trương Tam"}
    seen, logs = [], []

    def chat(cfg, prompt):
        batch = json.loads(prompt.split("\nBATCH:\n")[1].split("\nREFERENCE:\n")[0])
        assert len(batch) <= batch_size
        seen.extend(row["source"] for row in batch)
        decisions = [{"op": "update", "original_source": row["source"],
                      "source": "巨龟岩台号" if row["source"] == "巨 龟 岩 台 号" else row["source"],
                      "target": changes.get(row["source"], row["target"]), "reason": "Rà soát"}
                     for row in batch]
        return json.dumps(decisions[::-1] if reverse else decisions)

    monkeypatch.setattr(curator.openai_client, "run_chat", chat)
    selected = originals if select_aliases else originals[:11]
    result = curator.curate(storage, OpenAIConfig(), sources=[s for s, _t, _n in selected],
                            batch_size=batch_size, log=logs.append)
    blocked = {"巨龟岩台号", "巨 龟 岩 台 号", "巨龟岩台"}
    assert set(seen) == {s for s, _t, _n in originals}
    assert len(seen) == len(set(seen))
    assert {r["source"] for r in result["held"]} == blocked
    assert result["failed_batches"] == 0
    assert len(result["operations"]) == 10
    assert storage.read_translated(chapter) == "Cự Quy Nham Đài gặp Trương Tam."
    assert all(row in storage.read_glossary_entries_merged() for row in originals if row[0] in blocked)
    assert storage.read_glossary_file("names.txt")["泛银河文明共同体"] == changes["泛银河文明共同体"]
    assert storage.read_extra_json("glossary_pending") == [pending[0]]
    audits = storage.read_extra_json("glossary_curator_audit")
    assert {r["source"] for audit in audits for r in audit["held"]} == blocked
    assert all(old != "Cự Quy Nham Đài" for audit in audits for old, _new in audit["replacement_pairs"])
    assert any("Giữ 巨龟岩台号" in line for line in logs)


@pytest.mark.parametrize("reverse", [False, True])
def test_whitespace_key_collision_preserves_alias_notes_and_propagates_consensus(tmp_path, reverse):
    storage = Storage(tmp_path, "t")
    storage.write_glossary_entries("names.txt", [
        ("巨龟岩台号", "Cự Quy Nham Đài", "chính"),
        ("巨 龟 岩 台 号", "Cự Quy Nham Đài", "alias"),
    ])
    chapter = Chapter(index=1, url="http://x/1")
    storage.save_manifest(Manifest(slug="t", chapters=[chapter]))
    storage.write_translated(chapter, "Cự Quy Nham Đài khởi hành.")
    operations = [{"op": "update", "original_source": row["source"],
                   "source": "巨龟岩台号", "target": "Tàu Cự Quy Nham Đài"} for row in rows(storage)]
    result = curator.apply_operations(storage, rows(storage), operations[::-1] if reverse else operations,
                                      selected_only=True)
    assert result["held"] == []
    assert set(storage.read_glossary_entries_merged()) == {
        ("巨龟岩台号", "Tàu Cự Quy Nham Đài", "chính"),
        ("巨 龟 岩 台 号", "Tàu Cự Quy Nham Đài", "alias"),
    }
    assert storage.read_translated(chapter) == "Tàu Cự Quy Nham Đài khởi hành."


def test_real_key_collision_defers_destination_but_not_independent_changes(tmp_path):
    storage = Storage(tmp_path, "t")
    storage.write_glossary_entries("names.txt", [
        ("张三", "Trương Tam", "chính"), ("李四", "Lý Tứ", "khác"), ("王五", "Vương Sai", ""),
    ])
    result = curator.apply_operations(storage, rows(storage), [
        {"op": "update", "original_source": "李四", "source": " 张三 ", "target": "Tên khác"},
        {"op": "update", "original_source": "张三", "source": "张三", "target": "Tên mới"},
        {"op": "update", "original_source": "王五", "source": "王五", "target": "Vương Ngũ"},
    ], selected_only=True, defer_conflicts=True)
    assert {r["source"] for r in result["held"]} == {"张三", "李四"}
    assert storage.read_glossary_entries_merged() == [
        ("张三", "Trương Tam", "chính"), ("李四", "Lý Tứ", "khác"), ("王五", "Vương Ngũ", ""),
    ]
    assert storage.read_extra_json("glossary_curator_audit")[0]["replacement_pairs"] == [["Vương Sai", "Vương Ngũ"]]


def test_deferred_conflict_preserves_transitive_pending_owners(tmp_path, monkeypatch):
    storage = Storage(tmp_path, "t")
    originals = [("张三", "Tên A", ""), ("李四", "Tên A", ""), ("王五", "Tên B", "")]
    storage.write_glossary_entries("names.txt", originals + [("赵六", "Triệu Sai", "")])
    pending = [{"source": "李四", "target": "Tên B", "existing_target": "Tên A", "note": "", "chapter_index": 0}]
    storage.write_extra_json("glossary_pending", pending)
    chapter = Chapter(index=1, url="http://x/1")
    storage.save_manifest(Manifest(slug="t", chapters=[chapter]))
    storage.write_translated(chapter, "Tên A gặp Tên B và Triệu Sai.")
    seen = []

    def chat(cfg, prompt):
        batch = json.loads(prompt.split("\nBATCH:\n")[1].split("\nREFERENCE:\n")[0])
        seen.extend(r["source"] for r in batch)
        return json.dumps([
            {"op": "update", "original_source": r["source"], "source": r["source"],
             "target": "Triệu Lục" if r["source"] == "赵六" else "Tên mới"}
            if r["source"] != "王五" else {"op": "keep", "original_source": "王五"}
            for r in batch
        ])

    monkeypatch.setattr(curator.openai_client, "run_chat", chat)
    result = curator.curate(storage, OpenAIConfig(), sources=["张三", "赵六"], batch_size=1)
    assert seen == ["张三", "李四", "王五", "赵六"]
    assert {r["source"] for r in result["held"]} == {"张三", "李四", "王五"}
    assert storage.read_glossary_entries_merged() == originals + [("赵六", "Triệu Lục", "")]
    assert storage.read_extra_json("glossary_pending") == pending
    assert storage.read_translated(chapter) == "Tên A gặp Tên B và Triệu Lục."


@pytest.mark.parametrize("failure", ["keep", "delete", "disagree", "missing", "outside", "timeout", "stale", "write"])
def test_failed_alias_review_preserves_entire_group(tmp_path, monkeypatch, failure):
    storage = Storage(tmp_path, "t")
    storage.write_glossary_entries("names.txt", [("猎魔人", "Tên cũ", ""), ("猎 魔 人", "Tên cũ", "")])
    pending = [{"source": "猎魔人", "target": "Tên mới", "existing_target": "Tên cũ", "note": "", "chapter_index": 0}]
    storage.write_extra_json("glossary_pending", pending)
    chapter = Chapter(index=1, url="http://x/1")
    storage.save_manifest(Manifest(slug="t", chapters=[chapter]))
    storage.write_translated(chapter, "Tên cũ đi chợ.")
    monkeypatch.setattr(curator, "AI_RETRY_DELAY_SECONDS", 0)
    if failure == "write":
        propagate = storage.apply_replacements

        def fail_write(*args, **kwargs):
            propagate(*args, **kwargs)
            raise RuntimeError("disk failure")

        monkeypatch.setattr(storage, "apply_replacements", fail_write)

    def chat(cfg, prompt):
        batch = json.loads(prompt.split("\nBATCH:\n")[1].split("\nREFERENCE:\n")[0])
        key = batch[0]["source"]
        if key == "猎魔人":
            return json.dumps([{"op": "keep", "original_source": key, "reason": "ORIGINAL_RESPONSE"}])
        assert key == "猎 魔 人"
        if failure == "timeout":
            raise openai_client.RetryableAIError("alias timeout")
        if failure == "stale":
            storage.upsert_glossary_entry(key, "Sửa bên ngoài")
        if failure == "missing":
            return "[]"
        return json.dumps([{
            "op": failure if failure in {"keep", "delete"} else "update",
            "original_source": "猎魔人" if failure == "outside" else key,
            "source": key, "target": "Khác" if failure == "disagree" else "Tên mới", "reason": "ALIAS_RESPONSE",
        }])

    monkeypatch.setattr(curator.openai_client, "run_chat", chat)
    logs = []
    deferred = failure in {"keep", "delete", "disagree"}
    if deferred:
        result = curator.curate(storage, OpenAIConfig(), sources=["猎魔人"], log=logs.append)
        assert result["operations"] == []
        assert {r["source"] for r in result["held"]} == {"猎魔人", "猎 魔 人"}
    else:
        with pytest.raises(RuntimeError if failure == "write" else ValueError):
            curator.curate(storage, OpenAIConfig(), sources=["猎魔人"], log=logs.append)
    assert storage.read_glossary_file("names.txt") == {
        "猎魔人": "Tên cũ", "猎 魔 人": "Sửa bên ngoài" if failure == "stale" else "Tên cũ",
    }
    assert storage.read_extra_json("glossary_pending") == pending
    assert storage.read_translated(chapter) == "Tên cũ đi chợ."
    if deferred:
        assert storage.read_extra_json("glossary_curator_audit")[0]["operations"] == []
    else:
        assert storage.read_extra_json("glossary_curator_audit") is None
    if failure in {"outside", "stale"}:
        assert "ORIGINAL_RESPONSE" in logs[-1] and "ALIAS_RESPONSE" in logs[-1]


@pytest.mark.parametrize("other_op", ["keep", "update", "delete", "unselected"])
def test_shared_translation_without_consensus_still_blocks_atomically(tmp_path, other_op):
    storage = Storage(tmp_path, "t")
    storage.write_glossary_entries("names.txt", [("传奇", "Truyền Kì", ""), ("传奇级", "Truyền Kì", "")])
    before = rows(storage)
    operations = [{"op": "update", "original_source": "传奇", "source": "传奇", "target": "Truyền Kỳ"}]
    batch = before
    if other_op == "unselected":
        batch = before[:1]
    else:
        operations.append({"op": other_op, "original_source": "传奇级", "source": "传奇级",
                           "target": "Cấp Truyền Kỳ", "reason": "Rà soát"})
    with pytest.raises(ValueError, match="传奇.*Truyền Kì.*传奇级"):
        curator.apply_operations(storage, batch, operations, selected_only=True)
    assert rows(storage) == before
    assert storage.read_extra_json("glossary_curator_audit") is None


def test_legacy_rejected_owner_invalidates_dependent_propagation(tmp_path):
    storage = Storage(tmp_path, "t")
    storage.write_glossary_entries("names.txt", [("张三", "Tên A", ""), ("李四", "Tên B", ""), ("王五", "Tên B", "")])
    storage.write_extra_json("glossary_pending", [
        {"source": "张三", "target": "Tên chung", "existing_target": "Tên A", "note": ""},
        {"source": "李四", "target": "Tên chung", "existing_target": "Tên B", "note": ""},
    ])
    result = curator.apply_operations(storage, storage.read_extra_json("glossary_pending"), [
        {"op": "update", "original_source": source, "source": source, "target": "Tên mới"}
        for source in ("张三", "李四")
    ])
    assert result["operations"] == []
    assert {r["source"] for r in result["held"]} == {"张三", "李四"}
    assert len(storage.read_extra_json("glossary_pending")) == 2
    assert storage.read_glossary_file("names.txt")["张三"] == "Tên A"


def test_oversized_batches_split_without_losing_rows(tmp_path, monkeypatch):
    storage = setup_storage(tmp_path)
    storage.write_glossary_entries("names.txt", [(f"张{i}", f"Trương {i}", "n" * 800) for i in range(4)])
    base_size = curator.token_upper_bound(curator.build_prompt([], [], {}, ""))
    monkeypatch.setattr(curator, "CONTEXT_TOKENS", base_size + 1800)
    monkeypatch.setattr(curator, "OUTPUT_RESERVE", 500)
    sent = []
    def chat(cfg, prompt):
        batch = json.loads(prompt.split("\nBATCH:\n")[1].split("\nREFERENCE:\n")[0])
        sent.extend(r["source"] for r in batch)
        assert len(batch) == 1
        return json.dumps([{"op": "keep", "original_source": r["source"]} for r in batch])
    monkeypatch.setattr(curator.openai_client, "run_chat", chat)
    result = curator.curate(storage, OpenAIConfig())
    assert len(sent) == 4
    assert len(set(sent)) == 4
    assert result["failed_batches"] == 0


def test_rejects_malformed_field_types_and_preserves_position(tmp_path):
    storage = setup_storage(tmp_path)
    before = storage.read_glossary_entries("names.txt")
    result = curator.apply_operations(storage, rows(storage), [
        {"op": [], "original_source": "张三"},
        {"op": "update", "original_source": "张三", "source": "张三", "target": None},
        {"op": "keep", "original_source": "长生剑法"},
    ])
    assert len(result["held"]) == 2
    assert storage.read_glossary_entries("names.txt") == before


def test_selected_cleanup_propagates_corrections_but_not_deletions(tmp_path, monkeypatch):
    storage = setup_storage(tmp_path)
    storage.upsert_glossary_entry("王五", "Vương 五")
    pending = [
        {"source": "张三", "target": "Trương 三", "note": "", "existing_target": "Trương Sai"},
        {"source": "王五", "target": "Vương 五", "note": "", "existing_target": "Vương 五"},
        {"source": "李四", "target": "Lý Tứ", "note": "", "existing_target": ""},
    ]
    storage.write_extra_json("glossary_pending", pending)
    chapter = Chapter(index=1, url="http://x/1")
    storage.save_manifest(Manifest(slug="t", chapters=[chapter]))
    text = "Trương Sai gặp Trương 三, Vương 五. lỗi vẫn là nội dung."
    storage.write_translated(chapter, text)
    def forbidden(*args, **kwargs):
        pytest.fail("Selected cleanup must not migrate unrelated entries")
    monkeypatch.setattr(storage, "migrate_glossary_queue", forbidden)
    batches = []
    def chat(cfg, prompt):
        batch = json.loads(prompt.split("\nBATCH:\n")[1].split("\nREFERENCE:\n")[0])
        batches.append([r["source"] for r in batch])
        return json.dumps([
            {"op": "update", "original_source": r["source"], "source": r["source"], "target": "Trương Tam"}
            if r["source"] == "张三" else
            {"op": "delete", "original_source": r["source"], "reason": "Mục lỗi"}
            for r in batch
        ])
    monkeypatch.setattr(curator.openai_client, "run_chat", chat)
    result = curator.curate(storage, OpenAIConfig(), sources=["张三", "王五", "rác", "张三"], batch_size=2)
    assert result["requested"] == 3
    assert batches == [["张三", "王五"], ["rác"]]
    assert storage.read_glossary_file("names.txt") == {"张三": "Trương Tam", "长生剑法": "Trường Sinh Kiếm Pháp"}
    assert [p["source"] for p in storage.read_extra_json("glossary_pending")] == ["李四"]
    assert storage.read_translated(chapter) == "Trương Tam gặp Trương Tam, Vương 五. lỗi vẫn là nội dung."
    audits = storage.read_extra_json("glossary_curator_audit")
    assert {tuple(pair) for audit in audits for pair in audit["replacement_pairs"]} == {
        ("Trương Sai", "Trương Tam"), ("Trương 三", "Trương Tam"),
    }


def test_selected_keep_approves_and_propagates_pending_target(tmp_path):
    storage = setup_storage(tmp_path)
    chapter = Chapter(index=1, url="http://x/1")
    storage.save_manifest(Manifest(slug="t", chapters=[chapter]))
    storage.write_translated(chapter, "Trương Sai đi chợ.")
    pending = {"source": "张三", "target": "Trương Tam", "note": "", "existing_target": "Trương Sai"}
    storage.write_extra_json("glossary_pending", [pending])
    curator.apply_operations(storage, [pending], [{"op": "keep", "original_source": "张三"}], selected_only=True)
    assert storage.read_extra_json("glossary_pending") == []
    assert storage.read_translated(chapter) == "Trương Tam đi chợ."


@pytest.mark.parametrize("batch_size", [1, 10])
def test_pending_keep_case_only_shared_targets_complete_across_batches(tmp_path, monkeypatch, batch_size):
    storage = Storage(tmp_path, "t")
    # The failing 10-entry batch: eight casing changes, including a Chinese
    # alias and legacy Vietnamese keys outside the selection.
    changes = [
        ("军团", "Quân Đoàn", "Quân đoàn", "Quân Đoàn"),
        ("传奇", "Truyền Kỳ", "Truyền kỳ", "Truyền Kỳ"),
        ("鲜血统领", "Thống Lĩnh Huyết Sắc", "Thống lĩnh Huyết Sắc", "血色统领"),
        ("系统", "Hệ thống", "Hệ Thống", "Hệ thống"),
        ("遗物", "Di vật", "Di Vật", "Di vật"),
        ("大师", "Đại Sư", "Đại sư", "Đại Sư"),
        ("极地人", "Cực Địa nhân", "Cực Địa Nhân", "Cực Địa nhân"),
        ("排行榜", "Bảng xếp hạng", "Bảng xếp hạng", None),
        ("领主", "Lãnh chúa", "Lãnh Chúa", "Lãnh chúa"),
        ("缝纫铺", "Tiệm may", "Tiệm may", None),
    ]
    original = [(source, old, "") for source, old, _new, _alias in changes]
    aliases = [(alias, old, "Ghi chú giữ nguyên") for _source, old, _new, alias in changes if alias]
    storage.write_glossary_entries("names.txt", original + aliases)
    pending = [
        {"source": source, "target": new, "existing_target": old, "note": "", "chapter_index": 1}
        for source, old, new, _alias in changes
    ]
    unrelated = {"source": "王五", "target": "Vương Ngũ", "existing_target": "", "note": "", "chapter_index": 1}
    storage.write_extra_json("glossary_pending", pending + [unrelated])
    chapter = Chapter(index=1, url="http://x/1")
    storage.save_manifest(Manifest(slug="t", chapters=[chapter]))
    text = ". ".join(old for _source, old, _new, _alias in changes)
    storage.write_translated(chapter, text)

    def chat(cfg, prompt):
        batch = json.loads(prompt.split("\nBATCH:\n")[1].split("\nREFERENCE:\n")[0])
        return json.dumps([{"op": "keep", "original_source": row["source"]} for row in batch])

    monkeypatch.setattr(curator.openai_client, "run_chat", chat)
    result = curator.curate(storage, OpenAIConfig(), sources=[p["source"] for p in pending], batch_size=batch_size)
    assert len(result["operations"]) == 10
    assert result["held"] == []
    assert result["failed_batches"] == 0
    glossary = storage.read_glossary_file("names.txt")
    assert all(glossary[source] == new for source, _old, new, _alias in changes)
    assert all(alias in storage.read_glossary_entries_merged() for alias in aliases)
    assert storage.read_extra_json("glossary_pending") == [unrelated]
    assert storage.read_translated(chapter) == text
    assert all(audit["replacement_pairs"] == [] for audit in storage.read_extra_json("glossary_curator_audit"))


@pytest.mark.parametrize("shared", [False, True])
def test_case_only_update_approves_without_rewriting_chapters(tmp_path, shared):
    storage = Storage(tmp_path, "t")
    storage.write_glossary_entries("names.txt", [("军团", "Quân Đoàn", "ghi chú")])
    if shared:
        storage.upsert_glossary_entry("兵团", "Quân Đoàn")
    chapter = Chapter(index=1, url="http://x/1")
    storage.save_manifest(Manifest(slug="t", chapters=[chapter]))
    text = "Quân Đoàn ở đây. quân đoàn ở đó."
    storage.write_translated(chapter, text)
    result = curator.apply_operations(storage, [rows(storage)[0]], [
        {"op": "update", "original_source": "军团", "source": "军团", "target": "Quân đoàn"},
    ], selected_only=True)
    assert result["held"] == []
    assert result["replacements"]["total"] == 0
    assert ("军团", "Quân đoàn", "ghi chú") in storage.read_glossary_entries_merged()
    assert storage.read_translated(chapter) == text


def test_pending_keep_propagates_word_changes_but_not_case_variants(tmp_path):
    storage = Storage(tmp_path, "t")
    storage.write_glossary_entries("names.txt", [("军团", "Lính", ""), ("兵团", "Quân Đoàn", "")])
    pending = {"source": "军团", "target": "Quân đoàn", "existing_target": "Quân Đoàn", "note": ""}
    storage.write_extra_json("glossary_pending", [pending])
    chapter = Chapter(index=1, url="http://x/1")
    storage.save_manifest(Manifest(slug="t", chapters=[chapter]))
    storage.write_translated(chapter, "Lính gặp Quân Đoàn.")
    result = curator.apply_operations(storage, [pending], [{"op": "keep", "original_source": "军团"}], selected_only=True)
    assert result["held"] == []
    assert storage.read_translated(chapter) == "Quân đoàn gặp Quân Đoàn."
    assert storage.read_extra_json("glossary_curator_audit")[0]["replacement_pairs"] == [["Lính", "Quân đoàn"]]
    assert storage.read_extra_json("glossary_pending") == []


def test_selected_propagation_failure_rolls_back_deletion_and_queue(tmp_path, monkeypatch):
    storage = setup_storage(tmp_path)
    chapter = Chapter(index=1, url="http://x/1")
    storage.save_manifest(Manifest(slug="t", chapters=[chapter]))
    storage.write_translated(chapter, "Trương Sai đi chợ.")
    pending = {"source": "张三", "target": "Trương Tam", "note": "", "existing_target": "Trương Sai"}
    storage.write_extra_json("glossary_pending", [pending])
    before_queue = storage.read_extra_json("glossary_pending")
    before_glossary = storage.read_glossary_entries_merged()
    propagate = storage.apply_replacements
    def fail(*args, **kwargs):
        propagate(*args, **kwargs)
        raise RuntimeError("disk failure")
    monkeypatch.setattr(storage, "apply_replacements", fail)
    with pytest.raises(RuntimeError, match="disk failure"):
        curator.apply_operations(storage, [pending, {"source": "rác", "target": "lỗi", "note": "log kỹ thuật"}], [
            {"op": "delete", "original_source": "rác", "reason": "Mục rác"},
            {"op": "keep", "original_source": "张三"},
        ], selected_only=True)
    assert storage.read_glossary_entries_merged() == before_glossary
    assert storage.read_extra_json("glossary_pending") == before_queue
    assert storage.read_translated(chapter) == "Trương Sai đi chợ."
    assert storage.read_extra_json("glossary_curator_audit") is None


@pytest.mark.parametrize("operations", [
    [],
    [{"op": "keep", "original_source": "长生剑法"}] * 2,
    [{"op": "delete", "original_source": "张三", "reason": "outside selection"}],
    [{"op": "create", "original_source": "长生剑法", "source": "长生", "target": "Trường Sinh"}],
    [{"op": "update", "original_source": "长生剑法", "source": "长生剑法", "target": "Kiếm 法"}],
])
@pytest.mark.parametrize("defer_conflicts", [False, True])
def test_selected_invalid_response_fails_without_writes(tmp_path, operations, defer_conflicts):
    storage = setup_storage(tmp_path)
    before = rows(storage)
    with pytest.raises(ValueError):
        curator.apply_operations(storage, [r for r in before if r["source"] == "长生剑法"], operations,
                                 selected_only=True, defer_conflicts=defer_conflicts)
    assert rows(storage) == before
    assert storage.read_extra_json("glossary_curator_audit") is None


def test_repeated_provider_timeout_splits_batch_and_finishes(tmp_path, monkeypatch):
    """Provider hết thời gian 2 lần -> tự chia nhỏ lô, không bỏ cả job."""
    storage = Storage(tmp_path, "t")
    pending = [{"source": f"张{i}", "target": f"Trương {i}", "note": ""} for i in range(8)]
    storage.write_extra_json("glossary_pending", pending)
    sources = [p["source"] for p in pending]
    sizes = []
    calls = {"n": 0}

    def chat(cfg, prompt):
        batch = json.loads(prompt.split("\nBATCH:\n")[1].split("\nREFERENCE:\n")[0])
        sizes.append(len(batch))
        # Hai lần gọi đầu với lô 4 mục đều hết thời gian từ provider; lô nhỏ hơn thì ok.
        if len(batch) == 4 and calls["n"] < 2:
            calls["n"] += 1
            raise openai_client.RetryableAIError("Không nhận được reply trong thời hạn (120000ms)")
        return json.dumps([{"op": "keep", "original_source": row["source"]} for row in batch])

    monkeypatch.setattr(curator.openai_client, "run_chat", chat)
    logs = []
    result = curator.curate(storage, OpenAIConfig(), sources=sources, batch_size=4, log=logs.append)
    assert calls["n"] == curator.AI_RETRY_ATTEMPTS
    assert result["failed_batches"] == 0
    assert len(result["operations"]) == 8
    assert storage.read_extra_json("glossary_pending") == []
    assert sizes == [4, 4, 2, 4, 2]
    assert any("provider quá tải/hết thời gian" in line for line in logs)


def test_single_entry_timeout_is_not_split(tmp_path, monkeypatch):
    """Lô 1 mục hết thời gian thì báo lỗi, không chia tiếp mãi."""
    storage = Storage(tmp_path, "t")
    storage.write_extra_json("glossary_pending", [{"source": "张一", "target": "Trương 1", "note": ""}])
    calls = {"n": 0}

    def chat(cfg, prompt):
        calls["n"] += 1
        raise openai_client.RetryableAIError("Không nhận được reply trong thời hạn (120000ms)")

    monkeypatch.setattr(curator.openai_client, "run_chat", chat)
    with pytest.raises(ValueError, match="120000ms"):
        curator.curate(storage, OpenAIConfig(), sources=["张一"])
    assert calls["n"] == curator.AI_RETRY_ATTEMPTS
    assert len(storage.read_extra_json("glossary_pending")) == 1


def test_auth_error_is_not_retried(tmp_path, monkeypatch):
    """401 là lỗi cấu hình -> không thử lại, báo lỗi ngay."""
    storage = Storage(tmp_path, "t")
    storage.write_extra_json("glossary_pending", [{"source": "张一", "target": "Trương 1", "note": ""}])
    calls = {"n": 0}

    def chat(cfg, prompt):
        calls["n"] += 1
        raise RuntimeError("AI trả về mã lỗi HTTP 401:\nunauthorized")

    monkeypatch.setattr(curator.openai_client, "run_chat", chat)
    with pytest.raises(ValueError, match="401"):
        curator.curate(storage, OpenAIConfig(), sources=["张一"])
    assert calls["n"] == 1


def test_selected_default_ten_and_keep_clears_pending(tmp_path, monkeypatch):
    storage = Storage(tmp_path, "t")
    pending = [{"source": f"张{i}", "target": f"Trương {i}", "note": ""} for i in range(51)]
    storage.write_extra_json("glossary_pending", pending)
    sizes = []
    def chat(cfg, prompt):
        batch = json.loads(prompt.split("\nBATCH:\n")[1].split("\nREFERENCE:\n")[0])
        sizes.append(len(batch))
        return json.dumps([{"op": "keep", "original_source": r["source"]} for r in batch])
    monkeypatch.setattr(curator.openai_client, "run_chat", chat)
    curator.curate(storage, OpenAIConfig(), sources=[p["source"] for p in pending])
    assert sizes == [10, 10, 10, 10, 10, 1]
    assert storage.read_extra_json("glossary_pending") == []
    assert len(storage.read_glossary_entries_merged()) == 51
