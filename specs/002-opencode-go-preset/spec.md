# Feature Specification: OpenCode Go Translation & AI Preset

**Feature Branch**: `002-opencode-go-preset`

**Created**: 2026-06-22

**Status**: Draft

**Input**: User description: "làm một preset để dịch, crawler dữ liệu dùng opencode Go"

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Translate chapters via OpenCode Go with one config change (P1)

A user who has an OpenCode Go subscription wants to translate Chinese web novel chapters into Vietnamese using Go's curated open coding models (Qwen, DeepSeek, MiniMax, etc.). They should be able to add a short preset reference (e.g. `translate: go`) in their ebook config or `config.yaml` and immediately get chapter and title translation working with sensible defaults — Go-compatible prompt templates, correct command, and a recommended cost-efficient model.

**Why this priority**: Translation is the core product value; making Go instantly usable removes friction for paying subscribers and is the primary reason for this feature.

**Independent Test**: Can be tested by setting up a minimal `config.yaml` with `translate.type: cli` pointing to Go and running a single-chapter translate on any crawled novel. The output must be readable Vietnamese with glossary applied.

**Acceptance Scenarios**:

1. **Given** a user has OpenCode Go CLI installed and authenticated, **When** they set `translate.preset: go` in their config, **Then** translation runs using `opencode run` as the command without additional CLI configuration.
2. **Given** a user sets `translate.preset: go` with an explicit `translate.cli.model`, **When** translation is invoked, **Then** the specified model is used (overriding the preset default).
3. **Given** a chapter with Chinese text is translated via the Go preset, **When** `translate_title()` is called for the chapter title, **Then** it returns a Vietnamese title in proper format.
4. **Given** a character/term exists in the glossary, **When** translation completes, **Then** the glossary term appears in the output as specified.

---

### User Story 2 — Use Go models for AI-assisted glossary suggestions and rewrites (P2)

A user who configures the Go preset should be able to reuse the same Go CLI config for auxiliary AI features: glossary suggestion from raw/translated pairs, chapter rewrite for fluency, and translation evaluation.

**Why this priority**: These features already exist and reuse the same `cli_runner` infrastructure; adding Go preset support is simply about making the preset apply to all CLI-based AI features, not just translation.

**Independent Test**: Run `suggest_glossary()` with a Go model; verify it returns glossary candidates in the expected format.

**Acceptance Scenarios**:

1. **Given** the Go preset is active, **When** `suggest_glossary()` is called, **Then** it uses the same Go CLI command and model as chapter translation.
2. **Given** the Go preset is active, **When** `rewrite_chapter()` is called, **Then** it rewrites the chapter using the Go model with the rewrite prompt template.

---

### User Story 3 — AI-powered fallback crawling via Go (P3)

When the configured crawler engine cannot extract chapter content (e.g. complex JS sites, anti-bot pages, or non-standard HTML), the user may optionally configure Go to act as an AI-powered extraction fallback — sending the page HTML to the Go model and asking it to extract clean chapter text.

**Why this priority**: This is exploratory and may depend on model context limits and cost considerations; it is the lowest priority.

**Independent Test**: Run a single-page crawl on a known difficult site with `crawl.ai_fallback: true` and verify the chapter text is extracted correctly.

**Acceptance Scenarios**:

1. **Given** a page with JS-rendered chapter content, **When** the primary crawler engine returns empty/no content and `crawl.ai_fallback` is enabled, **Then** the system sends the raw page HTML to the Go model and extracts chapter text from the response.
2. **Given** a page where the primary crawler succeeds, **When** `crawl.ai_fallback` is enabled, **Then** the AI fallback is NOT triggered (primary result is used).

---

### Edge Cases

- What happens when `opencode` CLI is not installed or not authenticated? The translator should raise a clear `FileNotFoundError` or a helpful message guiding the user to install/authenticate via `opencode auth`.
- What happens when the Go subscription has reached its usage limits? The user needs a fallback model or explicit error message suggesting they top up or switch models.
- How does the system handle a Go model that returns empty or malformed translation output? The existing retry logic in `TranslationRetryConfig` should apply.
- What if the user has `translate.preset: go` but also explicitly sets `translate.cli.command` to something else? Explicit fields should override the preset values.
- If AI fallback crawling is enabled, what happens when the Go model's context window is too small for the full page HTML? The system should truncate the HTML to the model's context limit or skip AI extraction with a warning.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST define a built-in Go preset (`go` or `opencode-go`) that sets `translate.cli.command` to `opencode run` and defaults to a cost-efficient recommended Go model.
- **FR-002**: The Go preset MUST be activatable via a single `translate.preset: go` field in YAML config, without requiring the user to specify CLI command, model, or prompt templates manually.
- **FR-003**: Any field explicitly set by the user under `translate.cli.*` MUST override the preset's default for that specific field (preset is a baseline, not a lock).
- **FR-004**: The Go preset MUST include appropriate default prompt templates optimized for open-weight coding models (Qwen, DeepSeek, etc.) — shorter, more direct instructions compared to Claude-specific prompts.
- **FR-005**: The preset's default model MUST be a cost-efficient, high-quality model from the Go lineup — e.g. `opencode-go/qwen3.7-plus` or `opencode-go/deepseek-v4-flash`.
- **FR-006**: The Go preset MUST apply consistently to the CLI translator, glossary AI suggestions, chapter rewrite, and translation evaluation features (all features that use `cli_runner`).
- **FR-007**: System MUST validate that `opencode` CLI binary is available and authenticated when the Go preset is active, providing a clear setup guide in the error message if not.
- **FR-008**: If `crawl.ai_fallback` is enabled with the Go preset, the system MUST attempt AI-powered content extraction only when the primary crawler yields empty/no content for a chapter page.
- **FR-009**: AI fallback crawl MUST include configurable max HTML length to respect the Go model's context window, defaulting to a safe value (e.g. 32000 characters).

### Key Entities

- **Go Preset**: A named set of default config values (`command`, `model`, `prompt_templates`) stored internally and referenced by `translate.preset: go` in YAML config.
- **Translation Config**: Existing `TranslateConfig` dataclass with an added optional `preset` field that triggers preset loading.
- **Config Loading**: The `load_config()` function in `config.py` must resolve presets before returning the final `TranslateConfig`.
- **AI Fallback Crawl Config**: Optional field `crawl.ai_fallback` that, when enabled, adds an AI-powered extraction step using the same Go CLI config.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can go from a stock `config.example.yaml` to translated chapters with Go in under 5 minutes, needing only to add `translate.preset: go` and their OpenCode Go API key.
- **SC-002**: The Go preset's default prompt templates produce Vietnamese output with glossary terms applied at >=90% accuracy on a test set of 50 chapter titles and 10 full chapters from a known novel.
- **SC-003**: AI fallback crawling (when enabled) successfully extracts chapter content from at least 3 different Chinese novel sites whose HTML structure would defeat the standard crawler selectors.
- **SC-004**: Zero code changes are required in `translator.py` or `cli_runner.py` — the feature is purely config/preset layer in `config.py` and optional addition in `crawler.py`.

## Assumptions

- Users have an active OpenCode Go subscription and have installed the `opencode` CLI (`opencode auth` completed).
- The `opencode run` command accepts `--model` flag and prompt via stdin, consistent with the current `cli_runner.py` stdin mode.
- Go models are capable of Chinese-to-Vietnamese translation at acceptable quality for web novel content.
- The current `CLITranslator` and `cli_runner` infrastructure does not require changes — only config-layer additions.
- AI fallback crawling is experimental v1 and may have high latency or cost; it is opt-in only.
