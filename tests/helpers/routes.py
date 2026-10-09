"""Config/client cô lập và job giả cho các test route thao tác hàng loạt."""
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import deps
from novel2epub.config import (
    Config,
    CrawlConfig,
    NovelConfig,
    OutputConfig,
    TranslateConfig,
)


def make_config(tmp_path, *, translate_type="cli"):
    return Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/book/", delay_seconds=0),
        translate=TranslateConfig(type=translate_type, delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


class FakeJob:
    """Ghi nhận job; chỉ chạy target đồng bộ khi test yêu cầu rõ ràng."""

    def __init__(self, *, run_targets=False):
        self.started = []
        self.run_targets = run_targets

    def status(self):
        return {
            category: {"running": False, "step": "", "error": "", "log": []}
            for category in ("crawl", "translate")
        }

    def start_custom(self, name, target, *, category, **kwargs):
        self.started.append({"name": name, "target": target, "category": category, **kwargs})
        if self.run_targets:
            target(lambda msg: None)
        return True


def make_client(cfg, monkeypatch, *, run_jobs=False, **kwargs):
    """Cài dependency/job tạm; monkeypatch khôi phục sau mỗi test.

    Không vào lifespan vì route tests không cần worker/scheduler chạy nền.
    """
    monkeypatch.setattr(deps, "library", lambda: SimpleNamespace(ebooks={}))
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    from app.main import app

    monkeypatch.setattr(app.state, "job", FakeJob(run_targets=run_jobs))
    client = TestClient(app, **kwargs)
    return client
