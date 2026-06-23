## ADDED Requirements

### Requirement: Translator streams per-chunk progress via callback

The system MUST stream per-chunk translation progress to the pipeline via a
callback. Every concrete `Translator` implementation (`CLITranslator`,
`GoogleTranslator`, `NoopTranslator`) MUST accept a keyword-only `on_chunk`
parameter in its `translate(text)` method. After a chunk finishes translating
(including post-processing such as glossary replacement and Han-residual retry
for `CLITranslator`), the translator MUST invoke `on_chunk` **before** starting
the next chunk. The callback signature MUST be
`on_chunk(index: int, total: int, chunk_text: str, is_final: bool) -> None`
where `index` is 1-based, `total` is the number of chunks, `chunk_text` is the
cleaned translated text of that chunk alone (not concatenated with earlier
chunks), and `is_final` is `True` only for the last chunk.

The `translate()` method MUST still return the full concatenated translated
text, identical in content to what would be produced by concatenating each
`chunk_text` delivered via `on_chunk` (plus, for `CLITranslator`, the
chunk-overlap lines stripped between chunks).

#### Scenario: Single-chapter translates through one chunk callback
- **WHEN** `CLITranslator.translate("X")` runs on a 300-character text with
  `chunk.max_chars=6000` and `on_chunk=cb`
- **THEN** `cb` is invoked exactly once with
  `(1, 1, "<cleaned translation of X>", True)` and the return value equals
  the same cleaned translation

#### Scenario: Multi-chunk chapter fires one callback per chunk in order
- **WHEN** `CLITranslator.translate(R)` runs on a 2760-character text split
  into 4 chunks (with the default `chunk.overlap_paragraphs=0`) and
  `on_chunk=cb`
- **THEN** `cb` is invoked exactly 4 times with indexes `(1, 4, ...)`,
  `(2, 4, ...)`, `(3, 4, ...)`, `(4, 4, "...")` in that order, each carrying
  the cleaned translation of its chunk, and only the 4th call has
  `is_final=True`

#### Scenario: Missing on_chunk falls back to current behavior
- **WHEN** `Translator.translate(text)` is called without the `on_chunk`
  keyword
- **THEN** the method runs exactly as before, returns the full concatenated
  translation, and never raises

#### Scenario: Callback exception aborts the translation
- **WHEN** the user-supplied `on_chunk` callback raises an exception
- **THEN** the translator MUST propagate that exception out of `translate()`
  without retrying the current chunk or starting the next one

### Requirement: Pipeline writes translated content progressively

`Pipeline._translate_one` MUST persist each translated chunk to
`translated/{stem}.md` as soon as the chunk is available, by passing an
`on_chunk` callback that appends to the file. The first chunk MUST create the
file (write mode) and subsequent chunks MUST append. When `is_final` is
`True`, the pipeline MUST also write `meta["complete"] = True` to
`translation_meta/{stem}.json`.

The same `on_chunk` contract MUST be honoured by both the sequential
(`_translate_chapters_sequential`) and parallel
(`_translate_chapters_parallel`) paths. The callback used in the parallel
path MUST serialise file writes per-chapter (e.g. via a per-`ch.stem` lock)
because two worker threads must never write to the same file at once.

#### Scenario: Sequential path writes file after each chunk
- **WHEN** `_translate_one` is invoked for a chapter that splits into 3 chunks
  and the translator returns successfully
- **THEN** after chunk 1 finishes, `translated/0007.md` exists and contains
  only chunk 1's text; after chunk 2, it contains chunks 1+2; after chunk 3
  (the final one), it contains all 3 chunks and
  `translation_meta/0007.json` has `complete: true`

#### Scenario: Parallel workers never interleave writes to the same file
- **WHEN** `_translate_chapters_parallel` runs N=4 workers over chapters
  whose chunk counts vary
- **THEN** for every chapter, the bytes written to `translated/{stem}.md`
  are exactly the concatenation of its own chunks in order, with no
  interleaving from a sibling chapter's chunks

#### Scenario: Force-retranslate re-runs from scratch
- **WHEN** `step_translate_selected(force=True, selected_indexes=[idx])` is
  called for a chapter whose `translated/{stem}.md` exists and
  `meta["complete"] == True`
- **THEN** the chapter is re-translated: the file is overwritten, the meta
  is rewritten, and `complete` is set to `True` again at the end

### Requirement: Cache considers partial translations as not done

`Storage.has_translated(ch)` MUST return `True` only when both
`translated/{stem}.md` exists and `translation_meta/{stem}.json` contains
`complete == True`. If the meta file is missing entirely (legacy data
written before this change) the chapter MUST be treated as complete, to avoid
forcing users to re-translate their existing library. If the meta file exists
but `complete` is missing or `False`, the chapter MUST be treated as
not-done (a partial result left behind by a crashed job) and a fresh
translation MUST be produced on the next run.

#### Scenario: Legacy chapter without meta is treated as complete
- **WHEN** `translated/0042.md` exists but `translation_meta/0042.json` does
  not
- **THEN** `Storage.has_translated(ch_42)` returns `True`

#### Scenario: Partially translated chapter is treated as not done
- **WHEN** `translated/0043.md` exists (2 of 4 chunks written) and
  `translation_meta/0043.json` exists with `{"complete": false}` (or no
  `complete` key at all)
- **THEN** `Storage.has_translated(ch_43)` returns `False`, and the next
  `step_translate_selected(selected_indexes=[43])` call (without `force`)
  re-translates chapter 43 from scratch

#### Scenario: Fully translated chapter is treated as done
- **WHEN** `translated/0044.md` exists and
  `translation_meta/0044.json` has `{"complete": true}`
- **THEN** `Storage.has_translated(ch_44)` returns `True`, and a normal
  `step_translate_selected` run skips chapter 44

### Requirement: Web API exposes current translated text for live preview

The web layer MUST expose a JSON endpoint
`GET /api/ebooks/{slug}/chapters/{index}/translated` that returns
`{"text": <str>, "complete": <bool>, "mtime": <float>, "char_count": <int>}`.
`text` MUST be the current contents of `translated/{stem}.md` (or the empty
string if the file does not exist), `complete` MUST reflect the `complete`
flag in the chapter's meta, `mtime` MUST be the file's modification time as
a Unix timestamp (or `0` if the file does not exist), and `char_count` MUST
be `len(text)`. The endpoint MUST return 404 if the chapter index does not
exist in the manifest.

#### Scenario: Endpoint returns the in-progress translation
- **WHEN** a job is mid-translation of chapter 7 (chunk 2/4 done) and a
  client requests `GET /api/ebooks/chi-tam-tam-gioi/chapters/7/translated`
- **THEN** the response is `200 OK` with JSON
  `{"text": "<chunks 1+2 concatenated>", "complete": false, "mtime": <recent>, "char_count": <len>}`

#### Scenario: Endpoint returns 404 for unknown chapter
- **WHEN** a client requests the endpoint for `index=9999` but the manifest
  has no such chapter
- **THEN** the response is `404` with `{"detail": "Không tìm thấy chương."}`

#### Scenario: Endpoint returns empty text before translation starts
- **WHEN** a chapter has raw but no `translated/{stem}.md` yet
- **THEN** the response is `200 OK` with
  `{"text": "", "complete": false, "mtime": 0, "char_count": 0}`

### Requirement: Chapter page polls translated content during a running job

The chapter detail template (`app/templates/chapter.html`) MUST, while the
translate job slot is `running`, poll the JSON endpoint above at the same
1.5-second cadence used for `/api/status` and MUST update
`<textarea name="translated">` and the `#translated-preview` element when
`mtime` differs from the previously rendered value. When the translate slot
is no longer running, polling the translated endpoint MUST stop. When the
job slot transitions from running to idle, the page MUST continue to use
the existing `location.reload()` flow to pick up the final, authoritative
state (because the textarea may have unsaved user edits that the in-memory
re-render would clobber).

#### Scenario: Polling updates the preview while job is running
- **WHEN** the chapter page is open, the translate slot is `running`, and
  the next chunk is written to disk
- **THEN** within one poll cycle (≤1.5s) the textarea value matches the new
  `text` from the JSON endpoint and `#translated-preview` re-renders to
  reflect the new content

#### Scenario: Polling stops when the job stops
- **WHEN** the translate slot transitions to idle
- **THEN** no further requests are made to
  `/api/ebooks/{slug}/chapters/{index}/translated`, and the existing
  `location.reload()` logic runs once

#### Scenario: Local textarea edits are not clobbered
- **WHEN** the user is editing the textarea (focus is on it) and a new chunk
  is written
- **THEN** the polling update MUST skip the textarea (so the user's cursor
  and selection are preserved) and update only the read-only preview pane
