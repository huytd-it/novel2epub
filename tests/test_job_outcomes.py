from pathlib import Path
import json
import subprocess

from fastapi.testclient import TestClient
import pytest
import time

from app.queue import JobQueue
from novel2epub import pipeline
from novel2epub.config import Config, CrawlConfig, NovelConfig, OutputConfig, TranslateConfig
from novel2epub.storage import Chapter, Manifest, Storage


def test_ebook_page_contains_queue_outcome_aggregation():
    template = (Path(__file__).parents[1] / "app" / "templates" / "ebook.html").read_text(encoding="utf-8")

    assert "const pendingOutcomeGroups" in template
    assert "function summarizeOutcomes(action, jobs)" in template
    assert "function finishOutcomeGroups(queueSnapshot)" in template
    assert 'fetch("/api/queue")' in template
    assert "pendingOutcomeGroups.push" in template
    assert "finishOutcomeGroups(queueSnapshot)" in template


def _evaluate_outcome_helpers(script):
    template = (Path(__file__).parents[1] / "app" / "templates" / "ebook.html").read_text(encoding="utf-8")
    start = template.index("const pendingOutcomeGroups = [];")
    end = template.index("// Poll status", start)
    helpers = template[start:end]
    result = subprocess.run(
        ["node", "-e", f"let toasts = []; let reloads = 0; const toast = (...args) => toasts.push(args); const ebookSoftReload = () => reloads += 1; {helpers}\n{script}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(result.stdout)


def test_queue_outcome_helpers_merge_running_array_and_complete_without_reload():
    result = _evaluate_outcome_helpers(
        """
const snapshot = {
    running: [{ id: "running-1", state: "running" }, { id: "running-2", state: "running" }],
    pending: { crawl: [{ id: "pending-1", state: "pending" }] },
    history: [{ id: "done-1", state: "done", outcome: { processed: 0, skipped: 1, failed: 0 } }],
};
const ids = [...collectJobsById(snapshot).keys()];
pendingOutcomeGroups.push({ action: "crawl", jobIds: ["done-1"] });
const outcomeResult = finishOutcomeGroups(snapshot);
console.log(JSON.stringify({ ids, outcomeResult, remaining: pendingOutcomeGroups.length, reloads, toasts }));
"""
    )

    assert result["ids"] == ["running-1", "running-2", "pending-1", "done-1"]
    assert result["outcomeResult"] == {"completed": True, "refreshToc": False}
    assert result["remaining"] == 0
    assert result["reloads"] == 0
    assert result["toasts"] == [["Crawl xong: 1 bỏ qua.", "info"]]


def test_queue_outcome_helpers_summarize_terminal_groups_once_and_exclude_cancellations():
    result = _evaluate_outcome_helpers(
        """
const cases = {
    success: [{ id: "success", state: "done", outcome: { processed: 2, skipped: 0, failed: 0 } }],
    skipOnly: [{ id: "skip", state: "done", outcome: { processed: 0, skipped: 2, failed: 0, skip_reasons: { "đã có raw": 2 } } }],
    genericSkip: [{ id: "generic-skip", state: "done", outcome: { processed: 0, skipped: 1, failed: 0 } }],
    mixedFailure: [{ id: "mixed", state: "done", outcome: { processed: 1, skipped: 0, failed: 1 } }],
    failureOnly: [{ id: "failed", state: "failed" }],
    allCancelled: [{ id: "cancelled", state: "cancelled" }],
    partialCancellation: [
        { id: "cancelled-partial", state: "cancelled", outcome: { processed: 9, skipped: 9, failed: 9 } },
        { id: "processed-partial", state: "done", outcome: { processed: 1, skipped: 0, failed: 0 } },
    ],
    absentOutcome: [
        { id: "cancelled-absent", state: "cancelled" },
        { id: "skipped-present", state: "done", outcome: { processed: 0, skipped: 1, failed: 0 } },
    ],
};
const summaries = Object.fromEntries(Object.entries(cases).filter(([name]) => name !== "allCancelled").map(([name, jobs]) => {
    const summary = summarizeOutcomes("crawl", jobs);
    return [name, { message: summary.message, kind: summary.kind, processed: summary.processed }];
}));
const snapshot = { history: [...cases.allCancelled, ...cases.partialCancellation] };
pendingOutcomeGroups.push({ action: "crawl", jobIds: ["cancelled"] });
pendingOutcomeGroups.push({ action: "crawl", jobIds: ["cancelled-partial", "processed-partial"] });
const first = finishOutcomeGroups(snapshot);
const second = finishOutcomeGroups(snapshot);
console.log(JSON.stringify({ summaries, first, second, remaining: pendingOutcomeGroups.length, toasts }));
"""
    )

    assert result["summaries"] == {
        "success": {"message": "Crawl xong: 2 mới.", "kind": "success", "processed": 2},
        "skipOnly": {"message": "Crawl xong: 2 bỏ qua (đã có raw).", "kind": "info", "processed": 0},
        "genericSkip": {"message": "Crawl xong: 1 bỏ qua.", "kind": "info", "processed": 0},
        "mixedFailure": {"message": "Crawl xong: 1 mới, 1 lỗi.", "kind": "warning", "processed": 1},
        "failureOnly": {"message": "Crawl thất bại: 1 lỗi.", "kind": "error", "processed": 0},
        "partialCancellation": {"message": "Crawl xong: 1 mới.", "kind": "success", "processed": 1},
        "absentOutcome": {"message": "Crawl xong: 1 bỏ qua.", "kind": "info", "processed": 0},
    }
    assert result["first"] == {"completed": True, "refreshToc": True}
    assert result["second"] == {"completed": False, "refreshToc": False}
    assert result["remaining"] == 0
    assert result["toasts"] == [["Crawl xong: 1 mới.", "success"], ["Đã hủy Crawl.", "info"]]


def test_queue_outcome_reload_policy_waits_for_outcome_completion():
    result = _evaluate_outcome_helpers(
        """
console.log(JSON.stringify({
    unrelatedFinish: shouldSoftReload(true, false, false),
    completedNoChange: shouldSoftReload(true, true, false),
    completedWithChanges: shouldSoftReload(true, true, true),
}));
"""
    )

    assert result == {
        "unrelatedFinish": True,
        "completedNoChange": False,
        "completedWithChanges": True,
    }


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
    def translate(self, text, *, on_chunk=None, on_glossary=None):
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
    def translate(self, text, *, on_chunk=None, on_glossary=None):
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
    _manifest(cfg, Chapter(index=1, url="http://x/1"))
    runner = _FakeJobRunner()
    monkeypatch.setattr(deps, "resolved_cfg", lambda _: cfg)
    app.state.job = runner
    client = TestClient(app)

    response = client.post(
        "/ebooks/t/jobs/chapter-action",
        data={"action": "crawl", "targeting_mode": "checked", "checked_indexes": "1"},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert response.json() == {"job_ids": ["job-1"], "action": "crawl"}
    assert runner.queue.enqueued[0][1:3] == ("crawl", "chapter-crawl")


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
