<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan:
specs/001-refactor-toc/plan.md
<!-- SPECKIT END -->

## Crawl4AI

Crawl4AI 0.9.0 đã cài và hoạt động trên Windows.
Crawl engines available: `http`, `crawl4ai`, `firecrawl`.

Khi dùng `engine: crawl4ai`, tham số `magic` phải được đặt trong `CrawlerRunConfig`
(không truyền như kwarg riêng của `arun`) — xem `Crawl4AICrawler._run_cfg` trong
`novel2epub/crawler.py`.

## Source presets

Config riêng theo website được lưu ở `novel2epub/sources.yaml`.
Load bằng `novel2epub.sources.load_presets()`.

## Test commands

```sh
pytest tests/ -v
pytest tests/test_crawler_meta.py -v
```

## Các nguồn đã test cho 赤心巡天 (情何以甚)

| Source | URL | Engine | Status |
|--------|-----|--------|--------|
| sto9 (思兔) | https://sto9.com/book/3352/index.html | crawl4ai | ✓ |
| aixdzs (爱下电子书) | https://www.aixdzs.com/novel/赤心巡天/ | http | ✓ |
| qidian (起点) | https://www.qidian.com/book/1016530091/ | crawl4ai | untested |
| 69shuba | https://www.69shuba.com/book/51265/ | crawl4ai | JS chapter list, needs more testing |
| shuqi (书旗) | https://www.shuqi.com/book/9162887.html | crawl4ai | SPA, needs more testing |
