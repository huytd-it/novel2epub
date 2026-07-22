# Task 3 Report: Aggregate Completed Job Outcomes

## Status

Completed.

## Changes

- Added `pendingOutcomeGroups` in `app/templates/ebook.html`.
- Kept the immediate queue-submission toast and register a group only after a successful selected crawl/translate response returns `job_ids` and `action`.
- Poll `/api/queue` while groups are pending, merge `running`, all pending job arrays, and history into an ID map, and emit one toast only after every group job is terminal.
- Summarize processed work, skip reasons, per-outcome failures, and failed jobs without an outcome. Format counts as new, skips, then errors.
- Display all-cancelled groups as `Đã hủy <action>.` and refresh the TOC once when a completed group processed chapters.
- Added a focused template source test for the aggregation hooks.

## Verification

- RED: `python -m pytest tests/test_job_outcomes.py -v` failed because the aggregation hooks were absent.
- GREEN: `python -m pytest tests/test_job_outcomes.py tests/test_job_cancel.py -v` passed: 20 tests.
- `node --check app/static/app.js` passed.
- Required source scan for `pendingOutcomeGroups`, `summarizeOutcomes`, and `job_ids` found the expected implementation.
- `git diff --check` passed.

## Scope

- No queue or pipeline contract changes were needed: `/api/queue` already returns the full queue snapshot including history and job records.

## Concerns

- Browser-level interaction was not run in this environment; the source-level test covers hook presence and focused backend tests cover returned `job_ids` and job outcomes.
