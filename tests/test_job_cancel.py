from novel2epub import pipeline
from novel2epub.config import Config, CrawlConfig, NovelConfig, OutputConfig, TranslateConfig
from novel2epub.crawler import TocResult
from novel2epub.storage import Chapter, Storage

from app.job import JobRunner


def _cfg(tmp_path, translate_type="cli"):
    return Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/book/1/", delay_seconds=0),
        translate=TranslateConfig(type=translate_type, delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


class _FakeCrawler:
    def __init__(self, toc):
        self._toc = toc

    def fetch_toc(self):
        return self._toc

    def fetch_chapter(self, ch):
        return f"noi dung {ch.index}"

    def sleep(self):
        pass

    def close(self):
        pass


class _UpperTranslator:
    def translate(self, text, *, on_chunk=None):
        out = f"VI:{text}"
        if on_chunk is not None:
            on_chunk(1, 1, out, True)
        return out

    def translate_title(self, text, kind="tên chương"):
        return f"VI:{text}", ""


def _toc(n):
    return TocResult(
        title="书名",
        chapters=[Chapter(index=i, url=f"http://x/{i}") for i in range(1, n + 1)],
    )


def test_step_crawl_selected_stops_when_cancelled(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "make_crawler", lambda c: _FakeCrawler(_toc(5)))

    cfg = _cfg(tmp_path)
    seen = []
    calls = {"n": 0}

    def should_cancel():
        calls["n"] += 1
        return calls["n"] > 2

    def log(msg):
        seen.append(msg)

    pipeline.step_crawl_selected(cfg, log, should_cancel=should_cancel)

    storage = Storage(tmp_path, "t")
    manifest = storage.load_manifest()
    # Job bị dừng sớm: không phải cả 5 chương đều được crawl.
    crawled = [ch for ch in manifest.chapters if storage.has_raw(ch)]
    assert 0 < len(crawled) < 5
    assert any("Đã dừng theo yêu cầu" in m for m in seen)


def test_step_translate_selected_stops_when_cancelled(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "make_crawler", lambda c: _FakeCrawler(_toc(5)))
    monkeypatch.setattr(pipeline, "make_translator", lambda c, log=None: _UpperTranslator())

    cfg = _cfg(tmp_path)
    pipeline.step_crawl_selected(cfg, lambda m: None)

    seen = []
    calls = {"n": 0}

    def should_cancel():
        calls["n"] += 1
        return calls["n"] > 2

    def log(msg):
        seen.append(msg)

    pipeline.step_translate_selected(cfg, log, should_cancel=should_cancel)

    storage = Storage(tmp_path, "t")
    manifest = storage.load_manifest()
    translated = [ch for ch in manifest.chapters if storage.has_translated(ch)]
    assert 0 < len(translated) < 5
    assert any("Đã dừng theo yêu cầu" in m for m in seen)


def test_job_runner_request_cancel_only_affects_running_category():
    runner = JobRunner()

    # Không job nào chạy -> không có gì để dừng.
    assert runner.request_cancel("crawl") is False

    runner._slots["crawl"].running = True
    assert runner.request_cancel("crawl") is True
    assert runner.status()["crawl"]["cancelling"] is True
    assert runner.status()["translate"]["cancelling"] is False
