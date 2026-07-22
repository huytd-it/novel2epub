# Task 2 Review Fix Report

## Status

Restored job-level translation backend failures as queue failures.

- `step_translate_chapter_outcome` no longer converts backend exceptions into a failed outcome dictionary.
- The exception now reaches `JobQueue`, which records terminal `failed` state and its nonempty error without an outcome.
- Crawl per-chapter fetch failures remain non-throwing batch outcomes.

## Tests

- Updated the direct translation outcome test to expect the raised backend error and retained chapter `failed` status.
- Added a queue-boundary regression test covering a failing translation target, live snapshot serialization, and reloaded history serialization.

## Verification

- `python -m pytest tests/test_job_outcomes.py tests/test_job_cancel.py tests/test_job_queue.py -v` passed: 37 tests passed.
- `git diff --check` exited 0. Git emitted only existing CRLF normalization warnings.
