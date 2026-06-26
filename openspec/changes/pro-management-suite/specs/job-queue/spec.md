## ADDED Requirements

### Requirement: FIFO job queue per category

The system SHALL maintain a FIFO queue of background jobs for each execution category (crawl, translate, and the combined build/run category) such that starting a job while another in the same category is running enqueues the new job instead of rejecting it.

#### Scenario: Second job enqueues instead of rejecting

- **WHEN** a crawl job is running and the user starts another crawl job
- **THEN** the new job is added to the crawl queue with state `pending`
- **AND** the request succeeds rather than returning a busy error

#### Scenario: Pending job auto-starts when slot frees

- **WHEN** a running job in a category finishes and that category's queue has a pending job
- **THEN** the next pending job transitions to `running` automatically

#### Scenario: Independent categories run in parallel

- **WHEN** a crawl job and a translate job are both started
- **THEN** both run concurrently because they occupy different category queues

### Requirement: Configurable concurrent worker pool per category

Each category SHALL run a configurable number of concurrent workers (default may be 1) so that multiple jobs in the same category can run in parallel up to that limit, while jobs beyond the limit remain `pending`.

#### Scenario: Multiple workers run jobs in parallel

- **WHEN** a category is configured with 3 workers and 5 jobs are enqueued in it
- **THEN** 3 jobs run concurrently and the remaining 2 stay `pending` until a worker frees

#### Scenario: Build/run job needs exclusive access

- **WHEN** a combined build/run job is dequeued
- **THEN** it runs only when no other job is active in the categories it spans, and it blocks new jobs in those categories until it finishes

### Requirement: Job lifecycle and identity

Each enqueued job SHALL have a unique id and progress through a defined lifecycle: `pending` → `running` → (`done` | `failed` | `cancelled`), with the originating ebook, step, enqueue time, start time, and end time recorded.

#### Scenario: Job exposes its state and metadata

- **WHEN** a client requests the status of a known job id
- **THEN** the system returns the job's current state, ebook, step, and timestamps

#### Scenario: Failed job records error

- **WHEN** a running job raises an error
- **THEN** the job transitions to `failed` and its recorded error message is retrievable

### Requirement: Queue control — cancel, retry, reorder

The system SHALL let a user cancel a pending or running job, retry a finished job (failed or done) by enqueuing an equivalent new job, and reorder pending jobs within a category.

#### Scenario: Cancel a pending job

- **WHEN** a user cancels a job that is `pending`
- **THEN** the job transitions to `cancelled` and never starts

#### Scenario: Cancel a running job

- **WHEN** a user cancels a job that is `running`
- **THEN** the system signals cancellation and the job stops at the next safe checkpoint and transitions to `cancelled`

#### Scenario: Retry a failed job

- **WHEN** a user retries a `failed` job
- **THEN** an equivalent new job with the same parameters is enqueued with a new id

#### Scenario: Reorder pending jobs

- **WHEN** a user moves a pending job ahead of another pending job in the same category
- **THEN** the moved job will start before the other when slots free, while the running job is unaffected

### Requirement: Queue status and history

The system SHALL expose a status view listing running and pending jobs with their queue position and live progress, and SHALL retain a bounded history of recently finished jobs with their final state.

#### Scenario: Status lists position and progress

- **WHEN** a client requests queue status
- **THEN** the response lists each running job with progress and each pending job with its position in its category queue

#### Scenario: History retained after completion

- **WHEN** a job finishes
- **THEN** it appears in the recent-history list with its final state and timestamps
- **AND** the history is capped to a bounded number of entries
