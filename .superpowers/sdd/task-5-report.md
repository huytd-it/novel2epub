# Task 5 Report: Regression Verification and Documentation Audit

## Status

Completed with pre-existing Python test failures and an interactive-browser verification gap.

No production code or specification files were modified. No documentation commit was created because the implementation remains consistent with `docs/superpowers/specs/2026-07-22-ebook-ux-feedback-design.md`.

## Required Verification

Command:

```text
python -m pytest tests/ -v
```

Result: exit code 1 in 20.16s; 659 passed, 3 failed, 2 warnings.

Failures:

- `tests/test_bulk_transfer_api.py::test_export_raw_returns_translate_prompt_and_raw_text`
  Expected the export text to contain `Yêu cầu dịch truyện`; the current translation prompt begins `Bạn là dịch giả tiểu thuyết mạng Trung Quốc...`.
- `tests/test_bulk_transfer_api.py::test_batch_translate_uses_TRANSLATE_PROMPT`
  Expected the captured batch-translation prompt to contain `Yêu cầu dịch truyện`; it instead uses the current translation prompt beginning `Bạn là dịch giả tiểu thuyết mạng Trung Quốc...`.
- `tests/test_config.py::test_prompt_max_chars_defaults_7000`
  Expected `cfg.translate.prompt_max_chars == 7000`; observed `20000`.

Baseline comparison: Task 1 recorded 658 passed, 4 failed, 2 warnings, including the three failures above and `tests/test_crawl_throttle.py::test_rate_limiter_spaces_out_calls`. The throttle test passed in this run. The remaining three failures are unrelated to this UI-only feedback implementation and concern translation-prompt/default configuration expectations.

Command:

```text
rg -n "\b(window\.)?(alert|confirm)\s*\(" app/templates app/static
```

Result: no matches; `rg` exit code 1, which is the expected exit code for an empty result.

Command:

```text
git diff --check
```

Result: exit code 0; no whitespace errors.

Additional command:

```text
node --check app/static/app.js
```

Result: exit code 0.

## Documentation Audit

The implementation preserves the documented behavior:

- The shared toast and asynchronous confirmation helpers replace native dialogs.
- Feedback messages are rendered safely using DOM text content.
- Existing routes, APIs, and job semantics remain unchanged.
- The specification permits warning toasts, modal cancellation paths, and sticky/fixed selected actions.

No specification correction is required. Per Task 5, no empty documentation commit was made.

## Manual/Browser Verification

Feasible server smoke check performed:

```text
python -m uvicorn app.main:app --host 127.0.0.1 --port 8011
GET http://127.0.0.1:8011/
```

Result: server started successfully and `/` returned HTTP 200. The rendered page contained `#toast-region` and `#confirm-dialog`; the available ebook link was `/ebooks/default`.

Interactive browser verification was not feasible. The `playwright` executable is installed, but `playwright install --dry-run` reported browser download locations rather than installed browser binaries, and no browser-control tool is available in this environment. The following representative flows remain unverified manually: library bulk delete, settings source sync, queue clear-failed, chapter delete translation, glossary bulk delete, reader discard changes, and ebook batch delete.

## Final Review Fix

- `showPopupMessage()` now creates a fixed, inline-styled notification that does not depend on the parent application's Tailwind or component CSS. It uses accessible status roles, transitions into view, and removes itself after four seconds.
- Ebook chapter and glossary import success continue to notify through the parent-page `toast()` before the popup closes. The redundant popup-local ebook success message was removed, while popup validation, HTTP error, and network error feedback remain local and visible.
- Final verification results:
  - `node --check app/static/app.js`: exit code 0.
  - `rg -n "\b(window\.)?(alert|confirm)\s*\(" app/templates app/static`: no matches (normalized expected `rg` exit code 1 to success).
  - `git diff --check`: exit code 0; no whitespace errors.
