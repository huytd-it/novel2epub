"""Báo cáo dung lượng + dọn dẹp/đóng gói archive (xem spec storage-management)."""
from __future__ import annotations

import zipfile

from app.storage_report import build_archive_bundle, ebook_storage_report, purge_raw, purge_translated_mt, remove_epub
from novel2epub.storage import Chapter, Storage


def _storage_with_data(tmp_path):
    storage = Storage(tmp_path, "t")
    storage.ensure_dirs()
    ch = Chapter(index=1, url="http://x/1")
    storage.write_raw(ch, "raw content")
    storage.write_translated_mt(ch, "mt content")
    storage.write_translated(ch, "edited content")
    return storage, ch


def test_ebook_storage_report_sums_by_category(tmp_path):
    storage, ch = _storage_with_data(tmp_path)
    report = ebook_storage_report(storage)
    assert report["raw"] > 0
    assert report["translated_mt"] > 0
    assert report["translated"] > 0
    assert report["total"] == sum(
        report[k] for k in ("raw", "translated", "translated_mt", "meta", "glossary", "epub")
    )


def test_ebook_storage_report_includes_epub_when_present(tmp_path):
    storage, ch = _storage_with_data(tmp_path)
    epub_path = tmp_path / "out.epub"
    epub_path.write_bytes(b"x" * 100)
    report = ebook_storage_report(storage, epub_path)
    assert report["epub"] == 100


def test_purge_raw_removes_raw_but_keeps_translated(tmp_path):
    storage, ch = _storage_with_data(tmp_path)
    freed = purge_raw(storage)
    assert freed > 0
    assert not storage.has_raw(ch)
    assert storage.read_translated(ch) == "edited content"


def test_purge_translated_mt_removes_mt_but_keeps_translated(tmp_path):
    storage, ch = _storage_with_data(tmp_path)
    freed = purge_translated_mt(storage)
    assert freed > 0
    assert not storage.has_translated_mt(ch)
    assert storage.read_translated(ch) == "edited content"


def test_remove_epub_deletes_file_and_returns_size(tmp_path):
    epub_path = tmp_path / "out.epub"
    epub_path.write_bytes(b"x" * 50)
    freed = remove_epub(epub_path)
    assert freed == 50
    assert not epub_path.exists()


def test_remove_epub_missing_file_returns_zero(tmp_path):
    assert remove_epub(tmp_path / "missing.epub") == 0


def test_build_archive_bundle_includes_artifacts_and_config(tmp_path):
    storage, ch = _storage_with_data(tmp_path)
    out = build_archive_bundle(storage, tmp_path / "bundle.zip", config_snippet="novel:\n  title: x\n")
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert any(n.endswith("raw/0001.md") for n in names)
        assert any(n.endswith("config.yaml") for n in names)
