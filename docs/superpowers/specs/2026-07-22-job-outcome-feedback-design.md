# Job Outcome Feedback Design

Date: 2026-07-22

## Goal

Show a concise, accurate completion toast for crawl and translation actions. The toast must distinguish chapters that were newly processed, skipped, and failed, so users understand why an action did not change existing data.

Example:

`Crawl xong: 3 mới, 7 bỏ qua (đã có raw), 1 lỗi.`

## Scope

In scope:

- Structured outcomes for per-chapter crawl and translation jobs.
- Queue persistence and API exposure of job outcome summaries.
- Ebook page aggregation of all jobs submitted by one selected-action request.
- One completion toast per submitted action group after every associated job reaches a terminal state.
- Concise Vietnamese skip reasons for crawl and translate.

Out of scope:

- Listing individual chapter indexes in the completion toast.
- Replacing the queue/history visual UI.
- Changing whether existing data is skipped or overwritten.
- Inferring outcomes from frontend before/after snapshots or free-form logs.

## Data Model

Each queue job gains an optional structured `outcome` field:

```python
{
    "processed": 0,
    "skipped": 0,
    "failed": 0,
    "skip_reasons": {"đã có raw": 0},
}
```

Rules:

- `processed` counts chapters whose requested operation completed and wrote/updated its expected output.
- `skipped` counts chapters intentionally not processed.
- `failed` counts per-chapter operational failures. A job-level exception remains represented by existing job failure state/error and also contributes one failure to the displayed group summary.
- `skip_reasons` maps a stable Vietnamese reason string to its count.
- Empty or absent outcomes remain backward-compatible for jobs unrelated to crawl/translate.

## Outcome Producers

### Crawl

Each selected crawl job reports exactly one outcome for its target chapter:

- Processed: raw content was crawled and stored.
- Skipped `đã có raw`: raw already exists and overwrite was not selected.
- Skipped `chương đã bỏ qua`: the TOC chapter is marked skipped.
- Skipped `thiếu URL`: chapter cannot be crawled because it has no URL.
- Failed: fetch, extraction, or write failure.

### Translate

Each selected translation job reports exactly one outcome for its target chapter:

- Processed: translation was generated and stored.
- Skipped `đã có bản dịch`: translation already exists and overwrite was not selected.
- Skipped `chưa có raw`: source raw content is absent.
- Skipped `chương đã bỏ qua`: the TOC chapter is marked skipped.
- Failed: translation backend or write failure.

Existing batch operations that already return synchronous API summaries may continue to use their current immediate feedback. This feature first covers queue-backed crawl/translate action flows.

## Queue and API Flow

1. A selected action route enqueues one job per selected chapter and returns the submitted job IDs.
2. Each job target returns its outcome dictionary to the queue.
3. `JobQueue` stores the outcome on the completed job and includes it in its serialized snapshot/history representation.
4. The existing queue/status endpoint exposes the outcome without removing existing fields.
5. The ebook page records the returned job IDs as one pending action group, including the action label.
6. Its existing poll loop observes each recorded job reach `completed`, `failed`, or `cancelled`, aggregates outcomes, then emits exactly one completion toast and clears that pending group.

The immediate `Đã gửi ... vào hàng đợi.` toast remains, followed later by the completion summary.

## Toast Rules

Format counts in this order:

1. `N mới` when processed is nonzero.
2. `N bỏ qua (lý do)` for each nonzero skip reason.
3. `N lỗi` when failed is nonzero.

Examples:

- Success: `Crawl xong: 3 mới, 7 bỏ qua (đã có raw).`
- Informational skip: `Dịch xong: 5 bỏ qua (đã có bản dịch).`
- Mixed warning: `Dịch xong: 2 mới, 1 bỏ qua (chưa có raw), 1 lỗi.`
- Error: `Crawl thất bại: 2 lỗi.`

Toast kind:

- `success`: processed is positive and failed is zero.
- `info`: all jobs intentionally skipped and failed is zero.
- `warning`: processed and/or skipped plus at least one failure.
- `error`: no processed/skipped work and at least one failure.

Cancelled jobs display `Đã hủy <action>.` and do not claim processing occurred.

## Testing

- Unit-test outcome creation for each crawl/translate skip condition and success/failure condition.
- Unit-test queue serialization preserves a returned outcome.
- Route/API test confirms selected action response contains job IDs.
- Frontend-focused source tests or manual verification confirm one aggregate toast is emitted only after all job IDs in a group complete.
- Run `python -m pytest tests/ -v`; retain the currently known unrelated prompt/default baseline failures in the verification record unless they change.

## Risks

- Existing queue `Job` persistence needs a backward-compatible schema/data migration for old records without outcomes.
- Status polling currently summarizes categories, so job-level lookup/snapshot data must be available to the ebook page without making polling excessively large.
- A batch can be partially cancelled or fail before an outcome is returned; aggregation must still finish and report a truthful result.
