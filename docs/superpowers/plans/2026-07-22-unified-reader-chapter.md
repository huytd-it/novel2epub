# Unified Reader Chapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/ebooks/{slug}/read/{index}` the default chapter page for reading and editing, with large Crawl/Dịch empty-state CTAs and a raw comparison mode.

**Architecture:** Keep backend actions in `app/routes/chapters.py` and move the primary UI into `app/templates/reader.html`. Add a small reader context helper in `app/routes/reader.py` for raw/translated paragraph data. Redirect the old slug chapter GET route to reader edit mode while preserving existing POST/API routes.

**Tech Stack:** Python 3.10+, FastAPI, Jinja2, pytest, vanilla JavaScript, existing Tailwind utility classes/CSS variables.

## Global Constraints

- Do not introduce new dependencies.
- Reader is the default UI; editing tools are hidden until edit mode is enabled.
- If raw is missing, show a large centered **Crawl** button.
- If raw exists but translation is missing, show a large centered **Dịch** button.
- Raw comparison replaces the reader content with a two-column `ZH raw | VI biên tập` view.
- Keep existing chapter POST/API endpoints to avoid rewriting backend behavior.
- Do not remove `chapter.html` in this change.

---

## File Structure

- Modify `app/routes/reader.py`
  - Add paragraph splitting/padding helper for reader compare data.
  - Pass raw, translated, paragraph arrays, and counts to `reader.html`.
- Modify `app/routes/chapters.py`
  - Redirect GET `/ebooks/{slug}/chapters/{index}` to `/ebooks/{slug}/read/{index}?edit=1`.
  - Leave existing POST/API routes unchanged.
- Modify `app/templates/reader.html`
  - Add centered empty-state action forms.
  - Add edit-mode toolbar.
  - Add raw comparison view and JavaScript toggles.
- Modify tests:
  - `tests/test_chapter_three_column.py` for redirect behavior replacing old render assertion.
  - Create or modify `tests/test_reader_unified_chapter.py` for reader states.

---

### Task 1: Add Reader Context for Raw and Paragraph Compare Data

**Files:**
- Modify: `app/routes/reader.py:1-87`
- Test: `tests/test_reader_unified_chapter.py`

**Interfaces:**
- Produces: `_reader_paras(text: str) -> list[str]`
- Produces: `_pad_paras(left: list[str], right: list[str]) -> tuple[list[str], list[str]]`
- Produces template keys: `has_raw`, `raw`, `raw_paras`, `edit_paras`, `raw_char_count`

- [ ] **Step 1: Write failing helper tests**

Create `tests/test_reader_unified_chapter.py` with:

```python
from __future__ import annotations

from app.routes.reader import _pad_paras, _reader_paras


def test_reader_paras_splits_blank_lines_and_joins_wrapped_lines():
    assert _reader_paras("甲。\n续行。\n\n乙。\n   \n丙。") == ["甲。 续行。", "乙。", "丙。"]
    assert _reader_paras("") == []


def test_pad_paras_extends_shorter_side():
    left, right = _pad_paras(["raw 1", "raw 2"], ["vi 1"])
    assert left == ["raw 1", "raw 2"]
    assert right == ["vi 1", ""]
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_reader_unified_chapter.py -v`

Expected: FAIL with import error for `_pad_paras` or `_reader_paras`.

- [ ] **Step 3: Implement helpers and route context**

In `app/routes/reader.py`, add `import re` near imports and add helpers above `reader_root`:

```python
def _reader_paras(text: str) -> list[str]:
    """Split chapter text into display paragraphs for reader compare mode."""
    if not text:
        return []
    blocks = re.split(r"\n\s*\n", text.strip())
    return [" ".join(block.splitlines()) for block in blocks if block.strip()]


def _pad_paras(left: list[str], right: list[str]) -> tuple[list[str], list[str]]:
    total = max(len(left), len(right))
    return left + [""] * (total - len(left)), right + [""] * (total - len(right))
```

In `reader_chapter`, after `translated_paras`:

```python
    has_raw = storage.has_raw(ch)
    raw = storage.read_raw(ch) if has_raw else ""
    raw_paras = _reader_paras(raw)
    edit_paras = _reader_paras(translated) if translated else []
    raw_paras, edit_paras = _pad_paras(raw_paras, edit_paras)
```

Add these keys to the `TemplateResponse` context:

```python
            "has_raw": has_raw,
            "raw": raw,
            "raw_paras": raw_paras,
            "edit_paras": edit_paras,
            "raw_char_count": len(raw),
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_reader_unified_chapter.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Only if the user asked to commit:

```bash
git add app/routes/reader.py tests/test_reader_unified_chapter.py
git commit -m "feat: add reader chapter compare context"
```

---

### Task 2: Render Reader Empty-State CTAs

**Files:**
- Modify: `app/templates/reader.html:181-266`
- Test: `tests/test_reader_unified_chapter.py`

**Interfaces:**
- Consumes template keys from Task 1: `has_raw`, `has_translated`, `slug`, `ch`
- Produces CSS classes: `.reader-empty-action`, `.reader-empty-action-card`

- [ ] **Step 1: Add failing route tests**

Append to `tests/test_reader_unified_chapter.py`:

```python
from fastapi.testclient import TestClient

from app import deps
from novel2epub.config import Config, CrawlConfig, NovelConfig, OutputConfig, TranslateConfig
from novel2epub.storage import Chapter, Manifest, Storage


def _cfg(tmp_path):
    return Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/book/", delay_seconds=0),
        translate=TranslateConfig(type="none", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


def _client(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    from app.main import app
    return TestClient(app)


def _seed(tmp_path, *, raw=None, translated=None):
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=7, url="http://x/7", title="Bảy")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    if raw is not None:
        storage.write_raw(ch, raw)
    if translated is not None:
        storage.write_translated(ch, translated)
    return storage, ch


def test_reader_missing_raw_shows_large_crawl_cta(tmp_path, monkeypatch):
    _seed(tmp_path)
    client = _client(tmp_path, monkeypatch)

    res = client.get("/ebooks/t/read/7")

    assert res.status_code == 200
    assert 'class="reader-empty-action-card"' in res.text
    assert 'name="action" value="crawl"' in res.text
    assert ">Crawl<" in res.text


def test_reader_raw_without_translation_shows_large_translate_cta(tmp_path, monkeypatch):
    _seed(tmp_path, raw="原文")
    client = _client(tmp_path, monkeypatch)

    res = client.get("/ebooks/t/read/7")

    assert res.status_code == 200
    assert 'class="reader-empty-action-card"' in res.text
    assert 'name="action" value="translate"' in res.text
    assert ">Dịch<" in res.text
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_reader_unified_chapter.py -v`

Expected: FAIL because `reader-empty-action-card` and action forms are missing.

- [ ] **Step 3: Add empty-state CSS**

In `app/templates/reader.html`, inside the `<style>` block after existing `.reader-empty` rules, add:

```css
.reader-empty-action { min-height: 45vh; display: flex; align-items: center; justify-content: center; padding: 3rem 1rem; }
.reader-empty-action-card { text-align: center; max-width: 28rem; border: 1px solid var(--tw-border, #e4e4e7); border-radius: 16px; padding: 2rem; background: var(--tw-surface-light, #ffffff); box-shadow: var(--tw-shadow-card, 0 1px 3px rgba(0,0,0,0.06)); }
.dark .reader-empty-action-card { border-color: var(--tw-border-dark, #3f3f46); background: var(--tw-surface-dark, #18181b); box-shadow: var(--tw-shadow-card-dark, 0 1px 3px rgba(0,0,0,0.3)); }
.reader-empty-action-card p { color: var(--tw-fg-muted, #71717a); margin: 0.4rem 0 1.2rem; }
.dark .reader-empty-action-card p { color: var(--tw-fg-muted-dark, #a1a1aa); }
.reader-empty-action-card button { font-size: 1.05rem; padding: 0.75rem 1.6rem; border-radius: 999px; border: 1px solid var(--tw-brand-600, #059669); background: var(--tw-brand-600, #059669); color: #fff; cursor: pointer; }
```

- [ ] **Step 4: Replace empty-state template branch**

Replace the current `{% else %}` branch inside `<article class="reader-content" id="reader-content">` with:

```jinja2
        {% elif not has_raw %}
            <div class="reader-empty-action">
                <form method="post" action="/ebooks/{{ slug }}/chapters/{{ ch.index }}/action" class="reader-empty-action-card">
                    <input type="hidden" name="action" value="crawl">
                    <input type="hidden" name="override" value="true">
                    <h2>Chưa có raw</h2>
                    <p>Crawl chương này trước khi dịch hoặc so sánh.</p>
                    <button type="submit">Crawl</button>
                </form>
            </div>
        {% else %}
            <div class="reader-empty-action">
                <form method="post" action="/ebooks/{{ slug }}/chapters/{{ ch.index }}/action" class="reader-empty-action-card">
                    <input type="hidden" name="action" value="translate">
                    <input type="hidden" name="override" value="true">
                    <h2>Chưa có bản dịch</h2>
                    <p>Raw đã sẵn sàng. Dịch chương này để đọc và biên tập.</p>
                    <button type="submit">Dịch</button>
                </form>
            </div>
        {% endif %}
```

The full branch must be:

```jinja2
        {% if has_translated %}
            {% for para in translated_paras %}
            <p class="reader-para" data-para="{{ loop.index0 }}">{{ para }}<button type="button" class="para-copy-btn" title="Copy đoạn" data-para="{{ loop.index0 }}">&#128203;</button><button type="button" class="para-edit-btn" title="Sửa đoạn" data-para="{{ loop.index0 }}">&#9998;</button></p>
            {% endfor %}
        {% elif not has_raw %}
            <div class="reader-empty-action">
                <form method="post" action="/ebooks/{{ slug }}/chapters/{{ ch.index }}/action" class="reader-empty-action-card">
                    <input type="hidden" name="action" value="crawl">
                    <input type="hidden" name="override" value="true">
                    <h2>Chưa có raw</h2>
                    <p>Crawl chương này trước khi dịch hoặc so sánh.</p>
                    <button type="submit">Crawl</button>
                </form>
            </div>
        {% else %}
            <div class="reader-empty-action">
                <form method="post" action="/ebooks/{{ slug }}/chapters/{{ ch.index }}/action" class="reader-empty-action-card">
                    <input type="hidden" name="action" value="translate">
                    <input type="hidden" name="override" value="true">
                    <h2>Chưa có bản dịch</h2>
                    <p>Raw đã sẵn sàng. Dịch chương này để đọc và biên tập.</p>
                    <button type="submit">Dịch</button>
                </form>
            </div>
        {% endif %}
```

- [ ] **Step 5: Run tests to verify pass**

Run: `pytest tests/test_reader_unified_chapter.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

Only if the user asked to commit:

```bash
git add app/templates/reader.html tests/test_reader_unified_chapter.py
git commit -m "feat: show reader crawl and translate empty states"
```

---

### Task 3: Add Edit Mode Toolbar to Reader

**Files:**
- Modify: `app/templates/reader.html:181-255,294-445`
- Test: `tests/test_reader_unified_chapter.py`

**Interfaces:**
- Consumes existing POST endpoint: `/ebooks/{slug}/chapters/{index}/action`
- Consumes existing delete endpoints used by `chapter.html`: `/ebooks/{slug}/chapters/{index}/delete-raw`, `/ebooks/{slug}/chapters/{index}/delete-translation`
- Produces DOM IDs: `edit-mode-toggle-btn`, `reader-edit-toolbar`

- [ ] **Step 1: Add failing test for hidden toolbar markup**

Append to `tests/test_reader_unified_chapter.py`:

```python
def test_reader_with_translation_contains_edit_mode_toolbar(tmp_path, monkeypatch):
    _seed(tmp_path, raw="原文", translated="Bản dịch")
    client = _client(tmp_path, monkeypatch)

    res = client.get("/ebooks/t/read/7")

    assert res.status_code == 200
    assert 'id="edit-mode-toggle-btn"' in res.text
    assert 'id="reader-edit-toolbar"' in res.text
    assert 'name="action" value="cleanup-han"' in res.text
    assert '/ebooks/t/glossary' in res.text
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_reader_unified_chapter.py::test_reader_with_translation_contains_edit_mode_toolbar -v`

Expected: FAIL because toolbar IDs are missing.

- [ ] **Step 3: Add edit mode button**

In `reader.html`, inside `.reader-nav-right`, before the bookmark button, add:

```jinja2
            <button type="button" id="edit-mode-toggle-btn" class="reader-toolbar-btn" title="Chế độ biên tập" aria-label="Edit mode">Edit</button>
```

- [ ] **Step 4: Add edit toolbar markup**

After `</nav>` for the top reader nav and before `reader-settings-panel`, add:

```jinja2
    <div id="reader-edit-toolbar" class="reader-settings-panel" hidden>
        <div class="settings-row">
            {% if not has_raw %}
            <form method="post" action="/ebooks/{{ slug }}/chapters/{{ ch.index }}/action" class="m-0">
                <input type="hidden" name="action" value="crawl">
                <input type="hidden" name="override" value="true">
                <button type="submit" class="reader-nav-btn">Crawl</button>
            </form>
            {% else %}
            <form method="post" action="/ebooks/{{ slug }}/chapters/{{ ch.index }}/delete-raw" class="m-0" data-confirm="Xóa nội dung đã crawl của chương này?" data-confirm-danger="true">
                <button type="submit" class="reader-nav-btn">Xóa raw</button>
            </form>
            {% endif %}
            <form method="post" action="/ebooks/{{ slug }}/chapters/{{ ch.index }}/action" class="m-0">
                <input type="hidden" name="action" value="translate">
                <input type="hidden" name="override" value="true">
                <button type="submit" class="reader-nav-btn">Dịch</button>
            </form>
            <form method="post" action="/ebooks/{{ slug }}/chapters/{{ ch.index }}/action" class="m-0">
                <input type="hidden" name="action" value="cleanup-han">
                <input type="hidden" name="override" value="true">
                <button type="submit" class="reader-nav-btn">Làm sạch Hán</button>
            </form>
            {% if has_translated %}
            <form method="post" action="/ebooks/{{ slug }}/chapters/{{ ch.index }}/delete-translation" class="m-0" data-confirm="Xóa bản dịch của chương này?" data-confirm-danger="true">
                <button type="submit" class="reader-nav-btn">Xóa bản dịch</button>
            </form>
            {% endif %}
            <a href="/ebooks/{{ slug }}/glossary" class="reader-nav-btn">Glossary</a>
        </div>
    </div>
```

- [ ] **Step 5: Add edit mode JavaScript**

In the first script block after settings toggle code, add:

```javascript
    const editToolbar = document.getElementById('reader-edit-toolbar');
    const editModeBtn = document.getElementById('edit-mode-toggle-btn');
    const initialEditMode = new URLSearchParams(window.location.search).get('edit') === '1';
    function setEditMode(on) {
        if (!editToolbar || !editModeBtn) return;
        editToolbar.hidden = !on;
        editModeBtn.classList.toggle('active', on);
    }
    editModeBtn?.addEventListener('click', () => setEditMode(editToolbar.hidden));
    setEditMode(initialEditMode);
```

- [ ] **Step 6: Run test to verify pass**

Run: `pytest tests/test_reader_unified_chapter.py::test_reader_with_translation_contains_edit_mode_toolbar -v`

Expected: PASS.

- [ ] **Step 7: Commit**

Only if the user asked to commit:

```bash
git add app/templates/reader.html tests/test_reader_unified_chapter.py
git commit -m "feat: add reader edit mode toolbar"
```

---

### Task 4: Add Raw Comparison Mode to Reader

**Files:**
- Modify: `app/templates/reader.html:139-167,255-270,447-1124`
- Test: `tests/test_reader_unified_chapter.py`

**Interfaces:**
- Consumes template keys: `has_raw`, `raw_paras`, `edit_paras`
- Produces DOM IDs: `raw-compare-toggle-btn`, `raw-compare-view`

- [ ] **Step 1: Add failing test for raw compare markup and data**

Append to `tests/test_reader_unified_chapter.py`:

```python
def test_reader_with_raw_and_translation_contains_raw_compare_view(tmp_path, monkeypatch):
    _seed(tmp_path, raw="甲。\n\n乙。", translated="Một.\n\nHai.")
    client = _client(tmp_path, monkeypatch)

    res = client.get("/ebooks/t/read/7")

    assert res.status_code == 200
    assert 'id="raw-compare-toggle-btn"' in res.text
    assert 'id="raw-compare-view"' in res.text
    assert "ZH raw" in res.text
    assert "VI biên tập" in res.text
    assert "甲。" in res.text
    assert "Một." in res.text
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_reader_unified_chapter.py::test_reader_with_raw_and_translation_contains_raw_compare_view -v`

Expected: FAIL because raw compare markup is missing.

- [ ] **Step 3: Add raw compare CSS**

In the existing compare CSS section, add:

```css
.raw-compare-view { max-width: 1100px; margin: 1.5rem auto; line-height: 1.75; font-size: 0.95rem; }
.raw-compare-head, .raw-compare-row { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
.raw-compare-head { font-weight: 600; font-size: 0.8125rem; color: var(--tw-fg-muted, #71717a); text-transform: uppercase; letter-spacing: 0.03em; padding-bottom: 0.4rem; border-bottom: 1px solid var(--tw-border, #e4e4e7); }
.dark .raw-compare-head { color: var(--tw-fg-muted-dark, #a1a1aa); border-bottom-color: var(--tw-border-dark, #3f3f46); }
.raw-compare-row { padding: 0.55rem 0; border-bottom: 1px dashed var(--tw-surface-muted, #eee); }
.dark .raw-compare-row { border-bottom-color: var(--tw-surface-muted-dark, #2e2e38); }
.raw-compare-raw { color: var(--tw-fg-muted, #71717a); }
.dark .raw-compare-raw { color: var(--tw-fg-muted-dark, #a1a1aa); }
.raw-compare-vi { font-family: 'Literata', 'Georgia', serif; }
@media (max-width: 640px) {
    .raw-compare-head { display: none; }
    .raw-compare-row { grid-template-columns: 1fr; gap: 0.2rem; }
    .raw-compare-raw { font-size: 0.85em; }
}
```

- [ ] **Step 4: Add raw compare toggle button**

Inside `.reader-nav-right`, near the existing compare button, add:

```jinja2
            {% if has_raw %}
            <button type="button" id="raw-compare-toggle-btn" class="reader-toolbar-btn" title="So sánh raw / bản dịch" aria-label="Raw compare">Raw</button>
            {% endif %}
```

- [ ] **Step 5: Add raw compare markup**

Replace `<div id="compare-view" class="compare-view" hidden></div>` with:

```jinja2
    {% if has_raw %}
    <div id="raw-compare-view" class="raw-compare-view" hidden>
        <div class="raw-compare-head">
            <div>ZH raw</div>
            <div>VI biên tập</div>
        </div>
        {% for i in range(raw_paras|length) %}
        <div class="raw-compare-row" data-para="{{ i }}">
            <div class="raw-compare-raw">{{ raw_paras[i] }}</div>
            <div class="raw-compare-vi">{{ edit_paras[i] }}</div>
        </div>
        {% endfor %}
    </div>
    {% endif %}

    <div id="compare-view" class="compare-view" hidden></div>
```

- [ ] **Step 6: Add raw compare JavaScript**

In the first script block after `const content = document.getElementById('reader-content');`, add:

```javascript
    const rawCompareBtn = document.getElementById('raw-compare-toggle-btn');
    const rawCompareView = document.getElementById('raw-compare-view');
    function setRawCompareMode(on) {
        if (!rawCompareBtn || !rawCompareView || !content) return;
        content.hidden = on;
        rawCompareView.hidden = !on;
        rawCompareBtn.classList.toggle('active', on);
    }
    rawCompareBtn?.addEventListener('click', () => setRawCompareMode(rawCompareView.hidden));
```

- [ ] **Step 7: Run test to verify pass**

Run: `pytest tests/test_reader_unified_chapter.py::test_reader_with_raw_and_translation_contains_raw_compare_view -v`

Expected: PASS.

- [ ] **Step 8: Commit**

Only if the user asked to commit:

```bash
git add app/templates/reader.html tests/test_reader_unified_chapter.py
git commit -m "feat: add raw comparison mode to reader"
```

---

### Task 5: Redirect Old Chapter GET Route to Reader Edit Mode

**Files:**
- Modify: `app/routes/chapters.py:177-195`
- Test: `tests/test_chapter_three_column.py`

**Interfaces:**
- Produces redirect: `/ebooks/{slug}/chapters/{index}` -> `/ebooks/{slug}/read/{index}?edit=1`
- Keeps POST `/ebooks/{slug}/chapters/{index}` unchanged

- [ ] **Step 1: Update failing test expectation**

In `tests/test_chapter_three_column.py`, replace `test_chapter_page_renders_three_columns` with:

```python
def test_slug_chapter_page_redirects_to_reader_edit_mode(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=7, url="http://x/7")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    storage.write_raw(ch, "原文 ZH")
    storage.write_translated_mt(ch, "VI MÁY")
    storage.write_translated(ch, "VI ĐÃ SỬA")
    _patch_deps(monkeypatch, cfg)
    from app.main import app
    client = TestClient(app)

    res = client.get("/ebooks/t/chapters/7", follow_redirects=False)

    assert res.status_code == 302
    assert res.headers["location"] == "/ebooks/t/read/7?edit=1"
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_chapter_three_column.py::test_slug_chapter_page_redirects_to_reader_edit_mode -v`

Expected: FAIL because route still returns 200.

- [ ] **Step 3: Change route implementation**

In `app/routes/chapters.py`, find the GET route for `/ebooks/{slug}/chapters/{index}` and replace its body with:

```python
    return RedirectResponse(url=f"/ebooks/{slug}/read/{index}?edit=1", status_code=302)
```

Keep the route decorator and function signature unchanged.

- [ ] **Step 4: Run route tests**

Run: `pytest tests/test_chapter_three_column.py tests/test_reader_unified_chapter.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Only if the user asked to commit:

```bash
git add app/routes/chapters.py tests/test_chapter_three_column.py
git commit -m "feat: redirect chapter view to reader edit mode"
```

---

### Task 6: Final Verification

**Files:**
- No code changes unless verification fails.

**Interfaces:**
- Verifies all previous tasks together.

- [ ] **Step 1: Run focused tests**

Run:

```bash
pytest tests/test_reader_unified_chapter.py tests/test_chapter_three_column.py tests/test_routes_para_edit.py tests/test_routes_notes.py -v
```

Expected: all selected tests PASS.

- [ ] **Step 2: Run broader route/template tests**

Run:

```bash
pytest tests/test_chapter_api.py tests/test_routes_glossary.py tests/test_reader_sync.py tests/test_reader_push_api.py -v
```

Expected: all selected tests PASS.

- [ ] **Step 3: Manual browser check**

Run:

```bash
uvicorn app.main:app --reload --port 8010
```

Open an ebook chapter and verify:

- Translated chapter opens in reader mode.
- Chapter without raw shows centered **Crawl** CTA.
- Chapter with raw and no translation shows centered **Dịch** CTA.
- Edit mode button shows/hides toolbar.
- `/ebooks/<slug>/chapters/<index>` lands on `/ebooks/<slug>/read/<index>?edit=1`.
- Raw compare button toggles `ZH raw | VI biên tập` view.
- Mobile width stacks raw above VI per paragraph.

Stop the server after manual verification.

- [ ] **Step 4: Commit final verification notes**

Only if the user asked to commit and code changed during verification:

```bash
git add app/routes/reader.py app/routes/chapters.py app/templates/reader.html tests/test_reader_unified_chapter.py tests/test_chapter_three_column.py
git commit -m "test: verify unified reader chapter flow"
```

---

## Self-Review

- Spec coverage: Reader default, empty-state CTA Crawl/Dịch, edit toolbar, raw comparison, old route redirect, and testing are all covered by Tasks 1-6.
- Placeholder scan: no TBD/TODO/fill-later placeholders remain. Code steps include concrete snippets and exact commands.
- Type consistency: `_reader_paras(text: str) -> list[str]`, `_pad_paras(left, right) -> tuple[list[str], list[str]]`, and template keys match across tasks.
