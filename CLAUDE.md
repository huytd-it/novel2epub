<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan:
specs/002-opencode-go-preset/plan.md
<!-- SPECKIT END -->

# novel2epub

Crawl Chinese web novels → translate to Vietnamese → build EPUB.

## Pipeline

```
TOC fetch -> crawl raw/*.md -> translate -> translated/*.md -> build -> .epub
```

## Key Commands

```sh
python -m novel2epub crawl          # crawl chapters
python -m novel2epub translate      # translate crawled chapters
python -m novel2epub build          # build EPUB
python -m novel2epub run            # crawl + translate + build

uvicorn app.main:app --reload --port 8010   # Web UI
pytest tests/ -v                             # run tests
```

## Architecture

- `crawler.py` — 3 engines: `http` (requests+BS4), `crawl4ai` (Playwright), `firecrawl` (API)
- `translator.py` — 3 backends: `cli` (external AI), `google`, `none`
- `config.py` — YAML config with dataclass models, preset merging, validation
- `pipeline.py` — Orchestrates crawl → translate → build + AI actions (review/suggest/rewrite/evaluate)
- `epub_builder.py` — EPUB via ebooklib with glossary footnotes
- `cli.py` — Argparse CLI with subcommands, range selection, sort/filter/search
- `app/` — FastAPI web UI (Jinja2 templates)

## Technical Notes

- Crawl4AI 0.9.0: `magic` param goes inside `CrawlerRunConfig`, see `Crawl4AICrawler._run_cfg` in `crawler.py`
- Pagination: `crawl.next_page_selector` (CSS) or `crawl.next_page_url_pattern` (regex with 1 capture group)
- Translation presets: `translate.preset: go` activates Go-optimized prompts via `presets/go.py`
- Config: single file `novel2epub.yaml` (gitignored) with 3 blocks — `defaults` (shared base), `sources` (site presets), `ebooks` (per-ebook overrides). Effective ebook config = `deep_merge(defaults, ebooks[slug])`. Committed template: `novel2epub.example.yaml`. Run a given ebook via `-e <slug>` / web `resolved_cfg(slug)`.
- ENV override: `NOVEL2EPUB_FILE` (path to the unified file; falls back to `NOVEL2EPUB_CONFIG`)
- One-off migration from the old multi-file layout: `python scripts/migrate_to_single_yaml.py`

## Tech Stack

Python 3.10+, FastAPI, ebooklib, requests+BS4, crawl4ai, deep-translator, PyYAML+ruamel, pytest
