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
  <div id="list">
    <a href="/book/12345/1.html">Chương 1</a>
    <a href="/book/12345/2.html">Chương 2</a>
    <a href="/book/12345/3.html">Chương 3</a>
  </div>
  <a href="/login">Đăng nhập</a>
  <a href="https://other.com/x/9.html">ngoài site</a>
</body></html>
"""


def test_clean_html_strips_scripts_and_truncates():
    out = selector_ai.clean_html_for_ai(TOC_HTML, max_chars=10_000)
    assert "var x = 1" not in out
    assert "color:red" not in out
    assert "book-title" in out  # giữ class để suy selector
    assert 'href="/book/12345/1.html"' in out


def test_clean_html_respects_max_chars():
    out = selector_ai.clean_html_for_ai(TOC_HTML, max_chars=50)
    assert len(out) <= 50


def test_clean_html_empty():
    assert selector_ai.clean_html_for_ai("") == ""


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


def test_parse_detection_plain_json():
    raw = '{"content_selector": "#content", "chapter_link_pattern": "/\\\\d+\\\\.html$"}'
    out = selector_ai.parse_detection(raw)
    assert out["content_selector"] == "#content"
    assert out["chapter_link_pattern"] == r"/\d+\.html$"
    # Field thiếu → ""
    assert out["title_selector"] == ""


def test_parse_detection_strips_code_fence_and_prose():
    raw = "Đây là kết quả:\n```json\n{\"content_selector\": \"#c\"}\n```\nHết."
    out = selector_ai.parse_detection(raw)
    assert out["content_selector"] == "#c"


def test_parse_detection_only_whitelisted_keys():
    raw = '{"content_selector": "#c", "evil": "drop", "notes": "x"}'
    out = selector_ai.parse_detection(raw)
    assert "evil" not in out and "notes" not in out
    assert set(out) == set(selector_ai.SELECTOR_FIELDS)


def test_parse_detection_rejects_non_json():
    import pytest

    with pytest.raises(ValueError):
        selector_ai.parse_detection("không có json ở đây")


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


def test_build_detect_prompt_includes_fields():
    prompt = selector_ai.build_detect_prompt(
        toc_url="https://s.test/b/1/",
        chapter_url="https://s.test/b/1/1.html",
        toc_html="<div id=list></div>",
        chapter_html="<div id=content></div>",
        sample_links=["https://s.test/b/1/1.html"],
    )
    assert "https://s.test/b/1/1.html" in prompt
    assert "content_selector" in prompt
    assert "id=list" in prompt
