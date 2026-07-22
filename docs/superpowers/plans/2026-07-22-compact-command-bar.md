# Compact Chapter Command Bar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the oversized fixed selected-chapter command bar with visible primary actions, a grouped dropdown, and a shared AI configuration modal.

**Architecture:** Keep every existing batch form and endpoint in `ebook.html`, but relocate low-frequency forms into an accessible `Thêm` menu. A single modal chooses the existing Dịch TOC or Biên tập form, backend, and override value, then dispatches that retained form through the current selected-action submit handler.

**Tech Stack:** Jinja2, vanilla JavaScript, existing Tailwind CDN utilities and global `openModal`/`closeModal`, `toast`, and `confirmDialog` helpers.

**Spec:** `docs/superpowers/specs/2026-07-22-compact-command-bar-design.md`

## Global Constraints

- Modify only `app/templates/ebook.html` unless a focused test requires another file.
- Keep existing routes, form attributes, IDs, selected-index serialization, confirmation dialogs, toasts, and job outcome summaries unchanged.
- Direct command-bar controls: selection count, Crawl, Dịch, Build EPUB, Ghi đè, and Thêm.
- Move all other command actions to grouped `Thêm` menu sections.
- Use no new dependencies and no horizontal scrolling for command controls.
- Dynamic UI strings must use existing safe toast/dialog helpers.

---

### Task 1: Restructure the command bar and menu

**Files:**
- Modify: `app/templates/ebook.html:250-340` and local command-bar CSS

**Interfaces:**
- Consumes: existing `.selected-action-form`, `.batch-form`, `#selected-override`, batch index input IDs, export/import button IDs, and reindex preview button ID.
- Produces: `#selected-more-menu` with `#selected-more-trigger`, action menu sections, and all former forms/buttons retained inside it.

- [ ] **Step 1: Add a failing source-layout test**

Add a focused assertion to the existing template/source test file that verifies the selected command bar has direct Crawl/Dịch/Build/Ghi đè controls, `#selected-more-trigger`, and menu section labels `AI & Nội dung`, `TOC`, `Xuất / Nhập`, and `Nguy hiểm`.

- [ ] **Step 2: Run the focused test**

Run: `python -m pytest tests/test_job_outcomes.py -v`

Expected: FAIL because the compact menu markup does not exist.

- [ ] **Step 3: Move existing action elements without changing contracts**

Keep these direct in `.selected-primary`: `#checked-info`, crawl form, translate form, build-selected form, and `#selected-override` label. Move the original cleanup, TOC, AI, export/import, and destructive forms/buttons into `#selected-more-menu` grouped by the specified headings. Preserve each form action, class, hidden input ID, `data-confirm`, and action button behavior.

- [ ] **Step 4: Add compact responsive CSS**

Replace `.selected-scroll` horizontal scrolling with a positioned menu panel. Desktop keeps a compact row. At narrow widths, use wrapping: count/Crawl/Dịch first, Build/Ghi đè/Thêm second. Apply danger styling to delete items and ensure menu panel layers above the fixed bar/table.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/test_job_outcomes.py -v`

Expected: PASS.

Run: `git diff --check`

Expected: no whitespace errors.

```powershell
git add app/templates/ebook.html tests/test_job_outcomes.py
git commit -m "feat: compact chapter command bar"
```

---

### Task 2: Add menu interaction and AI configuration modal

**Files:**
- Modify: `app/templates/ebook.html: command-bar markup and scripts`
- Test: `tests/test_job_outcomes.py`

**Interfaces:**
- Consumes: existing `openModal`, `closeModal`, selected-action delegated submit handler, `#bulk-backend-select` behavior, and retained Dịch TOC/Biên tập forms.
- Produces: `openSelectedMoreMenu`, `closeSelectedMoreMenu`, `openAiActionModal`, and an AI modal that dispatches a retained target form.

- [ ] **Step 1: Add failing behavior assertions**

Extend the Node-evaluated browser-helper fixture to assert the menu trigger exposes `aria-expanded`, the menu closes on outside click/Escape, and the AI modal maps action `translate-toc` to the existing translate-TOC form and `rewrite` to the existing rewrite form with selected backend/override values.

- [ ] **Step 2: Implement menu lifecycle**

Implement click toggle for `#selected-more-trigger`; close on outside pointer/click and Escape. Set `aria-expanded` truthfully. When a menu action button/form is activated, close the menu before the existing delegated submit/click flow runs.

- [ ] **Step 3: Add shared AI modal markup**

Add `#selected-ai-modal` using the existing `.modal-backdrop`/`.modal` structure. Include action select (`translate-toc`, `rewrite`), backend select (`openai`, `hachimimt`), synchronized override checkbox, dynamic description, Cancel, and a dynamic submit button.

- [ ] **Step 4: Dispatch retained forms from the modal**

On modal submit, select the retained form by stable ID/data attribute, set its existing backend hidden input and override state, close the modal only after invoking the normal form submit path, and preserve zero-selection guards/confirmation/toast handling. Sync either override checkbox when the other changes.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/test_job_outcomes.py -v`

Expected: PASS.

Run: `node --check app/static/app.js`

Expected: PASS.

```powershell
git add app/templates/ebook.html tests/test_job_outcomes.py
git commit -m "feat: add chapter AI action modal"
```

---

### Task 3: End-to-end regression verification

**Files:**
- Test: `tests/test_job_outcomes.py`

- [ ] **Step 1: Run focused tests**

Run: `python -m pytest tests/test_job_outcomes.py tests/test_job_queue.py tests/test_job_cancel.py -v`

Expected: PASS.

- [ ] **Step 2: Verify source contracts**

Run: `rg -n "selected-more-trigger|selected-ai-modal|batch-indexes-delete|batch-indexes-raw|btn-export-chapters|btn-import-chapters" app/templates/ebook.html`

Expected: all retained controls and new surfaces are found.

Run: `git diff --check`

Expected: no whitespace errors.

- [ ] **Step 3: Manual responsive verification**

On `/ebooks/<slug>`, select chapters and confirm direct actions work. Open/close Thêm via trigger, outside click, and Escape. Run a destructive menu action and verify confirmation. Open the AI modal for both actions, choose each backend/override state, and confirm requests/toasts follow the existing action flow. Check narrow viewport has no command-bar horizontal scroll.
