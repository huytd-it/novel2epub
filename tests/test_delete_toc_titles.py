from fastapi.testclient import TestClient

from app import deps
from app.main import app
from novel2epub.config import Config, CrawlConfig, NovelConfig, OutputConfig, TranslateConfig
from novel2epub.storage import Chapter, Manifest, Storage


def test_delete_chapters_clears_only_titles(tmp_path, monkeypatch):
    cfg = Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="https://example.test/book"),
        translate=TranslateConfig(type="none"),
        output=OutputConfig(data_dir=str(tmp_path)),
    )
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    storage = Storage(tmp_path, "t")
    chapter = Chapter(
        index=1,
        url="https://example.test/1",
        title="Chương 1: Tên chương",
        title_zh="第一章 章名",
        title_note="ghi chú",
        missing_fields=["description"],
        last_action_status="completed",
        skipped=True,
    )
    storage.save_manifest(Manifest(slug="t", chapters=[chapter]))
    storage.write_raw(chapter, "Nội dung gốc")
    storage.write_translated(chapter, "Nội dung dịch")
    storage.write_translated_mt(chapter, "Bản dịch máy")
    storage.write_meta(chapter, {"complete": True, "custom": "kept"})

    response = TestClient(app).post("/ebooks/t/jobs/delete-chapters", follow_redirects=False)

    assert response.status_code == 303
    kept = storage.load_manifest().chapters[0]
    assert kept.title == ""
    assert kept.title_zh == ""
    assert kept.url == chapter.url
    assert kept.title_note == "ghi chú"
    assert kept.missing_fields == ["description"]
    assert kept.last_action_status == "completed"
    assert kept.skipped is True
    assert storage.read_raw(kept) == "Nội dung gốc"
    assert storage.read_translated(kept) == "Nội dung dịch"
    assert storage.read_translated_mt(kept) == "Bản dịch máy"
    assert storage.read_meta(kept) == {"complete": True, "custom": "kept"}
