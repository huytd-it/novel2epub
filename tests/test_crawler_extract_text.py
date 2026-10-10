"""Trích chính văn khi site trộn hai kiểu markup giữa các trang con.

Bug thật (m.kudushu.org): trang ĐẦU của mỗi chương để chính văn là text trần
cạnh ``<br>``, các ``<p>`` duy nhất trong khối nội dung là thanh điều hướng.
`_extract_text` cũ "có <p> thì chỉ lấy <p>" nên trả về mấy nhãn nút bấm và
vứt toàn bộ chính văn; trang 2 trở đi bọc ``<p>`` nên vẫn đúng — khiến chương
nào cũng mất đúng trang đầu.
"""
from __future__ import annotations

import pytest

from novel2epub.config import CrawlConfig, ScraplingConfig
from novel2epub.crawler import (
    ChapterPageError,
    RateLimitError,
    ScraplingCrawler,
    _chapter_base_id,
    _crosses_chapter_boundary,
    _make_css_resolver,
    _next_page_url_from_pattern,
    fetch_chapter_paginated,
)
from novel2epub.storage import Chapter

pytest.importorskip("scrapling.fetchers")

from scrapling.parser import Selector  # noqa: E402

NAV = (
    '<p class="p1"><a href="/html/9/100/">Chuong truoc</a></p>'
    '<p class="p2"><a href="/book/9/">Muc luc</a></p>'
    '<p class="p1 p3"><a href="{next}">Trang sau</a></p>'
)

# Trang đầu: chính văn là text TRẦN, chỉ có <p> điều hướng.
PAGE_BARE = (
    '<html><body><div id="novelcontent" class="novelcontent">'
    "<p></p>"
    "Doan mot cua trang dau.<br><br>"
    "Doan hai cua trang dau.<br><br>"
    + NAV.format(next="/html/9/101_2/")
    + "</div></body></html>"
)

# Trang 2: chính văn được bọc <p>, vẫn kèm thanh điều hướng.
PAGE_WRAPPED = (
    '<html><body><div id="novelcontent" class="novelcontent">'
    "<p>Doan mot cua trang hai.<br><br>Doan hai cua trang hai.</p>"
    + NAV.format(next="/html/9/101_3/")
    + "</div></body></html>"
)


def _page(html: str, url: str = "https://m.example.org/html/9/101/") -> Selector:
    return Selector(content=html.encode("utf-8"), url=url, encoding="utf-8")


def _crawler(**kwargs) -> ScraplingCrawler:
    cfg = CrawlConfig(
        toc_url="https://m.example.org/book/9/",
        content_selector=".novelcontent",
        scrapling=ScraplingConfig(mode="fetcher"),
        **kwargs,
    )
    return ScraplingCrawler(cfg)


class TestExtractTextBareContent:
    def test_bare_text_survives_nav_paragraphs(self):
        """Chính văn text trần không bị mấy <p> điều hướng che mất."""
        text = _crawler()._extract_text(_page(PAGE_BARE))
        assert "Doan mot cua trang dau." in text
        assert "Doan hai cua trang dau." in text

    def test_nav_labels_never_reach_content(self):
        """Nhãn nút điều hướng không được lẫn vào chính văn — ở CẢ hai kiểu."""
        crawler = _crawler()
        for html in (PAGE_BARE, PAGE_WRAPPED):
            text = crawler._extract_text(_page(html))
            assert "Chuong truoc" not in text
            assert "Muc luc" not in text
            assert "Trang sau" not in text

    def test_br_separates_paragraphs(self):
        """<br><br> thành ranh giới đoạn (dòng trắng), không dính liền nhau."""
        text = _crawler()._extract_text(_page(PAGE_BARE))
        assert "Doan mot cua trang dau.\n\nDoan hai cua trang dau." in text

    def test_wrapped_page_still_uses_paragraph_mode(self):
        """Trang bọc <p> giữ nguyên hành vi cũ (trừ phần điều hướng)."""
        text = _crawler()._extract_text(_page(PAGE_WRAPPED))
        assert "Doan mot cua trang hai." in text
        assert "Doan hai cua trang hai." in text

    def test_two_page_shapes_are_not_confused_as_duplicates(self):
        """Hai trang khác nhau phải cho text khác nhau.

        Trước fix, MỌI trang đầu chương đều trả cùng chuỗi nhãn điều hướng nên
        trang đầu chương kế tiếp bị chấm là 'nội dung trùng lặp'.
        """
        crawler = _crawler()
        assert crawler._extract_text(_page(PAGE_BARE)) != crawler._extract_text(
            _page(PAGE_WRAPPED)
        )

    def test_plain_paragraph_site_unchanged(self):
        """Site <p> thuần: vẫn tách đoạn bằng dòng trắng như trước."""
        html = (
            '<html><body><div class="novelcontent">'
            "<p>Doan A.</p><p>Doan B.</p><p>Doan C.</p>"
            "</div></body></html>"
        )
        assert _crawler()._extract_text(_page(html)) == "Doan A.\n\nDoan B.\n\nDoan C."

    def test_inline_tags_do_not_split_a_paragraph(self):
        """Thẻ inline (<b>, <em>) KHÔNG được cắt đoạn — chỉ <br>/thẻ khối mới."""
        html = (
            '<html><body><div class="novelcontent">'
            "Mot <b>hai</b> ba.<br><br>Doan sau."
            "</div></body></html>"
        )
        text = _crawler()._extract_text(_page(html))
        assert "Mot hai ba." in text
        assert text.count("\n\n") == 1

    def test_stray_text_does_not_flip_a_paragraph_site(self):
        """Vài dòng text lạc ngoài <p> KHÔNG được kéo site <p> sang nhánh text trần.

        Đo trên nguồn thật: site kiểu <p> phủ ~100% nội dung, còn site text trần
        phủ 0% — ngưỡng 50% nằm giữa hai cực nên không bị lung lay. Test này giữ
        khoảng cách đó.
        """
        html = (
            '<html><body><div class="novelcontent">'
            "<p>Doan dai thu nhat, nhieu chu.</p>"
            "<p>Doan dai thu hai, cung nhieu chu.</p>"
            "<p>Doan dai thu ba, van nhieu chu.</p>"
            "lac mot mau text tran"
            "</div></body></html>"
        )
        text = _crawler()._extract_text(_page(html))
        assert text == (
            "Doan dai thu nhat, nhieu chu.\n\n"
            "Doan dai thu hai, cung nhieu chu.\n\n"
            "Doan dai thu ba, van nhieu chu."
        )

    def test_inline_siblings_stay_on_one_line(self):
        """Hai <span> cạnh nhau trong cùng khối = MỘT dòng.

        Khác bản cũ (mỗi text node một dòng). Giữ có chủ đích: đây mới là cách
        hiểu đúng thẻ inline. Đổi lại, dòng header kiểu "ngày + tác giả" của
        69shuba giờ gộp làm một — `strip_patterns` neo theo dòng cần khớp lại.
        """
        html = (
            '<html><body><div class="novelcontent">'
            '<div class="info"><span>2020-11-03</span> <span>tac gia: X</span></div>'
            "Chinh van.<br><br>"
            "</div></body></html>"
        )
        lines = [ln for ln in _crawler()._extract_text(_page(html)).splitlines() if ln.strip()]
        assert lines[0] == "2020-11-03 tac gia: X"

    def test_strip_patterns_still_apply(self):
        """`strip_patterns` vẫn lọc được rác của nhánh text trần (vd watermark)."""
        html = (
            '<html><body><div class="novelcontent">'
            '<div id="content_tip"><b>moi nhat: example.org</b></div>'
            "Chinh van.<br><br>"
            "</div></body></html>"
        )
        crawler = _crawler(strip_patterns=[r"moi nhat"])
        text = crawler._extract_text(_page(html))
        assert "example.org" not in text
        assert "Chinh van." in text


class TestChapterBaseId:
    @pytest.mark.parametrize(
        "url,expected",
        [
            # dạng cũ — có đuôi file
            ("https://e.org/book/9/101.html", "101"),
            ("https://e.org/book/9/101_2.html", "101"),
            ("https://e.org/book/9/101-2.html", "101"),
            # dạng mới — site mobile, không đuôi file
            ("https://m.e.org/html/9/101/", "101"),
            ("https://m.e.org/html/9/101_2/", "101"),
            ("https://m.e.org/html/9/101_3/", "101"),
            ("https://m.e.org/html/9/102/", "102"),
            # không đủ tin cậy để so sánh
            ("https://e.org/book/9/chuong-mot", None),
        ],
    )
    def test_base_id(self, url, expected):
        assert _chapter_base_id(url) == expected

    def test_next_chapter_url_crosses_boundary(self):
        """URL không đuôi file: chương kế tiếp phải bị nhận ra là ranh giới.

        Trước fix, `_chapter_base_id` đòi có đuôi file nên trả None với URL
        kiểu `.../101/` ⇒ chốt chặn tê liệt ⇒ crawler nuốt luôn chương sau.
        """
        base = _chapter_base_id("https://m.e.org/html/9/101/")
        assert _crosses_chapter_boundary(base, "https://m.e.org/html/9/102/") is True
        assert _crosses_chapter_boundary(base, "https://m.e.org/html/9/101_2/") is False


class TestPaginationStopsAtChapterBoundary:
    def test_bare_first_page_then_stops_before_next_chapter(self):
        """Chạy trọn vòng phân trang trên đúng hình dạng DOM của bug."""
        pages = {
            "https://m.example.org/html/9/101/": PAGE_BARE,
            "https://m.example.org/html/9/101_2/": PAGE_WRAPPED,
            "https://m.example.org/html/9/101_3/": (
                '<html><body><div class="novelcontent">'
                "<p>Doan cuoi chuong.</p>"
                + NAV.format(next="/html/9/102/")  # nút đổi thành "chương sau"
                + "</div></body></html>"
            ),
            # chương KẾ TIẾP — không được lọt vào nội dung chương này
            "https://m.example.org/html/9/102/": (
                '<html><body><div class="novelcontent">'
                "Chuong sau khong duoc gop vao.<br><br>"
                + NAV.format(next="/html/9/102_2/")
                + "</div></body></html>"
            ),
        }
        fetched: list[str] = []

        cfg = CrawlConfig(
            toc_url="https://m.example.org/book/9/",
            content_selector=".novelcontent",
            next_page_selector="p.p1.p3 > a",
            max_pages_per_chapter=10,
            scrapling=ScraplingConfig(mode="fetcher"),
        )
        crawler = ScraplingCrawler(cfg)
        resolver = _make_css_resolver(cfg)

        def fetch_page(url: str):
            fetched.append(url)
            return _page(pages[url], url=url)

        text, count = fetch_chapter_paginated(
            cfg,
            Chapter(index=3, url="https://m.example.org/html/9/101/", title="Chuong 3"),
            fetch_page=fetch_page,
            extract_text=crawler._extract_text,
            next_page_url=resolver,
        )

        assert count == 3
        assert "https://m.example.org/html/9/102/" not in fetched
        assert "Chuong sau khong duoc gop vao" not in text
        # cả 3 trang con đều có mặt, trang đầu KHÔNG còn bị mất
        assert "Doan mot cua trang dau." in text
        assert "Doan mot cua trang hai." in text
        assert "Doan cuoi chuong." in text


class TestPaginationPageErrorGuard:
    """Guard bắt buộc: lỗi ở một trang con ⇒ cả chương thất bại, không trả
    phần đã tải (pipeline sẽ không ghi raw cụt vào DB)."""

    URL = "https://m.example.org/html/9/101/"

    def _run(self, pages: dict, *, next_page_url=None, **cfg_kwargs):
        cfg = CrawlConfig(
            toc_url="https://m.example.org/book/9/",
            content_selector=".novelcontent",
            max_pages_per_chapter=10,
            scrapling=ScraplingConfig(mode="fetcher"),
            **cfg_kwargs,
        )
        crawler = ScraplingCrawler(cfg)

        def fetch_page(url: str):
            page = pages[url]
            if isinstance(page, Exception):
                raise page
            return _page(page, url=url)

        return fetch_chapter_paginated(
            cfg,
            Chapter(index=3, url=self.URL, title="Chuong 3"),
            fetch_page=fetch_page,
            extract_text=crawler._extract_text,
            next_page_url=next_page_url or _make_css_resolver(cfg),
        )

    def test_fetch_error_on_later_page_fails_whole_chapter(self):
        pages = {
            self.URL: PAGE_BARE,
            "https://m.example.org/html/9/101_2/": TimeoutError("timed out"),
        }
        with pytest.raises(ChapterPageError, match="trang 2"):
            self._run(pages, next_page_selector="p.p1.p3 > a")

    def test_rate_limit_on_later_page_keeps_retry_after(self):
        pages = {
            self.URL: PAGE_BARE,
            "https://m.example.org/html/9/101_2/": RateLimitError("HTTP 429", retry_after=7),
        }
        with pytest.raises(RateLimitError) as err:
            self._run(pages, next_page_selector="p.p1.p3 > a")
        assert err.value.retry_after == 7

    def test_fetch_error_on_first_page_propagates(self):
        with pytest.raises(TimeoutError):
            self._run({self.URL: TimeoutError("timed out")}, next_page_selector="p.p1.p3 > a")

    def test_linked_page_without_content_fails_whole_chapter(self):
        pages = {
            self.URL: PAGE_BARE,
            "https://m.example.org/html/9/101_2/": "<html><body>Access denied</body></html>",
        }
        with pytest.raises(ChapterPageError, match="không có nội dung"):
            self._run(pages, next_page_selector="p.p1.p3 > a")

    def test_next_url_resolve_error_fails_whole_chapter(self):
        def broken(url, page_obj):
            raise ValueError("selector hỏng")

        with pytest.raises(ChapterPageError, match="không dò được trang kế"):
            self._run({self.URL: PAGE_BARE}, next_page_url=broken)

    def test_guessed_page_without_content_just_ends_chapter(self):
        """URL do pattern tự sinh không phải link thật: trang rỗng nghĩa là đã
        hết chương, không phải lỗi."""
        url = "https://m.example.org/html/9/101_1.html"
        body = '<html><body><div class="novelcontent"><p>{}</p></div></body></html>'
        pages = {
            url: body.format("Trang mot."),
            "https://m.example.org/html/9/101_2.html": body.format("Trang hai."),
            "https://m.example.org/html/9/101_3.html": "<html><body>404</body></html>",
        }
        cfg = CrawlConfig(
            toc_url="https://m.example.org/book/9/",
            content_selector=".novelcontent",
            next_page_url_pattern=r"_(\d+)\.html",
            scrapling=ScraplingConfig(mode="fetcher"),
        )
        text, count = fetch_chapter_paginated(
            cfg,
            Chapter(index=3, url=url, title="Chuong 3"),
            fetch_page=lambda u: _page(pages[u], url=u),
            extract_text=ScraplingCrawler(cfg)._extract_text,
            next_page_url=_next_page_url_from_pattern(cfg),
        )
        assert count == 2
        assert text == "Trang mot.\n\nTrang hai."
