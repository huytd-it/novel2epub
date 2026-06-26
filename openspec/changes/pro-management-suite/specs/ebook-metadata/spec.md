## ADDED Requirements

### Requirement: Editable publishing metadata fields

The system SHALL let a user view and edit the following publishing metadata for an ebook: publisher, publication date, language, subjects/topics, series, series index, and description. Title and author remain editable as today.

#### Scenario: Edited metadata persists

- **WHEN** a user sets the publisher, series, and series index for an ebook and saves
- **THEN** those values are persisted in the ebook's configuration and shown on next load

#### Scenario: Multiple subjects supported

- **WHEN** a user enters more than one subject/topic for an ebook
- **THEN** all entered subjects are stored and available for packaging

### Requirement: Stable urn:uuid identifier

Each ebook SHALL have a unique identifier rendered as a `urn:uuid`. The system SHALL generate one automatically when absent and keep it stable across rebuilds; a user MAY override it.

#### Scenario: Identifier auto-generated once

- **WHEN** an ebook has no identifier and is built for the first time
- **THEN** a `urn:uuid` identifier is generated, persisted, and used

#### Scenario: Identifier stable across rebuilds

- **WHEN** an ebook with an existing identifier is rebuilt
- **THEN** the same `urn:uuid` is used rather than a newly generated one

### Requirement: Auto-recorded date added

The system SHALL record the date an ebook was added to the library and make it available as packaging metadata.

#### Scenario: Date added set on creation

- **WHEN** a new ebook is created in the library
- **THEN** its date-added is recorded automatically

### Requirement: Metadata embedded in the built EPUB

The EPUB builder SHALL embed all populated metadata into the generated `.epub` using standard mappings: Dublin Core for identifier, title, language, publisher, publication date, subjects, and description; and series, series index, and date-added via the conventional Calibre/EPUB collection metadata so common readers and Calibre display them.

#### Scenario: Populated fields appear in the EPUB

- **WHEN** an ebook with publisher, publication date, two subjects, series, series index, and a `urn:uuid` identifier is built
- **THEN** the produced `.epub` contains the corresponding metadata entries (identifier as `urn:uuid`, one subject entry per subject, and series/series-index recognized by Calibre)

#### Scenario: Empty fields are omitted

- **WHEN** an optional metadata field is empty
- **THEN** the builder omits that field from the EPUB rather than writing a blank value

### Requirement: Displayed file size

The system SHALL display the byte size of the built EPUB as a derived value; file size SHALL NOT be a user-editable metadata field.

#### Scenario: Size shown after build

- **WHEN** an ebook has a built EPUB
- **THEN** its file size is shown, computed from the file on disk
