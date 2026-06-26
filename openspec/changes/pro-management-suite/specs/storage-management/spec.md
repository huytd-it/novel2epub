## ADDED Requirements

### Requirement: Disk-usage reporting per ebook

The system SHALL report disk usage per ebook broken down by artifact category: raw chapters, machine-translation snapshots, edited translations, and the built EPUB.

#### Scenario: Usage broken down by category

- **WHEN** a user opens the storage overview
- **THEN** each ebook shows its total disk usage and the per-category breakdown for raw, MT snapshot, translated, and EPUB

#### Scenario: Aggregate total shown

- **WHEN** the storage overview is loaded
- **THEN** it shows the combined disk usage across all ebooks

### Requirement: Cleanup actions

The system SHALL let a user reclaim space by purging an ebook's raw chapters, purging its MT snapshots, or removing its built EPUB, each as an explicit, confirmed action that does not touch the edited translations.

#### Scenario: Purge raw preserves translations

- **WHEN** a user purges the raw chapters of an ebook
- **THEN** the raw files are removed
- **AND** the edited translations and MT snapshots are preserved

#### Scenario: Cleanup requires confirmation

- **WHEN** a user triggers any cleanup action
- **THEN** the UI requires explicit confirmation, naming what will be deleted, before proceeding

### Requirement: Full-ebook archive bundle

The system SHALL let a user export a full ebook (config plus its on-disk artifacts) as a single compressed bundle for backup, and the bundle SHALL be sufficient to restore the ebook.

#### Scenario: Archive bundle is self-contained

- **WHEN** a user archives an ebook to a bundle
- **THEN** the bundle contains the ebook's configuration and its stored chapter artifacts in a single downloadable file
