# CLI Contract: Refactor TOC

## Goals

The CLI must expose the same TOC metadata and chapter action semantics as the Web UI:
metadata import, Hán Việt metadata translation, deterministic chapter listing, selection
by active visible order, and explicit override for crawl/translate output.

## Commands

### Fetch TOC Metadata

```text
python -m novel2epub -c <config> toc
```

**Expected behavior**

- Imports or refreshes source metadata and chapter list without downloading chapter body text.
- Shows title, description, author, source URL, chapter count, and missing-field warnings.
- Reuses existing curated metadata unless an explicit override option is provided.

### Translate Metadata

```text
python -m novel2epub -c <config> meta [--force]
```

**Expected behavior**

- Translates title, author, and description into displayed Vietnamese values.
- Uses Hán Việt naming defaults and existing glossary/translation rules.
- Without `--force`, skips displayed metadata that already exists.
- With `--force`, replaces displayed metadata values.

### List Chapters

```text
python -m novel2epub -c <config> chapters [--sort <key>] [--desc]
  [--search <text>] [--filter <filter>]
```

**Sort keys**

- `source`: source order by chapter index.
- `title`: visible chapter title.
- `raw`: crawl status.
- `translated`: translation status.

**Filters**

- `raw:yes`, `raw:no`
- `translated:yes`, `translated:no`
- `missing:yes`, `missing:no`

**Expected behavior**

- Prints visible chapter rows with index, title, source URL, raw status, translated status,
  and missing-field status.
- The same sort/search/filter inputs define range selection for subsequent selected actions.

### Crawl Selected Chapters

```text
python -m novel2epub -c <config> crawl --sort <key> [--desc]
  [--search <text>] [--filter <filter>] [--range <start>:<end>] [--force]
```

**Expected behavior**

- Resolves `--range` against the active sorted and filtered chapter list.
- Without `--force`, skips chapters that already have raw content.
- With `--force`, replaces raw content only for selected chapters.
- Reports completed, skipped, failed, and replaced counts with per-chapter failure details.

### Translate Selected Chapters

```text
python -m novel2epub -c <config> translate --sort <key> [--desc]
  [--search <text>] [--filter <filter>] [--range <start>:<end>] [--force]
```

**Expected behavior**

- Resolves `--range` against the active sorted and filtered chapter list.
- Requires raw content for chapters to be translated.
- Without `--force`, skips chapters that already have translated content.
- With `--force`, replaces translated content only for selected chapters.
- Reports completed, skipped, failed, and replaced counts with per-chapter failure details.

## Compatibility

- Existing `crawl --from/--to --force` and `translate --chapter/--from/--to --force` behavior
  may remain as source-order shortcuts.
- New active-list selection must not change default behavior when no sort/search/filter/range
  options are provided.
