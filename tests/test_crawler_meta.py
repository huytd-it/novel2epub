from bs4 import BeautifulSoup

from novel2epub.config import CrawlConfig
from novel2epub.crawler import HttpCrawler, _meta_get


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
