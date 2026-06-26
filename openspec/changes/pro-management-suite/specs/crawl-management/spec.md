## ADDED Requirements

### Requirement: Per-chapter crawl status

The crawl console for an ebook SHALL display each chapter's crawl status — not fetched, fetched (with content), or fetched-but-empty — derived from the manifest and on-disk raw content.

#### Scenario: Empty raw distinguished from missing

- **WHEN** a chapter has a raw file that is empty or below a minimal content threshold
- **THEN** the console marks it as fetched-but-empty, distinct from chapters with no raw file

### Requirement: Gap and failure detection

The crawl console SHALL detect and surface gaps in the crawled range (missing chapters between fetched ones) and the set of failed/empty chapters as a single actionable list.

#### Scenario: Gaps surfaced as a list

- **WHEN** chapters 1–10 exist but chapters 4 and 7 have no raw content
- **THEN** the console reports chapters 4 and 7 as missing within the crawled range

### Requirement: Bulk retry of failed or empty chapters

The crawl console SHALL let a user enqueue a crawl job that targets exactly the failed, empty, or missing chapters in one action.

#### Scenario: Retry targets only problem chapters

- **WHEN** a user triggers "retry failed" with chapters 4 and 7 missing
- **THEN** a crawl job is enqueued whose selected chapters are exactly 4 and 7

### Requirement: Concurrent crawling with per-source limit

The system SHALL crawl multiple chapters concurrently using a configurable worker count, and SHALL cap concurrency per source (preset) so that the number of simultaneous in-flight requests to a given site never exceeds that source's configured limit.

#### Scenario: Concurrency honors the per-source cap

- **WHEN** a source's concurrency cap is 5 and a crawl job targets 100 chapters
- **THEN** no more than 5 chapter requests to that source are in flight at any moment

#### Scenario: Browser-mode default is conservative

- **WHEN** a crawl uses a browser-based engine mode (e.g. stealthy/dynamic)
- **THEN** the default concurrency is low to bound memory use, distinct from the higher default for the lightweight HTTP fetcher mode

### Requirement: Adaptive anti-block throttling

The system SHALL apply a per-domain request rate limit with randomized delay, and SHALL adaptively reduce effective concurrency when the source returns a burst of rate-limit/anti-bot responses, recovering gradually afterward. Existing exponential backoff and `Retry-After` handling SHALL be preserved.

#### Scenario: Concurrency backs off on rate limiting

- **WHEN** a source returns repeated 429 / anti-bot responses during a crawl
- **THEN** the system reduces the effective concurrency for that source and slows the request rate rather than continuing at full speed

#### Scenario: Retry-After is honored

- **WHEN** a response includes a `Retry-After` header
- **THEN** the next request to that source waits at least the indicated duration

### Requirement: Surfaced crawl controls

The crawl console SHALL expose engine, request delay, retry count, and force-overwrite as first-class controls applied to the next crawl job, overriding the ebook's stored defaults for that run only.

#### Scenario: Per-run override does not persist

- **WHEN** a user sets a different engine and delay for a single crawl run and starts it
- **THEN** the job uses the overridden engine and delay
- **AND** the ebook's stored configuration is unchanged after the run
