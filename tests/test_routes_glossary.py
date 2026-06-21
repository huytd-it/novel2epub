from novel2epub.storage import Storage
from app.routes.glossary import _append_glossary_entry


def test_append_new_entry_writes_line(tmp_path):
    storage = Storage(tmp_path, "slug")
    storage.ensure_dirs()

    changed = _append_glossary_entry(storage, "vietphrase.txt", "庄国", "Trang Quốc")

    assert changed is True
    assert storage.read_glossary_file("vietphrase.txt") == {"庄国": "Trang Quốc"}


def test_append_skips_when_already_present_with_same_value(tmp_path):
    storage = Storage(tmp_path, "slug")
    storage.ensure_dirs()
    storage.write_glossary_file("vietphrase.txt", "庄国 = Trang Quốc\n")

    changed = _append_glossary_entry(storage, "vietphrase.txt", "庄国", "Trang Quốc")

    assert changed is False
    content = storage.glossary_path("vietphrase.txt").read_text(encoding="utf-8")
    assert content.count("庄国") == 1


def test_append_updates_when_value_differs(tmp_path):
    storage = Storage(tmp_path, "slug")
    storage.ensure_dirs()
    storage.write_glossary_file("vietphrase.txt", "庄国 = Trang Quốc cũ\n")

    changed = _append_glossary_entry(storage, "vietphrase.txt", "庄国", "Trang Quốc mới")

    assert changed is True
    content = storage.glossary_path("vietphrase.txt").read_text(encoding="utf-8")
    assert "Trang Quốc cũ" in content and "Trang Quốc mới" in content


def test_append_rejects_blank_or_invalid_target(tmp_path):
    storage = Storage(tmp_path, "slug")
    storage.ensure_dirs()

    assert _append_glossary_entry(storage, "vietphrase.txt", "", "Trang Quốc") is False
    assert _append_glossary_entry(storage, "vietphrase.txt", "庄国", "") is False
    assert _append_glossary_entry(storage, "khong-hop-le.txt", "庄国", "Trang Quốc") is False
