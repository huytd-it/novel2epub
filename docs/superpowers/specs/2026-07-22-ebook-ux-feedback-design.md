# Ebook UX Redesign and Global Feedback Design

Date: 2026-07-22

## Goal

Redesign the ebook management page for heavy chapter-management workflows and replace browser-native `alert()` / `confirm()` usage across the Web UI with consistent in-app feedback.

The primary user pain is selecting many chapters, scrolling through a long table, and losing access to selected actions. The secondary pain is silent or browser-default feedback after actions, which makes success and failure unclear.

## Scope

In scope:

- Redesign `app/templates/ebook.html` as a dense, operational workflow screen.
- Make selected chapter actions fixed or sticky so they remain available while scrolling.
- Increase checkbox visual size and click target to about 2x the current interaction size.
- Add clear selected-row styling and visible selection count.
- Add reusable toast and confirmation dialog helpers in shared Web UI JavaScript.
- Replace `alert()` and `window.confirm()` in existing Web UI templates/static scripts with in-app toast/dialog flows.
- Ensure every user-triggered action gives success, error, or started feedback.

Out of scope:

- Rewriting the entire app shell/navigation.
- Changing backend job semantics or API response contracts unless a tiny response message improvement is necessary.
- Adding new dependencies for UI components.

## Design Read

This is a web-app data/workflow screen for power users managing many novel chapters. The design should be compact, predictable, and fast rather than marketing-like.

Design dials:

- Variance: 4 — structured, not experimental.
- Motion: 2 — minimal animation, only feedback transitions.
- Density: 8 — optimized for large tables and batch operations.

## Ebook Page Layout

### Header

The ebook header should become a compact information panel:

- Cover thumbnail, title, author, slug, chapter count.
- Crawl and translation status badges.
- Translation/editor model chips.
- Primary actions grouped by intent: Read/Publish, Crawl/Translate, Manage.

The goal is to reduce vertical space above the table while keeping important status visible.

### Search and Filter Toolbar

The filter toolbar should be sticky near the top of the viewport while scrolling the chapter table.

It should include:

- Search input.
- Sort and direction controls.
- Raw/translated/missing/skipped filters.
- Page size or pager controls near the table navigation.

Filters remain client-side as they are today. LocalStorage persistence stays unchanged.

### Selected Actions

The selected action toolbar should be redesigned as a command bar:

- Hidden or visually minimized when zero chapters are selected.
- Fixed or sticky when at least one chapter is selected.
- Always shows selected count.
- Primary actions appear first: Crawl, Dịch, Build EPUB.
- Destructive actions are grouped and visually separated: Xóa dịch, Xóa raw.
- TOC and AI actions remain available but grouped to reduce scanning cost.
- Options such as `Ghi đè` and backend selection remain visible inside the command bar.

The command bar should work at both desktop and mobile widths. On small screens, actions may wrap or scroll horizontally, but selection count and primary actions must stay visible.

### Chapter Table

The chapter table should be easier to scan and use:

- Sticky table header.
- Larger checkbox and hit area in the first column.
- Selected rows receive a subtle highlighted background.
- Per-row actions remain compact.
- Status and missing fields remain visible.
- Existing client-side render/pagination logic remains the base implementation.

## Global Feedback Layer

### Toasts

The existing `toast(message, kind)` helper in `app/static/app.js` should become the standard transient feedback mechanism.

Required behavior:

- Supports `success`, `error`, `info`, and optionally `warning`.
- Escapes message text before inserting into DOM.
- Has accessible live region semantics through the existing toast region.
- Auto-dismisses after a short duration.
- Can be called safely if the region exists; no hard failure if absent.

### Confirmation Dialog

Add a shared async confirmation helper, for example:

```js
confirmDialog(message, options) -> Promise<boolean>
```

Required behavior:

- Replaces `window.confirm()` for destructive or costly actions.
- Uses the existing modal/backdrop styling pattern where possible.
- Has confirm and cancel buttons.
- Supports destructive styling for dangerous actions.
- Closes on Escape and cancel/backdrop.
- Returns `true` only when the user confirms.

### Action Feedback

Every form/API action should produce feedback:

- Before/after job-starting actions: toast that the job/action was submitted or started.
- On HTTP error: toast with backend `detail` if present.
- On network error: toast `Lỗi kết nối mạng.`.
- On successful batch API mutation: toast success and refresh/update the visible state.
- On zero selected chapters: toast warning/info instead of alert.

Browser-native `alert()` and `confirm()` should not remain in Web UI code.

## Implementation Constraints

- Prefer editing existing files: `app/templates/ebook.html`, `app/static/app.js`, and any templates/scripts that currently call `alert()` or `confirm()`.
- Avoid new dependencies.
- Preserve existing endpoint URLs and form behavior.
- Keep progressive fallback reasonable: if JavaScript fails, server-rendered forms may still submit where they already did.
- Use semantic HTML where possible.

## Testing and Verification

Manual verification:

- Select rows, scroll, and confirm selected actions remain accessible.
- Check checkbox size and click target on desktop and narrow viewport.
- Run non-destructive selected actions and confirm success feedback appears.
- Trigger zero-selection action and confirm toast appears instead of alert.
- Trigger a destructive action and confirm in-app confirmation dialog appears.
- Cancel destructive dialog and confirm no request is sent.
- Force/network-simulate an API error if practical and confirm toast error appears.

Automated/light verification:

- Run existing tests: `pytest tests/ -v`.
- Search Web UI files for remaining `alert(` and `confirm(` usage.

## Risks

- The existing `ebook.html` script is large, so changes should be incremental and localized.
- Global confirm behavior can conflict with existing modal helpers if Escape/backdrop handling is not isolated.
- Sticky/fixed command bars can overlap content on small screens unless bottom padding is added when active.
