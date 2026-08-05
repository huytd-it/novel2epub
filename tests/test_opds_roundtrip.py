"""Khứ hồi: build EPUB -> đọc neo từ XHTML -> PATCH qua API -> soi lại DB.

Test quan trọng nhất của cả tính năng. Nó bắt đúng lớp lỗi mà các test đơn lẻ
bỏ sót: neo đúng trong EPUB nhưng lệch so với chỉ số mà `replace_para` dùng.
Phải bao cả chương có block nhiều dòng và chương có footnote — hai chỗ mà hai
định nghĩa đoạn từng lệch nhau.
"""
from __future__ import annotations

import re
import zipfile

from novel2epub.notes import split_paras
from novel2epub.pipeline import step_build_selected
from novel2epub.storage import Chapter, Manifest, Storage

from .test_opds_routes import _cfg, _client

# Chương cố ý có block nhiều dòng (đoạn 2 và 3 dính chung một block) — đúng
# hình dạng đã làm dòng-không-rỗng (161) lệch khỏi block (160) trong dữ liệu thật.
MD = (
    "# Chương 1\n\n"
    "Đoạn mở đầu.\n\n"
    "Dòng thoại một\nDòng thoại hai\n\n"
    "Trang Quốc là nơi đó.\n\n"
    "Đoạn kết."
)


def _build(tmp_path):
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=1, url="http://x/1", title="Chương 1")
    storage.save_manifest(Manifest(slug="t", title="Truyện T", chapters=[ch]))
    storage.write_translated(ch, MD)
    storage.mark_translated_complete(ch)
    storage.write_glossary_file("names.txt", "Trang Quốc = Trang Quốc | nước hư cấu\n")
    cfg = _cfg(tmp_path, "t", epub_name=str(tmp_path / "t.epub"))
    step_build_selected(cfg, log=lambda _m: None)
    return storage, ch


def _chapter_xhtml(epub_path) -> str:
    with zipfile.ZipFile(epub_path) as z:
        name = next(n for n in z.namelist() if n.endswith("chap_0001.xhtml"))
        return z.read(name).decode("utf-8")


def test_neo_trong_epub_khop_chi_so_cua_split_paras(tmp_path):
    _build(tmp_path)
    xhtml = _chapter_xhtml(tmp_path / "t.epub")
    anchors = [int(n) for n in re.findall(r'data-n2e-p="(\d+)"', xhtml)]
    assert anchors == list(range(len(split_paras(MD))))


def test_sua_theo_neo_lay_tu_epub_doi_dung_doan_do(monkeypatch, tmp_path):
    storage, ch = _build(tmp_path)
    xhtml = _chapter_xhtml(tmp_path / "t.epub")

    # Đường đi của client thật: tìm neo trong EPUB, rồi lấy `expected` từ API
    # (KHÔNG lấy từ EPUB — bản trong EPUB đã escape và có <sup> footnote).
    target = int(re.search(r'data-n2e-p="(\d+)"[^>]*>Dòng thoại hai<', xhtml).group(1))

    client = _client(monkeypatch, tmp_path, ["t"])
    paragraphs = client.get("/api/v1/ebooks/t/chapters/1").json()["paragraphs"]
    expected = paragraphs[target]["text"]
    assert expected == "Dòng thoại hai"

    r = client.patch(
        f"/api/v1/ebooks/t/chapters/1/paragraphs/{target}",
        json={"text": "Dòng thoại hai ĐÃ SỬA", "expected": expected},
    )
    assert r.status_code == 200

    truoc = split_paras(MD)
    sau = split_paras(storage.read_translated(ch))
    assert sau[target] == "Dòng thoại hai ĐÃ SỬA"
    # Không đoạn nào khác động.
    assert len(sau) == len(truoc)
    for i, (a, b) in enumerate(zip(truoc, sau)):
        if i != target:
            assert a == b, f"đoạn {i} bị đổi ngoài ý muốn"


def test_neo_van_dung_o_doan_co_footnote(monkeypatch, tmp_path):
    storage, ch = _build(tmp_path)
    xhtml = _chapter_xhtml(tmp_path / "t.epub")
    assert "<sup" in xhtml  # footnote đã được chèn, test mới có ý nghĩa

    client = _client(monkeypatch, tmp_path, ["t"])
    paragraphs = client.get("/api/v1/ebooks/t/chapters/1").json()["paragraphs"]
    target = next(p["index"] for p in paragraphs if "Trang Quốc" in p["text"])

    r = client.patch(
        f"/api/v1/ebooks/t/chapters/1/paragraphs/{target}",
        json={"text": "Đã sửa đoạn có footnote.", "expected": paragraphs[target]["text"]},
    )
    assert r.status_code == 200
    assert split_paras(storage.read_translated(ch))[target] == "Đã sửa đoạn có footnote."


def test_sua_xong_build_lai_thi_neo_van_lien_tuc(tmp_path, monkeypatch):
    storage, ch = _build(tmp_path)
    client = _client(monkeypatch, tmp_path, ["t"])
    paragraphs = client.get("/api/v1/ebooks/t/chapters/1").json()["paragraphs"]
    client.patch(
        "/api/v1/ebooks/t/chapters/1/paragraphs/1",
        json={"text": "Mở đầu mới.", "expected": paragraphs[1]["text"]},
    )
    cfg = _cfg(tmp_path, "t", epub_name=str(tmp_path / "t.epub"))
    step_build_selected(cfg, log=lambda _m: None)

    xhtml = _chapter_xhtml(tmp_path / "t.epub")
    anchors = [int(n) for n in re.findall(r'data-n2e-p="(\d+)"', xhtml)]
    assert anchors == list(range(len(split_paras(storage.read_translated(ch)))))


def test_epub_tai_qua_opds_chinh_la_file_co_neo(monkeypatch, tmp_path):
    _build(tmp_path)
    client = _client(monkeypatch, tmp_path, ["t"])
    r = client.get("/opds/download/t.epub")
    assert r.status_code == 200
    assert r.content == (tmp_path / "t.epub").read_bytes()
