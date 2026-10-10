"""Một nguồn nhận diện được NHIỀU domain khác nhau: trường `domains` chấp
nhận phẩy/dấu cách/xuống dòng/`;` và cả URL dán nguyên."""
from __future__ import annotations

from novel2epub.sources import (
    SourcePreset,
    detect_preset,
    normalize_domains,
    preset_matches_url,
    split_domains,
)


def test_split_domains_chap_nhan_nhieu_kieu_ngan_cach_va_url():
    raw = "69shuba.com, https://www.69shu.com/book/1.htm\nTWKAN.com;69shuba.com  *.shu69.cx:8443"
    assert split_domains(raw) == ["69shuba.com", "69shu.com", "twkan.com", "shu69.cx"]
    assert normalize_domains(raw) == "69shuba.com,69shu.com,twkan.com,shu69.cx"


def test_split_domains_giu_token_khong_phai_domain_day_du():
    assert split_domains("biquge,bqg") == ["biquge", "bqg"]
    assert split_domains("") == []


def test_preset_khop_moi_domain_trong_danh_sach():
    preset = SourcePreset(name="69", domains="69shuba.com https://www.twkan.com/")
    assert preset_matches_url(preset, "https://www.69shuba.com/book/1/")
    assert preset_matches_url(preset, "https://twkan.com/book/2.html")
    assert not preset_matches_url(preset, "https://khac.com/")


def test_detect_preset_voi_domain_thu_hai_va_uu_tien_token_dai_hon():
    presets = {
        "chung": SourcePreset(name="chung", domains="shu.com"),
        "rieng": SourcePreset(name="rieng", domains="abc.net; 69shu.com"),
    }
    assert detect_preset("https://www.69shu.com/1/", presets) == "rieng"
    assert detect_preset("https://abc.net/x", presets) == "rieng"
    assert detect_preset("https://khac.org/x", presets) is None
