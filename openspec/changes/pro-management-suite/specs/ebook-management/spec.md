## ADDED Requirements

### Requirement: Library dashboard with progress overview

The library view SHALL present each ebook as a card showing its title, author, cover (when available), and progress for crawl, translate, and build expressed against the known chapter count.

#### Scenario: Card shows progress against total

- **WHEN** an ebook has a manifest with N chapters, of which C are crawled and T are translated
- **THEN** its card shows crawled C/N and translated T/N as progress, and whether a built EPUB exists

#### Scenario: Empty library guidance

- **WHEN** the library contains no ebooks
- **THEN** the view shows guidance directing the user to add an ebook

### Requirement: Per-ebook quick actions

Each ebook card SHALL provide quick actions to open the ebook, edit its settings, start crawl/translate/build, download the EPUB when present, and remove the ebook from the library.

#### Scenario: Download disabled without EPUB

- **WHEN** an ebook has no built EPUB
- **THEN** the download action is unavailable or disabled on its card

#### Scenario: Remove requires confirmation

- **WHEN** a user triggers removal of an ebook from the library
- **THEN** the UI requires explicit confirmation before the ebook is removed

### Requirement: Bulk actions across ebooks

The library view SHALL let a user select multiple ebooks and apply a bulk action (e.g. build, or translate pending chapters) that enqueues the corresponding job for each selected ebook.

#### Scenario: Bulk build enqueues per ebook

- **WHEN** a user selects three ebooks and triggers bulk build
- **THEN** a build job is enqueued for each of the three ebooks

### Requirement: Archive and unarchive ebooks

The system SHALL let a user archive an ebook so it is hidden from the default library view without deleting its data, and unarchive it to restore visibility.

#### Scenario: Archived ebook hidden by default

- **WHEN** an ebook is archived
- **THEN** it does not appear in the default library view
- **AND** it appears when the user chooses to show archived ebooks
- **AND** its on-disk data and config are preserved

### Requirement: Config import and export

The system SHALL let a user export an ebook's effective configuration to a file and create a new ebook by importing such a file.

#### Scenario: Export then import recreates ebook config

- **WHEN** a user exports ebook A's config and imports it under a new slug
- **THEN** a new ebook is created whose configuration matches the exported config
