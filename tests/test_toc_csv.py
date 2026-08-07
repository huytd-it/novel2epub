import csv
import io

from fastapi.testclient import TestClient

from app import deps
from app.main import app
from novel2epub.config import Config, CrawlConfig, NovelConfig, OutputConfig, TranslateConfig
from novel2epub.storage import Chapter, Manifest, Storage


def _setup(tmp_path, monkeypatch):
    cfg = Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="https://example.test/book"),
        translate=TranslateConfig(type="none"),
        output=OutputConfig(data_dir=str(tmp_path)),
    )
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    storage = Storage(tmp_path, "t")
    chapters = [
        Chapter(index=1, url="https://example.test/1", title="Chương 1", title_zh="第一章", title_note="giữ"),
        Chapter(index=2, url="https://example.test/2", title="Chương 2", title_zh="第二章", skipped=True),
    ]
    storage.save_manifest(Manifest(slug="t", chapters=chapters))
    storage.write_raw(chapters[0], "raw giữ nguyên")
    storage.write_translated(chapters[0], "dịch giữ nguyên")
    return TestClient(app), storage


def test_toc_csv_export_is_excel_friendly(tmp_path, monkeypatch):
    client, _storage = _setup(tmp_path, monkeypatch)

    response = client.get("/ebooks/t/toc.csv")

    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert rows[0] == {
        "index": "1", "url": "https://example.test/1",
        "title": "Chương 1", "title_zh": "第一章",
    }


def test_toc_csv_import_updates_only_titles(tmp_path, monkeypatch):
    client, storage = _setup(tmp_path, monkeypatch)
    content = "index,url,title,title_zh\n1,ignored,Chương 1: Tên mới,第一章 新名\n"

    response = client.post(
        "/ebooks/t/toc.csv",
        files={"file": ("toc.csv", content.encode("utf-8"), "text/csv")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    chapters = storage.load_manifest().chapters
    assert chapters[0].title == "Chương 1: Tên mới"
    assert chapters[0].title_zh == "第一章 新名"
    assert chapters[0].url == "https://example.test/1"
    assert chapters[0].title_note == "giữ"
    assert chapters[1].title == "Chương 2"
    assert chapters[1].skipped is True
    assert storage.read_raw(chapters[0]) == "raw giữ nguyên"
    assert storage.read_translated(chapters[0]) == "dịch giữ nguyên"


def test_toc_csv_import_rejects_unknown_index_without_partial_update(tmp_path, monkeypatch):
    client, storage = _setup(tmp_path, monkeypatch)
    content = "index,title,title_zh\n1,Đã đổi,一\n99,Không tồn tại,九十九\n"

    response = client.post(
        "/ebooks/t/toc.csv",
        files={"file": ("toc.csv", content.encode("utf-8"), "text/csv")},
    )

    assert response.status_code == 400
    assert storage.load_manifest().chapters[0].title == "Chương 1"
