"""`load_config` nhớ đệm ảnh chụp raw của settings/sources/ebooks theo thread —
phải nhanh hơn nhưng KHÔNG được trả cấu hình cũ sau khi DB đổi, và không được
để caller sửa nhầm vào bộ nhớ đệm dùng chung."""
from __future__ import annotations

import threading

from tests.conftest import write_db_config

from novel2epub.config import load_config
from novel2epub.db import get_connection, get_thread_connection


def _db(tmp_path, title="Tựa cũ"):
    return write_db_config(
        tmp_path / "novel2epub.db",
        defaults={"api": {"cors_origins": ["https://a.test"]}},
        ebooks={"t": {"novel": {"slug": "t", "title": title}}},
    )


def test_reloads_after_write_from_another_connection(tmp_path):
    path = _db(tmp_path)
    assert load_config(path, "t").novel.title == "Tựa cũ"

    other = get_connection(str(path))
    with other:
        other.execute("UPDATE ebooks SET title = 'Tựa mới' WHERE slug = 't'")
    other.close()

    assert load_config(path, "t").novel.title == "Tựa mới"


def test_reloads_after_write_from_the_same_connection(tmp_path):
    """`PRAGMA data_version` cố ý KHÔNG đổi cho commit của chính kết nối đó —
    khoá đệm phải kèm `total_changes`, nếu không route vừa lưu xong sẽ đọc lại
    đúng bản cũ."""
    path = _db(tmp_path)
    assert load_config(path, "t").novel.title == "Tựa cũ"

    conn = get_thread_connection(path)
    with conn:
        conn.execute("UPDATE ebooks SET title = 'Tựa mới' WHERE slug = 't'")

    assert load_config(path, "t").novel.title == "Tựa mới"


def test_mutating_one_config_does_not_leak_into_the_next(tmp_path):
    path = _db(tmp_path)
    first = load_config(path, "t")
    first.api.cors_origins.append("https://ke-khac.test")
    first.novel.title = "Bị sửa tại chỗ"

    second = load_config(path, "t")

    assert second.api.cors_origins == ["https://a.test"]
    assert second.novel.title == "Tựa cũ"


def test_cache_is_per_thread(tmp_path):
    path = _db(tmp_path)
    load_config(path, "t")
    titles: list[str] = []

    def _read():
        titles.append(load_config(path, "t").novel.title)

    thread = threading.Thread(target=_read)
    thread.start()
    thread.join()

    assert titles == ["Tựa cũ"]
