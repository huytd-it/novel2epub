# Web UI Performance — Bulk SQL for Chapter List

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate N+1 SQL queries in `chapter_rows()` so `/ebooks/{slug}` loads in ~50–100ms instead of 3–5s.

**Architecture:** Add `Storage.bulk_chapter_stats()` to fetch all chapter stats in one SQL query. Update `chapter_rows()` to accept an optional `stats_map` dict; when provided it uses pre-fetched data instead of per-chapter `_chapter_row()` calls. Update `ebook_home` to call bulk stats and pass the map through. Client-side JS rendering is already in place — no template changes needed.

**Tech Stack:** Python 3.10+, SQLite (via existing `Storage` class), pytest

## Global Constraints

- No new dependencies — use only stdlib + existing project libraries
- Backward compatible: `chapter_rows(chapters, storage)` without `stats_map` must continue to work unchanged
- `has_translated` must respect the `complete` flag in `meta_json` (same logic as `Storage.has_translated()`)
- `word_count` and `zh_char_count` are display estimates — not used for business logic
- All changes in `novel2epub/storage.py`, `novel2epub/toc.py`, `app/routes/ebooks.py` only

---

### Task 1: Add `Storage.bulk_chapter_stats()`

**Files:**
- Modify: `novel2epub/storage.py` (after `_chapter_row` method, ~line 130)
- Test: `tests/test_bulk_chapter_stats.py` (new file)

**Interfaces:**
- Produces: `Storage.bulk_chapter_stats() -> dict[int, dict]`
  - Key: chapter `idx` (int)
  - Value: `{"has_raw": bool, "has_translated": bool, "translated_len": int, "raw_len": int, "meta_json": str | None}`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bulk_chapter_stats.py
import json
import pytest
from novel2epub.storage import Storage, Chapter
from pathlib import Path
import tempfile


@pytest.fixture
def tmp_storage(tmp_path):
    from novel2epub.storage import _init_db, get_thread_connection
    db = tmp_path / "data.db"
    conn = get_thread_connection(db)
    _init_db(conn)
    s = Storage(tmp_path, "test-slug")
    s.ensure_dirs()
    return s


def _ch(idx):
    return Chapter(index=idx, url=f"http://example.com/{idx}", title=f"Ch {idx}")


def test_bulk_chapter_stats_empty(tmp_storage):
    result = tmp_storage.bulk_chapter_stats()
    assert result == {}


def test_bulk_chapter_stats_flags(tmp_storage):
    s = tmp_storage
    ch1 = _ch(1)
    ch2 = _ch(2)
    ch3 = _ch(3)

    s.write_raw(ch1, "你好世界")
    s.write_raw(ch2, "再见")
    s.write_translated(ch2, "Xin chào thế giới")
    s.mark_translated_complete(ch2)
    # ch3: write translated but mark incomplete
    s.write_translated(ch3, "partial")
    s.write_meta(ch3, {"complete": False})

    result = s.bulk_chapter_stats()

    assert result[1]["has_raw"] is True
    assert result[1]["has_translated"] is False

    assert result[2]["has_raw"] is True
    assert result[2]["has_translated"] is True
    assert result[2]["translated_len"] > 0
    assert result[2]["raw_len"] > 0

    # ch3: incomplete translation should count as not translated
    assert result[3]["has_translated"] is False


def test_bulk_chapter_stats_meta_json(tmp_storage):
    s = tmp_storage
    ch = _ch(10)
    s.write_translated(ch, "Xin chào")
    s.write_meta(ch, {"complete": True, "ai_rewrite": {"text": "draft", "generated_at": "2026-01-01"}})
    s.mark_translated_complete(ch)
    result = s.bulk_chapter_stats()
    assert result[10]["meta_json"] is not None
    meta = json.loads(result[10]["meta_json"])
    assert meta.get("ai_rewrite") is not None
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_bulk_chapter_stats.py -v
```

Expected: `AttributeError: 'Storage' object has no attribute 'bulk_chapter_stats'`

- [ ] **Step 3: Implement `bulk_chapter_stats()`**

Add this method to `Storage` class in `novel2epub/storage.py` after the `_chapter_row` method (~line 130):

```python
def bulk_chapter_stats(self) -> dict[int, dict]:
    """Fetch stats for all chapters of this ebook in one SQL query.

    Returns dict keyed by chapter idx with:
      has_raw, has_translated (respects complete flag), translated_len,
      raw_len, meta_json.
    """
    import json as _json
    rows = self.conn.execute(
        "SELECT idx, "
        "  CASE WHEN raw_text IS NOT NULL AND raw_text != '' THEN 1 ELSE 0 END AS has_raw_int, "
        "  CASE WHEN translated_text IS NOT NULL AND translated_text != '' THEN 1 ELSE 0 END AS has_tr_int, "
        "  LENGTH(translated_text) AS translated_len, "
        "  LENGTH(raw_text) AS raw_len, "
        "  meta_json "
        "FROM chapters WHERE ebook_slug = ?",
        (self.slug,),
    ).fetchall()
    result: dict[int, dict] = {}
    for row in rows:
        has_tr_raw = bool(row["has_tr_int"])
        if has_tr_raw:
            try:
                meta = _json.loads(row["meta_json"] or "{}")
            except Exception:
                meta = {}
            has_translated = bool(meta.get("complete", True))
        else:
            has_translated = False
        result[row["idx"]] = {
            "has_raw": bool(row["has_raw_int"]),
            "has_translated": has_translated,
            "translated_len": row["translated_len"] or 0,
            "raw_len": row["raw_len"] or 0,
            "meta_json": row["meta_json"],
        }
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_bulk_chapter_stats.py -v
```

Expected: all 3 tests PASS

- [ ] **Step 5: Commit**

```
git add novel2epub/storage.py tests/test_bulk_chapter_stats.py
git commit -m "perf: add Storage.bulk_chapter_stats() — one SQL query for all chapter stats"
```

---

### Task 2: Update `chapter_rows()` to accept `stats_map`

**Files:**
- Modify: `novel2epub/toc.py` (function `chapter_rows`, lines 84–128)
- Test: `tests/test_bulk_chapter_stats.py` (extend existing file)

**Interfaces:**
- Consumes: `Storage.bulk_chapter_stats() -> dict[int, dict]` (from Task 1)
- Produces: `chapter_rows(chapters, storage, stats_map=None) -> list[ChapterRow]`
  - When `stats_map` is provided: use it instead of per-chapter `_chapter_row()` calls
  - When `stats_map` is `None`: behavior unchanged (backward compatible)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_bulk_chapter_stats.py`:

```python
from novel2epub.toc import chapter_rows, ChapterRow


def test_chapter_rows_with_stats_map(tmp_storage):
    s = tmp_storage
    ch1 = _ch(1)
    ch2 = _ch(2)
    s.write_raw(ch1, "你好世界再见朋友")
    s.write_raw(ch2, "再见")
    s.write_translated(ch2, "Xin chao the gioi")
    s.mark_translated_complete(ch2)

    stats_map = s.bulk_chapter_stats()
    rows = chapter_rows([ch1, ch2], s, stats_map=stats_map)

    assert len(rows) == 2
    r1 = next(r for r in rows if r.index == 1)
    r2 = next(r for r in rows if r.index == 2)

    assert r1.has_raw is True
    assert r1.has_translated is False
    assert r1.word_count == 0
    assert r1.zh_char_count > 0  # estimated from raw_len

    assert r2.has_translated is True
    assert r2.word_count > 0  # estimated from translated_len


def test_chapter_rows_without_stats_map_still_works(tmp_storage):
    s = tmp_storage
    ch = _ch(5)
    s.write_raw(ch, "你好")
    rows = chapter_rows([ch], s)
    assert rows[0].has_raw is True
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_bulk_chapter_stats.py::test_chapter_rows_with_stats_map -v
```

Expected: `TypeError: chapter_rows() got an unexpected keyword argument 'stats_map'`

- [ ] **Step 3: Update `chapter_rows()` in `novel2epub/toc.py`**

Replace the existing `chapter_rows` function (lines 84–128) with:

```python
def chapter_rows(
    chapters: Iterable[Chapter],
    storage: Storage,
    stats_map: dict[int, dict] | None = None,
) -> list[ChapterRow]:
    import json as _json
    rows = []
    for ch in chapters:
        if stats_map is not None:
            s = stats_map.get(ch.index, {})
            has_raw = s.get("has_raw", False)
            has_translated = s.get("has_translated", False)
            # ponytail: byte-length estimates for display only, not business logic
            word_count = (s.get("translated_len") or 0) // 5 if has_translated else 0
            zh_char_count = (s.get("raw_len") or 0) // 3 if has_raw else 0
            meta_json = s.get("meta_json")
            try:
                meta = _json.loads(meta_json or "{}")
            except Exception:
                meta = {}
        else:
            has_translated = storage.has_translated(ch)
            word_count = count_words(storage.read_translated(ch)) if has_translated else 0
            has_raw = storage.has_raw(ch)
            zh_char_count = count_han_chars(storage.read_raw(ch)) if has_raw else 0
            meta = storage.read_meta(ch) if (has_translated and storage.has_meta(ch)) else {}

        bientap = ""
        bientap_tooltip = ""
        if has_translated and meta:
            try:
                if meta.get("ai_rewrite"):
                    ar = meta["ai_rewrite"]
                    when = ar.get("generated_at", "") if isinstance(ar, dict) else ""
                    bientap = "📝 Nháp AI"
                    tip = "AI rewrite draft pending review"
                    if when:
                        tip += f"\ngenerated_at: {when}"
                    bientap_tooltip = tip
                elif meta.get("before_rewrite"):
                    bientap = "✏️ Đã biên tập"
                    bientap_tooltip = "AI rewrite đã được áp dụng (giữ bản gốc trong before_rewrite để khôi phục)"
            except Exception:
                pass

        rows.append(ChapterRow(
            index=ch.index,
            title=ch.title,
            visible_title=ch.title or f"Chương {ch.index}",
            url=ch.url,
            has_raw=has_raw,
            has_translated=has_translated,
            missing_fields=chapter_missing(ch),
            duplicate_of=ch.duplicate_of,
            last_action_status=ch.last_action_status,
            word_count=word_count,
            zh_char_count=zh_char_count,
            bientap=bientap,
            bientap_tooltip=bientap_tooltip,
            skipped=ch.skipped,
        ))
    return rows
```

- [ ] **Step 4: Run all tests**

```
pytest tests/test_bulk_chapter_stats.py -v
```

Expected: all 5 tests PASS

- [ ] **Step 5: Commit**

```
git add novel2epub/toc.py tests/test_bulk_chapter_stats.py
git commit -m "perf: chapter_rows() accepts stats_map to skip N+1 queries"
```

---

### Task 3: Wire bulk stats into `ebook_home`

**Files:**
- Modify: `app/routes/ebooks.py` (functions `_chapter_rows` and `ebook_home`, lines 24–46 and 168–216)

**Interfaces:**
- Consumes: `Storage.bulk_chapter_stats() -> dict[int, dict]` (Task 1)
- Consumes: `chapter_rows(chapters, storage, stats_map=None)` (Task 2)

- [ ] **Step 1: Update `_chapter_rows()` to accept and forward `stats_map`**

Replace `_chapter_rows` (lines 24–46) in `app/routes/ebooks.py`:

```python
def _chapter_rows(
    cfg,
    *,
    sort: str = "source",
    direction: str = "asc",
    search: str = "",
    filter_raw: str = "any",
    filter_translated: str = "any",
    filter_missing: str = "any",
    stats_map: dict | None = None,
):
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    manifest = storage.load_manifest()
    if manifest is None:
        return []
    return apply_chapter_query(
        chapter_rows(manifest.chapters, storage, stats_map=stats_map),
        sort=sort,
        direction=direction,
        search=search,
        filter_raw=filter_raw,
        filter_translated=filter_translated,
        filter_missing=filter_missing,
    )
```

- [ ] **Step 2: Update `ebook_home` to use bulk stats**

Replace the `all_chapters = _chapter_rows(cfg)` and storage initialization block (lines 182–188) in `ebook_home`:

```python
cfg = deps.resolved_cfg(slug)
storage = Storage(cfg.output.data_dir, cfg.novel.slug)
manifest = storage.load_manifest()
epub_path = Path(cfg.epub_path)
crawl_problems = crawl_problem_indexes(manifest.chapters, storage) if manifest else []
stats_map = storage.bulk_chapter_stats()
all_chapters = _chapter_rows(cfg, stats_map=stats_map)
chapters_json = [dataclasses.asdict(r) for r in all_chapters]
cost_summary = read_cost_summary(storage)
```

- [ ] **Step 3: Run existing tests to verify nothing is broken**

```
pytest tests/ -v -x
```

Expected: all tests PASS (or same pass/fail as before this change)

- [ ] **Step 4: Manual smoke test**

Start the server and open `/ebooks/{slug}` for a novel with 500+ chapters. The page should load visibly faster. Check browser DevTools Network tab — server response time should be under 200ms.

```
uvicorn app.main:app --reload --port 8010
```

- [ ] **Step 5: Commit**

```
git add app/routes/ebooks.py
git commit -m "perf: ebook_home uses bulk_chapter_stats — eliminates N+1 SQL queries"
```
