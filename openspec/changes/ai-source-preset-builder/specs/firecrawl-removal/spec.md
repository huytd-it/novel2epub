## REMOVED Requirements

### Requirement: `firecrawl` engine in `make_crawler`
**Reason**: `firecrawl-py` is a paid third-party dependency (requires an API key from Firecrawl) and the project already covers the same use-cases with the free `http` and `crawl4ai` engines. Keeping the third engine complicates the configuration surface, the Web UI, and the preset library without delivering value to the in-repo flows.

**Migration**: In `configs/*.yaml` and any preset row in `sources.yaml` that uses `engine: firecrawl`, change the value to `engine: crawl4ai` (default for JS-heavy sites) or `engine: http` (for static HTML sites). Remove the `api_key` line — the `api_key` and `api_url` fields are dropped from `CrawlConfig`. If a host absolutely needs a remote Markdown service, the user can self-host Crawl4AI or fall back to the in-process `crawl4ai` engine.

### Requirement: `CrawlConfig.api_key` and `CrawlConfig.api_url`
**Reason**: These two fields exist exclusively to configure the Firecrawl client (`FirecrawlApp(api_key=..., api_url=...)`). With the engine gone, the fields are dead weight and risk being mistaken for general-purpose credentials.

**Migration**: Remove the two lines from any `configs/*.yaml` that declares them. The preset builder and the Web UI no longer read them, and the YAML loader silently drops unknown keys.

### Requirement: `firecrawl` option in the Web UI engine `<select>`
**Reason**: The `<option value="firecrawl">` entries in `app/templates/sources.html`, `app/templates/library.html`, and `app/templates/settings.html` reference an engine that no longer exists, and would let the user pick an invalid value at form time.

**Migration**: Users who were selecting `firecrawl` from the engine dropdown should pick `crawl4ai` instead. The form simply no longer offers the removed option.

### Requirement: `firecrawl` references in docs and AGENTS.md
**Reason**: The `README.md` install instructions and the `AGENTS.md` "engines available" table list `firecrawl` / `firecrawl-py`, which would mislead new contributors into installing a paid dependency that the codebase no longer uses.

**Migration**: No code action required; the docs are updated in this change. New contributors install only `requests beautifulsoup4` (for the `http` engine) and `crawl4ai` (for the `crawl4ai` engine), as already documented elsewhere.

## ADDED Requirements

### Requirement: `make_crawler` only supports `http` and `crawl4ai`
The `make_crawler(cfg)` factory in `novel2epub/crawler.py` SHALL return either `HttpCrawler` (when `cfg.engine == "http"`) or `Crawl4AICrawler` (when `cfg.engine == "crawl4ai"`). Any other value of `cfg.engine` SHALL raise `ValueError` with a message that lists the valid engines and points to the dropped `firecrawl` migration note in `README.md`.

#### Scenario: http engine
- **WHEN** `cfg.engine == "http"`
- **THEN** `make_crawler(cfg)` returns an `HttpCrawler` instance.

#### Scenario: crawl4ai engine
- **WHEN** `cfg.engine == "crawl4ai"`
- **THEN** `make_crawler(cfg)` returns a `Crawl4AICrawler` instance.

#### Scenario: legacy firecrawl engine value
- **WHEN** `cfg.engine == "firecrawl"`
- **THEN** `make_crawler(cfg)` raises `ValueError` whose message includes the literal string `"firecrawl"`, the valid engines list, and a one-line migration hint such as "set engine: crawl4ai (or http) and remove api_key".

### Requirement: `CrawlConfig` no longer carries `api_key` / `api_url`
The `CrawlConfig` dataclass in `novel2epub/config.py` SHALL drop the `api_key: str` and `api_url: str | None` fields, and `load_config` SHALL NOT read the `FIRECRAWL_API_KEY` environment variable. Any `api_key` / `api_url` keys that still appear in user YAML SHALL be ignored silently (round-trip loss is acceptable; no exception is raised).

#### Scenario: YAML with stale api_key
- **WHEN** a user has `crawl:\n  api_key: "fc-..."` in `configs/foo.yaml`
- **THEN** `load_config("configs/foo.yaml")` succeeds, the returned `Config.crawl` has no `api_key` attribute, and the file is re-saved without that key (or, if round-trip is required, the loader logs a one-line `crawl.api_key ignored (firecrawl engine removed)` and keeps the key untouched in YAML).

#### Scenario: FIRECRAWL_API_KEY env var set
- **WHEN** the env var `FIRECRAWL_API_KEY` is set
- **THEN** `load_config` does not propagate it to `CrawlConfig` (no error), and no log entry references Firecrawl.

### Requirement: `FirecrawlCrawler` class is removed
The class `FirecrawlCrawler` and any helper function used only by it (e.g. `_scrape`, `_meta_get` if the latter has no other caller) SHALL be removed from `novel2epub/crawler.py`. No `import firecrawl` statement SHALL remain in the codebase.

#### Scenario: grep for firecrawl
- **WHEN** `grep -R "firecrawl" novel2epub/` is run after the change
- **THEN** zero matches are produced (the removed comments and the dropped dependency are gone).
