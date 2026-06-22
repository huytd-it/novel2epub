# Research: OpenCode Go Preset

**Phase 0** — Resolves unknowns and documents technology decisions.

## 1. Preset Resolution Mechanism

**Question**: How should preset values be loaded and merged with user config?

**Decision**: Use a dedicated `novel2epub/presets/` package. Each preset is a module exporting a `def load_preset(name: str) -> dict` function. The `go.py` module will return a dict of overrides for `CliTranslatorConfig` fields. In `load_config()`, after parsing the YAML, check for `translate.preset` — if set, look up the preset module, load its defaults, and apply user-provided fields on top (user wins).

**Rationale**: Keeps preset definitions isolated, testable, and extensible to future presets. Follows the existing pattern in `sources.py` where site-specific defaults are separated from user config.

**Alternatives considered**:
- Hardcoding in `config.py` — simple but tightly coupled; violates open/closed principle.
- YAML file per preset — more flexible but adds file-discovery complexity with no current need.

## 2. Go CLI Command Interface

**Question**: How does `opencode run` behave with `--model` and stdin?

**Decision**: `opencode run <prompt>` accepts prompt via stdin by default, which matches `cli_runner.py`'s existing `stdin` mode. The `--model` flag is supported: `opencode run --model opencode-go/qwen3.7-plus`. This works with `build_argv()` which appends `["--model", model]` to the command. No changes needed to `cli_runner.py`.

**Rationale**: Confirmed by OpenCode docs: Go uses model IDs like `opencode-go/<model-id>`. `opencode run` is the canonical command.

## 3. Default Go Model Selection

**Question**: Which Go model should be the preset default?

**Decision**: `opencode-go/deepseek-v4-flash` as the default. It offers:
- Cheapest model in the Go lineup ($0.14 input / $0.28 output per 1M tokens)
- Highest throughput (~31k requests per 5-hour window)
- Good coding task performance, sufficient for translation

**Rationale**: The preset should be cost-efficient and accessible. DeepSeek V4 Flash gives the most translations per dollar. Users who want higher quality can override with `translate.cli.model: opencode-go/qwen3.7-plus` or another model.

**Alternatives considered**:
- `opencode-go/qwen3.7-plus` — better quality but 3x the cost; good as an optional upgrade.

## 4. Go-Optimized Prompt Templates

**Question**: Do the existing Claude-optimized prompts (`DEFAULT_PROMPT`, `TITLE_PROMPT`) work well with open-weight models like DeepSeek and Qwen?

**Decision**: Ship shorter, more explicit Go-specific prompt templates that:
- Remove verbose multi-paragraph instructions (open models follow shorter commands better)
- Keep glossary and Hán Việt rules (these are non-negotiable per constitution)
- Add explicit output format constraints (open models over-explain more than Claude)
- Reduce total prompt length to stay within context window more efficiently

The existing Claude prompts remain as the global default. Go preset overrides them with Go-optimized versions.

## 5. AI Fallback Crawling (P3) Architecture

**Question**: How should `crawl.ai_fallback` integrate with the existing crawler?

**Decision**: Add an optional post-processing step in `HttpCrawler.fetch_chapter()` and `Crawl4AICrawler.fetch_chapter()`. After the primary extraction, if the result is empty/too short and `cfg.ai_fallback` is set, call `cli_runner.run_cli()` with a specialized HTML-extraction prompt. The extracted page HTML is sent as the prompt body (truncated to model context limit minus overhead). The Go model's response is used as the chapter text.

**Rationale**: Keeping fallback inside the crawler class avoids an extra abstraction layer. The existing `cli_runner` is reused, so no new subprocess infrastructure is needed. The feature is opt-in (P3) and experimental.

**Alternatives considered**:
- New `AIFallbackCrawler` wrapper — cleaner separation but adds complexity for an experimental feature.
- Web UI-level fallback — too far from the extraction point.

## 6. Preset Field Override Rules

**Question**: Which fields should the Go preset set, and how does user override work?

**Decision**: The Go preset defines these defaults:

| Field | Preset Value | Overridable |
|-------|-------------|-------------|
| `cli.command` | `opencode run` | Yes |
| `cli.model` | `opencode-go/deepseek-v4-flash` | Yes |
| `cli.prompt_template` | Go-optimized chapter prompt | Yes |
| `cli.title_prompt_template` | Go-optimized title prompt | Yes |
| `cli.timeout_seconds` | `300` | Yes |
| `cli.mode` | `stdin` | Yes (unlikely needed) |

Override rule: **user-specified fields win over preset values**. Implemented by loading the preset first into a dict, then applying user-provided translate.cli.* fields on top. This matches YAML inherit/merge patterns.
