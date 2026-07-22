# Task 4 Report: Chapter, Glossary, and Reader Feedback

## Status

Completed.

## Changes

- Replaced chapter inline form confirmations with `data-confirm` and
  `data-confirm-danger`, plus a delegated asynchronous submit guard that
  preserves method/action fallback when JavaScript is unavailable.
- Replaced scoped native dialog calls with global `toast`, `confirmDialog`, and
  `showPopupMessage` helpers.
- Added success feedback for accepted chapter jobs, glossary saves, and
  glossary propagation.
- Made the reader dirty-editor guard asynchronous and awaited it before opening
  another paragraph editor.

## Verification

- Scoped `rg` scan for native `alert`/`confirm`: no matches.
- Jinja-neutralized `node --check` of inline scripts: passed.
- `git diff --check`: passed.
- Baseline `python -m pytest tests/ -v`: 658 passed, 4 failed before Task 4.
  Failures are in `tests/test_bulk_transfer_api.py`, `tests/test_config.py`, and
  `tests/test_crawl_throttle.py`; Task 4 modifies only client templates.

## Commit

`ff8b6ec feat: unify chapter glossary and reader feedback`

## Review Follow-up

- Glossary import success now uses the parent-page `toast` before the popup closes;
  validation and request failures continue to use popup-local `showPopupMessage`.
- Reader paragraph editor switches now ignore competing clicks while a dirty-state
  confirmation is pending. The guard is reset in `finally` on every exit path.

## Follow-up Verification

- Scoped `rg -n "\b(window\.)?(alert|confirm)\s*\(" app/templates/glossary.html app/templates/reader.html`: no matches.
- Jinja-neutralized inline-script syntax check for `glossary.html` and `reader.html`: passed.
- `git diff --check`: passed.
