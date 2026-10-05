import json

import pytest

from novel2epub import glossary_curator as curator
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
    assert "Trương Tam" in prompts[1]
    assert all(curator.token_upper_bound(p) < curator.CONTEXT_TOKENS - curator.OUTPUT_RESERVE for p in prompts)
    assert "rác" in storage.read_glossary_file("names.txt")


def test_budget_bounds_reference_and_rejects_oversized_entry():
    batch = [{"source": "张三", "target": "Trương Tam", "note": ""}]
    reference = [{"source": str(i), "target": "x" * 20_000} for i in range(20)]
    prompt = curator.build_prompt(batch, reference, {}, "")
    assert curator.token_upper_bound(prompt) <= curator.CONTEXT_TOKENS - curator.OUTPUT_RESERVE
    batch[0]["note"] = "中" * 200_000
    with pytest.raises(ValueError, match="200k"):
        curator.build_prompt(batch, [], {}, "")


def test_ambiguous_old_target_is_held(tmp_path):
    storage = setup_storage(tmp_path)
    storage.upsert_glossary_entry("李四", "Trương Sai")
    result = curator.apply_operations(storage, rows(storage), [{"op": "update", "original_source": "张三", "source": "张三", "target": "Trương Tam"}])
    assert len(result["held"]) == 1
    assert storage.read_glossary_file("names.txt")["张三"] == "Trương Sai"


def test_oversized_batches_split_without_losing_rows(tmp_path, monkeypatch):
    storage = setup_storage(tmp_path)
    storage.write_glossary_entries("names.txt", [(f"张{i}", f"Trương {i}", "n" * 800) for i in range(4)])
    base_size = curator.token_upper_bound(curator.build_prompt([], [], {}, ""))
    monkeypatch.setattr(curator, "CONTEXT_TOKENS", base_size + 1800)
    monkeypatch.setattr(curator, "OUTPUT_RESERVE", 500)
    sent = []
    def chat(cfg, prompt):
        batch = json.loads(prompt.split("\nLÔ:\n")[1].split("\nTHAM CHIẾU:\n")[0])
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
