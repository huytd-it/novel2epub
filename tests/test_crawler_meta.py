import pytest
from bs4 import BeautifulSoup

from novel2epub.config import CrawlConfig
from novel2epub.crawler import HttpCrawler, _meta_get, make_crawler


def _crawler(**kw):
    return HttpCrawler(CrawlConfig(toc_url="http://site.com/book/1/", **kw))


def test_extract_meta_from_og_tags():
    html = """
    <html><head>
      <title>Trang tiêu đề HTML</title>
      <meta property="og:novel:book_name" content="原书名">
      <meta property="og:novel:author" content="某作者">
      <meta property="og:description" content="简介内容">
      <meta property="og:image" content="/img/cover.jpg">
    </head><body></body></html>
    """
    title, author, description, cover = _crawler()._extract_meta(BeautifulSoup(html, "html.parser"))
    assert title == "原书名"
    assert author == "某作者"
    assert description == "简介内容"
    # cover_url phải được join thành URL tuyệt đối
    assert cover == "http://site.com/img/cover.jpg"


def test_extract_meta_selector_overrides_and_title_fallback():
    html = """
    <html><head><title>Tiêu đề trang</title></head>
    <body>
      <div id="info"><h1>书名从选择器</h1><p>作者甲</p></div>
      <div id="intro">介绍文字</div>
      <div id="fmimg"><img src="http://cdn.com/a.png"></div>
    </body></html>
    """
    c = _crawler(
        title_selector="#info h1",
        author_selector="#info p",
        desc_selector="#intro",
        cover_selector="#fmimg img",
    )
    title, author, description, cover = c._extract_meta(BeautifulSoup(html, "html.parser"))
    assert title == "书名从选择器"
    assert author == "作者甲"
    assert description == "介绍文字"
    assert cover == "http://cdn.com/a.png"


def test_extract_meta_falls_back_to_html_title():
    html = "<html><head><title>Chỉ có title</title></head><body></body></html>"
    title, author, description, cover = _crawler()._extract_meta(BeautifulSoup(html, "html.parser"))
    assert title == "Chỉ có title"
    assert author == "" and description == "" and cover == ""


def test_meta_get_picks_first_nonempty_and_handles_list():
    assert _meta_get({"a": "", "b": "x"}, "a", "b") == "x"
    assert _meta_get({"og:image": ["http://x/1.jpg", "http://x/2.jpg"]}, "og:image") == "http://x/1.jpg"
    assert _meta_get(None, "a") == ""


def _make_fake_response(html_text: str):
    class FakeResponse:
        status_code = 200
        text = html_text
        encoding = "utf-8"

        def raise_for_status(self):
            pass

    return FakeResponse()


def test_ai_fallback_triggers_when_content_empty(monkeypatch):
    from novel2epub import openai_client
    from novel2epub.config import OpenAIConfig
    from novel2epub.storage import Chapter

    html = "<html><body><p>Chương một nội dung.</p></body></html>"
    cfg = CrawlConfig(
        toc_url="http://site.com/",
        content_selector=".nonexistent",
        ai_fallback=True,
        ai_fallback_max_html=500,
        _openai_fallback=OpenAIConfig(base_url="https://api.test/v1"),
    )
    c = HttpCrawler(cfg)

    monkeypatch.setattr(c._session, "get", lambda url, **kw: _make_fake_response(html))

    calls = []

    def _mock_run(cfg_, prompt):
        calls.append({"cfg": cfg_, "prompt": prompt})
        return "Nội dung chapter đã trích xuất."

    monkeypatch.setattr(openai_client, "run_chat", _mock_run)
    ch = Chapter(index=1, url="http://site.com/ch1", title_zh="Chương 1")
    result = c.fetch_chapter(ch)
    assert result == "Nội dung chapter đã trích xuất."
    assert len(calls) == 1


def test_ai_fallback_skipped_when_cli_not_configured(monkeypatch):
    from novel2epub.storage import Chapter

    html = "<html><body><p>nội dung</p></body></html>"
    cfg = CrawlConfig(
        toc_url="http://site.com/",
        content_selector=".nonexistent",
        ai_fallback=True,
        _openai_fallback=None,
    )
    c = HttpCrawler(cfg)
    monkeypatch.setattr(c._session, "get", lambda url, **kw: _make_fake_response(html))

    ch = Chapter(index=1, url="http://site.com/ch1", title_zh="Chương 1")
    result = c.fetch_chapter(ch)
    assert result == ""


def test_ai_fallback_skipped_when_primary_succeeds(monkeypatch):
    from novel2epub import openai_client
    from novel2epub.config import OpenAIConfig
    from novel2epub.storage import Chapter

    html = "<html><body><div id='content'><p>Nội dung chính.</p></div></body></html>"
    cfg = CrawlConfig(
        toc_url="http://site.com/",
        content_selector="#content",
        ai_fallback=True,
        ai_fallback_max_html=5000,
        _openai_fallback=OpenAIConfig(base_url="https://api.test/v1"),
    )
    c = HttpCrawler(cfg)
    monkeypatch.setattr(c._session, "get", lambda url, **kw: _make_fake_response(html))

    calls = []

    def _mock_run(cfg_, prompt):
        calls.append(prompt)
        return ""

    monkeypatch.setattr(openai_client, "run_chat", _mock_run)
    ch = Chapter(index=1, url="http://site.com/ch1", title_zh="Chương 1")
    result = c.fetch_chapter(ch)
    assert result == "Nội dung chính."
    assert len(calls) == 0  # fallback NOT called


def test_make_crawler_rejects_firecrawl_with_helpful_message():
    cfg = CrawlConfig(toc_url="http://x", engine="firecrawl")
    with pytest.raises(ValueError) as exc_info:
        make_crawler(cfg)
    msg = str(exc_info.value)
    assert "firecrawl" in msg
    assert "crawl4ai" in msg
    assert "remove api_key" in msg or "api_key" in msg
