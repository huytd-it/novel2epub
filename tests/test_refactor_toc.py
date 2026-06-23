import sys

from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from novel2epub import pipeline
from novel2epub.cli import main
from novel2epub.config import Config, CrawlConfig, NovelConfig, OutputConfig, TranslateConfig
from novel2epub.crawler import HttpCrawler, TocResult
from novel2epub.storage import Chapter, Manifest, Storage
from novel2epub.toc import apply_chapter_query, chapter_rows, mark_duplicate_chapters, select_visible_range


CLI_CONTRACT = "specs/001-refactor-toc/contracts/cli.md"
WEB_UI_CONTRACT = "specs/001-refactor-toc/contracts/web-ui.md"


def _cfg(tmp_path, translate_type="none"):
    return Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/book/", delay_seconds=0),
        translate=TranslateConfig(type=translate_type, delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


class _FakeCrawler:
    def __init__(self, toc, content="raw"):
        self._toc = toc
        self._content = content

    def fetch_toc(self):
        return self._toc

    def fetch_chapter(self, ch):
        return f"{self._content}:{ch.index}"

    def sleep(self):
        pass

    def close(self):
        pass


class _FakeTranslator:
    def translate(self, text):
        return f"VI:{text}"

    def translate_title(self, text, kind="tên chương"):
        return f"VI:{text}", ""


def test_mark_duplicate_chapters_and_visible_range(tmp_path):
    chapters = mark_duplicate_chapters([
        Chapter(index=1, url="http://x/1", title_zh="B"),
        Chapter(index=2, url="http://x/2", title_zh="A"),
        Chapter(index=3, url="http://x/1", title_zh="C"),
    ])
    storage = Storage(tmp_path, "t")
    rows = chapter_rows(chapters, storage)
    assert rows[2].duplicate_of == 1
    assert "duplicate" in rows[2].missing_fields

    visible = apply_chapter_query(rows, sort="title", search="", filter_missing="any")
    assert [r.index for r in visible] == [2, 1, 3]
    assert select_visible_range(visible, 3, 2) == [2, 1, 3]
    assert apply_chapter_query(rows, sort="source", filter_missing="yes")[0].index == 3


def test_http_crawler_toc_has_source_missing_and_chapters():
    html = """
    <html><head><meta property="og:novel:book_name" content="书名"></head>
    <body><div id="list"><a href="/1.html">第一章</a><a href="/2.html">第二章</a></div></body></html>
    """
    crawler = HttpCrawler(CrawlConfig(toc_url="http://x/book/", toc_selector="#list", chapter_link_pattern=r".*\.html$"))
    crawler._get_soup = lambda url: BeautifulSoup(html, "html.parser")
    toc = crawler.fetch_toc()
    assert toc.source_url == "http://x/book/"
    assert toc.title == "书名"
    assert toc.metadata_missing == ["author", "description"]
    assert [c.url for c in toc.chapters] == ["http://x/1.html", "http://x/2.html"]


def test_fetch_toc_ignores_max_chapters_limit(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    cfg.crawl.max_chapters = 1
    toc = TocResult(chapters=[
        Chapter(index=1, url="http://x/1"),
        Chapter(index=2, url="http://x/2"),
        Chapter(index=3, url="http://x/3"),
    ])
    monkeypatch.setattr(pipeline, "make_crawler", lambda c: _FakeCrawler(toc))

    pipeline.step_fetch_toc(cfg, lambda m: None)

    manifest = Storage(tmp_path, "t").load_manifest()
    assert [ch.index for ch in manifest.chapters] == [1, 2, 3]


def test_default_crawl_applies_max_chapters_without_truncating_manifest(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    cfg.crawl.max_chapters = 1
    toc = TocResult(chapters=[
        Chapter(index=1, url="http://x/1"),
        Chapter(index=2, url="http://x/2"),
        Chapter(index=3, url="http://x/3"),
    ])
    monkeypatch.setattr(pipeline, "make_crawler", lambda c: _FakeCrawler(toc))

    pipeline.step_crawl_selected(cfg, lambda m: None)

    storage = Storage(tmp_path, "t")
    manifest = storage.load_manifest()
    assert [ch.index for ch in manifest.chapters] == [1, 2, 3]
    assert storage.has_raw(manifest.chapters[0])
    assert not storage.has_raw(manifest.chapters[1])


def test_fetch_toc_preserves_curated_metadata_without_force(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.save_manifest(Manifest(slug="t", title="curated", title_vi="Tên Việt", chapters=[Chapter(index=1, url="http://old/1", title_vi="Cũ")]))
    toc = TocResult(title="new", author="a", description="d", source_url="http://x/book/", chapters=[Chapter(index=1, url="http://new/1", title_zh="第一章")])
    monkeypatch.setattr(pipeline, "make_crawler", lambda c: _FakeCrawler(toc))

    pipeline.step_fetch_toc(cfg, lambda m: None)
    manifest = storage.load_manifest()
    assert manifest.title == "curated"
    assert manifest.title_vi == "Tên Việt"
    assert manifest.source_url == "http://x/book/"

    pipeline.step_fetch_toc(cfg, lambda m: None, force=True)
    assert storage.load_manifest().title == "new"


def test_selected_crawl_and_translate_respect_force(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, translate_type="cli")
    manifest = Manifest(slug="t", chapters=[Chapter(index=1, url="http://x/1", title_zh="第一章")])
    storage = Storage(tmp_path, "t")
    storage.save_manifest(manifest)
    storage.write_raw(manifest.chapters[0], "old raw")
    storage.write_translated(manifest.chapters[0], "old vi")
    toc = TocResult(chapters=manifest.chapters)
    monkeypatch.setattr(pipeline, "make_crawler", lambda c: _FakeCrawler(toc, "new raw"))
    monkeypatch.setattr(pipeline, "make_translator", lambda c, log=None: _FakeTranslator())

    pipeline.step_crawl_selected(cfg, lambda m: None, selected_indexes=[1])
    assert storage.read_raw(manifest.chapters[0]) == "old raw"
    pipeline.step_crawl_selected(cfg, lambda m: None, selected_indexes=[1], force=True)
    assert storage.read_raw(manifest.chapters[0]) == "new raw:1"

    pipeline.step_translate_selected(cfg, lambda m: None, selected_indexes=[1])
    assert storage.read_translated(manifest.chapters[0]) == "old vi"
    pipeline.step_translate_selected(cfg, lambda m: None, selected_indexes=[1], force=True)
    assert storage.read_translated(manifest.chapters[0]) == "VI:new raw:1"


def test_cli_chapters_lists_filtered_rows(tmp_path, capsys):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "novel:\n  slug: t\ncrawl:\n  toc_url: http://x/book/\ntranslate:\n  type: none\noutput:\n  data_dir: " + str(tmp_path).replace("\\", "/") + "\n",
        encoding="utf-8",
    )
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=1, url="http://x/1", title_zh="第一章")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    assert main(["-c", str(cfg_path), "chapters", "--sort", "title", "--search", "第一"]) == 0
    out = capsys.readouterr().out
    assert "第一章" in out and "raw=False" in out


def test_cli_toc_command_fetches_manifest(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "novel:\n  slug: t\ncrawl:\n  toc_url: http://x/book/\ntranslate:\n  type: none\noutput:\n  data_dir: " + str(tmp_path).replace("\\", "/") + "\n",
        encoding="utf-8",
    )
    toc = TocResult(title="书名", source_url="http://x/book/", chapters=[Chapter(index=1, url="http://x/1")])
    monkeypatch.setattr(pipeline, "make_crawler", lambda c: _FakeCrawler(toc))
    sys.modules["novel2epub.cli"].step_fetch_toc = pipeline.step_fetch_toc
    assert main(["-c", str(cfg_path), "toc"]) == 0
    assert Storage(tmp_path, "t").load_manifest().title == "书名"


def test_ebook_route_applies_query_controls(tmp_path, monkeypatch):
    from app import deps
    from app.main import app

    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.save_manifest(Manifest(slug="t", title="书名", source_url="http://x/book/", chapters=[
        Chapter(index=1, url="http://x/1", title_zh="B"),
        Chapter(index=2, url="http://x/2", title_zh="A", missing_fields=["title"]),
    ]))
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    client = TestClient(app)

    res = client.get("/ebooks/default?sort=title&filter_missing=yes")
    assert res.status_code == 200
    assert "书名" in res.text
    assert "A" in res.text
    assert "http://x/1" not in res.text
    assert 'class="chapter-check"' in res.text
    assert 'form="bulk-action-form"' in res.text
    assert 'class="row-actions"' in res.text
    assert 'class="compact-toolbar"' in res.text
    assert "simpleDatatables.DataTable" not in res.text
    assert 'value="crawl"' in res.text
    assert 'value="translate"' in res.text


def test_chapter_action_routes_start_custom_job(tmp_path, monkeypatch):
    from app import deps
    from app.main import app

    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.save_manifest(Manifest(slug="t", chapters=[Chapter(index=1, url="http://x/1", title_zh="A")]))
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    calls = []

    class Job:
        def status(self):
            empty = {"running": False, "step": "", "error": "", "log": []}
            return {"crawl": empty, "translate": empty}

        def start_custom(self, step, target, category):
            calls.append(step)
            return True

        def start(self, step, cfg):
            calls.append(step)
            return True

    app.state.job = Job()
    client = TestClient(app)
    res = client.post("/ebooks/default/jobs/chapter-action", data={"action": "crawl", "range_start": "1", "range_end": "1"}, follow_redirects=False)
    assert res.status_code == 303
    res = client.post("/ebooks/default/chapters/1/action", data={"action": "translate"}, follow_redirects=False)
    assert res.status_code == 303
    assert calls == ["chapter-crawl", "chapter-translate"]


def test_chapter_detail_shows_quick_glossary_and_edit_rules(tmp_path, monkeypatch):
    from app import deps
    from app.main import app

    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=1, url="http://x/1", title_zh="第一章")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    storage.write_raw(ch, "庄国 có một vị công tử")
    storage.write_translated(ch, "Trang Quốc có một vị công tử")
    storage.write_glossary_file("names.txt", "庄国 = Trang Quốc\n")
    storage.write_glossary_file("vietphrase.txt", "公子 = công tử\n")
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    client = TestClient(app)

    res = client.get("/ebooks/default/chapters/1")

    assert res.status_code == 200
    assert "Chú giải nhanh" in res.text
    assert "庄国" in res.text and "Trang Quốc" in res.text
    assert "Checklist edit hay" in res.text
    assert "docs/rule.md" in res.text
    assert "glossary-chip relevant" in res.text


def test_bulk_chapter_action_checked_mode_uses_visible_checked_rows(tmp_path, monkeypatch):
    from app import deps
    from app.main import app
    import app.routes.jobs as jobs

    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    storage.save_manifest(Manifest(slug="t", chapters=[
        Chapter(index=1, url="http://x/1", title_zh="visible", missing_fields=["title"]),
        Chapter(index=2, url="http://x/2", title_zh="hidden"),
    ]))
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    selected_calls = []

    def fake_crawl(cfg, log, **kwargs):
        selected_calls.append(kwargs.get("selected_indexes"))

    monkeypatch.setattr(jobs, "step_crawl_selected", fake_crawl)

    class Job:
        def status(self):
            empty = {"running": False, "step": "", "error": "", "log": []}
            return {"crawl": empty, "translate": empty}

        def start_custom(self, step, target, category):
            target(lambda m: None)
            return True

    app.state.job = Job()
    client = TestClient(app)
    res = client.post(
        "/ebooks/default/jobs/chapter-action",
        data={
            "action": "crawl",
            "targeting_mode": "checked",
            "checked_indexes": ["1", "2"],
            "filter_missing": "yes",
        },
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert selected_calls == [[1]]
