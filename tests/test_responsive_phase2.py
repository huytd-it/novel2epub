"""Responsive Phase 2: các lớp chia sẻ (responsive-table, mobile-actions, safe-panels)
được áp dụng đúng vào template; mọi ID/route/hành vi được giữ nguyên.

CSS/JS của các lớp chia sẻ nằm ở base.html/app.js (sub-project khác) — test này chỉ
xác nhận template đã treo đúng hook và không phá vỡ gì.
"""
import re
from pathlib import Path


ROOT = Path(__file__).parents[1] / "app" / "templates"


def _read(name):
    return (ROOT / name).read_text(encoding="utf-8")


INDEX = _read("index.html")
EBOOK = _read("ebook.html")
SETTINGS = _read("settings.html")
READER = _read("reader.html")
SETTINGS_PANELS = {
    "settings_novel.html": "/ebooks/{{ slug }}/settings/novel",
    "settings_crawl.html": "/ebooks/{{ slug }}/settings/source",
    "settings_translate.html": "/ebooks/{{ slug }}/settings/translate",
    "settings_ai.html": "/ebooks/{{ slug }}/settings/ai",
    "settings_output.html": "/ebooks/{{ slug }}/settings/output",
    "settings_reader.html": "/ebooks/{{ slug }}/settings/reader",
}


# ── index.html: thư viện ──────────────────────────────────────────────────────
def test_index_library_table_is_responsive_table():
    assert 'class="table responsive-table table-grid-mobile lib-table"' in INDEX
    assert 'id="lib-table"' in INDEX
    assert 'id="lib-tbody"' in INDEX
    assert 'id="select-all"' in INDEX


def test_index_rows_carry_data_labels_and_mobile_actions():
    for label in ["Tên", "Tác giả", "Slug", "Chương", "Tiến độ", "EPUB", "Thao tác"]:
        assert f'data-label="{label}"' in INDEX
    assert "mobile-actions" in INDEX


def test_index_keeps_one_row_per_ebook():
    # Một bản ghi = một <tr>; data-slug xuất hiện ở cả <tr> và checkbox trong dòng.
    assert INDEX.count('class="lib-row') == 1
    assert '<tr class="lib-row' in INDEX


def test_index_preserves_controls_and_routes():
    for needle in [
        'id="lib-search"',
        'id="lib-count"',
        'id="bulk-bar"',
        'action="/library/ebooks/bulk-action"',
        'id="lib-empty"',
        'id="import-config-btn"',
    ]:
        assert needle in INDEX


# ── ebook.html: bảng chương (row dựng bằng JS) ────────────────────────────────
def test_ebook_chapter_table_is_responsive_table():
    assert '<table id="chapter-table" class="table responsive-table table-grid-mobile scrollbar-thin"' in EBOOK
    assert 'id="chapter-table"' in EBOOK
    assert 'id="check-all"' in EBOOK


def test_ebook_dynamic_rows_have_explicit_data_labels():
    for label in ["Chọn", "#", "Tiêu đề", "Ký tự ZH", "Số từ", "Glossary", "Tổng chars", "Thao tác"]:
        assert f'data-label="{label}"' in EBOOK


def test_ebook_dynamic_row_stays_one_row_per_chapter():
    row_fn = EBOOK[EBOOK.index("function buildChapterRow"):EBOOK.index("function getFilteredData")]
    assert row_fn.count("<td") == 8
    assert row_fn.count("<tr ") == 1
    assert "mobile-actions" in row_fn


def test_ebook_preserves_toc_controls_and_ids():
    for needle in [
        'id="pager"',
        'id="pager-info"',
        'id="page-size"',
        'id="selected-command-bar"',
        'id="selected-more-trigger"',
        'id="selected-more-menu"',
        'id="selected-ai-modal"',
        'id="manual-chapter-modal"',
        'id="reindex-preview-banner"',
        'id="btn-preview-reindex"',
    ]:
        assert needle in EBOOK


# ── settings.html: select mobile + heading đồng bộ tabs desktop ───────────────
def test_settings_has_mobile_select_and_heading():
    assert 'id="settings-tab-select"' in SETTINGS
    assert 'id="settings-tab-heading"' in SETTINGS


def test_settings_desktop_tabs_hidden_on_mobile():
    assert '<nav class="hidden md:flex border-b-2' in SETTINGS


def test_settings_select_options_match_tab_ids():
    tabs = set(re.findall(r'class="settings-tab[^"]*" data-tab="([^"]+)"', SETTINGS))
    options = set(re.findall(r'<option value="(tab-[^"]+)">', SETTINGS))
    assert options == tabs == {"tab-novel", "tab-crawl", "tab-translate", "tab-ai", "tab-output", "tab-reader"}


def test_settings_select_heading_and_tabs_synchronized():
    # switchSettingsTab cập nhật cả select + heading
    assert "select.value = tabName" in SETTINGS
    assert "heading.textContent = TAB_LABELS[tabName]" in SETTINGS
    # change trên select gọi lại switchSettingsTab
    assert 'settingsTabSelect.addEventListener("change"' in SETTINGS
    for tab in ("tab-novel", "tab-crawl", "tab-translate", "tab-ai", "tab-output", "tab-reader"):
        assert f'"{tab}":' in SETTINGS  # trong bản đồ TAB_LABELS


def test_settings_preserves_panels_and_ids():
    for tab in ("tab-novel", "tab-crawl", "tab-translate", "tab-ai", "tab-output", "tab-reader"):
        assert f'id="{tab}" class="settings-panel' in SETTINGS
    assert 'id="settings-layout"' in SETTINGS
    assert 'id="save-status"' in SETTINGS


# ── settings_*.html: form + hàng nút đáy wrap trên mobile ─────────────────────
def test_settings_panels_keep_form_routes():
    for panel, action in SETTINGS_PANELS.items():
        text = _read(panel)
        assert f'<form method="post" action="{action}" class="settings-form">' in text


def test_settings_panels_footer_rows_wrap_on_mobile():
    for panel in SETTINGS_PANELS:
        assert "flex flex-wrap gap-2 items-center mt-3 pt-3 border-t" in _read(panel)


# ── reader.html: header hook + overflow công cụ phụ + safe panels ─────────────
def test_reader_has_minimal_header_hook_marker():
    assert 'document.documentElement.classList.add("reader-page")' in READER
    assert "{% block head %}" in READER


def test_reader_mobile_toolbar_keeps_touch_targets_clickable():
    assert 'class="reader-nav-right mobile-actions"' in READER
    assert "overflow: visible" in READER
    assert "touch-action: manipulation" in READER
    assert "document.body.append(mobileTools)" in READER
    assert ".reader-nav-right {" in READER


def test_reader_safe_panels():
    assert READER.count("safe-panels") == 4
    assert "env(safe-area-inset-top)" in READER
    assert "env(safe-area-inset-bottom)" in READER


def test_reader_preserves_ui_ids():
    for needle in [
        'id="toc-sidebar"',
        'id="toc-backdrop"',
        'id="search-bar"',
        'id="search-input"',
        'id="notes-panel"',
        'id="reader-content"',
        'id="chapter-select"',
        'id="settings-toggle-btn"',
        'id="toc-toggle-btn"',
        'id="bookmark-toggle-btn"',
    ]:
        assert needle in READER
