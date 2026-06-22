# Data Model: OpenCode Go Preset

## Entities

### GoPreset

A static bundle of default configuration values loaded when `translate.preset: go` is set.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | `"go"` | Preset identifier |
| `cli.command` | `str` | `"opencode run"` | CLI command for OpenCode Go |
| `cli.model` | `str` | `"opencode-go/deepseek-v4-flash"` | Default Go model (cost-efficient) |
| `cli.prompt_template` | `str` | Go-optimized chapter prompt | Prompt for full chapter translation |
| `cli.title_prompt_template` | `str` | Go-optimized title prompt | Prompt for title translation |
| `cli.timeout_seconds` | `int` | `300` | Max seconds per CLI call |
| `cli.mode` | `str` | `"stdin"` | Input mode (always stdin for Go) |

**Relationships**:
- A `GoPreset` produces a dict of `CliTranslatorConfig` overrides.
- The preset is resolved at config load time and merged into `TranslateConfig.cli`.

### TranslateConfig (extended)

Add one optional field:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `preset` | `str` | `""` | Named preset to activate (`"go"` or empty) |

**Validation Rules**:
- If `preset` is set to an unknown name, `load_config()` raises `ValueError`.
- If `preset` is set, the corresponding preset module must exist.
- User-specified fields under `translate.cli.*` always override preset defaults.

### CrawlConfig (extended, P3 only)

Add one optional field:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `ai_fallback` | `bool` | `False` | Enable AI-powered content extraction fallback |
| `ai_fallback_max_html` | `int` | `32000` | Max HTML chars sent to the AI model |

**Validation Rules**:
- `ai_fallback` requires `translate.preset: go` to be active (reuses Go CLI config).
- If `ai_fallback` is true but no Go CLI backend is available, fallback is silently skipped.

## Preset Resolution Flow

```
User YAML config
  → parse translate.preset = "go"
  → load presets/go.py → get default CliTranslatorConfig dict
  → apply user's translate.cli.* fields on top (user wins)
  → construct final TranslateConfig
  → use as normal
```

## State Transitions

Preset loading is stateless and idempotent — it runs once at config load time and produces the same result for the same inputs.
