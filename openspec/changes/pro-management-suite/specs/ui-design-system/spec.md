## ADDED Requirements

### Requirement: Application shell with persistent navigation

The web UI SHALL render every page inside a shared shell that exposes persistent navigation to the primary sections: Library (home), Sources, Storage, Automation, and the active Queue.

#### Scenario: Navigation visible on every page

- **WHEN** a user loads any page of the web UI
- **THEN** the shell renders a persistent navigation region containing links to Library, Sources, Storage, and Automation
- **AND** the link for the section matching the current page is visually marked as active

#### Scenario: Queue indicator in shell

- **WHEN** one or more jobs are running or pending
- **THEN** the shell shows a queue indicator with the count of running plus pending jobs that links to the queue view

### Requirement: Reusable component and design-token set

The UI SHALL provide a single shared stylesheet defining design tokens (color, spacing, typography, radius) and reusable component styles (cards, tables, badges, buttons, form controls, modals, toasts) used consistently across all pages.

#### Scenario: Components share token-driven styling

- **WHEN** any two pages render the same component type (e.g. a status badge)
- **THEN** both instances derive their colors and spacing from the shared design tokens rather than page-local ad-hoc styles

### Requirement: Light and dark theme

The UI SHALL support a light and a dark theme, default to the operating-system color-scheme preference, and let the user override the theme with the choice persisted across sessions.

#### Scenario: Theme defaults to system preference

- **WHEN** a user with a dark OS color-scheme preference and no saved override loads the UI
- **THEN** the UI renders in the dark theme

#### Scenario: User override persists

- **WHEN** a user toggles the theme to light and then reloads the page
- **THEN** the UI renders in the light theme

### Requirement: Fluid wide layout

The UI SHALL use a fluid, full-width layout for management and data-dense views so content uses the available horizontal space, while long-form reading content (chapter prose) retains a comfortable max-width for readability.

#### Scenario: Data tables use available width

- **WHEN** a data-dense view (library, queue, storage) is shown on a wide viewport
- **THEN** its tables/cards expand to use the available content width rather than being constrained to a narrow centered column

#### Scenario: Reading column stays readable

- **WHEN** chapter prose is displayed
- **THEN** the prose column is capped at a readable max-width even on a wide viewport

#### Scenario: Layout adapts on small viewports

- **WHEN** the viewport is narrow
- **THEN** the navigation collapses and content reflows to a single column

### Requirement: Non-blocking action feedback

The UI SHALL report the outcome of a user action (success or failure) via a transient toast notification instead of relying solely on a full-page reload.

#### Scenario: Toast on enqueue

- **WHEN** a user starts a crawl, translate, or build action
- **THEN** a toast appears confirming the job was enqueued, including identifying information for the job
