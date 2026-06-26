## ADDED Requirements

### Requirement: Define automation pipelines

The system SHALL let a user define an automation that runs an ordered sequence of pipeline steps (any of: fetch TOC, crawl new chapters, translate pending, build) for a specific ebook.

#### Scenario: Create an update automation

- **WHEN** a user creates an automation for ebook A with steps fetch-TOC → crawl-new → translate-pending → build
- **THEN** the automation is persisted and listed for ebook A with its step sequence

### Requirement: Scheduling and triggers

An automation SHALL support a recurring schedule (e.g. daily at a set time) or manual-only triggering, and the user SHALL be able to enable or disable it without deleting it.

#### Scenario: Recurring automation runs on schedule

- **WHEN** an enabled automation's scheduled time arrives
- **THEN** its steps are enqueued in order as background jobs

#### Scenario: Disabled automation does not run

- **WHEN** an automation is disabled and its scheduled time arrives
- **THEN** no jobs are enqueued for it

### Requirement: Run-now and last-run status

The system SHALL let a user trigger an automation immediately and SHALL record and display each automation's last-run time and outcome (success, failure, or partial).

#### Scenario: Run now enqueues steps

- **WHEN** a user triggers run-now on an automation
- **THEN** its steps are enqueued immediately regardless of schedule

#### Scenario: Last-run outcome recorded

- **WHEN** an automation run completes
- **THEN** its last-run time and outcome are recorded and shown in the automation list

### Requirement: Automations honor the job queue

Automation steps SHALL be submitted through the job queue and respect its per-category serialization rather than bypassing it.

#### Scenario: Automation steps queue behind manual jobs

- **WHEN** an automation enqueues a crawl step while a manual crawl job is running
- **THEN** the automation's crawl step waits in the crawl queue rather than running concurrently in the same category
