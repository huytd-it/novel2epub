# Ebook UX Redesign and Global Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the chapter-management workflow and replace all browser-native alerts/confirms in the Web UI with accessible in-app notifications and confirmation dialogs.

**Architecture:** Extend `base.html` and `app/static/app.js` with one global feedback layer: safe toast rendering, a reusable async confirmation dialog, and data-attribute-aware AJAX forms. Redesign `ebook.html` around a sticky filter surface and a responsive selected-chapter command bar while preserving its existing client-side TOC, pagination, and endpoint contracts. Migrate each existing template's direct browser dialogs to the shared helpers, including export/import popup windows with their own in-window feedback.

**Tech Stack:** Python 3.10+, FastAPI, Jinja2, vanilla JavaScript, Tailwind CDN utilities, pytest.

**Spec:** `docs/superpowers/specs/2026-07-22-ebook-ux-feedback-design.md`

## Global Constraints

- All user-facing UI copy remains Vietnamese and follows existing wording such as `Lỗi kết nối mạng.`.
- Add no dependencies; use current vanilla JS and Tailwind utility classes.
- Preserve existing form routes, APIs, client-side filtering, LocalStorage keys, and job semantics.
- Do not leave `alert(`, `window.alert(`, `confirm(`, or `window.confirm(` in `app/templates` or `app/static`.
- Use `textContent`, not `innerHTML`, for arbitrary toast or dialog messages.
- The selected command bar must remain reachable during table scroll and must not cover the last table rows on mobile.
- Verify with `python -m pytest tests/ -v` from `D:\Projects\novel2epub`.

---

### Task 1: Add the shared feedback primitives

**Files:**
- Modify: `app/templates/base.html:185-195, after main/toast region`
- Modify: `app/static/app.js:4-28, 85-143, 145-191, 203-214`

**Interfaces:**
- Produces: `toast(message, kind = "info")`, where `kind` is `success`, `error`, `info`, or `warning`.
- Produces: `confirmDialog(message, {confirmLabel, destructive} = {}) -> Promise<boolean>`.
- Produces: `showPopupMessage(document, message, kind)` for standalone export/import windows.

- [ ] **Step 1: Add the global confirmation dialog markup and warning styles**

Add a hidden `#confirm-dialog` modal backdrop to `app/templates/base.html` beside the existing toast region. Include `#confirm-dialog-message`, Cancel, and Confirm buttons. Add `toast-warning` and destructive-confirm button styling to the component layer, preserving the existing light/dark semantic tokens.

- [ ] **Step 2: Replace unsafe toast HTML construction with DOM nodes**

In `app/static/app.js`, replace the `el.innerHTML` message interpolation in `toast` with a fixed icon element plus a `span` whose `textContent` is `String(message)`. Add warning icon/border handling and keep the current auto-dismiss transition.

- [ ] **Step 3: Implement `confirmDialog`**

Add an async helper that writes the message with `textContent`, changes the confirm button label/style from its options, opens `#confirm-dialog`, focuses Cancel, and resolves once only. Resolve `true` on confirm and `false` on cancel, backdrop click, or Escape. Do not change the behavior of page-specific modals or canvases.

- [ ] **Step 4: Update the shared AJAX form helper**

Make the `data-ajax` submit listener await `confirmDialog(form.dataset.confirm, { destructive: form.dataset.confirmDanger === "true" })` instead of `window.confirm`. After a successful request, show `data-toast` if supplied; otherwise show `Đã hoàn tất thao tác.`. Continue surfacing HTTP `detail` and network errors through `toast`.

- [ ] **Step 5: Verify shared JavaScript and global scan**

Run: `node --check app/static/app.js`

Expected: exits with code `0`.

Run: `rg -n "\\b(window\\.)?(alert|confirm)\\s*\\(" app/static/app.js app/templates/base.html`

Expected: no matches.

- [ ] **Step 6: Commit**

```powershell
git add app/static/app.js app/templates/base.html
git commit -m "feat: add shared in-app feedback dialogs"
```

---

### Task 2: Redesign the ebook command workflow

**Files:**
- Modify: `app/templates/ebook.html:4-65, 93-353, 603-785, popup/import/publish handlers`

**Interfaces:**
- Consumes: `toast(message, kind)`, `confirmDialog(message, options)`, and existing `CHAPTERS_DATA`, `renderToc`, `paginate`, and form endpoints.
- Produces: a selected command bar whose active state is controlled by `refreshCheckedInfo()` and CSS class `has-selection`.

- [ ] **Step 1: Rework local layout styles and markup**

Replace the compact local layout with these surfaces while retaining existing form controls and form actions:

```html
<section class="ebook-overview">...</section>
<div class="toc-workspace">
  <form class="toc-filter-bar compact-toolbar">...</form>
  <div id="selected-command-bar" class="selected-actions" aria-live="polite">...</div>
  <div class="table-container toc-table-container">...</div>
</div>
```

Use a sticky filter bar below the global header, a sticky table header, and a fixed bottom command bar only while chapters are selected. Add bottom workspace padding while the command bar is active. On narrow viewports, allow the command actions to horizontally scroll while keeping the selected count and main Crawl/Dịch controls visible.

- [ ] **Step 2: Increase checkbox size and selected row affordance**

Replace the current `transform: scale(1.2)` selector with a shared local `.chapter-check`, `#check-all`, and `#selected-override` rule that gives controls a `1.5rem` visual box and a minimum `2.75rem` label/cell hit target. Add `.is-selected` row styling using existing brand surface tokens.

- [ ] **Step 3: Make selection state persistent through re-renders**

Add a module-level `selectedIndexes = new Set()` in `ebook.html`. Update checkbox change handlers to mutate it. In `buildChapterRow`, render `checked` when the index is in the set and add `is-selected` to the row. Update `check-all`, pagination, and `refreshCheckedInfo()` to operate on the set, so filtering, paging, and `renderToc()` do not silently discard the user selection.

- [ ] **Step 4: Replace ebook browser dialogs and add action feedback**

In the submit handler, replace zero-selection alerts with `toast(..., "warning")` and await `confirmDialog` for `data-confirm` forms. Show `toast("Đã gửi thao tác vào hàng đợi.", "success")` after accepted job actions. Preserve detailed API errors as error toasts.

For export/import popup windows, use `toast` in the parent window when a popup is blocked, and use `showPopupMessage(win.document, ...)` rather than `win.alert` inside the popup. For Reader publishing, replace every `alert`/`confirm` with parent `toast`/`confirmDialog`, including the no-changes response.

- [ ] **Step 5: Verify syntax and interaction behavior**

Run: `node --check app/static/app.js`

Expected: exits with code `0`.

Manually verify `/ebooks/<slug>`: select chapters on page 1, change page/filter, and confirm the count and checked rows persist; scroll to the bottom and confirm the command bar remains actionable; use a destructive action and confirm the in-app dialog appears; cancel it and verify no request is sent.

- [ ] **Step 6: Commit**

```powershell
git add app/templates/ebook.html
git commit -m "feat: redesign ebook chapter workflow"
```

---

### Task 3: Migrate settings, library, and queue feedback flows

**Files:**
- Modify: `app/templates/index.html:345-371`
- Modify: `app/templates/settings.html:174-208`
- Modify: `app/templates/settings_crawl.html:220`
- Modify: `app/templates/settings_translate.html:462`
- Modify: `app/templates/queue.html:481-489`
- Modify: `app/templates/logs.html:141`

**Interfaces:**
- Consumes: global `toast` and async `confirmDialog`.
- Produces: no browser-native dialog calls in the listed templates.

- [ ] **Step 1: Convert confirmation-bearing handlers to async functions**

For each handler currently returning after `confirm(...)`, mark the owning click/submit callback `async` and replace the guard with:

```js
if (!await confirmDialog(message, { destructive: true })) return;
```

Use `destructive: false` for fetch/retry/sync operations and `destructive: true` for delete/remove/clear-log operations.

- [ ] **Step 2: Convert validation and caught exceptions to toasts**

Replace direct `alert(...)` error paths in settings templates with `toast(message, "error")`; show `toast(..., "success")` after their existing successful fetch/form completions if a handler currently has no visible response.

- [ ] **Step 3: Verify the migrated files are dialog-free**

Run:

```powershell
rg -n "\b(window\.)?(alert|confirm)\s*\(" app/templates/index.html app/templates/settings.html app/templates/settings_crawl.html app/templates/settings_translate.html app/templates/queue.html app/templates/logs.html
```

Expected: no matches.

- [ ] **Step 4: Commit**

```powershell
git add app/templates/index.html app/templates/settings.html app/templates/settings_crawl.html app/templates/settings_translate.html app/templates/queue.html app/templates/logs.html
git commit -m "feat: unify settings and queue feedback"
```

---

### Task 4: Migrate chapter, glossary, and reader feedback flows

**Files:**
- Modify: `app/templates/chapter.html:140-294, 710-1011`
- Modify: `app/templates/glossary.html:184-557`
- Modify: `app/templates/reader.html:1026`

**Interfaces:**
- Consumes: global `toast`, `confirmDialog`, and `showPopupMessage`.
- Produces: async submit/click guards that block requests unless confirmation resolves `true`.

- [ ] **Step 1: Replace inline chapter form `onsubmit` confirmations**

Remove inline `onsubmit="return confirm(...)"` attributes in `chapter.html`. Add `data-confirm` and `data-confirm-danger="true"` to these forms, then route them through an existing or small new delegated async submit handler that calls `confirmDialog` before sending. Keep normal non-JS form behavior possible by retaining method/action attributes.

- [ ] **Step 2: Replace chapter API alerts with explicit toasts**

Replace all chapter-page alert calls for job submission, glossary validation, API failure, and network failure with the correct `toast` kind. Add a success toast after each existing successful mutation path that currently changes the DOM silently.

- [ ] **Step 3: Replace glossary confirm and popup alerts**

Convert delete/clean handlers to await `confirmDialog`; use destructive styling for deletion and non-destructive styling for glossary cleanup. Replace popup-window `win.alert` calls in import/export flows with `showPopupMessage` and use parent `toast` for blocked popup errors.

- [ ] **Step 4: Replace reader dirty-editor confirmation**

Make the reader function that checks `openEditor.dirty` async and await `confirmDialog("Bỏ thay đổi chưa lưu ở đoạn đang mở?")`. Update each call site to await its boolean result before switching paragraph/editor state.

- [ ] **Step 5: Verify all remaining browser dialogs are removed**

Run: `rg -n "\b(window\.)?(alert|confirm)\s*\(" app/templates app/static`

Expected: no matches.

- [ ] **Step 6: Commit**

```powershell
git add app/templates/chapter.html app/templates/glossary.html app/templates/reader.html
git commit -m "feat: unify chapter glossary and reader feedback"
```

---

### Task 5: Regression verification and documentation audit

**Files:**
- Modify: `docs/superpowers/specs/2026-07-22-ebook-ux-feedback-design.md` only if implementation changes a documented behavior.

**Interfaces:**
- Verifies: the shared feedback layer and all migrated UI flows.

- [ ] **Step 1: Run the full Python suite**

Run: `python -m pytest tests/ -v`

Expected: all existing tests pass.

- [ ] **Step 2: Run final source scans**

Run:

```powershell
rg -n "\b(window\.)?(alert|confirm)\s*\(" app/templates app/static
```

Expected: no matches.

Run:

```powershell
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 3: Manually verify the representative workflows**

Check library bulk delete, settings source sync, queue clear-failed, chapter delete translation, glossary bulk delete, reader discard changes, and ebook batch delete. Each must show an in-app confirmation where applicable plus success/error feedback after its request.

- [ ] **Step 4: Commit any documentation correction**

```powershell
git add docs/superpowers/specs/2026-07-22-ebook-ux-feedback-design.md
git commit -m "docs: align ebook feedback design"
```

Only make this commit if the implementation required a spec correction; otherwise do not create an empty commit.
