import pytest

from app.library_state import archived_slugs, set_archived


def test_archived_slugs_empty_when_no_file(tmp_path):
    assert archived_slugs(tmp_path / "novel2epub.db") == set()


def test_set_archived_persists_and_round_trips(tmp_path):
    path = tmp_path / "novel2epub.db"
    set_archived(path, "a", True)
    set_archived(path, "b", True)
    assert archived_slugs(path) == {"a", "b"}


def test_set_archived_false_removes_slug(tmp_path):
    path = tmp_path / "novel2epub.db"
    set_archived(path, "a", True)
    set_archived(path, "a", False)
    assert archived_slugs(path) == set()


def test_set_archived_rejects_non_sqlite_file(tmp_path):
    """File tồn tại nhưng không phải SQLite hợp lệ → lỗi rõ ràng, không âm
    thầm ghi đè (khác hành vi cũ dựa trên JSON, nay dựa trên định dạng DB)."""
    path = tmp_path / "novel2epub.db"
    path.write_text("not a sqlite file", encoding="utf-8")
    with pytest.raises(Exception):
        set_archived(path, "a", True)
