# Job Outcome Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Report concise, accurate crawl/translation completion summaries, including reasons chapters were skipped.

**Architecture:** Add an optional outcome dictionary to queue jobs and persist it in job JSON. Make per-chapter selected crawl/translate targets return one structured outcome, expose completed job records through the queue API, then have `ebook.html` aggregate the job IDs returned by one submission and emit one completion toast.

**Tech Stack:** Python 3.10+, FastAPI, SQLite-backed `JobQueue`, Jinja2, vanilla JavaScript, pytest.

**Spec:** `docs/superpowers/specs/2026-07-22-job-outcome-feedback-design.md`

## Global Constraints

- Add no dependencies and preserve existing endpoint URLs and normal crawl/translate behavior.
- An outcome has `processed`, `skipped`, `failed`, and `skip_reasons`; absent outcomes remain valid for unrelated jobs and historical records.
- Crawl reasons: `đã có raw`, `chương đã bỏ qua`, `thiếu URL`; translate reasons: `đã có bản dịch`, `chưa có raw`, `chương đã bỏ qua`.
- Emit one Vietnamese completion toast per submitted action group only after all returned job IDs are terminal.
- Keep immediate queue-submission feedback and use `textContent` for dynamic UI strings.
- Run `python -m pytest tests/ -v`; document the existing prompt/default baseline failures if still present.

---

### Task 1: Persist structured job outcomes

**Files:**
- Modify: `app/queue.py:29-68, 493-513, 587-637`
- Test: `tests/test_job_queue.py`

**Interfaces:**
- Produces: `Job.outcome: dict | None`; `Job.to_dict()` includes `outcome` when present.
- Produces: targets may return an outcome dictionary; `_execute()` stores it before terminal history persistence.

- [ ] **Step 1: Write failing queue tests**

Add tests proving a target returning `{"processed": 0, "skipped": 1, "failed": 0, "skip_reasons": {"đã có raw": 1}}` appears in `snapshot()["history"]`, survives `_save_history()`/new `JobQueue(db_path=...)`, and an old JSON record with no `outcome` loads as `None`.

- [ ] **Step 2: Run the focused tests**

Run: `python -m pytest tests/test_job_queue.py -v`

Expected: FAIL because `outcome` is missing.

- [ ] **Step 3: Implement queue support**

Add `outcome: dict | None = None` to `Job`; include it in `to_dict`; assign `job.outcome = job.target(log_fn)` only when the returned value is a dictionary; restore `outcome=item.get("outcome")` in `_load_history`.

- [ ] **Step 4: Verify and commit**

Run: `python -m pytest tests/test_job_queue.py -v`

Expected: PASS.

```powershell
git add app/queue.py tests/test_job_queue.py
git commit -m "feat: persist queue job outcomes"
```

---

### Task 2: Produce reason-aware crawl/translation outcomes

**Files:**
- Modify: `novel2epub/pipeline.py:487-661, 986 onward`
- Modify: `app/routes/jobs.py` selected chapter action target construction
- Test: `tests/test_job_cancel.py` or a new focused `tests/test_job_outcomes.py`

**Interfaces:**
- Consumes: `JobQueue` target return contract from Task 1.
- Produces: selected single-chapter crawl/translate targets return exactly one outcome dictionary.

- [ ] **Step 1: Write failing pipeline tests**

Create focused tests using a manifest with one chapter for each condition. Assert crawl returns skip outcome `{"skipped": 1, "skip_reasons": {"đã có raw": 1}}` when raw exists without force, and translation returns `đã có bản dịch` or `chưa có raw` under the corresponding storage state. Assert successful fake crawl/translator returns `{"processed": 1, "skipped": 0, "failed": 0, "skip_reasons": {}}`.

- [ ] **Step 2: Run focused tests**

Run: `python -m pytest tests/test_job_outcomes.py -v`

Expected: FAIL because selected steps return a manifest or no structured outcome.

- [ ] **Step 3: Implement minimal outcome helpers**

Add a small private pipeline helper that returns the four-key outcome shape. Preserve multi-chapter CLI return values. For route-created per-chapter jobs, invoke a single-chapter outcome-capable path which checks TOC skip, URL/raw/translated existence, then returns processed/skipped/failed outcome. Keep exceptions for true operational failures so queue state/error remains correct.

- [ ] **Step 4: Return job IDs from selected-action route**

Ensure the chapter-action response contains `{"job_ids": [...], "action": "crawl"|"translate"}` while retaining any existing response fields. Add route tests asserting IDs correspond to enqueued jobs.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/test_job_outcomes.py tests/test_job_cancel.py -v`

Expected: PASS.

```powershell
git add novel2epub/pipeline.py app/routes/jobs.py tests/test_job_outcomes.py tests/test_job_cancel.py
git commit -m "feat: report crawl and translate outcomes"
```

---

### Task 3: Aggregate completed job outcomes on the ebook page

**Files:**
- Modify: `app/routes/jobs.py` queue snapshot endpoint only if it does not already return history/job records
- Modify: `app/templates/ebook.html: submit handler and poll loop`

**Interfaces:**
- Consumes: selected action response `job_ids`, queue history records with `state`, `outcome`, and `error`.
- Produces: one `pendingOutcomeGroups` entry per action submission and one final toast per completed group.

- [ ] **Step 1: Add the outcome aggregation functions**

In `ebook.html`, add `pendingOutcomeGroups`, `summarizeOutcomes(action, jobs)`, and `finishOutcomeGroups(queueSnapshot)`. Aggregate processed/failed counts and `skip_reasons`; count failed terminal jobs without outcome once; handle all-cancelled groups with `Đã hủy <action>.`.

- [ ] **Step 2: Register groups only after accepted responses**

After a selected crawl/translate response succeeds, parse JSON, record its `job_ids`, and retain the existing immediate submission toast. Do not create a group for synchronous batch API mutations.

- [ ] **Step 3: Format toast results**

Emit parts in this exact order: `N mới`, each `N bỏ qua (lý do)`, then `N lỗi`. Use success for processed/no failures, info for skip-only, warning for mixed failures, and error for failures only.

- [ ] **Step 4: Poll job-level queue data**

Use `/api/queue` from the existing ebook polling loop, merge `running`, every `pending` array, and `history` into an ID map, and finish a group only when all IDs are `done`, `failed`, or `cancelled`. Refresh TOC once after a completed group that processed chapters.

- [ ] **Step 5: Verify and commit**

Run: `node --check app/static/app.js`

Expected: PASS.

Run: `rg -n "pendingOutcomeGroups|summarizeOutcomes|job_ids" app/templates/ebook.html app/routes/jobs.py`

Expected: matching implementation lines.

```powershell
git add app/templates/ebook.html app/routes/jobs.py
git commit -m "feat: show crawl and translate outcome summaries"
```

---

### Task 4: Regression verification

**Files:**
- Test: `tests/test_job_queue.py`, `tests/test_job_outcomes.py`, relevant route tests

- [ ] **Step 1: Run focused verification**

Run: `python -m pytest tests/test_job_queue.py tests/test_job_outcomes.py tests/test_job_cancel.py -v`

Expected: PASS.

- [ ] **Step 2: Run full verification and source checks**

Run: `python -m pytest tests/ -v`

Expected: all new outcome tests pass; record any existing prompt/default failures unchanged.

Run: `git diff --check`

Expected: no whitespace errors.

- [ ] **Step 3: Manual verification**

On an ebook with existing raw, select chapters and press Crawl. Confirm an immediate queued toast appears, then one completion info toast such as `Crawl xong: 2 bỏ qua (đã có raw).` Repeat with existing translations and Dịch, then with mixed missing raw and new chapters.

---
