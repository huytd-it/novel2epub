"""Tests CRUD bảng nhân vật & quan hệ trong Storage."""
import pytest

from novel2epub.storage import Storage


@pytest.fixture()
def storage(tmp_path):
    return Storage(str(tmp_path), "truyen-test")


def test_upsert_and_read_character(storage):
    assert storage.upsert_character("林凡", "Lâm Phàm", "凡儿|林少爷", "nam",
                                    "ta", "hắn", "đồ đệ", "main") is True
    rows = storage.read_character_entries()
    assert rows == [("林凡", "Lâm Phàm", "凡儿|林少爷", "nam", "ta", "hắn", "đồ đệ", "main")]


def test_upsert_character_requires_source(storage):
    assert storage.upsert_character("", "Lâm Phàm") is False
    assert storage.read_character_entries() == []


def test_upsert_character_updates_in_place(storage):
    storage.upsert_character("林凡", "Lâm Phàm", importance="side")
    storage.upsert_character("林凡", "Lâm Phong", importance="main")
    rows = storage.read_character_entries()
    assert len(rows) == 1
    assert rows[0][1] == "Lâm Phong"
    assert rows[0][7] == "main"


def test_relation_roundtrip_and_multiple_milestones(storage):
    storage.upsert_relation("林凡", "苏清雪", 0, "nàng", "ta")
    storage.upsert_relation("林凡", "苏清雪", 120, "em", "anh")
    rows = storage.read_relation_entries()
    assert len(rows) == 2
    assert {r[2] for r in rows} == {0, 120}


def test_delete_character_cascades_to_relations(storage):
    storage.upsert_character("林凡", "Lâm Phàm")
    storage.upsert_character("苏清雪", "Tô Thanh Tuyết")
    storage.upsert_relation("林凡", "苏清雪", 0, "nàng", "ta")
    storage.upsert_relation("苏清雪", "林凡", 0, "chàng", "ta")

    assert storage.delete_character("林凡") is True
    assert storage.read_relation_entries() == []
    assert [r[0] for r in storage.read_character_entries()] == ["苏清雪"]


def test_delete_relation_targets_one_milestone(storage):
    storage.upsert_relation("林凡", "苏清雪", 0, "nàng", "ta")
    storage.upsert_relation("林凡", "苏清雪", 120, "em", "anh")
    assert storage.delete_relation("林凡", "苏清雪", 120) is True
    rows = storage.read_relation_entries()
    assert [r[2] for r in rows] == [0]
