# Quickstart: OpenCode Go Preset Validation

## Prerequisites

- Python 3.10+
- `opencode` CLI installed and authenticated with a Go subscription
- novel2epub cloned and `pip install -r requirements.txt` done
- A test novel config file (e.g., `tests/fixtures/go-test.yaml`)

## Test 1: Preset activates with minimal config

**Setup**:
```yaml
# tests/fixtures/go-test.yaml
novel:
  title: "Test"
  slug: "test-go"
crawl:
  toc_url: "https://example.com/toc"
  engine: http
translate:
  preset: go
output:
  data_dir: tests/fixtures/data
```

**Run**:
```bash
pytest tests/test_config.py -k "test_go_preset_resolution" -v
```

**Expected**: `load_config("go-test.yaml").translate.cli.command == "opencode run"`

---

## Test 2: User field overrides preset

**Setup**: Same config but with:
```yaml
translate:
  preset: go
  cli:
    model: opencode-go/qwen3.7-plus
    timeout_seconds: 600
```

**Run**:
```bash
pytest tests/test_config.py -k "test_go_preset_override" -v
```

**Expected**: `cfg.translate.cli.model == "opencode-go/qwen3.7-plus"`, `cfg.translate.cli.timeout_seconds == 600`, and `cfg.translate.cli.command == "opencode run"` (preserved from preset).

---

## Test 3: Unknown preset raises error

**Setup**:
```yaml
translate:
  preset: nonexistent
```

**Run**:
```bash
pytest tests/test_config.py -k "test_unknown_preset_raises" -v
```

**Expected**: `ValueError` with message containing "unknown" and listing available presets.

---

## Test 4: End-to-end chapter title translation (mock CLI)

**Run**:
```bash
pytest tests/test_translator.py -k "test_go_preset_title_translation" -v
```

**Expected**: A mocked `opencode run` subprocess receives the Go-optimized title prompt and returns a properly formatted Vietnamese title.

---

## Test 5: End-to-end chapter translation (mock CLI)

**Run**:
```bash
pytest tests/test_translator.py -k "test_go_preset_chapter_translation" -v
```

**Expected**: A mocked `opencode run` subprocess receives the Go-optimized chapter prompt with glossary, returns translated text, and the glossary is applied to the output.

---

## Test 6: AI fallback crawling (P3, optional)

**Setup**:
```yaml
crawl:
  toc_url: "https://example.com/difficult-page"
  engine: http
  content_selector: ".nonexistent"  # will produce empty content
  ai_fallback: true
translate:
  preset: go
```

**Run**:
```bash
pytest tests/test_crawler_meta.py -k "test_ai_fallback_extraction" -v
```

**Expected**: When `HttpCrawler.fetch_chapter()` returns empty content, the AI fallback is triggered, calls `cli_runner.run_cli()` with the page HTML, and returns the model's extracted text.

---

## Manual Validation

1. Create a real config for a known novel with `translate.preset: go`
2. Run `novel2epub fetch-toc <config>` to verify TOC loads normally
3. Run `novel2epub translate-meta <config>` to verify metadata is translated via Go
4. Run `novel2epub translate <config>` to verify chapter translation works
5. Run `novel2epub build <config>` to verify EPUB generation
6. Open the EPUB and verify Vietnamese titles, author, and chapter content
