"""`step_build_selected(translated_only=True)` — EPUB phục vụ qua OPDS.

Chương chưa dịch rơi về `raw_text` là chữ Hán gốc, VÀ không được gắn neo
`data-n2e-p` (xem `step_build_selected`), nên vừa vô nghĩa khi đọc vừa không
sửa được từ readest. Đường build cho OPDS phải bỏ hẳn chúng, còn đường build
tay thì giữ nguyên hành vi cũ.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from novel2epub import pipeline
from novel2epub.config import Config, CrawlConfig, NovelConfig, OutputConfig, TranslateConfig
from novel2epub.storage import Chapter, Manifest, Storage


def _cfg(tmp_path) -> Config:
    return Config(
        novel=NovelConfig(slug="t", title="Truyện", author="TG"),
        crawl=CrawlConfig(toc_url="http://x/", delay_seconds=0),
        translate=TranslateConfig(type="cli", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path), epub_path=str(tmp_path / "out.epub")),
    )


def _seed(tmp_path):
    """Chương 1 đã dịch, chương 2 mới chỉ crawl thô."""
    storage = Storage(tmp_path, "t")
    ch1 = Chapter(index=1, url="http://x/1", title="Chương 1")
    ch2 = Chapter(index=2, url="http://x/2", title="Chương 2")
    storage.save_manifest(Manifest(slug="t", title="Truyện", chapters=[ch1, ch2]))
    storage.write_translated(ch1, "# Chương 1\n\nĐoạn đã dịch.")
    storage.write_raw(ch2, "# 第二章\n\n這是原文。")
    return storage, ch1, ch2


def _chapter_files(epub_path: str) -> list[str]:
    with zipfile.ZipFile(epub_path) as z:
        return sorted(n for n in z.namelist() if n.endswith(".xhtml") and "chap_" in n)


def _text(epub_path: str) -> str:
    with zipfile.ZipFile(epub_path) as z:
        return "".join(
            z.read(n).decode("utf-8") for n in z.namelist() if n.endswith(".xhtml")
        )


def test_translated_only_bo_han_chuong_chua_dich(tmp_path):
    _seed(tmp_path)
    out = pipeline.step_build_selected(_cfg(tmp_path), lambda m: None, translated_only=True)
    assert len(_chapter_files(out)) == 1
    body = _text(out)
    assert "Đoạn đã dịch" in body
    assert "這是原文" not in body


def test_mac_dinh_van_giu_nhanh_roi_ve_raw(tmp_path):
    """Nút Build và CLI `build` không được đổi hành vi."""
    _seed(tmp_path)
    out = pipeline.step_build(_cfg(tmp_path), lambda m: None)
    assert len(_chapter_files(out)) == 2
    assert "這是原文" in _text(out)


def test_chuong_giu_lai_van_co_neo(tmp_path):
    """Neo `data-n2e-p` là điều kiện để sửa đoạn từ readest — lọc chương
    không được làm mất neo của chương còn lại."""
    _seed(tmp_path)
    out = pipeline.step_build_selected(_cfg(tmp_path), lambda m: None, translated_only=True)
    assert 'data-n2e-p="0"' in _text(out)


def test_khong_co_chuong_nao_da_dich_thi_bao_loi_ro_rang(tmp_path):
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=1, url="http://x/1", title="Chương 1")
    storage.save_manifest(Manifest(slug="t", title="Truyện", chapters=[ch]))
    storage.write_raw(ch, "# 第一章\n\n原文。")

    with pytest.raises(RuntimeError, match="đã dịch"):
        pipeline.step_build_selected(_cfg(tmp_path), lambda m: None, translated_only=True)
    assert not Path(tmp_path / "out.epub").exists()
