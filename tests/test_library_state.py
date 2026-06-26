from app.library_state import archived_slugs, set_archived


def test_archived_slugs_empty_when_no_file(tmp_path):
    assert archived_slugs(tmp_path / "library_state.json") == set()


def test_set_archived_persists_and_round_trips(tmp_path):
    path = tmp_path / "library_state.json"
    set_archived(path, "a", True)
    set_archived(path, "b", True)
    assert archived_slugs(path) == {"a", "b"}


def test_set_archived_false_removes_slug(tmp_path):
    path = tmp_path / "library_state.json"
    set_archived(path, "a", True)
    set_archived(path, "a", False)
    assert archived_slugs(path) == set()


def test_set_archived_corrupt_file_resets_gracefully(tmp_path):
    path = tmp_path / "library_state.json"
    path.write_text("not json", encoding="utf-8")
    set_archived(path, "a", True)
    assert archived_slugs(path) == {"a"}
