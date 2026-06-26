## Context

Hiện tại `novel2epub` có 3 crawl engine: `http` (requests+BS4), `crawl4ai` (Playwright), `scrapling` (stealth browser). Trong thực tế, Scrapling với 3 mode (`fetcher`/`stealthy`/`dynamic`) đã cover được mọi use case: HTTP nhẹ, stealth bypass Cloudflare, và full Playwright automation. HttpCrawler không vượt được chặn cơ bản, Crawl4AICrawler phụ thuộc Playwright riêng và có nhiều config trùng với Scrapling `dynamic` mode.

Config file `novel2epub.yaml` có nhiều field chỉ dùng cho engine cũ (`toc_selector`, `encoding`, `js_code`, `magic`, `stealth`, `user_agent`, `title_selector`, `author_selector`, `desc_selector`, `cover_selector`, `chapter_title_selector`) làm phức tạp cấu hình và gây nhầm lẫn.

## Goals / Non-Goals

**Goals:**
- Xoá sạch code `HttpCrawler` và `Crawl4AICrawler`
- Scrapling là engine duy nhất, mặc định `scrapling_mode: fetcher` (nhẹ, nhanh)
- Config gọn: Scrapling-specific fields gom vào block `crawl.scrapling:` riêng
- Loại bỏ toàn bộ dependency `requests`, `beautifulsoup4`, `crawl4ai`
- Viết lại README.md đơn giản, chỉ nói về Scrapling
- Hỗ trợ 3 mode: `fetcher` (default), `stealthy`, `dynamic`

**Non-Goals:**
- Không thay đổi pipeline translate/build
- Không thay đổi storage/glossary
- Không thay đổi Web UI ngoài việc ẩn field `engine` selector
- Không thêm crawl engine mới

## Decisions

1. **Scrapling mode mặc định: `fetcher` thay vì `stealthy`**
   - Lý do: Đa số site Trung Quốc chỉ chặn theo TLS fingerprint, không cần browser thật. `fetcher` nhanh hơn, nhẹ hơn, concurrency cao hơn. Người dùng vẫn có thể override thành `stealthy`/`dynamic` khi cần.
   - Config mới: `crawl.scrapling.mode` thay vì `crawl.scrapling_mode` (gọn hơn).

2. **Gom Scrapling config vào block riêng: `crawl.scrapling:`**
   - Tránh lẫn với config chung.
   - Block mới: `mode`, `solve_cloudflare`, `network_idle`, `impersonate`.
   - Xoá field `scrapling_mode`, `solve_cloudflare`, `network_idle`, `impersonate` khỏi CrawlConfig top-level.

3. **Xoá toàn bộ field chỉ dùng cho http/crawl4ai khỏi CrawlConfig**
   - Xoá: `toc_selector`, `chapter_title_selector`, `title_selector`, `author_selector`, `desc_selector`, `cover_selector`, `encoding`, `user_agent`, `js_code`, `magic`, `stealth`.
   - Giữ: `content_selector` (dùng chung cho mọi mode Scrapling), `next_page_*`, `strip_patterns`, `delay_seconds`, `max_workers`, `concurrency_cap`, `retry`.

4. **Xoá block `sources` khỏi config**
   - Vì chỉ còn 1 engine, không cần preset theo engine. Selector config được ghi trực tiếp trong `crawl:` của ebook hoặc `defaults:`.
   - Đơn giản hoá: người dùng chỉ cần chỉnh `content_selector` cho từng site.
   - Loại bỏ `novel2epub/sources.py` nếu không còn code nào khác dùng.

5. **Xoá `sources.py` module + route `/sources` trên Web UI**
   - Vì source preset CRUD không còn cần thiết.
   - Trang `/sources` chuyển hướng về `/` hoặc hiển thị thông báo đã được đơn giản hoá.

## Risks / Trade-offs

- **[Risk] Người dùng từ http/crawl4ai sẽ fail config cũ** → Mitigation: `make_crawler` báo lỗi rõ ràng + migration guide trong README. Cập nhật `novel2epub.example.yaml`.
- **[Risk] Scrapling `fetcher` không xử lý được site có JS** → Mitigation: người dùng chuyển sang `stealthy` hoặc `dynamic`. 3 mode đã cover mọi mức độ.
- **[Trade-off] Mất tính năng `encoding` auto-detect của http engine** → Không cần: Scrapling tự động xử lý encoding qua HTTP headers.
- **[Risk] Test HttpCrawler và Crawl4AICrawler bị xoá** → Mitigation: test ScraplingCrawler hiện có, thêm test cho mode `fetcher` mặc định mới.
