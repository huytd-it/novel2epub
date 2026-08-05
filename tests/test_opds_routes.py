"""Route OPDS: chỉ liệt kê sách đã build, mã lỗi đúng, xác thực đúng chỗ."""
from __future__ import annotations

import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient

from novel2epub.config import (
    ApiConfig,
    Config,
    CrawlConfig,
    NovelConfig,
    OutputConfig,
    TranslateConfig,
)
from novel2epub.storage import Chapter, Manifest, Storage

ATOM = "http://www.w3.org/2005/Atom"


def _cfg(tmp_path, slug: str, *, epub_name: str = "", token: str = "") -> Config:
    return Config(
        novel=NovelConfig(slug=slug, title=f"Tên {slug}", author="Tác Giả"),
        crawl=CrawlConfig(toc_url="http://x/", delay_seconds=0),
        translate=TranslateConfig(type="cli", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path), epub_path=epub_name),
        api=ApiConfig(token=token),
    )


def _seed_ebook(tmp_path, slug: str, *, with_epub: bool, cover: bytes | None = None):
    storage = Storage(tmp_path, slug)
    storage.save_manifest(
        Manifest(slug=slug, title=f"Tên {slug}", author="Tác Giả",
                 chapters=[Chapter(index=1, url="http://x/1", title="C1")])
    )
    if cover is not None:
        storage.write_cover(cover, "jpg")
    if with_epub:
        (tmp_path / f"{slug}.epub").write_bytes(b"PK\x03\x04gia-lap-epub")
    return storage


def _client(monkeypatch, tmp_path, slugs: list[str], *, token: str = "", host: str = "127.0.0.1"):
    from app import deps
    from app.main import app
    from novel2epub.config import LibraryConfig

    cfgs = {s: _cfg(tmp_path, s, epub_name=str(tmp_path / f"{s}.epub"), token=token)
            for s in slugs}
    monkeypatch.setattr(deps, "library", lambda: LibraryConfig(ebooks={s: object() for s in slugs}))
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfgs[slug])
    monkeypatch.setattr(deps, "cfg", lambda: next(iter(cfgs.values())))
    monkeypatch.setattr("app.routes.opds.archived_slugs", lambda _p: set())
    return TestClient(app, client=(host, 12345))


def test_feed_goc_tra_atom_va_content_type_navigation(monkeypatch, tmp_path):
    _seed_ebook(tmp_path, "a", with_epub=True)
    r = _client(monkeypatch, tmp_path, ["a"]).get("/opds")
    assert r.status_code == 200
    assert "kind=navigation" in r.headers["content-type"]
    assert ET.fromstring(r.text).tag == f"{{{ATOM}}}feed"


def test_feed_books_liet_ke_sach_da_build(monkeypatch, tmp_path):
    _seed_ebook(tmp_path, "a", with_epub=True)
    r = _client(monkeypatch, tmp_path, ["a"]).get("/opds/books")
    assert r.status_code == 200
    assert "kind=acquisition" in r.headers["content-type"]
    titles = [e.text for e in ET.fromstring(r.text).findall(f"{{{ATOM}}}entry/{{{ATOM}}}title")]
    assert titles == ["Tên a"]


def test_sach_chua_build_epub_khong_xuat_hien(monkeypatch, tmp_path):
    _seed_ebook(tmp_path, "a", with_epub=True)
    _seed_ebook(tmp_path, "b", with_epub=False)
    r = _client(monkeypatch, tmp_path, ["a", "b"]).get("/opds/books")
    titles = [e.text for e in ET.fromstring(r.text).findall(f"{{{ATOM}}}entry/{{{ATOM}}}title")]
    assert titles == ["Tên a"]


def test_sach_da_archive_khong_xuat_hien(monkeypatch, tmp_path):
    _seed_ebook(tmp_path, "a", with_epub=True)
    _seed_ebook(tmp_path, "b", with_epub=True)
    client = _client(monkeypatch, tmp_path, ["a", "b"])
    monkeypatch.setattr("app.routes.opds.archived_slugs", lambda _p: {"b"})
    titles = [e.text for e in ET.fromstring(client.get("/opds/books").text)
              .findall(f"{{{ATOM}}}entry/{{{ATOM}}}title")]
    assert titles == ["Tên a"]


def test_tai_epub_tra_dung_byte_va_media_type(monkeypatch, tmp_path):
    _seed_ebook(tmp_path, "a", with_epub=True)
    r = _client(monkeypatch, tmp_path, ["a"]).get("/opds/download/a.epub")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/epub+zip"
    assert r.content == b"PK\x03\x04gia-lap-epub"


def test_tai_epub_chua_build_tra_404(monkeypatch, tmp_path):
    _seed_ebook(tmp_path, "a", with_epub=False)
    r = _client(monkeypatch, tmp_path, ["a"]).get("/opds/download/a.epub")
    assert r.status_code == 404


def test_bia_tra_dung_byte(monkeypatch, tmp_path):
    _seed_ebook(tmp_path, "a", with_epub=True, cover=b"\xff\xd8\xff-gia-lap-jpg")
    r = _client(monkeypatch, tmp_path, ["a"]).get("/opds/cover/a")
    assert r.status_code == 200
    assert r.content == b"\xff\xd8\xff-gia-lap-jpg"


def test_khong_co_bia_tra_404_va_feed_khong_phat_link_anh(monkeypatch, tmp_path):
    _seed_ebook(tmp_path, "a", with_epub=True, cover=None)
    client = _client(monkeypatch, tmp_path, ["a"])
    assert client.get("/opds/cover/a").status_code == 404
    entry = ET.fromstring(client.get("/opds/books").text).find(f"{{{ATOM}}}entry")
    rels = {ln.get("rel") for ln in entry.findall(f"{{{ATOM}}}link")}
    assert "http://opds-spec.org/image" not in rels


def test_ebook_khong_ton_tai_tra_404(monkeypatch, tmp_path):
    _seed_ebook(tmp_path, "a", with_epub=True)
    r = _client(monkeypatch, tmp_path, ["a"]).get("/opds/download/khong-co.epub")
    assert r.status_code == 404


# ---------- xác thực ----------


def test_may_khac_khong_co_token_tra_401(monkeypatch, tmp_path):
    _seed_ebook(tmp_path, "a", with_epub=True)
    client = _client(monkeypatch, tmp_path, ["a"], token="tok", host="192.168.1.20")
    r = client.get("/opds")
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == 'Basic realm="novel2epub"'


def test_may_khac_chua_cau_hinh_token_tra_503(monkeypatch, tmp_path):
    _seed_ebook(tmp_path, "a", with_epub=True)
    client = _client(monkeypatch, tmp_path, ["a"], token="", host="192.168.1.20")
    assert client.get("/opds").status_code == 503


def test_moi_endpoint_opds_deu_duoc_bao_ve(monkeypatch, tmp_path):
    _seed_ebook(tmp_path, "a", with_epub=True, cover=b"x")
    client = _client(monkeypatch, tmp_path, ["a"], token="tok", host="192.168.1.20")
    for path in ("/opds", "/opds/books", "/opds/download/a.epub", "/opds/cover/a"):
        assert client.get(path).status_code == 401, path


def test_url_trong_feed_dung_host_ma_client_da_goi(monkeypatch, tmp_path):
    # readest trên điện thoại gọi bằng IP LAN — link trong feed phải là IP đó,
    # không phải localhost, nếu không nó tải về chính cái điện thoại.
    _seed_ebook(tmp_path, "a", with_epub=True)
    client = _client(monkeypatch, tmp_path, ["a"])
    r = client.get("/opds/books", headers={"Host": "192.168.1.9:8010"})
    assert "http://192.168.1.9:8010/opds/download/a.epub" in r.text
