## ADDED Requirements

### Requirement: Manage site presets

The system SHALL let a user create, edit, clone, and delete site presets, where each preset captures the crawl engine and selector/behavior configuration reused across ebooks.

#### Scenario: Clone a preset

- **WHEN** a user clones an existing preset under a new name
- **THEN** a new preset is created with the same configuration values and the original preset is unchanged

#### Scenario: Delete a preset in use warns

- **WHEN** a user deletes a preset that is referenced by one or more ebooks
- **THEN** the UI surfaces which ebooks use the preset before the deletion is confirmed

### Requirement: Validate a preset against a live URL

The system SHALL let a user test a preset by running a dry-run fetch against a sample TOC URL that retrieves the table of contents and one chapter's content without persisting any chapters, and SHALL report what was extracted or the failure reason.

#### Scenario: Successful dry-run reports extraction

- **WHEN** a user runs a preset test against a valid TOC URL for that source
- **THEN** the system reports the detected title, chapter count, and a sample of one chapter's extracted content
- **AND** no chapter files are written to the ebook's storage

#### Scenario: Failed dry-run reports reason

- **WHEN** a preset test fails to extract content (e.g. selector mismatch or blocked request)
- **THEN** the system reports the failure reason instead of a generic error

### Requirement: Import and export presets

The system SHALL let a user export the set of presets to a file and import presets from such a file, merging by name with explicit handling of name collisions.

#### Scenario: Import with name collision

- **WHEN** a user imports a preset whose name already exists
- **THEN** the system requires the user to choose whether to overwrite or import under a different name

### Requirement: Usage and health reporting

The sources view SHALL show, for each preset, the ebooks currently using it and the outcome of its most recent validation test.

#### Scenario: Usage list shown per preset

- **WHEN** the sources view is loaded and an ebook's resolved crawl config matches a preset
- **THEN** that ebook is listed under the preset's usage
