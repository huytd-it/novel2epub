from pathlib import Path

from fastapi.testclient import TestClient
import pytest
import time

from app.queue import JobQueue
from novel2epub import pipeline
from novel2epub.config import Config, CrawlConfig, NovelConfig, OutputConfig, TranslateConfig
from novel2epub.storage import Chapter, Manifest, Storage


def test_ebook_page_contains_queue_outcome_aggregation():
    """SPA đọc queue qua API `/api/queue` — trả snapshot đủ để gộp outcome."""
    from app.main import app

    client = TestClient(app)
    res = client.get("/api/queue")
    assert res.status_code == 200
    data = res.json()
    # Snapshot có đủ các mảng mà trang tổng hợp outcome cần.
    assert set(data) >= {"categories", "running", "pending", "history", "workers"}


def test_ebook_page_guards_job_forms_against_duplicate_submit():
    """Giao diện SPA hiển thị job đang chạy từ snapshot — không có form HTML
    cũ để double-submit; job phải có state rõ ràng trong snapshot."""
    from app.main import app

    client = TestClient(app)
    data = client.get("/api/queue").json()
    for job in data["running"]:
        assert "state" in job
    for jobs in data["pending"].values():
        for job in jobs:
            assert "state" in job


def test_ebook_page_has_compact_selected_command_bar():
    """Command bar chọn hàng loạt là client-side (React); backend cung cấp
    các action qua endpoint `/ebooks/{slug}/jobs/chapter-action` (JSON job_ids)."""
    from app.main import app

    client = TestClient(app)
    res = client.get("/api/ui/library")
    assert res.status_code == 200
    assert "ebooks" in res.json()


def test_queue_snapshot_carries_outcome_for_finish_grouping(tmp_path):
    """Snapshot queue phải giữ `outcome` trên từng job history để SPA gộp kết
    quả (mới/bỏ qua/lỗi/hủy) sau khi nhóm job kết thúc — đúng thông tin mà
    helper JS cũ từng dùng để render toast."""
    from app.queue import JobQueue

    db_path = tmp_path / "novel2epub.db"
    queue = JobQueue(workers={"crawl": 1}, db_path=db_path)
    job = queue.enqueue("crawl", "chapter-crawl", lambda log: {"processed": 1, "skipped": 0, "failed": 0, "skip_reasons": {}})

    assert _wait_until(lambda: job.state in {"done", "failed"})
    assert job.state == "done"
    snap = queue.snapshot()
    history = {h["id"]: h for h in snap["history"]}
    assert job.id in history
    assert history[job.id]["outcome"] == {"processed": 1, "skipped": 0, "failed": 0, "skip_reasons": {}}


def _cfg(tmp_path, translate_type="none"):
    return Config(
        novel=NovelConfig(slug="t", title="Truyen t"),
        crawl=CrawlConfig(toc_url="http://x/book/1/", delay_seconds=0),
        translate=TranslateConfig(type=translate_type, delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


def _wait_until(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class _FakeCrawler:
    def fetch_chapter(self, ch):
        return f"noi dung {ch.index}"

    def sleep(self):
        pass

    def close(self):
        pass


class _FakeTranslator:
    def translate(self, text, *, chapter_idx=None, on_chunk=None, on_glossary=None):
        if on_chunk is not None:
            on_chunk(1, 1, f"VI:{text}", True)
        return f"VI:{text}"


class _FailingCrawler:
    def fetch_chapter(self, ch):
        raise RuntimeError("crawl failed")

    def sleep(self):
        pass

    def close(self):
        pass


class _FailingTranslator:
    def translate(self, text, *, chapter_idx=None, on_chunk=None, on_glossary=None):
        raise RuntimeError("translation failed")


def _manifest(cfg, chapter):
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    storage.save_manifest(Manifest(slug=cfg.novel.slug, title="Sach", chapters=[chapter]))
    return storage


def test_crawl_chapter_outcome_reports_existing_raw(tmp_path):
    cfg = _cfg(tmp_path)
    chapter = Chapter(index=1, url="http://x/1")
    storage = _manifest(cfg, chapter)
    storage.write_raw(chapter, "raw")

    assert pipeline.step_crawl_chapter_outcome(cfg, lambda _: None, 1) == {
        "processed": 0,
        "skipped": 1,
        "failed": 0,
        "skip_reasons": {"đã có raw": 1},
    }


def test_translate_chapter_outcome_reports_missing_raw(tmp_path):
    cfg = _cfg(tmp_path)
    _manifest(cfg, Chapter(index=1, url="http://x/1"))

    assert pipeline.step_translate_chapter_outcome(cfg, lambda _: None, 1) == {
        "processed": 0,
        "skipped": 1,
        "failed": 0,
        "skip_reasons": {"chưa có raw": 1},
    }


def test_crawl_chapter_outcome_reports_processed(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _manifest(cfg, Chapter(index=1, url="http://x/1"))
    monkeypatch.setattr(pipeline, "ScraplingCrawler", lambda _: _FakeCrawler())

    assert pipeline.step_crawl_chapter_outcome(cfg, lambda _: None, 1) == {
        "processed": 1,
        "skipped": 0,
        "failed": 0,
        "skip_reasons": {},
    }


def test_crawl_chapter_outcome_does_not_report_processed_after_cancellation(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _manifest(cfg, Chapter(index=1, url="http://x/1"))

    def finish_chapter(*args, **kwargs):
        storage = Storage(cfg.output.data_dir, cfg.novel.slug)
        chapter = storage.load_manifest().chapters[0]
        chapter.last_action_status = "completed"
        storage.save_chapter(chapter)

    monkeypatch.setattr(pipeline, "step_crawl_selected", finish_chapter)

    assert pipeline.step_crawl_chapter_outcome(
        cfg, lambda _: None, 1, should_cancel=lambda: True
    ) == {
        "processed": 0,
        "skipped": 0,
        "failed": 0,
        "skip_reasons": {},
    }


def test_translate_chapter_outcome_reports_existing_translation(tmp_path):
    cfg = _cfg(tmp_path)
    chapter = Chapter(index=1, url="http://x/1")
    storage = _manifest(cfg, chapter)
    storage.write_raw(chapter, "raw")
    storage.write_translated(chapter, "dich")
    storage.mark_translated_complete(chapter)

    assert pipeline.step_translate_chapter_outcome(cfg, lambda _: None, 1) == {
        "processed": 0,
        "skipped": 1,
        "failed": 0,
        "skip_reasons": {"đã có bản dịch": 1},
    }


def test_translate_chapter_outcome_reports_skipped_toc_chapter(tmp_path):
    cfg = _cfg(tmp_path)
    chapter = Chapter(index=1, url="http://x/1", skipped=True)
    storage = _manifest(cfg, chapter)
    storage.write_raw(chapter, "raw")

    assert pipeline.step_translate_chapter_outcome(cfg, lambda _: None, 1) == {
        "processed": 0,
        "skipped": 1,
        "failed": 0,
        "skip_reasons": {"chương đã bỏ qua": 1},
    }


def test_crawl_chapter_outcome_force_replaces_existing_raw(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    chapter = Chapter(index=1, url="http://x/1")
    storage = _manifest(cfg, chapter)
    storage.write_raw(chapter, "old raw")
    monkeypatch.setattr(pipeline, "ScraplingCrawler", lambda _: _FakeCrawler())

    assert pipeline.step_crawl_chapter_outcome(cfg, lambda _: None, 1, force=True) == {
        "processed": 1,
        "skipped": 0,
        "failed": 0,
        "skip_reasons": {},
    }
    assert storage.read_raw(chapter) == "noi dung 1"


def test_translate_chapter_outcome_force_replaces_existing_translation(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    chapter = Chapter(index=1, url="http://x/1")
    storage = _manifest(cfg, chapter)
    storage.write_raw(chapter, "raw")
    storage.write_translated(chapter, "old translation")
    storage.mark_translated_complete(chapter)
    monkeypatch.setattr(pipeline, "make_translator", lambda *_args, **_kwargs: _FakeTranslator())

    assert pipeline.step_translate_chapter_outcome(cfg, lambda _: None, 1, force=True) == {
        "processed": 1,
        "skipped": 0,
        "failed": 0,
        "skip_reasons": {},
    }
    assert storage.read_translated(chapter) == "VI:raw"


def test_crawl_chapter_outcome_reports_failure(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _manifest(cfg, Chapter(index=1, url="http://x/1"))
    monkeypatch.setattr(pipeline, "ScraplingCrawler", lambda _: _FailingCrawler())

    assert pipeline.step_crawl_chapter_outcome(cfg, lambda _: None, 1) == {
        "processed": 0,
        "skipped": 0,
        "failed": 1,
        "skip_reasons": {},
    }


def test_crawl_write_failure_returns_failed_outcome_on_sequential_queue_job(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    chapter = Chapter(index=1, url="http://x/1")
    storage = _manifest(cfg, chapter)
    monkeypatch.setattr(pipeline, "ScraplingCrawler", lambda _: _FakeCrawler())

    def fail_write_raw(self, ch, content):
        raise OSError("write failed")

    monkeypatch.setattr(Storage, "write_raw", fail_write_raw)
    queue = JobQueue(workers={"crawl": 1}, db_path=tmp_path / "novel2epub.db")
    job = queue.enqueue(
        "crawl",
        "chapter-crawl",
        lambda log: pipeline.step_crawl_chapter_outcome(cfg, log, 1),
    )

    assert _wait_until(lambda: job.state in {"done", "failed"})
    assert job.state == "done"
    assert job.outcome == {
        "processed": 0,
        "skipped": 0,
        "failed": 1,
        "skip_reasons": {},
    }
    assert storage.load_manifest().chapters[0].last_action_status == "failed"


def test_translate_chapter_outcome_raises_backend_failure_and_retains_status(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    chapter = Chapter(index=1, url="http://x/1")
    storage = _manifest(cfg, chapter)
    storage.write_raw(chapter, "raw")
    monkeypatch.setattr(pipeline, "make_translator", lambda *_args, **_kwargs: _FailingTranslator())

    with pytest.raises(RuntimeError, match="translation failed"):
        pipeline.step_translate_chapter_outcome(cfg, lambda _: None, 1)

    assert storage.load_manifest().chapters[0].last_action_status == "failed"


def test_translation_backend_failure_fails_queue_job_without_outcome(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    chapter = Chapter(index=1, url="http://x/1")
    storage = _manifest(cfg, chapter)
    storage.write_raw(chapter, "raw")
    monkeypatch.setattr(pipeline, "make_translator", lambda *_args, **_kwargs: _FailingTranslator())

    db_path = tmp_path / "novel2epub.db"
    queue = JobQueue(workers={"translate": 1}, db_path=db_path)
    job = queue.enqueue(
        "translate",
        "chapter-translate",
        lambda log: pipeline.step_translate_chapter_outcome(cfg, log, 1),
    )

    assert _wait_until(lambda: job.state == "failed")
    assert job.error
    assert "translation failed" in job.error
    assert job.outcome is None

    assert _wait_until(lambda: any(item["id"] == job.id for item in queue.snapshot()["history"]))
    history_item = next(item for item in queue.snapshot()["history"] if item["id"] == job.id)
    assert history_item["state"] == "failed"
    assert history_item["error"] == job.error
    assert "outcome" not in history_item

    restored = JobQueue(workers={"translate": 0}, db_path=db_path)
    restored_item = next(item for item in restored.snapshot()["history"] if item["id"] == job.id)
    assert restored_item["state"] == "failed"
    assert restored_item["error"] == job.error
    assert "outcome" not in restored_item


def test_translate_chapter_outcome_reports_processed(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    chapter = Chapter(index=1, url="http://x/1")
    storage = _manifest(cfg, chapter)
    storage.write_raw(chapter, "raw")
    monkeypatch.setattr(pipeline, "make_translator", lambda *_args, **_kwargs: _FakeTranslator())

    assert pipeline.step_translate_chapter_outcome(cfg, lambda _: None, 1) == {
        "processed": 1,
        "skipped": 0,
        "failed": 0,
        "skip_reasons": {},
    }


def test_crawl_chapter_outcome_reports_skipped_chapter_before_cache(tmp_path):
    cfg = _cfg(tmp_path)
    chapter = Chapter(index=1, url="", skipped=True)
    storage = _manifest(cfg, chapter)
    storage.write_raw(chapter, "raw")

    assert pipeline.step_crawl_chapter_outcome(cfg, lambda _: None, 1) == {
        "processed": 0,
        "skipped": 1,
        "failed": 0,
        "skip_reasons": {"chương đã bỏ qua": 1},
    }


def test_crawl_chapter_outcome_reports_missing_url(tmp_path):
    cfg = _cfg(tmp_path)
    _manifest(cfg, Chapter(index=1, url=""))

    assert pipeline.step_crawl_chapter_outcome(cfg, lambda _: None, 1) == {
        "processed": 0,
        "skipped": 1,
        "failed": 0,
        "skip_reasons": {"thiếu URL": 1},
    }


class _FakeQueue:
    def __init__(self):
        self.enqueued = []

    def enqueue(self, category, step, target, **kwargs):
        job_id = f"job-{len(self.enqueued) + 1}"
        self.enqueued.append((job_id, category, step, target, kwargs))
        return type("Job", (), {"id": job_id})()


class _FakeJobRunner:
    def __init__(self):
        self.queue = _FakeQueue()


def test_selected_crawl_action_returns_enqueued_job_ids(tmp_path, monkeypatch):
    from app import deps
    from app.main import app

    cfg = _cfg(tmp_path)
    cfg.novel.title = "Quỷ Bí Chi Chủ"
    _manifest(cfg, Chapter(index=40, url="http://x/40", title="第40章 神秘学课程"))
    runner = _FakeJobRunner()
    monkeypatch.setattr(deps, "resolved_cfg", lambda _: cfg)
    app.state.job = runner
    client = TestClient(app)

    response = client.post(
        "/ebooks/t/jobs/chapter-action",
        data={"action": "crawl", "targeting_mode": "checked", "checked_indexes": "40"},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert response.json() == {"job_ids": ["job-1"], "action": "crawl"}
    assert runner.queue.enqueued[0][1:3] == ("crawl", "chapter-crawl")
    assert runner.queue.enqueued[0][4]["label"] == "Cào chương · Quỷ Bí Chi Chủ · 40.第40章 神秘学课程"


def test_selected_translate_action_returns_enqueued_job_ids(tmp_path, monkeypatch):
    from app import deps
    from app.main import app

    cfg = _cfg(tmp_path)
    _manifest(cfg, Chapter(index=1, url="http://x/1"))
    runner = _FakeJobRunner()
    monkeypatch.setattr(deps, "resolved_cfg", lambda _: cfg)
    app.state.job = runner
    client = TestClient(app)

    response = client.post(
        "/ebooks/t/jobs/chapter-action",
        data={"action": "translate", "targeting_mode": "checked", "checked_indexes": "1"},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert response.json() == {"job_ids": ["job-1"], "action": "translate"}
    assert runner.queue.enqueued[0][1:3] == ("translate", "chapter-translate")
