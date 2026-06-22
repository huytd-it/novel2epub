# CLI Config Contract: Go Preset

## `config.yaml` Schema (affected fields)

```yaml
translate:
  # NEW: activate the Go preset
  preset: go

  # Existing fields — any of these override the preset defaults:
  cli:
    command: opencode run        # preset default
    model: opencode-go/deepseek-v4-flash  # preset default; override for better quality
    prompt_template: "..."       # preset default; override for custom prompt
    title_prompt_template: "..." # preset default; override for custom title prompt
    timeout_seconds: 300         # preset default
    mode: stdin                  # preset default

  # All other translate.* fields work identically to before:
  type: cli                       # fixed when preset is active
  style:
    tone: "mượt, tự nhiên, có chất cổ trang"
    # ...
  glossary:
    Vân: Mây
    # ...
  retry:
    attempts: 2
    delay_seconds: 2.0
```

## Preset Resolution Rules

1. **If `translate.preset` is absent or empty**: behavior is identical to current — no change.
2. **If `translate.preset: go`**: the Go preset module loads defaults, then user-specified `translate.cli.*` fields are applied on top.
3. **If `translate.preset` is an unknown value**: `load_config()` raises `ValueError` with a message listing available presets.
4. **If both `translate.preset` and explicit `translate.cli.command` are set**: the explicit command wins.
5. **If both `translate.preset` and `translate.type` are set**: `type` must be `"cli"` (preset implies CLI mode). If set to anything else, `load_config()` warns and ignores the preset.

## Example Configurations

### Minimal (preset handles everything)
```yaml
translate:
  preset: go
```

### Override model for quality
```yaml
translate:
  preset: go
  cli:
    model: opencode-go/qwen3.7-plus
```

### Full custom (preset ignored for CLI fields)
```yaml
translate:
  preset: go
  cli:
    command: opencode run
    model: opencode-go/qwen3.7-plus
    prompt_template: "Bạn là dịch giả..."
    timeout_seconds: 600
```

## Error Handling

| Scenario | Behavior |
|----------|----------|
| `opencode` CLI not found | `cli_runner.resolve_command()` raises `FileNotFoundError` with hint to install/authenticate |
| Unknown preset name | `ValueError` at config load: `"Unknown translate.preset: 'foo'. Available: go"` |
| Go subscription exhausted | OpenCode CLI prints rate-limit error to stderr; `cli_runner` raises `RuntimeError` |
| `translate.type != cli` with preset | Warning logged; preset fields are not applied |
