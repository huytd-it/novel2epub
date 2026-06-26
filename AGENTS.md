<!-- CODEGRAPH_START -->
## CodeGraph

In repositories indexed by CodeGraph (a `.codegraph/` directory exists at the repo root), reach for it BEFORE grep/find or reading files when you need to understand or locate code:

- **MCP tools** (when available): `codegraph_explore` answers most code questions in one call — the relevant symbols' verbatim source plus the call paths between them. `codegraph_node` returns one symbol's source + callers, or reads a whole file with line numbers. If the tools are listed but deferred, load them by name via tool search.
- **Shell** (always works): `codegraph explore "<symbol names or question>"` and `codegraph node <symbol-or-file>` print the same output.

If there is no `.codegraph/` directory, skip CodeGraph entirely — indexing is the user's decision.
<!-- CODEGRAPH_END -->

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan:
specs/002-opencode-go-preset/plan.md
<!-- SPECKIT END -->

# novel2epub

Crawl Chinese web novels, translate to Vietnamese, and package into EPUB.

## Pipeline

```
TOC fetch -> crawl raw/*.md -> translate -> translated/*.md -> build -> .epub
```

Each step is cached on disk. Resume or re-run individual steps.

## Project Structure

```
novel2epub/
├── cli.py              # Argparse CLI (crawl/translate/meta/toc/build/run/list/...)
├── pipeline.py         # Pipeline orchestration
├── crawler.py          # 3 crawl engines: http, crawl4ai, scrapling
├── translator.py       # Translation backends: CLI (opencode), Google, noop
├── cli_runner.py       # Subprocess wrapper for AI CLI commands
├── config.py           # YAML config loading + dataclass models
├── config_writer.py    # Round-trip YAML writer
├── epub_builder.py     # EPUB packaging via ebooklib
├── footnotes.py        # Glossary footnote annotation engine
├── glossary_ai.py      # AI glossary suggestions + translation evaluation + rewrite
├── sources.py          # Site preset library CRUD + auto-detect
├── storage.py          # Disk-based manifest + chapter + glossary storage
├── toc.py              # Chapter table helpers (sort/filter/range/pagination)
└── presets/
    └── go.py           # OpenCode Go translation preset

app/
├── main.py             # FastAPI app (uvicorn app.main:app --port 8010)
├── deps.py             # Shared deps: config loading, template engine
├── job.py              # Background job runner
└── routes/             # ebooks, chapters, glossary, jobs, library, settings, sources
    └── templates/      # Jinja2 templates

novel2epub.yaml         # Single config file (gitignored): defaults + sources + ebooks
novel2epub.example.yaml # Committed template (copy → novel2epub.yaml)
```

## Crawl Engines

| Engine | Backend | When to use |
|--------|---------|-------------|
| `http` | requests + BeautifulSoup | Static HTML sites |
| `crawl4ai` | Playwright (browser) | JS-rendered sites, SPA |
| `scrapling` | Scrapling (stealth browser) | Anti-bot sites, Cloudflare bypass |

Crawl4AI 0.9.0 is installed. When using `engine: crawl4ai`, pass `magic` inside `CrawlerRunConfig`, not as a separate kwarg — see `Crawl4AICrawler._run_cfg` in `crawler.py`.

### Multi-page chapters (pagination)

Some sites split a chapter across multiple pages. Configure in `crawl:` section:

```yaml
crawl:
  next_page_selector: "a#pager_next"     # CSS selector for "next page" link
  next_page_url_pattern: "_(\d+)\.html$" # Regex fallback (exactly 1 capture group)
  max_pages_per_chapter: 10              # Safety limit
```

Auto-stops when: next link missing, URL visited, content unchanged, or limit reached.

## Translation Backends

| Type | Backend | Config Field |
|------|---------|-------------|
| `moxhimt` | Local NMT model (CTranslate2, offline, **default**) | `translate.moxhimt.*` |
| `openai` | OpenAI-Compatible HTTP (OpenAI, Ollama, LM Studio...) | `translate.openai.*` |
| `google` | deep-translator (Google Translate) | `translate.type: google` |
| `none` | Passthrough (noop) | `translate.type: none` |

The `translate.preset: go` activates OpenCode Go-optimized prompts and model defaults via `presets/go.py`.

## Source Presets

Site-specific crawl presets live in the `sources:` block of `novel2epub.yaml`. Load with `sources.load_presets()`. Auto-detect by domain with `sources.detect_preset(url)`.

## Commands

```sh
# CLI
python -m novel2epub crawl
python -m novel2epub translate
python -m novel2epub build
python -m novel2epub run                 # crawl + translate + build

# Web UI
uvicorn app.main:app --reload --port 8010

# Tests
pytest tests/ -v
pytest tests/test_crawler_meta.py -v
```

## Config File (single, unified)

`novel2epub.yaml` (gitignored) holds everything in 3 top-level blocks:

- `defaults` — shared base: crawl/translate/output defaults + prompt templates.
- `sources` — reusable crawl presets per website.
- `ebooks` — one entry per ebook holding ONLY the fields that differ from `defaults`
  (`name`, `novel`, plus crawl/translate/output overrides).

Effective config for an ebook = `deep_merge(defaults, ebooks[slug])`, resolved by
`load_config(path, slug)`. `novel2epub.example.yaml` is the committed template.
Migrate from the old multi-file layout: `python scripts/migrate_to_single_yaml.py`.

## Key Environment Variables

- `NOVEL2EPUB_FILE` — Override the unified config path (falls back to `NOVEL2EPUB_CONFIG`)

## Tech Stack

- Python 3.10+
- FastAPI + Jinja2 (Web UI)
- ebooklib (EPUB generation)
- requests + BeautifulSoup (HTTP crawl)
- crawl4ai (Playwright-based browser crawl)
- scrapling (stealth browser crawl, anti-bot bypass)
- deep-translator (Google Translate)
- PyYAML + ruamel.yaml (config)
- pytest (testing)

## Tested Sources (赤心巡天)

| Source | URL | Engine |
|--------|-----|--------|
| sto9 | https://sto9.com/book/3352/index.html | crawl4ai |
| aixdzs | https://www.aixdzs.com/novel/赤心巡天/ | http |
| qidian | https://www.qidian.com/book/1016530091/ | crawl4ai |
| 69shuba | https://www.69shuba.com/book/51265/ | crawl4ai |
| shuqi | https://www.shuqi.com/book/9162887.html | crawl4ai |
