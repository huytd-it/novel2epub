"""Test helper thuần của selector_ai (không đụng mạng/AI)."""
from novel2epub import selector_ai


TOC_HTML = """
<html><head>
  <title>Truyện Mẫu</title>
  <script>var x = 1;</script>
  <style>.a{color:red}</style>
  <meta property="og:title" content="Truyện Mẫu">
</head><body>
  <div id="info"><h1 class="book-title">Truyện Mẫu</h1><p class="author">Tác giả A</p></div>
  <div id="intro">Giới thiệu truyện mẫu rất hay.</div>
  <div class="book-img"><img src="/covers/123.jpg" alt="cover"></div>
  <div id="list">
    <a href="/book/12345/1.html">Chương 1</a>
    <a href="/book/12345/2.html">Chương 2</a>
    <a href="/book/12345/3.html">Chương 3</a>
  </div>
  <a href="/login">Đăng nhập</a>
  <a href="https://other.com/x/9.html">ngoài site</a>
  <a href="/book/12345/list_2.html">下一页</a>
</body></html>
"""

CHAPTER_HTML = """
<html><head><title>Chương 1</title><script>evil()</script></head><body>
  <h1>Chương 1 - Khởi đầu</h1>
  <div id="chaptercontent">
    <p>Nội dung đoạn một rất dài, mô tả bối cảnh truyện và nhân vật chính.</p>
    <p>Đoạn văn thứ hai tiếp nối câu chuyện với nhiều tình tiết hấp dẫn.</p>
    <p>Đoạn văn thứ ba kết thúc chương với cao trào đầu tiên.</p>
    <p>Đoạn văn thứ tư bổ sung thêm chi tiết để đủ độ dài heuristic.</p>
  </div>
  <a href="/book/12345/2.html">下一章</a>
  <a href="/book/12345/1.html">Mục lục</a>
</body></html>
"""


def test_guess_chapter_url_picks_same_host_numbered():
    hrefs = ["/login", "/book/12345/1.html", "https://other.com/9.html", "#top"]
    guessed = selector_ai.guess_chapter_url("https://site.test/book/12345/", hrefs)
    assert guessed == "https://site.test/book/12345/1.html"


def test_guess_chapter_url_none_when_no_candidate():
    hrefs = ["/login", "https://other.com/9.html"]
    assert selector_ai.guess_chapter_url("https://site.test/book/1/", hrefs) == ""


def test_collect_sample_links_same_host_with_digits_deduped():
    hrefs = [
        "/book/12345/1.html", "/book/12345/1.html", "/book/12345/2.html",
        "/about", "https://other.com/9.html",
    ]
    links = selector_ai.collect_sample_links("https://site.test/book/12345/", hrefs, limit=10)
    assert links == [
        "https://site.test/book/12345/1.html",
        "https://site.test/book/12345/2.html",
    ]


def test_collect_sample_links_limit():
    hrefs = [f"/c/{i}.html" for i in range(100)]
    links = selector_ai.collect_sample_links("https://s.test/c/", hrefs, limit=5)
    assert len(links) == 5


# ── validate_pattern ────────────────────────────────────────────────

def test_validate_pattern_counts_matches():
    links = ["https://s.test/b/1.html", "https://s.test/b/2.html", "https://s.test/about"]
    ok, hits = selector_ai.validate_pattern(r"/b/\d+\.html$", links)
    assert ok and hits == 2


def test_validate_pattern_invalid_regex():
    ok, hits = selector_ai.validate_pattern("[unclosed", ["x"])
    assert ok is False and hits == 0


def test_validate_pattern_empty_ok():
    ok, hits = selector_ai.validate_pattern("", ["x"])
    assert ok is True and hits == 0


# ── count_matches ───────────────────────────────────────────────────

def test_count_matches_basic():
    html = '<div id="a"><p>hi</p><p>hi2</p></div>'
    assert selector_ai.count_matches(html, "#a") == 1
    assert selector_ai.count_matches(html, "p") == 2
    assert selector_ai.count_matches(html, ".missing") == 0


def test_count_matches_invalid_selector_returns_minus_one():
    html = "<div></div>"
    assert selector_ai.count_matches(html, ":::bad") == -1


def test_count_matches_empty_inputs():
    assert selector_ai.count_matches("", "div") == 0
    assert selector_ai.count_matches("<div></div>", "") == 0
    assert selector_ai.count_matches("", "") == 0


# ── finder heuristics ───────────────────────────────────────────────

def test_find_link_wrapper_candidates_finds_list():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(TOC_HTML, "html.parser")
    out = selector_ai.find_link_wrapper_candidates(soup)
    sels = [s for s, _ in out]
    # #list hoặc div#list phải có mặt — chứa 3 link chương
    assert any("list" in s for s in sels)
    assert any("3 link" in d for _, d in out)


def test_find_text_wrapper_candidates_finds_chaptercontent():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(CHAPTER_HTML, "html.parser")
    out = selector_ai.find_text_wrapper_candidates(soup)
    sels = [s for s, _ in out]
    assert any("chaptercontent" in s for s in sels)


def test_find_heading_candidates_finds_h1():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(TOC_HTML, "html.parser")
    out = selector_ai.find_heading_candidates(soup)
    assert len(out) >= 1
    assert any("Truyện Mẫu" in d for _, d in out)


def test_find_keyword_candidates_author():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(TOC_HTML, "html.parser")
    out = selector_ai.find_keyword_candidates(soup, ("author", "zuozhe"))
    assert any("author" in s.lower() for s, _ in out)


def test_find_image_candidates_cover():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(TOC_HTML, "html.parser")
    out = selector_ai.find_image_candidates(soup)
    assert any("img" in s for s, _ in out)


def test_find_next_link_candidates():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(CHAPTER_HTML, "html.parser")
    out = selector_ai.find_next_link_candidates(soup)
    assert len(out) >= 1
    assert any("下一章" in d for _, d in out)


def test_find_next_link_none_when_no_keyword():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup('<html><body><a href="/x">Home</a></body></html>', "html.parser")
    assert selector_ai.find_next_link_candidates(soup) == []


# ── build_dom_digest ────────────────────────────────────────────────

def test_build_dom_digest_toc_produces_labels_and_strips_script():
    digest, label_map = selector_ai.build_dom_digest(TOC_HTML, selector_ai.TOC_FIELD_SPECS)
    # toc digest dùng TOC-field labels
    assert any(k.startswith("TOC-") for k in label_map)
    assert "var x = 1" not in digest
    # heading label cho title
    assert any(k.startswith("TITLE-") for k in label_map)


def test_build_dom_digest_chapter_produces_content_label():
    digest, label_map = selector_ai.build_dom_digest(CHAPTER_HTML, selector_ai.CHAPTER_FIELD_SPECS)
    assert any(k.startswith("CONTENT-") for k in label_map)
    assert "chaptercontent" in " ".join(label_map.values()).lower()


def test_build_dom_digest_empty_html():
    digest, label_map = selector_ai.build_dom_digest("", selector_ai.TOC_FIELD_SPECS)
    assert label_map == {}
    assert "trống" in digest


def test_build_dom_digest_respects_max_chars():
    big = TOC_HTML * 20
    digest, _ = selector_ai.build_dom_digest(big, selector_ai.TOC_FIELD_SPECS, max_chars=50)
    assert len(digest) <= 50


def test_build_dom_digest_no_candidates():
    html = "<html><body><p>hello</p></body></html>"
    digest, label_map = selector_ai.build_dom_digest(html, selector_ai.TOC_FIELD_SPECS)
    # Không có link-wrapper vì <3 link → TOC- labels vắng, nhưng vẫn có thể có logic khác?
    # Chỉ kiểm tra không crash và label_map subset
    assert isinstance(label_map, dict)


# ── build_suggest_prompt / parse_suggestion ─────────────────────────

def test_build_suggest_prompt_includes_digests_and_links():
    prompt = selector_ai.build_suggest_prompt(
        toc_url="https://s.test/b/1/",
        chapter_url="https://s.test/b/1/1.html",
        toc_digest="[TOC-1] div#list — 3 link",
        chapter_digest="[CONTENT-1] div#chaptercontent — 400 ký tự",
        sample_links=["https://s.test/b/1/1.html"],
    )
    assert "https://s.test/b/1/1.html" in prompt
    assert "[TOC-1]" in prompt
    assert "[CONTENT-1]" in prompt
    assert "chapter_link_pattern" in prompt


def test_parse_suggestion_resolves_labels_and_keeps_regex():
    label_map = {"TOC-1": "div#list", "CONTENT-1": "div#chaptercontent", "TITLE-1": "h1.book-title"}
    raw = '{"toc_selector": "TOC-1", "content_selector": "CONTENT-1", "title_selector": "TITLE-1", "chapter_link_pattern": "/\\\\d+\\\\.html$"}'
    out = selector_ai.parse_suggestion(raw, label_map)
    assert out["toc_selector"] == "div#list"
    assert out["content_selector"] == "div#chaptercontent"
    assert out["title_selector"] == "h1.book-title"
    assert out["chapter_link_pattern"] == r"/\d+\.html$"
    assert set(out) == set(selector_ai.SELECTOR_FIELDS)


def test_parse_suggestion_unknown_label_becomes_empty():
    label_map = {"TOC-1": "div#list"}
    raw = '{"toc_selector": "TOC-99", "content_selector": "CONTENT-1"}'
    out = selector_ai.parse_suggestion(raw, label_map)
    assert out["toc_selector"] == ""
    assert out["content_selector"] == ""


def test_parse_suggestion_strips_code_fence():
    label_map = {"TOC-1": "div#list"}
    raw = '```json\n{"toc_selector": "TOC-1"}\n```'
    out = selector_ai.parse_suggestion(raw, label_map)
    assert out["toc_selector"] == "div#list"


def test_parse_suggestion_rejects_non_json():
    import pytest

    with pytest.raises(ValueError):
        selector_ai.parse_suggestion("không có json ở đây", {})


def test_parse_suggestion_only_whitelisted_keys():
    raw = '{"toc_selector": "TOC-1", "evil": "drop"}'
    out = selector_ai.parse_suggestion(raw, {"TOC-1": "div#list"})
    assert "evil" not in out
    assert set(out) == set(selector_ai.SELECTOR_FIELDS)
