"""Contract/markup tests for the responsive UI work.

Static markup + shared-JS contracts only (no browser needed):

  * mobile drawer — ARIA, full nav route parity with the desktop nav, focus
    hooks / aria-hidden managed by the shared overlay manager in app.js;
  * reader minimal shell marker (base.html half of the contract);
  * settings — mobile select + desktop tab switcher visibility;
  * principal responsive tables — opt-in classes and the *dynamic label
    contract* (every content cell of a JS-rendered row carries an explicit
    `data-label`, so the card-mode pseudo-elements stay named on mobile);
  * datatable.js label generation for `[data-dt]` server-rendered tables;
  * action-menu triggers/containers (mobile "⋯" dropdown);
  * no duplicate static ids — with special care for the Queue pagination
    (two bars, shared via `data-role`, never ids);
  * modal/canvas viewport classes + dialog ARIA;
  * scan of the newly-changed templates for uncontrolled fixed/min widths
    (narrow allowlist).

Complementary to tests/test_responsive_phase2.py (shared hooks such as
`mobile-actions` / `safe-panels` and the index/ebook table-class assertions
live there and are intentionally not repeated here).
"""
import re
from pathlib import Path

ROOT = Path(__file__).parents[1] / "app" / "templates"
STATIC = Path(__file__).parents[1] / "app" / "static"

# Templates touched by the responsive overhaul — the fixed-width scan runs
# over exactly this set.
CHANGED_TEMPLATES = [
    "_delete_ebook_modal.html",
    "automation.html",
    "base.html",
    "chapter.html",
    "characters.html",
    "dashboard.html",
    "ebook.html",
    "glossary.html",
    "idioms.html",
    "index.html",
    "library_new.html",
    "logs.html",
    "queue.html",
    "reader.html",
    "settings.html",
    "settings_ai.html",
    "settings_crawl.html",
    "settings_novel.html",
    "settings_output.html",
    "settings_reader.html",
    "settings_translate.html",
    "sources.html",
    "storage.html",
]

ALL_TEMPLATES = [p.name for p in sorted(ROOT.glob("*.html"))]

BASE = (ROOT / "base.html").read_text(encoding="utf-8")
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
DATATABLE_JS = (STATIC / "datatable.js").read_text(encoding="utf-8")

READER = (ROOT / "reader.html").read_text(encoding="utf-8")
SETTINGS = (ROOT / "settings.html").read_text(encoding="utf-8")
QUEUE = (ROOT / "queue.html").read_text(encoding="utf-8")
INDEX = (ROOT / "index.html").read_text(encoding="utf-8")
SOURCES = (ROOT / "sources.html").read_text(encoding="utf-8")
AUTOMATION = (ROOT / "automation.html").read_text(encoding="utf-8")
IDIOMS = (ROOT / "idioms.html").read_text(encoding="utf-8")
LOGS = (ROOT / "logs.html").read_text(encoding="utf-8")
CHARACTERS = (ROOT / "characters.html").read_text(encoding="utf-8")
EBOOK = (ROOT / "ebook.html").read_text(encoding="utf-8")


def _read(name):
    return (ROOT / name).read_text(encoding="utf-8")


def _script_blocks(text):
    return [m.group(1) for m in re.finditer(r"<script[^>]*>(.*?)</script>", text, re.S)]


def _id_attribute_re():
    return re.compile(r'(?<![\w-])id="([^"]+)"')


# ── Mobile drawer: ARIA, nav routes, focus hooks ─────────────────────────────
def test_drawer_trigger_carries_aria_controls_expanded_and_label():
    assert 'id="drawer-open-btn"' in BASE
    assert 'aria-controls="n2e-drawer"' in BASE
    assert 'aria-expanded="false"' in BASE
    assert 'aria-label="Mở menu điều hướng"' in BASE
    assert 'class="md:hidden p-1.5 -ml-1 rounded-lg' in BASE  # only visible below `md`


def test_drawer_container_has_dialog_semantics():
    assert '<div id="n2e-drawer" class="n2e-drawer" hidden role="dialog" aria-modal="true" aria-label="Menu điều hướng">' in BASE
    assert '<div class="n2e-drawer-backdrop" data-close-drawer>' in BASE
    assert 'class="n2e-drawer-close" data-close-drawer aria-label="Đóng menu"' in BASE


def _routes_in(snippet):
    return set(re.findall(r'href="(/[^"]*)"', snippet))


def test_drawer_and_desktop_nav_expose_the_same_route_set():
    drawer_start = BASE.index('<nav class="n2e-drawer-nav"')
    drawer_nav = BASE[drawer_start:BASE.index("</nav>", drawer_start)]
    desktop_start = BASE.index('<nav class="hidden md:flex')
    desktop_nav = BASE[desktop_start:BASE.index("</nav>", desktop_start)]

    expected = {"/", "/sources", "/storage", "/wireguard", "/automation",
                "/idioms", "/dashboard", "/queue", "/logs"}
    assert _routes_in(drawer_nav) == expected
    assert _routes_in(desktop_nav) == expected
    # Both navs announce themselves the same way for screen readers.
    assert 'aria-label="Main navigation"' in drawer_nav
    assert 'aria-label="Main navigation"' in desktop_nav


def test_app_js_manages_focus_and_aria_hidden_for_overlays():
    assert "FOCUSABLE_SELECTOR" in APP_JS
    assert 'a[href], button:not([disabled])' in APP_JS
    assert "[data-autofocus], [autofocus]" in APP_JS
    assert "_n2eLastFocus" in APP_JS          # remembered opener …
    assert "restoreFocus" in APP_JS           # … and restored on close
    assert "trapTabFocus" in APP_JS           # Tab is trapped inside the overlay
    assert 'el.setAttribute("aria-hidden", "false")' in APP_JS
    assert 'el.setAttribute("aria-hidden", "true")' in APP_JS


def test_drawer_aria_expanded_synced_and_escape_closes():
    assert 'btn.setAttribute("aria-expanded", "true")' in APP_JS
    assert 'btn.setAttribute("aria-expanded", "false")' in APP_JS
    assert "top.classList.contains('n2e-drawer')" in APP_JS  # Escape → closeDrawer
    assert 'matchMedia("(min-width: 768px)")' in APP_JS       # breakpoint cleanup


# ── Reader minimal shell marker (base.html half) ──────────────────────────────
def test_reader_minimal_shell_css_lives_in_base():
    # Phase2 asserts reader.html adds the marker; here we pin the base.html
    # CSS that reacts to it (the other half of the same contract).
    assert "html.reader-page header { display: none; }" in BASE
    assert "html.reader-page main { padding-top: 0; }" in BASE


# ── Settings: mobile select + desktop tabs ───────────────────────────────────
def test_settings_mobile_select_is_md_hidden_with_aria_label():
    # Reciprocal of phase2's `hidden md:flex` desktop-tabs assertion.
    assert '<div class="md:hidden mb-3">' in SETTINGS
    assert 'id="settings-tab-select"' in SETTINGS
    assert 'aria-label="Chọn mục cài đặt"' in SETTINGS
    assert 'id="settings-tab-heading"' in SETTINGS
    assert "md:hidden text-lg font-semibold" in SETTINGS


# ── Principal responsive tables ───────────────────────────────────────────────
def test_queue_table_opt_in_responsive_classes():
    assert '<table class="table table-responsive table-grid-mobile" id="queue-table">' in QUEUE
    assert ".table-responsive.table-grid-mobile > thead" in BASE
    assert "display: table-header-group" in BASE


def test_dt_tables_opt_in_responsive_and_datatable():
    for text in (SOURCES, AUTOMATION):
        assert "table-responsive" in text
        assert "table-grid-mobile" in text
        assert "data-dt" in text
        assert "data-dt-sort" in text
    # Per-column filter opt-in is supported by datatable.js and used by at
    # least one server-rendered table (it is optional on a per-column basis).
    assert "data-dt-filter" in AUTOMATION


def test_secondary_editing_tables_opt_in_responsive():
    for text in (IDIOMS, LOGS, CHARACTERS):
        assert "table-responsive" in text
        assert "table-grid-mobile" in text


def _assert_row_labels(template, file_label):
    """Dynamic label contract: every content cell of a JS row is labelled.

    The leading checkbox/spacer column and full-width `colspan` cells are the
    only cells allowed to skip `data-label` — every other cell must carry one
    so card-mode keeps a column name above the value.
    """
    cells = re.findall(r"<td[^>]*>.*?</td>", template, re.S)
    if not cells:
        return  # not a data row (e.g. a thead row) — nothing to check
    content = [c for c in cells[1:] if "colspan" not in c] if len(cells) > 1 else []
    unlabeled = [c for c in content if "data-label=" not in c]
    assert not unlabeled, f"{file_label}: {len(unlabeled)} content cell(s) missing data-label"


def _check_row_templates_in_script(file_label, text):
    for block in _script_blocks(text):
        for m in re.finditer(r"<tr[^>]*>.*?</tr>", block, re.S):
            _assert_row_labels(m.group(0), file_label)


def test_queue_dynamic_rows_carry_explicit_data_labels():
    _check_row_templates_in_script("queue.html", QUEUE)
    # And they mirror the visible column headers exactly.
    for label in ("Label", "Cat.", "Trạng thái", "Bắt đầu", "Kết thúc / Thời lượng", "Thao tác"):
        assert f'data-label="{label}"' in QUEUE


def test_ebook_dynamic_rows_carry_explicit_data_labels():
    _check_row_templates_in_script("ebook.html", EBOOK)


def test_idioms_dynamic_rows_carry_explicit_data_labels():
    _check_row_templates_in_script("idioms.html", IDIOMS)


def test_logs_dynamic_rows_carry_explicit_data_labels():
    _check_row_templates_in_script("logs.html", LOGS)


def test_characters_dynamic_rows_carry_explicit_data_labels():
    _check_row_templates_in_script("characters.html", CHARACTERS)


def test_server_rendered_responsive_rows_carry_explicit_data_labels():
    # Server-rendered rows also carry labels up front (data-dt would backfill,
    # but explicit is the contract so card-mode works before JS runs).
    for text in (SOURCES, AUTOMATION, INDEX):
        assert "data-label=" in text


# ── datatable.js label generation ─────────────────────────────────────────────
def test_datatable_backfills_labels_from_header_text():
    assert "td.dataset.label = norm(th.textContent)" in DATATABLE_JS
    assert "!td.dataset.label && th && norm(th.textContent)" in DATATABLE_JS


def test_datatable_preserves_explicit_labels_and_is_idempotent():
    assert "table.__dt" in DATATABLE_JS
    assert 'table[data-dt]' in DATATABLE_JS
    assert 'data-dt-placeholder' in DATATABLE_JS


def test_datatable_toolbar_layout_is_responsive():
    assert ".dt-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; margin-bottom: 0.5rem; }" in BASE
    assert ".dt-toolbar .dt-search { flex: 1 1 100%; min-width: 0; }" in BASE
    assert "@media (min-width: 768px)" in BASE
    assert ".dt-toolbar .dt-search { flex: 0 0 auto; width: 16rem; }" in BASE


# ── Action menu (mobile "⋯" row dropdown) ─────────────────────────────────────
def test_action_menu_shared_css_contract():
    assert ".actions-menu { position: relative; display: inline-flex; }" in BASE
    assert ".actions-menu-toggle { display: none; }" in BASE
    assert ".actions-menu-panel { display: inline-flex; align-items: center; flex-wrap: wrap;" in BASE
    assert ".actions-menu.open .actions-menu-panel { display: flex; }" in BASE
    # Mobile block: hide the inline buttons, show the toggle + anchored panel.
    assert "@media (max-width: 767.98px)" in BASE
    assert ".actions-menu-toggle { display: inline-flex; }" in BASE
    assert ".actions-menu-panel {" in BASE
    assert "position: absolute;" in BASE


def test_queue_row_builds_action_menu_trigger_and_container():
    assert 'class="actions-menu-toggle" data-role="menu-toggle"' in QUEUE
    assert 'aria-label="Thao tác"' in QUEUE
    assert 'aria-haspopup="true"' in QUEUE
    assert 'aria-expanded="${menuOpen}"' in QUEUE
    assert '<div class="actions-menu-panel">' in QUEUE


def test_app_js_toggles_action_menus_and_syncs_aria():
    assert "closest('.actions-menu-toggle')" in APP_JS
    assert "menu.classList.toggle('open', willOpen)" in APP_JS
    assert "toggle.setAttribute('aria-expanded', String(willOpen))" in APP_JS
    assert "function closeActionMenus()" in APP_JS
    assert "if (!e.target.closest('.actions-menu')) closeActionMenus();" in APP_JS


# ── No duplicate ids (queue pagination uses data-role) ────────────────────────
def test_queue_pagination_bars_use_data_role_never_ids():
    assert QUEUE.count('data-role="pagination"') == 2  # top + bottom share one state
    for m in re.finditer(r'<div class="pagination-bar[^"]*"[^>]*data-role="pagination"[^>]*>.*?</div>', QUEUE, re.S):
        bar = m.group(0)
        for role in ("prev", "info", "next", "size"):
            assert f'data-role="{role}"' in bar
        assert 'id="' not in bar  # ids would collide between the two bars


def test_static_ids_are_unique_within_every_template():
    # `<script>` bodies are excluded — JS string literals are not live markup.
    for name in ALL_TEMPLATES:
        text = re.sub(r"<script[^>]*>.*?</script>", "", _read(name), flags=re.S)
        ids = _id_attribute_re().findall(text)
        dupes = {i for i in ids if ids.count(i) > 1}
        assert not dupes, f"{name}: duplicate id(s) {sorted(dupes)}"


def test_index_include_does_not_collide_ids_with_shared_modal():
    combined = INDEX + "\n" + _read("_delete_ebook_modal.html")
    ids = _id_attribute_re().findall(combined)
    dupes = {i for i in ids if ids.count(i) > 1}
    assert not dupes, f"index.html + _delete_ebook_modal.html collide on {sorted(dupes)}"


# ── Modal / canvas viewport classes + ARIA ────────────────────────────────────
def test_modal_viewport_classes_are_viewport_safe():
    assert ".modal-backdrop { @apply fixed inset-0 bg-black/40 backdrop-blur-sm z-40 flex items-center justify-center p-4 hidden; }" in BASE
    assert ".modal-backdrop.open { @apply flex; }" in BASE
    assert "max-h-[90vh] overflow-y-auto w-full max-w-lg;" in BASE
    assert ".modal-sm { @apply max-w-md; }" in BASE
    assert ".modal-lg { @apply max-w-3xl; }" in BASE
    assert ".modal-xl { @apply max-w-5xl; }" in BASE
    assert ".modal-backdrop[hidden], .canvas-backdrop[hidden] { display: none !important; }" in BASE


def test_canvas_viewport_classes_are_viewport_safe():
    assert ".canvas-backdrop { @apply fixed inset-0 bg-black/35 z-40 flex justify-end hidden; }" in BASE
    assert ".canvas-backdrop.open { @apply flex; }" in BASE
    assert "w-full max-w-xl md:max-w-2xl lg:max-w-3xl h-full overflow-y-auto" in BASE
    assert ".canvas-backdrop.open .canvas { @apply translate-x-0; }" in BASE


_MODAL_BACKDROP_RE = re.compile(
    r'<div id="(?P<id>[^"]+)" class="modal-backdrop"[^>]*>'
    r"(?P<body>.*?)"
    r'<(?P<tag>section|div)\s+class="modal(?P<cls>[^"]*)"(?P<attrs>[^>]*)>',
    re.S,
)
_CANVAS_BACKDROP_RE = re.compile(
    r'<div id="(?P<id>[^"]+)" class="canvas-backdrop"[^>]*>'
    r"(?P<body>.*?)"
    r'<div\s+class="canvas(?P<cls>[^"]*)"(?P<attrs>[^>]*)>',
    re.S,
)


def _assert_dialog_aria(attrs, text, container_id):
    role_ok = 'role="dialog"' in attrs or 'role="alertdialog"' in attrs
    assert role_ok, f"{container_id}: missing role=dialog/alertdialog"
    assert 'aria-modal="true"' in attrs, f"{container_id}: missing aria-modal=true"
    labelled = re.search(r'aria-labelledby="([^"]+)"', attrs)
    assert labelled, f"{container_id}: missing aria-labelledby"
    assert f'id="{labelled.group(1)}"' in text, f"{container_id}: aria-labelledby target missing"


def test_every_modal_carries_dialog_aria():
    for name in ALL_TEMPLATES:
        text = _read(name)
        for m in _MODAL_BACKDROP_RE.finditer(text):
            _assert_dialog_aria(m.group("attrs"), text, m.group("id"))


def test_canvas_carries_dialog_aria():
    for name in ALL_TEMPLATES:
        text = _read(name)
        for m in _CANVAS_BACKDROP_RE.finditer(text):
            _assert_dialog_aria(m.group("attrs"), text, m.group("id"))


# ── Uncontrolled fixed/min widths in changed templates ────────────────────────
# Only widths >= MIN_DANGER_PX are flagged (anything below cannot overflow a
# 320px viewport even stacked). Any flagged width must be in the narrow
# allowlist below; every entry is a width that is *controlled* elsewhere
# (viewport clamp, media override, or proportional table layout).
MIN_DANGER_PX = 160
WIDTH_RE = re.compile(
    r'(?<![\w-])(?:min-)?width:\s*(\d+)px'
    r'|(?<![\w-])w-\[(\d+)px\]'
    r'|(?<![\w-])min-w-\[(\d+)px\]'
)
WIDTH_ALLOWLIST = {
    # .slug-input min-width — overridden to `min-width: 0` at <=640px.
    "library_new.html": {200},
    # reader panels/search — vw-clamped or media-overridden (see docs).
    "reader.html": {200, 240, 300, 340},
    # <th> hints on `table-layout: fixed; width: 100%` — scaled proportionally.
    "sources.html": {180, 200, 220, 320},
}


def test_no_uncontrolled_fixed_or_min_widths_in_changed_templates():
    violations = []
    for name in CHANGED_TEMPLATES:
        allowed = WIDTH_ALLOWLIST.get(name, set())
        for lineno, line in enumerate(_read(name).splitlines(), 1):
            if "@media" in line:  # breakpoint guards, not element widths
                continue
            for m in WIDTH_RE.finditer(line):
                value = next(int(g) for g in m.groups() if g is not None)
                if value >= MIN_DANGER_PX and value not in allowed:
                    violations.append(f"{name}:{lineno}: {m.group(0)}")
    assert not violations, "uncontrolled fixed/min widths:\n" + "\n".join(violations)
