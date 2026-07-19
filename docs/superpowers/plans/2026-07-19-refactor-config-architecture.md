# Refactor Config Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the config architecture to ensure full config support for each ebook with high reusability. When adding new ebooks, allow skipping AI analysis (which slows things down) and only apply AI for new domains not in source presets.

**Architecture:** The current architecture uses a unified `novel2epub.db` SQLite database with three config layers: `defaults` (global), `sources` (source presets), and `ebooks` (per-ebook overrides). The refactor will:
1. Extend `SourcePreset` with AI glossary/analysis settings (glossary extraction, cleanup, evaluation prompts)
2. Extend `TranslateConfig` with `ai_glossary_analysis` toggle per-ebook
3. Update config merge logic to layer: `defaults` → `source_preset` → `ebook_overrides`
4. Update library routes to allow selecting source preset + AI glossary toggle when adding ebooks
5. Update pipeline to use per-ebook AI glossary settings

**Tech Stack:** Python 3.10+, FastAPI, SQLite, PyYAML, ebooklib, crawl4ai, scrapling

## Global Constraints

- Python 3.10+
- Single unified config in `novel2epub.db` (SQLite)
- Existing CLI commands must continue working: `crawl`, `translate`, `build`, `run`
- Web UI on `uvicorn app.main:app --port 8010`
- Tests in `tests/` with `pytest`
- Follow existing code patterns and conventions

---

### Task 1: Extend SourcePreset with AI Glossary/Analysis Settings

**Files:**
- Modify: `novel2epub/sources.py:20-65`
- Test: `tests/test_sources.py`

**Interfaces:**
- Consumes: `SourcePreset` dataclass (existing)
- Produces: Extended `SourcePreset` with new AI fields, updated `crawl_overrides()` method

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sources.py
def test_source_preset_ai_fields():
    from novel2epub.sources import SourcePreset
    
    preset = SourcePreset(
        name="test",
        url="https://example.com",
        # New AI glossary fields
        ai_glossary_extract_prompt="Extract glossary: {text}",
        ai_glossary_merge_prompt="Merge: {existing} + {new}",
        ai_cleanup_prompt="Cleanup: {text}",
        ai_eval_prompt="Evaluate: {original} vs {translated}",
        ai_glossary_enabled=True,
        ai_cleanup_enabled=False,
        ai_eval_enabled=False,
    )
    
    assert preset.ai_glossary_enabled is True
    assert preset.ai_cleanup_enabled is False
    assert preset.ai_eval_enabled is False
    assert preset.ai_glossary_extract_prompt == "Extract glossary: {text}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sources.py::test_source_preset_ai_fields -v`
Expected: FAIL with "TypeError: __init__() got unexpected keyword argument"

- [ ] **Step 3: Write minimal implementation**

```python
# novel2epub/sources.py (add to SourcePreset dataclass after line 64)
    # ----- AI glossary/analysis configuration -----
    ai_glossary_enabled: bool = False
    ai_glossary_extract_prompt: str = ""
    ai_glossary_merge_prompt: str = ""
    ai_cleanup_enabled: bool = False
    ai_cleanup_prompt: str = ""
    ai_eval_enabled: bool = False
    ai_eval_prompt: str = ""
```

- [ ] **Step 4: Update `crawl_overrides()` to exclude AI fields**

```python
# novel2epub/sources.py (in crawl_overrides method, add to _source_only set)
_source_only = {
    "name", "url", "domains", "engine",
    "toc_selector", "chapter_title_selector", "title_selector",
    "author_selector", "desc_selector", "cover_selector",
    "encoding", "user_agent", "magic", "js_code",
    "max_search_results",
    # New AI fields - not part of CrawlConfig
    "ai_glossary_enabled", "ai_glossary_extract_prompt", "ai_glossary_merge_prompt",
    "ai_cleanup_enabled", "ai_cleanup_prompt",
    "ai_eval_enabled", "ai_eval_prompt",
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_sources.py::test_source_preset_ai_fields -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add novel2epub/sources.py tests/test_sources.py
git commit -m "feat: add AI glossary/analysis fields to SourcePreset"
```

---

### Task 2: Add AI Glossary Toggle to TranslateConfig

**Files:**
- Modify: `novel2epub/config.py:316-362`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `TranslateConfig` dataclass (existing)
- Produces: Extended `TranslateConfig` with `ai_glossary_analysis` field

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
def test_translate_config_ai_glossary_analysis():
    from novel2epub.config import TranslateConfig
    
    cfg = TranslateConfig(ai_glossary_analysis=True)
    assert cfg.ai_glossary_analysis is True
    
    cfg2 = TranslateConfig(ai_glossary_analysis=False)
    assert cfg2.ai_glossary_analysis is False
    
    # Default should be False (opt-in for AI analysis)
    cfg3 = TranslateConfig()
    assert cfg3.ai_glossary_analysis is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py::test_translate_config_ai_glossary_analysis -v`
Expected: FAIL with "TypeError: __init__() got unexpected keyword argument"

- [ ] **Step 3: Write minimal implementation**

```python
# novel2epub/config.py (in TranslateConfig dataclass, after line 362)
    # AI glossary analysis per ebook (opt-in, slows down translation)
    # When True: run AI glossary extraction/merge/cleanup/eval per chapter
    # When False: use glossary as-is (fast path)
    ai_glossary_analysis: bool = False
```

- [ ] **Step 4: Update `load_config` to read the new field**

```python
# novel2epub/config.py (in load_config, around line 809)
        translate = TranslateConfig(
            ...
            ai_cleanup_han=bool(translate_raw.get("auto_cleanup_han", False)),
            cleanup_han=CleanupHanConfig(...),
            ai_glossary_analysis=bool(translate_raw.get("ai_glossary_analysis", False)),
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_config.py::test_translate_config_ai_glossary_analysis -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add novel2epub/config.py tests/test_config.py
git commit -m "feat: add ai_glossary_analysis toggle to TranslateConfig"
```

---

### Task 3: Update Config Merge Logic for Source Preset AI Fields

**Files:**
- Modify: `novel2epub/config.py:596-642` (`load_config` function)
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `load_config`, `_resolve_source_overrides`, `_deep_merge_raw`
- Produces: Config with AI glossary settings merged from source preset → ebook override

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
def test_load_config_merges_source_ai_fields():
    from novel2epub.config import load_config
    import tempfile
    import os
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        # Setup DB with defaults + source preset with AI fields + ebook
        # This requires test DB setup - use existing test helpers
        cfg = load_config(db_path, slug="test-ebook")
        # AI fields from source preset should be in config
        assert hasattr(cfg, 'ai_glossary_extract_prompt')
        # ebook override should win over source preset
```

- [ ] **Step 2: Update `_resolve_source_overrides` to include AI fields**

```python
# novel2epub/config.py (in _resolve_source_overrides, after line 635)
def _resolve_source_overrides(override: dict, sources_raw: dict) -> tuple[dict, str, list]:
    ...
    # After getting source_crawl from preset, also extract AI fields
    if source_name and source_name in sources_raw:
        source_data = sources_raw[source_name]
        # Merge AI glossary/analysis fields from source preset into override
        ai_fields = {
            "ai_glossary_enabled", "ai_glossary_extract_prompt", "ai_glossary_merge_prompt",
            "ai_cleanup_enabled", "ai_cleanup_prompt",
            "ai_eval_enabled", "ai_eval_prompt",
        }
        for field in ai_fields:
            if field in source_data and field not in override:
                override[field] = source_data[field]
    return source_crawl, source_name, source_warnings
```

- [ ] **Step 3: Update Config dataclass to include AI fields from source preset**

```python
# novel2epub/config.py (in Config dataclass, after line 451)
    # AI glossary/analysis settings from source preset (merged at load time)
    ai_glossary_enabled: bool = False
    ai_glossary_extract_prompt: str = ""
    ai_glossary_merge_prompt: str = ""
    ai_cleanup_enabled: bool = False
    ai_cleanup_prompt: str = ""
    ai_eval_enabled: bool = False
    ai_eval_prompt: str = ""
```

- [ ] **Step 4: Populate Config AI fields in load_config**

```python
# novel2epub/config.py (in load_config, after creating Config object, around line 848)
    config = Config(
        novel=novel,
        crawl=crawl,
        translate=translate,
        output=output,
        ai=ai,
        queue=queue,
        reader=reader,
        source=source_name,
        warnings=warnings,
        # AI glossary/analysis from source preset
        ai_glossary_enabled=override.get("ai_glossary_enabled", False),
        ai_glossary_extract_prompt=override.get("ai_glossary_extract_prompt", ""),
        ai_glossary_merge_prompt=override.get("ai_glossary_merge_prompt", ""),
        ai_cleanup_enabled=override.get("ai_cleanup_enabled", False),
        ai_cleanup_prompt=override.get("ai_cleanup_prompt", ""),
        ai_eval_enabled=override.get("ai_eval_enabled", False),
        ai_eval_prompt=override.get("ai_eval_prompt", ""),
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_config.py::test_load_config_merges_source_ai_fields -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add novel2epub/config.py tests/test_config.py
git commit -m "feat: merge source preset AI glossary fields into ebook config"
```

---

### Task 4: Update Library Routes for New Ebook Creation with Source Preset

**Files:**
- Modify: `app/routes/library.py:101-200` (`new_ebook_page`, `create_ebook`)
- Modify: `app/templates/library_new.html` (if exists, or create)
- Test: `tests/test_routes_library.py`

**Interfaces:**
- Consumes: `create_ebook` function, `load_presets`, `detect_preset`
- Produces: New ebook creation with source preset selection + AI glossary toggle

- [ ] **Step 1: Write the failing test**

```python
# tests/test_routes_library.py
def test_create_ebook_with_source_preset_and_ai_glossary(client):
    # Create ebook with source preset and ai_glossary_analysis=True
    resp = client.post("/library/ebooks", data={
        "toc_url": "https://example.com/novel",
        "source_preset": "sto9",
        "ai_glossary_analysis": "on",
        "slug": "test-novel",
    })
    assert resp.status_code == 303  # Redirect
    # Verify ebook created with correct config
```

- [ ] **Step 2: Update `create_ebook` to accept source_preset and ai_glossary_analysis**

```python
# app/routes/library.py (in create_ebook function, around line 257)
@router.post("/library/ebooks")
async def create_ebook(
    request: Request,
    toc_url: str = Form(...),
    source_preset: str = Form(""),  # Name of source preset to use
    ai_glossary_analysis: str = Form(""),  # "on" or empty
    scrapling_mode: str = Form(""),
    slug: str = Form(""),
    title: str = Form(""),
    author: str = Form(""),
):
    # Detect preset if not provided
    if not source_preset:
        presets = load_presets(deps.SOURCES_PATH)
        source_preset = detect_preset(toc_url, presets) or ""
    
    # Build crawl preview config
    crawl_cfg, detected_source = _build_meta_crawl_cfg(toc_url, scrapling_mode)
    
    # If user selected a preset, use it
    if source_preset:
        presets = load_presets(deps.SOURCES_PATH)
        if source_preset in presets:
            crawl_cfg = presets[source_preset].to_crawl_config(toc_url, scrapling_mode)
            detected_source = source_preset
    
    # Fetch metadata
    meta = _fetch_meta_with_cfg(crawl_cfg)
    
    # Override with user-provided title/author/slug
    if title:
        meta["title_raw"] = title
    if author:
        meta["author"] = author
    if slug:
        meta["slug"] = slug
    else:
        meta["slug"] = slugify(meta["title_raw"] or toc_url)
    
    # Save ebook with source_preset and ai_glossary_analysis
    from novel2epub.config_writer import add_ebook
    add_ebook(
        deps.WORKSPACE_PATH,
        meta["slug"],
        name=meta["title_raw"],
        title=meta["title_raw"],
        author=meta["author"],
        toc_url=toc_url,
        source_name=detected_source,
    )
    
    # Update ebook config with ai_glossary_analysis
    if ai_glossary_analysis == "on":
        from novel2epub.config_writer import update_ebook
        update_ebook(deps.WORKSPACE_PATH, meta["slug"], {
            "translate": {"ai_glossary_analysis": True}
        })
    
    return RedirectResponse(url=f"/ebooks/{meta['slug']}", status_code=303)
```

- [ ] **Step 3: Update `new_ebook_page` to pass source presets to template**

```python
# app/routes/library.py (in new_ebook_page, around line 106)
    return deps.templates.TemplateResponse(
        request,
        "library_new.html",
        {
            "cfg": deps.cfg(),
            "ebook_count": len(deps.library().ebooks),
            "presets": load_presets(deps.SOURCES_PATH),
            # Add AI glossary defaults from global config
            "ai_glossary_default": deps.cfg().translate.ai_glossary_analysis,
        },
    )
```

- [ ] **Step 4: Update template `library_new.html` to show source preset dropdown + AI glossary checkbox**

```html
<!-- app/templates/library_new.html (add to form) -->
<div class="form-group">
    <label>Source Preset</label>
    <select name="source_preset" id="source_preset">
        <option value="">Auto-detect</option>
        {% for name, preset in presets.items() %}
        <option value="{{ name }}">{{ name }}</option>
        {% endfor %}
    </select>
    <small>Chọn preset nguồn để tái dùng config crawl + AI glossary</small>
</div>

<div class="form-group checkbox">
    <label>
        <input type="checkbox" name="ai_glossary_analysis" value="on" 
               {% if ai_glossary_default %}checked{% endif %}>
        Bật AI phân tích glossary/chương (chậm hơn, chỉ bật cho domain mới)
    </label>
</div>
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_routes_library.py::test_create_ebook_with_source_preset_and_ai_glossary -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/routes/library.py app/templates/library_new.html tests/test_routes_library.py
git commit -m "feat: add source preset selection and AI glossary toggle to ebook creation"
```

---

### Task 5: Update config_writer.py for New Ebook Config Structure

**Files:**
- Modify: `novel2epub/config_writer.py:236-282` (`add_ebook` function)
- Test: `tests/test_config_writer.py`

**Interfaces:**
- Consumes: `add_ebook`, `update_ebook`
- Produces: Ebook records with `source_preset` and `translate_overrides_json` including `ai_glossary_analysis`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config_writer.py
def test_add_ebook_with_source_preset_and_ai_glossary():
    from novel2epub.config_writer import add_ebook, update_ebook
    import tempfile
    import os
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        # Initialize DB (use existing test helper)
        
        add_ebook(
            db_path,
            "test-novel",
            name="Test Novel",
            title="Test Novel",
            author="Author",
            toc_url="https://example.com",
            source_name="sto9",
        )
        
        update_ebook(db_path, "test-novel", {
            "translate": {"ai_glossary_analysis": True}
        })
        
        # Verify saved correctly
        from novel2epub.config import load_config
        cfg = load_config(db_path, "test-novel")
        assert cfg.translate.ai_glossary_analysis is True
        assert cfg.source == "sto9"
```

- [ ] **Step 2: Update `add_ebook` to accept and store `source_name` properly**

```python
# novel2epub/config_writer.py (in add_ebook, around line 236)
def add_ebook(
    path: str | Path,
    slug: str,
    *,
    name: str = "",
    title: str = "",
    author: str = "",
    toc_url: str = "",
    preset: dict[str, Any] | None = None,
    source_name: str = "",  # New parameter: source preset name
) -> None:
    ...
    with conn:
        conn.execute(
            """
            INSERT INTO ebooks (slug, name, title, author, date_added, identifier, source_preset, crawl_overrides_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                name = excluded.name,
                title = excluded.title,
                author = excluded.author,
                source_preset = excluded.source_preset,
                crawl_overrides_json = excluded.crawl_overrides_json
            """,
            (
                slug, name, title, author, date.today().isoformat(),
                f"urn:uuid:{uuid.uuid4()}", source_name or None,
                json.dumps(crawl_over, ensure_ascii=False),
            ),
        )
```

- [ ] **Step 3: Ensure `update_ebook` handles translate overrides including ai_glossary_analysis**

```python
# novel2epub/config_writer.py (in update_ebook, ensure it writes translate_overrides_json)
# The existing update_ebook should already handle this via the JSON merge logic
# Verify it works with the new field - may need no changes if using generic JSON merge
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config_writer.py::test_add_ebook_with_source_preset_and_ai_glossary -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add novel2epub/config_writer.py tests/test_config_writer.py
git commit -m "feat: update config_writer for source preset and AI glossary config"
```

---

### Task 6: Update Pipeline to Use Per-Ebook AI Glossary Settings

**Files:**
- Modify: `novel2epub/pipeline.py` (translation step functions)
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `Config` object with `ai_glossary_analysis` and source preset AI fields
- Produces: Translation pipeline that conditionally runs AI glossary analysis

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline.py
def test_pipeline_uses_ai_glossary_analysis_flag():
    from novel2epub.pipeline import _translate_chapters_parallel
    from novel2epub.config import Config, TranslateConfig
    from novel2epub.storage import Storage
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Setup storage with some chapters
        storage = Storage(tmpdir, "test")
        storage.ensure_dirs()
        
        # Config with ai_glossary_analysis=True
        cfg = Config(
            novel=NovelConfig(slug="test"),
            crawl=CrawlConfig(),
            translate=TranslateConfig(ai_glossary_analysis=True),
            output=OutputConfig(data_dir=tmpdir),
        )
        
        # Should call AI glossary functions when enabled
        # Mock and verify
```

- [ ] **Step 2: Update `_translate_chapters_parallel` to check `cfg.translate.ai_glossary_analysis`**

```python
# novel2epub/pipeline.py (in _translate_chapters_parallel or _translate_one)
# Around where translator is created and used

def _translate_one(ch: Chapter, cfg: Config, storage: Storage, log, glossary, ...) -> bool:
    translator = build_translator(cfg, storage, log)
    
    # Translate chapter
    translated = translator.translate(ch.raw_text, on_chunk=..., on_glossary=...)
    
    # NEW: If ai_glossary_analysis enabled, run AI glossary extraction/merge/cleanup/eval
    if cfg.translate.ai_glossary_analysis:
        # Run AI glossary extraction on translated chapter
        if cfg.ai_glossary_enabled and cfg.ai_glossary_extract_prompt:
            new_glossary = extract_glossary_ai(ch.raw_text, translated, cfg, storage, log)
            translator.extend_glossary(new_glossary, storage)
        
        # Run AI cleanup if enabled
        if cfg.ai_cleanup_enabled and cfg.ai_cleanup_prompt:
            translated = cleanup_translation_ai(translated, cfg, storage, log)
        
        # Run AI evaluation if enabled
        if cfg.ai_eval_enabled and cfg.ai_eval_prompt:
            eval_result = evaluate_translation_ai(ch.raw_text, translated, cfg, storage, log)
            log(f"AI Evaluation: {eval_result}")
    
    storage.write_translated(ch, translated)
    return True
```

- [ ] **Step 3: Add helper functions for AI glossary operations**

```python
# novel2epub/pipeline.py (add new helper functions)

def extract_glossary_ai(raw_text: str, translated: str, cfg: Config, storage: Storage, log) -> dict[str, str]:
    """Use AI to extract new glossary entries from chapter pair."""
    from novel2epub.glossary_ai import suggest_glossary_entries
    # Use source preset's extract prompt or default
    prompt = cfg.ai_glossary_extract_prompt or DEFAULT_EXTRACT_PROMPT
    return suggest_glossary_entries(raw_text, translated, prompt, cfg, log)

def cleanup_translation_ai(translated: str, cfg: Config, storage: Storage, log) -> str:
    """Use AI to clean up translation (remove Chinese chars, fix pronouns, etc)."""
    from novel2epub.glossary_ai import cleanup_translation
    prompt = cfg.ai_cleanup_prompt or DEFAULT_CLEANUP_PROMPT
    return cleanup_translation(translated, prompt, cfg, log)

def evaluate_translation_ai(raw_text: str, translated: str, cfg: Config, storage: Storage, log) -> dict:
    """Use AI to evaluate translation quality."""
    from novel2epub.glossary_ai import evaluate_translation
    prompt = cfg.ai_eval_prompt or DEFAULT_EVAL_PROMPT
    return evaluate_translation(raw_text, translated, prompt, cfg, log)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline.py::test_pipeline_uses_ai_glossary_analysis_flag -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add novel2epub/pipeline.py tests/test_pipeline.py
git commit -m "feat: pipeline uses per-ebook AI glossary analysis settings"
```

---

### Task 7: Update Web UI Settings to Show/Edit Source Preset AI Fields

**Files:**
- Modify: `app/routes/sources.py` (source preset edit form)
- Modify: `app/templates/sources.html`
- Test: `tests/test_routes_sources.py`

**Interfaces:**
- Consumes: `save_source_preset` route, `SourcePreset` dataclass
- Produces: Web UI for editing AI glossary/analysis fields in source presets

- [ ] **Step 1: Write the failing test**

```python
# tests/test_routes_sources.py
def test_save_source_preset_with_ai_fields(client):
    resp = client.post("/sources", data={
        "name": "test-source",
        "engine": "scrapling",
        "url": "https://example.com",
        "ai_glossary_enabled": "on",
        "ai_glossary_extract_prompt": "Extract: {text}",
        "ai_cleanup_enabled": "on",
        "ai_cleanup_prompt": "Cleanup: {text}",
    })
    assert resp.status_code == 303
    
    # Verify saved
    from novel2epub.sources import load_presets
    presets = load_presets(deps.SOURCES_PATH)
    assert presets["test-source"].ai_glossary_enabled is True
```

- [ ] **Step 2: Update `save_source_preset` to handle AI fields**

```python
# app/routes/sources.py (in save_source_preset, around line 82)
@router.post("/sources")
def save_source_preset(
    ...
    ai_glossary_enabled: str = Form(""),
    ai_glossary_extract_prompt: str = Form(""),
    ai_glossary_merge_prompt: str = Form(""),
    ai_cleanup_enabled: str = Form(""),
    ai_cleanup_prompt: str = Form(""),
    ai_eval_enabled: str = Form(""),
    ai_eval_prompt: str = Form(""),
):
    ...
    item = dict(item or {})
    item.pop("name", None)
    # Add AI fields
    item["ai_glossary_enabled"] = ai_glossary_enabled == "on"
    item["ai_glossary_extract_prompt"] = ai_glossary_extract_prompt
    item["ai_glossary_merge_prompt"] = ai_glossary_merge_prompt
    item["ai_cleanup_enabled"] = ai_cleanup_enabled == "on"
    item["ai_cleanup_prompt"] = ai_cleanup_prompt
    item["ai_eval_enabled"] = ai_eval_enabled == "on"
    item["ai_eval_prompt"] = ai_eval_prompt
    ...
```

- [ ] **Step 3: Update `sources.html` template to show AI fields**

```html
<!-- app/templates/sources.html (in preset edit form) -->
<div class="form-section">
    <h3>AI Glossary & Analysis</h3>
    <div class="form-group checkbox">
        <label>
            <input type="checkbox" name="ai_glossary_enabled" value="on" 
                   {% if edit and edit.ai_glossary_enabled %}checked{% endif %}>
            Bật trích xuất glossary AI
        </label>
    </div>
    <div class="form-group">
        <label>Prompt trích xuất glossary</label>
        <textarea name="ai_glossary_extract_prompt" rows="4">{% if edit %}{{ edit.ai_glossary_extract_prompt }}{% endif %}</textarea>
    </div>
    <div class="form-group">
        <label>Prompt merge glossary</label>
        <textarea name="ai_glossary_merge_prompt" rows="3">{% if edit %}{{ edit.ai_glossary_merge_prompt }}{% endif %}</textarea>
    </div>
    
    <div class="form-group checkbox">
        <label>
            <input type="checkbox" name="ai_cleanup_enabled" value="on"
                   {% if edit and edit.ai_cleanup_enabled %}checked{% endif %}>
            Bật cleanup bản dịch AI
        </label>
    </div>
    <div class="form-group">
        <label>Prompt cleanup</label>
        <textarea name="ai_cleanup_prompt" rows="4">{% if edit %}{{ edit.ai_cleanup_prompt }}{% endif %}</textarea>
    </div>
    
    <div class="form-group checkbox">
        <label>
            <input type="checkbox" name="ai_eval_enabled" value="on"
                   {% if edit and edit.ai_eval_enabled %}checked{% endif %}>
            Bật đánh giá bản dịch AI
        </label>
    </div>
    <div class="form-group">
        <label>Prompt đánh giá</label>
        <textarea name="ai_eval_prompt" rows="4">{% if edit %}{{ edit.ai_eval_prompt }}{% endif %}</textarea>
    </div>
</div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_routes_sources.py::test_save_source_preset_with_ai_fields -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/routes/sources.py app/templates/sources.html tests/test_routes_sources.py
git commit -m "feat: add AI glossary/analysis fields to source preset web UI"
```

---

### Task 8: Integration Tests and Verification

**Files:**
- Test: `tests/test_integration_config.py`
- Test: `tests/test_cli_run.py`

**Interfaces:**
- Full pipeline: CLI `run` command with ebook using source preset + AI glossary toggle

- [ ] **Step 1: Write integration test**

```python
# tests/test_integration_config.py
def test_full_pipeline_with_source_preset_and_ai_glossary(tmp_path):
    """Test complete flow: create ebook with source preset + AI glossary -> crawl -> translate -> build"""
    from novel2epub.cli import main
    from novel2epub.config import load_config
    import subprocess
    
    # 1. Create test DB with source preset (sto9) that has AI glossary enabled
    # 2. Add ebook referencing that preset with ai_glossary_analysis=True
    # 3. Run crawl (mocked)
    # 4. Run translate (mocked AI)
    # 5. Verify AI glossary functions were called
    # 6. Run build
    # 7. Verify EPUB created
```

- [ ] **Step 2: Run all existing tests to ensure no regressions**

```bash
pytest tests/ -v --tb=short
```

- [ ] **Step 3: Test CLI commands manually**

```bash
# Test config loading
python -m novel2epub crawl --slug test-novel
python -m novel2epub translate --slug test-novel
python -m novel2epub build --slug test-novel
python -m novel2epub run --slug test-novel
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration_config.py tests/test_cli_run.py
git commit -m "test: add integration tests for config refactor"
```

---

### Task 9: Update Documentation and Example Config

**Files:**
- Modify: `novel2epub.example.yaml` (add example source preset with AI fields)
- Modify: `README.md` or `docs/config.md` (if exists)

- [ ] **Step 1: Update example config**

```yaml
# novel2epub.example.yaml (add to sources section)
sources:
  sto9:
    name: "sto9"
    engine: "scrapling"
    url: "https://sto9.com/book/3352/index.html"
    domains: "sto9.com"
    chapter_link_pattern: ".*/chapter-\\d+\\.html"
    content_selector: "#chapter-content"
    # AI glossary settings for this source
    ai_glossary_enabled: true
    ai_glossary_extract_prompt: |
      Extract key terms from this Chinese-Vietnamese novel chapter pair.
      Return format: Hán = Việt (one per line)
      {text}
    ai_cleanup_enabled: true
    ai_cleanup_prompt: |
      Clean up this Vietnamese translation: remove remaining Chinese characters,
      fix pronouns, ensure consistent terminology.
      {text}
  # ... other sources
```

- [ ] **Step 2: Verify config example loads correctly**

```bash
cp novel2epub.example.yaml novel2epub.yaml
python -c "from novel2epub.config import load_config; cfg = load_config('novel2epub.db'); print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add novel2epub.example.yaml
git commit -m "docs: update example config with AI glossary source preset"
```

---

## Summary

This plan refactors the config architecture to:

1. **Source presets now include AI glossary/analysis settings** - reusable across ebooks from the same domain
2. **Per-ebook `ai_glossary_analysis` toggle** - opt-in for new domains, off by default for speed
3. **Three-layer config merge**: `defaults` → `source_preset` → `ebook_overrides`
4. **Web UI support** for selecting source preset and toggling AI analysis when adding ebooks
5. **Pipeline integration** to conditionally run AI glossary extraction/cleanup/evaluation

The key benefit: when adding a new ebook from a known source (e.g., sto9), you select the preset and get crawl config + AI glossary prompts automatically. For new domains, you enable `ai_glossary_analysis` once, and the system learns glossary from that ebook.