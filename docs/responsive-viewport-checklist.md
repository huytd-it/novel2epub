# Manual viewport checklist

Manual QA for the responsive UI. Run `uvicorn app.main:app --reload --port 8010`,
then walk each breakpoint below. Automated markup/contract coverage lives in
`tests/test_responsive_ui.py` (and `tests/test_responsive_phase2.py`) — this
checklist is for the *visual/interaction* behavior those tests can't see.

## Breakpoints

| Viewport | How | What you are checking |
|----------|-----|-----------------------|
| 320 × 568 | DevTools → iPhone SE | smallest supported phone |
| 375 × 667 | DevTools → iPhone 12/13 | common phone |
| 414 × 896 | DevTools → iPhone 11 Pro Max / device toolbar | large phone |
| 640 × 400 | drag the resize handle | `sm` boundary |
| 768 × 1024 | DevTools → iPad | `md` boundary (desktop nav/drawer swap) |
| 900 × 1000 | drag past 768 | reader `@media (max-width: 900px)` boundary |
| 1280 × 800 | desktop | baseline regression |
| 1920 × 1080 | desktop | wide desktop |

Also toggle **mobile emulation** (device toolbar) and, where available, the
**dark theme** (button top-right) at 375 and 768 — responsive CSS is duplicated
for `dark:` variants and both must hold.

---

## 1. Global header + mobile drawer

Open any non-reader page (e.g. `/`, `/sources`).

- [ ] **≤ 767px:** the hamburger (`#drawer-open-btn`) is the only nav control;
  the desktop link row is hidden. At ≥ 768px the hamburger disappears and the
  full link row returns — no gap or jump in header height.
- [ ] Tap the hamburger: the drawer slides in from the left, backdrop dims the
  page, body scroll locks (no background scrolling).
- [ ] Drawer contains **all 8 routes**: Thư viện, Nguồn, Lưu trữ, Tự động hóa,
  Từ điển chung, Bảng điều khiển, Hàng đợi, Nhật ký — identical to desktop.
- [ ] Active route is highlighted in the drawer.
- [ ] Close via: ✕ button, tapping the backdrop, **Esc**, and reopening the
  hamburger. Focus returns to the hamburger after close.
- [ ] **Tab** inside the open drawer loops within the drawer (no tab escape);
  **Shift+Tab** loops backwards.
- [ ] `aria-expanded` on the hamburger flips with the drawer (visible in the
  accessibility panel / element inspector).
- [ ] Cross the **768px breakpoint while the drawer is open** (resize window):
  the drawer closes itself, scroll lock releases, no stray backdrop.
- [ ] Safe areas: with iPhone-style notch emulation the drawer panel content is
  not clipped by the home indicator.

## 2. Reader minimal shell + tools

Open any chapter (`/ebooks/<slug>/read/<n>`).

- [ ] Header/footer of the app are gone; the page is a clean reading view.
- [ ] At 320: the bottom chapter-nav and the top toolbar row still fit. The
  auxiliary tools (Edit/Raw/Compare/…, `.reader-nav-right`) scroll
  horizontally *inside* the toolbar — the page itself never scrolls sideways.
- [ ] Chapter selector fits and remains usable at 375 and 320.
- [ ] Open TOC (T): sidebar ≤ 300px at ≤ 900px, full height, closes via Esc /
  ✕ / backdrop.
- [ ] Open search (Ctrl+Shift+F): the two inputs wrap onto separate lines on
  phones; results list scrolls vertically only.
- [ ] Open notes panel (N): on phones it becomes a **bottom sheet** (≤ 60vh);
  on tablets/desktop a right drawer (≤ 92vw). Textarea never overflows the
  viewport width.
- [ ] Reading font size / content width behave on 320 vs 900.

## 3. Settings tabs

Open `/ebooks/<slug>/settings`.

- [ ] **≤ 767px:** a `<select>` + a heading replace the tab row. Switching the
  select swaps the panel **and** updates the heading.
- [ ] **≥ 768px:** the desktop tab bar appears; the select/heading are hidden.
- [ ] All 6 tabs work in both modes; selected tab survives reload (session).
- [ ] Each panel's bottom action row wraps cleanly (no clipped buttons) at 320.
- [ ] Mobile keyboard does not cover the focused input in a panel.

## 4. Responsive tables (card mode)

Tables: library (`/`), chapters (`/ebooks/<slug>`), queue (`/queue`),
sources, automation, idioms, characters, logs.

- [ ] **≤ 767px** each table becomes stacked "cards": one record = one card,
  `<thead>` gone, each cell shows its **column label** above the value.
- [ ] Hidden-at-small-width columns (e.g. Tác giả, Cat., Bắt đầu, Slug) are
  *restored* in card mode — nothing important disappears.
- [ ] Columns without a header (checkbox / spacer) show no bogus label.
- [ ] Long content (URLs, selector strings, log lines) wraps or truncates —
  no horizontal page scroll.
- [ ] **≥ 768px** the same tables return to normal column layout.
- [ ] Library (`/`): search box grows full-width on phones; column filters
  (sources/automation, `[data-dt]`) wrap onto their own row; the result count
  stays visible.
- [ ] Chapter table (`/ebooks/<slug>`): row actions collapse behind the "⋯"
  menu (see §5); the bulk "Thêm" menu and modals still open.

## 5. Action menus (mobile "⋯" row dropdown)

Queue (and any `.actions-menu` row).

- [ ] **≥ 768px:** action buttons are inline in the row, no "⋯".
- [ ] **≤ 767px:** buttons collapse behind the "⋯" toggle. Tapping it opens
  that row's panel **and closes any other open one**.
- [ ] `aria-expanded` on the toggle reflects open/closed.
- [ ] Clicking anywhere outside closes it; Esc closes it.
- [ ] The panel is not clipped by the table's horizontal scroll container and
  does not overflow the right edge of the viewport.

## 6. Queue pagination

`/queue` with enough jobs to paginate.

- [ ] **Two** pagination bars (top + bottom) show/hide and update together.
- [ ] Previous/Next/Page-size work from **both** bars; info text matches.
- [ ] No duplicate-`id` console warnings; the bars rely on `data-role` only.
- [ ] At 320 the bars wrap without overlapping the filter row.

## 7. Modals & canvases

Open each: import config (library), delete ebook, test source (sources),
preset editor canvas (sources), add automation, log viewer (queue), manual
chapter + AI setup (chapters page).

- [ ] Dialog is centered with visible backdrop; **Esc** and backdrop click
  close it; body scroll locks while open.
- [ ] Focus moves into the dialog on open and returns to the opener on close;
  **Tab** is trapped inside.
- [ ] Width never exceeds the viewport (`max-w-*`): at 320 the modal leaves
  visible gutters on both sides; the canvas fills the width with no clipping.
- [ ] Long content scrolls **inside** the dialog (max height), never the page.
- [ ] Each dialog announces a title (`aria-labelledby`) — check with a screen
  reader / accessibility snapshot.

## 8. Horizontal overflow sweep

On every page at 320 and 375, in light + dark:

- [ ] No horizontal scrollbar on `<html>`/`<body>` (view from the root).
- [ ] Fixed overlays (drawer, canvas, toast, confirm) never push the page
  wider (`html/body { overflow-x: clip }`).
- [ ] `<pre>`/log blocks and code columns wrap or scroll inside their own
  container.

## 9. Touch ergonomics

- [ ] Buttons/links are large enough to tap (≥ ~40px) on the principal pages.
- [ ] No double-tap zoom on rapid taps (buttons have `touch-action`).
- [ ] Text doesn't auto-inflate when rotating to landscape.
