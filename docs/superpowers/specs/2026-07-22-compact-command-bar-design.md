# Compact Chapter Command Bar Design

Date: 2026-07-22

## Goal

Reduce the width and visual overload of the fixed selected-chapter command bar while preserving every existing batch action, confirmation, selection, and outcome-feedback behavior.

## Scope

In scope:

- Compact the fixed command bar in `app/templates/ebook.html`.
- Keep high-frequency actions directly visible.
- Move low-frequency actions into one grouped `Thêm` dropdown.
- Add one shared AI configuration modal for `Dịch TOC` and `Biên tập`.
- Preserve current endpoints, selected-index handling, confirmations, toasts, and outcome summaries.

Out of scope:

- Changing action semantics or backend configuration.
- Adding UI dependencies.
- Changing the top-level ebook header or filters.

## Command Bar

The active command bar contains only:

- `Đã chọn N` selection count.
- `Crawl`.
- `Dịch`.
- `Build EPUB`.
- `Ghi đè` checkbox.
- `Thêm` menu trigger.

The command bar remains hidden/minimized with zero selection and fixed while selection is nonzero.

## Thêm Menu

The menu groups actions with separators and headings:

### AI & Nội Dung

- `Thiết lập AI...` opens the shared AI modal.
- `Sạch Hán` runs immediately.
- `Glossary` runs immediately.

### TOC

- `Bỏ qua` runs immediately.
- `Hiện lại` runs immediately.
- `Xem trước index` toggles existing preview state.
- `Đánh index lại` follows the existing confirmation/action flow.

### Xuất / Nhập

- `Xuất biên tập`.
- `Xuất raw`.
- `Nhập`.

### Nguy Hiểm

- `Xóa dịch`.
- `Xóa raw`.

Dangerous menu items keep danger styling and invoke the global confirmation dialog before requests.

The menu closes after triggering an action, when the user clicks outside it, or presses Escape.

## Shared AI Modal

The modal has:

- Action selector: `Dịch TOC` or `Biên tập`.
- Backend selector: `OpenAI` or `Local NMT`.
- `Ghi đè` checkbox synchronized with the command bar checkbox.
- Dynamic explanatory text:
  - Dịch TOC translates selected chapter titles.
  - Biên tập uses OpenAI for an edit draft or Local NMT to translate again.
- Cancel button and action-specific submit button.

On submit, the modal dispatches the existing selected `Dịch TOC` or `Biên tập` form. It must preserve selected indexes and filter-independent selection state. It closes only after the form is accepted, while request errors remain visible through existing toast behavior.

## Responsive Behavior

- Desktop: one compact row.
- Mobile: selection count, Crawl, and Dịch occupy the first row; Build EPUB, Ghi đè, and Thêm wrap to a second row as necessary.
- The bar must not use horizontal scrolling for action controls.

## Accessibility and Feedback

- The `Thêm` trigger uses `aria-expanded` and an accessible menu label.
- Escape closes the menu or AI modal, prioritizing the currently open surface.
- Menu and modal actions reuse existing selected-action guards: zero selection shows a warning toast without sending a request.
- Every action retains existing success/error/queued/completion feedback.

## Verification

- Confirm Crawl, Dịch, Build EPUB, and Ghi đè remain directly reachable.
- Confirm each moved menu action sends the same form/API action as before.
- Confirm AI modal changes backend/action/override values sent by existing forms.
- Confirm outside click and Escape close the menu; Escape closes the modal.
- Confirm destructive menu actions require confirmation.
- Check desktop and narrow mobile layout without action-bar horizontal scrolling.
