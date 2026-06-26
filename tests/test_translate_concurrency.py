"""moxhimt không fan-out luồng-mỗi-chương (song song hóa qua CT2 batching/
threads); cli/google vẫn tôn trọng translate.max_workers như trước (xem
spec moxhimt-translator: 'CPU thread pool over thread-per-chapter')."""
from __future__ import annotations

from novel2epub import pipeline
from novel2epub.config import Config, CrawlConfig, NovelConfig, OutputConfig, TranslateConfig
from novel2epub.crawler import TocResult
from novel2epub.storage import Chapter


def _cfg(tmp_path, translate_type, max_workers=4):
    return Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/book/1/", delay_seconds=0),
        translate=TranslateConfig(type=translate_type, delay_seconds=0, max_workers=max_workers),
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


class _EchoTranslator:
    def translate(self, text, *, on_chunk=None):
        if on_chunk is not None:
            on_chunk(1, 1, text, True)
        return text

    def translate_title(self, text, kind="tên chương"):
        return text, ""


def _toc(n):
    return TocResult(
        title="书名",
        chapters=[Chapter(index=i, url=f"http://x/{i}") for i in range(1, n + 1)],
    )


def test_moxhimt_ignores_max_workers_and_runs_sequential(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "make_crawler", lambda c: _FakeCrawler(_toc(3)))
    monkeypatch.setattr(pipeline, "make_translator", lambda c, log=None: _EchoTranslator())

    calls = {"parallel": 0, "sequential": 0}
    orig_parallel = pipeline._translate_chapters_parallel
    orig_sequential = pipeline._translate_chapters_sequential

    def _wrap_parallel(*a, **kw):
        calls["parallel"] += 1
        return orig_parallel(*a, **kw)

    def _wrap_sequential(*a, **kw):
        calls["sequential"] += 1
        return orig_sequential(*a, **kw)

    monkeypatch.setattr(pipeline, "_translate_chapters_parallel", _wrap_parallel)
    monkeypatch.setattr(pipeline, "_translate_chapters_sequential", _wrap_sequential)

    cfg = _cfg(tmp_path, "moxhimt", max_workers=4)
    pipeline.step_crawl_selected(cfg, lambda m: None)
    pipeline.step_translate_selected(cfg, lambda m: None)

    assert calls["parallel"] == 0
    assert calls["sequential"] == 1


def test_cli_honors_max_workers_and_runs_parallel(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "make_crawler", lambda c: _FakeCrawler(_toc(3)))
    monkeypatch.setattr(pipeline, "make_translator", lambda c, log=None: _EchoTranslator())

    calls = {"parallel": 0, "sequential": 0}
    orig_parallel = pipeline._translate_chapters_parallel
    orig_sequential = pipeline._translate_chapters_sequential

    def _wrap_parallel(*a, **kw):
        calls["parallel"] += 1
        return orig_parallel(*a, **kw)

    def _wrap_sequential(*a, **kw):
        calls["sequential"] += 1
        return orig_sequential(*a, **kw)

    monkeypatch.setattr(pipeline, "_translate_chapters_parallel", _wrap_parallel)
    monkeypatch.setattr(pipeline, "_translate_chapters_sequential", _wrap_sequential)

    cfg = _cfg(tmp_path, "cli", max_workers=4)
    pipeline.step_crawl_selected(cfg, lambda m: None)
    pipeline.step_translate_selected(cfg, lambda m: None)

    assert calls["parallel"] == 1
    assert calls["sequential"] == 0
