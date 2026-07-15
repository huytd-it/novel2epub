# Refactor ranh giới TOC · Ebook · Sources (Change 1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ebook chỉ lưu `source_preset` + field user cố ý override; preset resolve live lúc load; `fetch-toc` không đụng metadata; JSON endpoint gom về `/api/v1`.

**Architecture:** Ba tầng một chiều `defaults → source preset → ebook overrides`, resolve tại `load_config` (đã có sẵn, không sửa). Mọi đường ghi copy dữ liệu preset xuống ebook bị xoá. Một helper thuần `strip_preset_defaults()` trong `novel2epub/sources.py` là nơi DUY NHẤT định nghĩa "override nào là thừa", dùng chung bởi migration script và route lưu settings.

**Tech Stack:** Python 3.10+, FastAPI, SQLite (`novel2epub.db`), Jinja2, pytest.

## Global Constraints

- Không đổi schema DB. Chỉ dọn *nội dung* cột `crawl_overrides_json`.
- Không thêm tính năng AI (đó là Change 2 / Change 3).
- Không sửa `pipeline.py` ngoài `_refresh_manifest` / `step_fetch_toc`.
- Comment và message tiếng Việt, khớp phong cách file xung quanh.
- Chạy test: `pytest tests/ -v`. Chạy một file: `pytest tests/test_x.py -v`.
- Working tree phải sạch trước khi bắt đầu (`git status --short` không ra gì).
- `deps.DB_PATH` kiểu `Path`. `deps.WORKSPACE_DIR` (`DB_PATH.parent / ".n2e"`) là thư mục KHÁC, **giữ nguyên**, không xoá.
- `novel2epub/cli.py` KHÔNG dùng alias của `deps` (nó có `DEFAULT_CONFIG_PATH` riêng) — đừng đụng vào.

## File Structure

| File | Trách nhiệm | Task |
|---|---|---|
| `novel2epub/sources.py` | Xoá `propagate_preset_update`; thêm `SCRAPLING_FIELD_MAP` + `strip_preset_defaults()` — luật "override thừa" ở đúng một chỗ | 1 |
| `scripts/cleanup_preset_overrides.py` | Script chạy tay dọn override do propagate để lại | 2 |
| `novel2epub/pipeline.py` | `_refresh_manifest` bỏ `force_meta`; `step_fetch_toc` bỏ `force` | 3 |
| `app/routes/settings.py` | `sync_to_source` bỏ propagate + trả ebook về tham chiếu; `save_source` dùng `strip_preset_defaults` | 4 |
| `app/deps.py` | Chỉ còn `DB_PATH` | 5 |
| `app/routes/api_v1/toc.py` | `POST /api/v1/toc/preview`, `POST /api/v1/ebooks/{slug}/meta/refresh` — thuần đọc | 6 |
| `app/templates/index.html` | Form hai khối EBOOK / SOURCE + preview danh sách chương | 6 |
| `app/routes/{ebooks,chapters,sources,settings,system}.py` + `api_v1/` | Gộp 13 → 6 module | 7 |

---

### Task 1: `strip_preset_defaults` + xoá `propagate_preset_update`

**Files:**
- Modify: `novel2epub/sources.py:196-235` (xoá `propagate_preset_update`), thêm helper mới
- Modify: `app/routes/sources.py:15` (import), `:154` (call site)
- Test: `tests/test_source_ebook_link.py`

**Interfaces:**
- Consumes: `SourcePreset.crawl_overrides() -> dict[str, Any]` (đã có, `novel2epub/sources.py:66`)
- Produces:
  - `SCRAPLING_FIELD_MAP: dict[str, str]` — map key lồng trong `crawl.scrapling` → tên field phẳng của `SourcePreset`
  - `strip_preset_defaults(crawl_over: dict[str, Any], preset: SourcePreset) -> tuple[dict[str, Any], list[str]]` — trả `(overrides đã lọc, danh sách key đã bỏ)`
  - `propagate_preset_update` KHÔNG CÒN TỒN TẠI — Task 2 và 4 phải không import nó

**Bối cảnh cho người triển khai:** `preset.crawl_overrides()` trả key **phẳng** (`scrapling_mode`, `proxy`, `solve_cloudflare`). Còn `crawl_overrides_json` của ebook có thể chứa dict **lồng** (`{"scrapling": {"mode": "stealthy"}}`) vì `update_ebook` ghi kiểu lồng. Hai dạng này cùng nghĩa nhưng khác tên — `mode` ↔ `scrapling_mode`. Helper phải quy đổi, nếu không sẽ không nhận ra override thừa.

- [ ] **Step 1: Viết test thất bại**

Thêm vào cuối `tests/test_source_ebook_link.py`:

```python
# ── strip_preset_defaults ───────────────────────────────────────────

from novel2epub.sources import strip_preset_defaults


class TestStripPresetDefaults:
    def _preset(self) -> SourcePreset:
        return SourcePreset(
            name="aixdzs",
            content_selector=".content",
            delay_seconds=2.0,
            scrapling_mode="stealthy",
        )

    def test_key_trung_preset_bi_bo(self):
        cleaned, removed = strip_preset_defaults(
            {"content_selector": ".content"}, self._preset()
        )
        assert cleaned == {}
        assert removed == ["content_selector"]

    def test_key_khac_preset_duoc_giu(self):
        cleaned, removed = strip_preset_defaults(
            {"content_selector": "#khac"}, self._preset()
        )
        assert cleaned == {"content_selector": "#khac"}
        assert removed == []

    def test_toc_url_luon_duoc_giu(self):
        cleaned, removed = strip_preset_defaults(
            {"toc_url": "https://example.com/book/1"}, self._preset()
        )
        assert cleaned == {"toc_url": "https://example.com/book/1"}
        assert removed == []

    def test_scrapling_long_duoc_quy_doi_ve_phang(self):
        # crawl.scrapling.mode ↔ preset.scrapling_mode — cùng nghĩa, khác tên.
        cleaned, removed = strip_preset_defaults(
            {"scrapling": {"mode": "stealthy"}}, self._preset()
        )
        assert cleaned == {}
        assert removed == ["scrapling.mode"]

    def test_scrapling_long_khac_preset_duoc_giu(self):
        cleaned, removed = strip_preset_defaults(
            {"scrapling": {"mode": "fetcher"}}, self._preset()
        )
        assert cleaned == {"scrapling": {"mode": "fetcher"}}
        assert removed == []

    def test_scrapling_giu_key_khac_bo_key_trung(self):
        cleaned, removed = strip_preset_defaults(
            {"scrapling": {"mode": "stealthy", "proxy": "http://p:1"}}, self._preset()
        )
        assert cleaned == {"scrapling": {"proxy": "http://p:1"}}
        assert removed == ["scrapling.mode"]

    def test_idempotent(self):
        preset = self._preset()
        once, _ = strip_preset_defaults({"content_selector": ".content"}, preset)
        twice, removed = strip_preset_defaults(once, preset)
        assert twice == once
        assert removed == []
```

- [ ] **Step 2: Chạy test để xác nhận nó fail**

Run: `pytest tests/test_source_ebook_link.py::TestStripPresetDefaults -v`
Expected: FAIL — `ImportError: cannot import name 'strip_preset_defaults' from 'novel2epub.sources'`

- [ ] **Step 3: Cài đặt helper**

Trong `novel2epub/sources.py`, thay TOÀN BỘ hàm `propagate_preset_update` (dòng 196-235, từ `def propagate_preset_update(` tới `return affected`) bằng:

```python
# Key lồng trong `crawl.scrapling` → tên field PHẲNG tương ứng của SourcePreset.
# `preset.crawl_overrides()` trả tên phẳng (`scrapling_mode`), còn ebook override
# ghi kiểu lồng (`{"scrapling": {"mode": ...}}`) — không quy đổi thì so sánh trượt.
SCRAPLING_FIELD_MAP = {
    "mode": "scrapling_mode",
    "solve_cloudflare": "solve_cloudflare",
    "network_idle": "network_idle",
    "impersonate": "impersonate",
    "proxy": "proxy",
    "dns_over_https": "dns_over_https",
}


def strip_preset_defaults(
    crawl_over: dict[str, Any],
    preset: SourcePreset,
) -> tuple[dict[str, Any], list[str]]:
    """Bỏ khỏi ``crawl_over`` những key có giá trị TRÙNG KHÍT preset.

    Ebook gắn source chỉ nên lưu field nó CỐ Ý override; field trùng preset là
    thừa và có hại — nó đóng băng ebook ở giá trị preset tại thời điểm ghi,
    khiến preset sửa về sau không còn tác dụng.

    ``toc_url`` không bao giờ bị bỏ: `SourcePreset` không có field này nên nó
    không xuất hiện trong ``preset.crawl_overrides()``.

    Trả ``(crawl_over đã lọc, danh sách key đã bỏ)``. Key lồng báo dạng
    ``"scrapling.mode"``. Hàm thuần, idempotent.
    """
    preset_vals = preset.crawl_overrides()
    cleaned: dict[str, Any] = {}
    removed: list[str] = []
    for key, value in crawl_over.items():
        if key == "scrapling" and isinstance(value, dict):
            nested: dict[str, Any] = {}
            for nk, nv in value.items():
                flat = SCRAPLING_FIELD_MAP.get(nk, nk)
                if flat in preset_vals and preset_vals[flat] == nv:
                    removed.append(f"scrapling.{nk}")
                else:
                    nested[nk] = nv
            if nested:
                cleaned[key] = nested
            continue
        if key in preset_vals and preset_vals[key] == value:
            removed.append(key)
        else:
            cleaned[key] = value
    return cleaned, removed
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `pytest tests/test_source_ebook_link.py::TestStripPresetDefaults -v`
Expected: PASS (7 test)

- [ ] **Step 5: Xoá `TestPropagatePresetUpdate` và thay bằng test luật mới**

Trong `tests/test_source_ebook_link.py`:

Sửa dòng 10 — bỏ `propagate_preset_update` khỏi import:

```python
from novel2epub.sources import SourcePreset, save_presets
```

Xoá TOÀN BỘ khối từ comment `# ── Task 9.2: propagate_preset_update ───` tới hết `class TestPropagatePresetUpdate` (dòng ~158-238). Thay bằng:

```python
# ── Luật: preset resolve LIVE, ebook không giữ bản sao ──────────────

class TestPresetResolveLive:
    def test_sua_preset_thi_ebook_an_theo_ngay_ma_khong_ghi_gi_vao_ebook(self, tmp_path):
        db = write_db_config(
            tmp_path / "novel2epub.db",
            defaults={"translate": {"type": "none"}},
            sources={"aixdzs": {"content_selector": ".old", "delay_seconds": 1.0}},
            ebooks={"novel-a": {"name": "A", "source": "aixdzs",
                                "crawl": {"toc_url": "https://aixdzs.com/d/1"}}},
        )
        before = _read_ebook_crawl(db, "novel-a")

        save_presets(db, {"aixdzs": SourcePreset(
            name="aixdzs", content_selector=".new", delay_seconds=2.0,
        )})

        cfg = load_config(db, "novel-a")
        assert cfg.crawl.content_selector == ".new"
        assert cfg.crawl.delay_seconds == 2.0
        # Điểm mấu chốt: ebook KHÔNG bị ghi thêm gì.
        assert _read_ebook_crawl(db, "novel-a") == before

    def test_override_cua_ebook_thang_preset(self, tmp_path):
        db = write_db_config(
            tmp_path / "novel2epub.db",
            defaults={"translate": {"type": "none"}},
            sources={"aixdzs": {"content_selector": ".preset"}},
            ebooks={"novel-a": {"name": "A", "source": "aixdzs",
                                "crawl": {"toc_url": "https://aixdzs.com/d/1",
                                          "content_selector": ".rieng"}}},
        )
        cfg = load_config(db, "novel-a")
        assert cfg.crawl.content_selector == ".rieng"
```

- [ ] **Step 6: Gỡ call site trong route**

Trong `app/routes/sources.py`:

Dòng 15 — bỏ `propagate_preset_update` khỏi import:

```python
from novel2epub.sources import SourcePreset, delete_preset, save_preset, save_presets
```

Xoá dòng 154 (`affected = propagate_preset_update(deps.DB_PATH, name, presets)`) và mọi dòng dùng biến `affected` liền sau đó. Đọc quanh dòng 150-165 trước khi sửa: nếu `affected` chỉ dùng để log/flash thì xoá luôn cả dòng đó; nếu nó vào response thì bỏ khỏi response.

Xác nhận không còn tham chiếu nào:

```bash
grep -rn "propagate_preset_update" --include=*.py app novel2epub tests scripts
```
Expected: không ra dòng nào.

- [ ] **Step 7: Sửa test monkeypatch propagate**

`tests/test_routes_sources_import.py:43` monkeypatch một hàm không còn tồn tại → xoá dòng đó:

```python
# XOÁ dòng này:
# monkeypatch.setattr(sources_route, "propagate_preset_update", lambda *a, **k: [])
```

- [ ] **Step 8: Chạy toàn bộ test**

Run: `pytest tests/ -v`
Expected: PASS. Nếu có test nào khác import `propagate_preset_update` thì fail là `ImportError` — sửa theo cùng cách.

- [ ] **Step 9: Commit**

```bash
git add novel2epub/sources.py app/routes/sources.py tests/test_source_ebook_link.py tests/test_routes_sources_import.py
git commit -m "refactor: xoá propagate_preset_update, thêm strip_preset_defaults

Preset đã resolve live tại load_config nên propagate là thừa; tệ hơn, nó
copy giá trị preset thành override cứng của ebook rồi tự khoá mình (lần
sửa preset sau bị bỏ qua vì key đã tồn tại).

strip_preset_defaults là nơi DUY NHẤT định nghĩa 'override nào là thừa',
có quy đổi scrapling lồng ↔ phẳng.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Script dọn override do propagate để lại

**Files:**
- Create: `scripts/cleanup_preset_overrides.py`
- Test: `tests/test_cleanup_preset_overrides.py` (tạo mới)

**Interfaces:**
- Consumes: `strip_preset_defaults(crawl_over, preset)` (Task 1), `load_presets(path) -> dict[str, SourcePreset]`
- Produces: `cleanup_overrides(db_path: str | Path, dry_run: bool = False) -> dict[str, list[str]]` — trả `{slug: [key đã bỏ]}`, chỉ gồm ebook thực sự có thay đổi

**Bối cảnh:** Chạy MỘT LẦN. Không cần hook lúc khởi động vì Task 1 đã chặn nguồn sinh override bẩn. Theo tiền lệ `scripts/migrate_to_single_yaml.py`.

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_cleanup_preset_overrides.py`:

```python
"""Test script dọn override thừa mà propagate_preset_update để lại."""
from __future__ import annotations

import json
from pathlib import Path

from novel2epub.db import get_connection
from tests.conftest import write_db_config

from scripts.cleanup_preset_overrides import cleanup_overrides


def _crawl(path: Path, slug: str) -> dict:
    conn = get_connection(str(path))
    row = conn.execute(
        "SELECT crawl_overrides_json FROM ebooks WHERE slug=?", (slug,)
    ).fetchone()
    return json.loads(row["crawl_overrides_json"] or "{}") if row else {}


def _db(tmp_path: Path, ebooks: dict) -> Path:
    return write_db_config(
        tmp_path / "novel2epub.db",
        defaults={"translate": {"type": "none"}},
        sources={"aixdzs": {"content_selector": ".content", "delay_seconds": 2.0,
                            "scrapling_mode": "stealthy"}},
        ebooks=ebooks,
    )


def test_bo_override_trung_preset(tmp_path):
    db = _db(tmp_path, {"a": {"name": "A", "source": "aixdzs", "crawl": {
        "toc_url": "https://aixdzs.com/d/1",
        "content_selector": ".content",   # trùng preset → bỏ
        "delay_seconds": 2.0,             # trùng preset → bỏ
    }}})
    report = cleanup_overrides(db)
    assert sorted(report["a"]) == ["content_selector", "delay_seconds"]
    assert _crawl(db, "a") == {"toc_url": "https://aixdzs.com/d/1"}


def test_giu_override_khac_preset(tmp_path):
    db = _db(tmp_path, {"a": {"name": "A", "source": "aixdzs", "crawl": {
        "toc_url": "https://aixdzs.com/d/1",
        "content_selector": ".rieng",     # khác preset → giữ
    }}})
    report = cleanup_overrides(db)
    assert "a" not in report
    assert _crawl(db, "a")["content_selector"] == ".rieng"


def test_ebook_khong_co_source_khong_bi_dung(tmp_path):
    db = _db(tmp_path, {"a": {"name": "A", "crawl": {
        "content_selector": ".content",
    }}})
    report = cleanup_overrides(db)
    assert report == {}
    assert _crawl(db, "a")["content_selector"] == ".content"


def test_source_khong_ton_tai_thi_bo_qua(tmp_path):
    db = _db(tmp_path, {"a": {"name": "A", "source": "khong-co", "crawl": {
        "content_selector": ".content",
    }}})
    report = cleanup_overrides(db)
    assert report == {}
    assert _crawl(db, "a")["content_selector"] == ".content"


def test_dry_run_khong_ghi_gi(tmp_path):
    db = _db(tmp_path, {"a": {"name": "A", "source": "aixdzs", "crawl": {
        "toc_url": "https://aixdzs.com/d/1",
        "content_selector": ".content",
    }}})
    before = _crawl(db, "a")
    report = cleanup_overrides(db, dry_run=True)
    assert report["a"] == ["content_selector"]
    assert _crawl(db, "a") == before


def test_idempotent(tmp_path):
    db = _db(tmp_path, {"a": {"name": "A", "source": "aixdzs", "crawl": {
        "toc_url": "https://aixdzs.com/d/1",
        "content_selector": ".content",
    }}})
    cleanup_overrides(db)
    after_first = _crawl(db, "a")
    report = cleanup_overrides(db)
    assert report == {}
    assert _crawl(db, "a") == after_first
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Run: `pytest tests/test_cleanup_preset_overrides.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.cleanup_preset_overrides'`

- [ ] **Step 3: Cài đặt script**

Kiểm tra trước xem `scripts/` đã có `__init__.py` chưa:

```bash
ls scripts/
```

Nếu chưa có `scripts/__init__.py` thì tạo file rỗng để test import được:

```bash
touch scripts/__init__.py
```

Tạo `scripts/cleanup_preset_overrides.py`:

```python
"""Dọn override thừa mà `propagate_preset_update` (đã xoá) để lại.

Propagate từng copy giá trị preset vào `crawl_overrides_json` của ebook. Những
override đó vừa thừa (load_config đã resolve preset live) vừa có hại: chúng
đóng băng ebook ở giá trị preset tại thời điểm copy, khiến preset sửa về sau
không còn tác dụng lên ebook đó.

Script này bỏ các key trùng khít preset, giữ nguyên key user thật sự override.
Chạy MỘT LẦN là đủ — nguồn sinh override bẩn đã bị xoá.

    python -m scripts.cleanup_preset_overrides --dry-run
    python -m scripts.cleanup_preset_overrides
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from novel2epub.db import get_thread_connection
from novel2epub.sources import load_presets, strip_preset_defaults


def cleanup_overrides(
    db_path: str | Path,
    dry_run: bool = False,
) -> dict[str, list[str]]:
    """Bỏ override trùng preset khỏi mọi ebook có `source_preset`.

    Trả ``{slug: [key đã bỏ]}`` — chỉ gồm ebook thực sự đổi. Ebook không có
    source, hoặc trỏ tới preset không tồn tại, được bỏ qua nguyên vẹn.
    Idempotent: chạy lần hai trả ``{}``.
    """
    path = Path(db_path).resolve()
    if not path.exists():
        return {}
    presets = load_presets(path)
    conn = get_thread_connection(path)
    rows = conn.execute(
        "SELECT slug, source_preset, crawl_overrides_json FROM ebooks "
        "WHERE source_preset IS NOT NULL AND source_preset != ''"
    ).fetchall()

    report: dict[str, list[str]] = {}
    updates: list[tuple[str, str]] = []
    for row in rows:
        preset = presets.get(row["source_preset"])
        if preset is None:
            continue  # preset đã bị xoá — không có gì để so, giữ nguyên
        crawl = json.loads(row["crawl_overrides_json"] or "{}")
        cleaned, removed = strip_preset_defaults(crawl, preset)
        if not removed:
            continue
        report[row["slug"]] = removed
        updates.append((json.dumps(cleaned, ensure_ascii=False), row["slug"]))

    if updates and not dry_run:
        with conn:
            conn.executemany(
                "UPDATE ebooks SET crawl_overrides_json = ? WHERE slug = ?",
                updates,
            )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-c", "--config",
        default=os.environ.get("NOVEL2EPUB_DB", "novel2epub.db"),
        help="Đường dẫn file DB gộp (mặc định: novel2epub.db)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Chỉ in ra những gì SẼ xoá, không ghi vào DB.",
    )
    args = parser.parse_args()

    report = cleanup_overrides(args.config, dry_run=args.dry_run)
    if not report:
        print("Không có override thừa nào. Không cần làm gì.")
        return

    prefix = "[dry-run] SẼ bỏ" if args.dry_run else "Đã bỏ"
    total = 0
    for slug, keys in sorted(report.items()):
        print(f"{prefix} khỏi {slug}: {', '.join(keys)}")
        total += len(keys)
    print(f"\n{len(report)} ebook, {total} override.")
    if args.dry_run:
        print("Chạy lại không có --dry-run để áp dụng.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `pytest tests/test_cleanup_preset_overrides.py -v`
Expected: PASS (6 test)

- [ ] **Step 5: Chạy thử dry-run trên DB thật**

```bash
python -m scripts.cleanup_preset_overrides --dry-run
```
Expected: in ra danh sách override sẽ bỏ (hoặc "Không có override thừa nào"). **Không** ghi gì. Đọc kỹ output — nếu thấy key nào bạn CỐ Ý đặt trùng giá trị preset thì dừng lại và báo người dùng trước khi chạy thật.

- [ ] **Step 6: Commit**

```bash
git add scripts/cleanup_preset_overrides.py scripts/__init__.py tests/test_cleanup_preset_overrides.py
git commit -m "feat: script dọn override thừa do propagate để lại

Chạy một lần; nguồn sinh override bẩn đã bị xoá ở commit trước.
--dry-run để xem trước.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `fetch-toc` không đụng metadata

**Files:**
- Modify: `novel2epub/pipeline.py:309` (`_refresh_manifest`), `:339-349`, `:652` (`step_fetch_toc`)
- Modify: `app/routes/jobs.py:329-341`
- Modify: `app/templates/ebook.html:164-167`
- Test: `tests/test_pipeline_meta.py`

**Interfaces:**
- Produces:
  - `_refresh_manifest(cfg, storage, crawler, log) -> Manifest` — **bỏ** keyword-only `force_meta`
  - `step_fetch_toc(cfg, log=_print, *, should_cancel=None) -> Manifest` — **bỏ** keyword-only `force`

**Bối cảnh:** Nút "Lấy toàn bộ danh mục" gửi `force=true` → `_refresh_manifest(force_meta=True)` → ghi đè `title`/`author` từ config và `description`/`cover_url` từ trang vừa crawl, đè lên metadata user đã sửa tay. Nhánh `manifest is None` (lần đầu, chưa có manifest) vẫn phải điền metadata — GIỮ NGUYÊN.

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_pipeline_meta.py` (đọc đầu file trước để tái dùng đúng fixture/fake crawler đang có — đã có `_toc(n)` và một fake crawler class ở dòng ~23):

```python
def test_fetch_toc_khong_de_len_metadata_user_da_sua(tmp_path, monkeypatch):
    """fetch-toc chỉ đồng bộ danh sách chương; metadata user sửa tay phải nguyên vẹn."""
    from novel2epub.pipeline import step_fetch_toc
    from novel2epub.storage import Storage

    cfg = _cfg(tmp_path)  # dùng helper sẵn có trong file
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)

    # Lần đầu: có manifest + metadata từ TOC.
    step_fetch_toc(cfg, lambda m: None)
    manifest = storage.load_manifest()

    # User sửa tay metadata.
    manifest.title = "Tên do user đặt"
    manifest.author = "Tác giả do user đặt"
    manifest.description = "Mô tả do user viết"
    storage.save_manifest(manifest)

    # Lấy TOC lần nữa.
    step_fetch_toc(cfg, lambda m: None)

    after = storage.load_manifest()
    assert after.title == "Tên do user đặt"
    assert after.author == "Tác giả do user đặt"
    assert after.description == "Mô tả do user viết"


def test_fetch_toc_khong_con_tham_so_force():
    """`force` đã bị bỏ — gọi kèm nó phải là TypeError, không im lặng bỏ qua."""
    import inspect

    from novel2epub.pipeline import step_fetch_toc

    assert "force" not in inspect.signature(step_fetch_toc).parameters
```

Nếu `tests/test_pipeline_meta.py` chưa có helper `_cfg(tmp_path)`, đọc `test_step_fetch_toc_saves_metadata_no_content` (dòng ~39) và dùng đúng cách dựng cfg + monkeypatch crawler mà nó đang dùng.

- [ ] **Step 2: Chạy test để xác nhận fail**

Run: `pytest tests/test_pipeline_meta.py -v -k "khong_de_len_metadata or khong_con_tham_so_force"`
Expected: FAIL — metadata bị đè (`assert 'Tên do TOC' == 'Tên do user đặt'`) và `force` vẫn còn trong signature.

- [ ] **Step 3: Bỏ `force_meta` khỏi `_refresh_manifest`**

`novel2epub/pipeline.py:309` — đổi chữ ký:

```python
def _refresh_manifest(cfg: Config, storage: Storage, crawler, log: LogFn) -> Manifest:
    """Lấy mục lục mới (nếu được) và trộn vào manifest cache, giữ title cũ.

    KHÔNG đụng tới metadata của manifest đã tồn tại: title/author/description/
    cover_url thuộc quyền ebook, chỉ form Settings mới được ghi. Metadata chỉ
    được điền ở lần đầu (chưa có manifest).

    Nếu không lấy được mục lục mới mà đã có cache => dùng lại cache. Nếu vừa
    không lấy được vừa chưa có cache => báo lỗi.
    """
```

Thay khối `else:` (dòng ~339-349) — xoá 4 lệnh gán metadata, giữ `source_url` và `metadata_missing`:

```python
        else:
            manifest.source_url = toc.source_url or manifest.source_url or cfg.crawl.toc_url
            manifest.metadata_missing = toc.metadata_missing
```

Phần trộn chương ngay dưới (từ comment `# Trộn danh sách chương:`) **giữ nguyên không đổi**.

- [ ] **Step 4: Bỏ `force` khỏi `step_fetch_toc`**

`novel2epub/pipeline.py:652`:

```python
def step_fetch_toc(cfg: Config, log: LogFn = _print, *, should_cancel: CancelFn | None = None) -> Manifest:
    """Chỉ lấy mục lục + metadata lần đầu (không crawl nội dung chương).

    Dùng để xem nhanh danh sách chương trước khi chọn phạm vi crawl. KHÔNG làm
    mới metadata của ebook đã có — dùng `POST /api/v1/ebooks/{slug}/meta/refresh`
    cho việc đó.
    """
```

Và trong thân hàm, đổi lời gọi:

```python
        manifest = _refresh_manifest(cfg, storage, crawler, log)
```

- [ ] **Step 5: Gỡ nhánh `force` trong route**

`app/routes/jobs.py:329-341` — thay toàn bộ hàm `start_ebook_job` bằng:

```python
@router.post("/ebooks/{slug}/jobs/{step}")
def start_ebook_job(request: Request, slug: str, step: str):
    cfg = deps.resolved_cfg(slug)
    request.app.state.job.start(step, cfg)
    return RedirectResponse(url=f"/ebooks/{slug}", status_code=303)
```

**Trước khi thay**, đọc dòng 329-345 để giữ đúng phần `return` / redirect hiện có — nhánh `else` của hàm cũ là hành vi cần giữ. Bỏ tham số `force: bool = Form(False)` và toàn bộ nhánh `if step == "fetch-toc" and force:`.

- [ ] **Step 6: Bỏ input `force` trong template**

`app/templates/ebook.html:164-167` — xoá dòng `<input type="hidden" name="force" value="true">`:

```html
<form method="post" action="/ebooks/{{ slug }}/jobs/fetch-toc" class="inline-form" data-job-category="crawl">
    <button type="submit" class="btn btn-sm btn-secondary">Lấy toàn bộ danh mục</button>
</form>
```

- [ ] **Step 7: Xác nhận không còn chỗ nào truyền `force_meta`**

```bash
grep -rn "force_meta" --include=*.py --include=*.html app novel2epub tests scripts
```
Expected: không ra dòng nào.

- [ ] **Step 8: Chạy test**

Run: `pytest tests/test_pipeline_meta.py -v`
Expected: PASS. Test `test_step_fetch_toc_saves_metadata_no_content` (dòng ~39) phải VẪN pass — nó test lần đầu (chưa có manifest), nhánh ta giữ nguyên. Nếu nó fail, đọc kỹ: có thể nó đang gọi `step_fetch_toc(cfg, log, force=True)` → bỏ `force=True`.

Rồi: `pytest tests/ -v` — Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add novel2epub/pipeline.py app/routes/jobs.py app/templates/ebook.html tests/test_pipeline_meta.py
git commit -m "fix: fetch-toc không còn ghi đè metadata ebook

Nút 'Lấy toàn bộ danh mục' gửi force=true → _refresh_manifest ghi đè
title/author từ config và description/cover từ trang vừa crawl, đè lên
metadata user đã sửa tay. Mỗi lần đồng bộ chương là một lần mất metadata.

TOC giờ chỉ đồng bộ chương. Metadata chỉ điền ở lần đầu (chưa có manifest).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: `settings.py` — `sync_to_source` + `save_source` về tham chiếu thuần

**Files:**
- Modify: `app/routes/settings.py:277-304` (`save_source` filter), `:317-370` (`sync_to_source`)
- Test: `tests/test_routes_settings_source.py` (tạo mới)

**Interfaces:**
- Consumes: `strip_preset_defaults(crawl_over, preset)` (Task 1), `save_preset(path, preset)` (đã có, `novel2epub/sources.py:238`)

**Bối cảnh — hai bug trong file này:**

1. `save_source:295-298` so `preset_vals.get(nk)` với `nk` ∈ `("mode", "solve_cloudflare", …)`, nhưng preset lưu tên **phẳng** `scrapling_mode`. `preset_vals.get("mode")` luôn là `None` → luôn khác → **mọi field scrapling luôn bị ghi thành override**. Đây chính là cỗ máy sinh override thừa. `strip_preset_defaults` có `SCRAPLING_FIELD_MAP` để quy đổi đúng.
2. `sync_to_source:365` gọi `propagate_preset_update` (đã xoá ở Task 1) → **file này hiện đang gãy import**, phải sửa.

Sau khi `sync_to_source` đẩy field lên preset, ebook vẫn giữ chính các override đó — giờ trùng khít preset nên thừa, và là thứ đóng băng ebook. Phải xoá chúng để ebook về tham chiếu thuần.

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_routes_settings_source.py`:

```python
"""Test luật sở hữu source↔ebook ở route settings: lưu source và sync-to-source
không được để lại override thừa."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from novel2epub.db import get_connection
from novel2epub.sources import load_presets
from tests.conftest import write_db_config


def _crawl(path: Path, slug: str) -> dict:
    conn = get_connection(str(path))
    row = conn.execute(
        "SELECT crawl_overrides_json FROM ebooks WHERE slug=?", (slug,)
    ).fetchone()
    return json.loads(row["crawl_overrides_json"] or "{}") if row else {}


def _fake_job():
    class Job:
        def status(self):
            return {
                "crawl": {"running": False, "step": "", "error": "", "log": []},
                "translate": {"running": False, "step": "", "error": "", "log": []},
            }

    return Job()


def _client(monkeypatch, tmp_path):
    db = write_db_config(
        tmp_path / "novel2epub.db",
        defaults={"translate": {"type": "none"}},
        sources={"aixdzs": {"content_selector": ".preset", "delay_seconds": 2.0,
                            "scrapling_mode": "stealthy",
                            "domains": "aixdzs.com"}},
        ebooks={
            "a": {"name": "A", "source": "aixdzs",
                  "crawl": {"toc_url": "https://aixdzs.com/d/1"}},
            # Ebook thứ hai cùng preset — dùng để khẳng định không ai ghi vào nó.
            "b": {"name": "B", "source": "aixdzs",
                  "crawl": {"toc_url": "https://aixdzs.com/d/2"}},
        },
    )
    from app import deps

    monkeypatch.setattr(deps, "DB_PATH", db)
    from app.main import app

    app.state.job = _fake_job()
    return db, TestClient(app, follow_redirects=False)


def _form(**over) -> dict:
    base = {
        "toc_url": "https://aixdzs.com/d/1",
        "chapter_link_pattern": ".*",
        "max_chapters": 0,
        "delay_seconds": 2.0,
        "max_workers": 1,
        "content_selector": ".preset",
        "scrapling_mode": "stealthy",
        "max_pages_per_chapter": 10,
        "toc_max_pages": 5,
        "retry_attempts": 3,
        "retry_delay_seconds": 5.0,
        "retry_backoff": 2.0,
        "retry_max_delay_seconds": 120.0,
    }
    base.update(over)
    return base


def test_luu_source_trung_preset_khong_sinh_override(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    r = client.post("/ebooks/a/settings/source", data=_form())
    assert r.status_code == 303
    crawl = _crawl(db, "a")
    # Chỉ còn toc_url + retry (retry không đến từ preset). Không có
    # content_selector/delay_seconds/scrapling vì chúng trùng preset.
    assert "content_selector" not in crawl
    assert "delay_seconds" not in crawl
    assert "scrapling" not in crawl
    assert crawl["toc_url"] == "https://aixdzs.com/d/1"


def test_luu_source_khac_preset_thi_giu_override(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    r = client.post("/ebooks/a/settings/source", data=_form(content_selector="#rieng"))
    assert r.status_code == 303
    assert _crawl(db, "a")["content_selector"] == "#rieng"


def test_sync_to_source_day_len_preset_va_don_override_cua_ebook(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    # Ebook override khác preset.
    client.post("/ebooks/a/settings/source", data=_form(content_selector="#rieng"))
    assert _crawl(db, "a")["content_selector"] == "#rieng"

    r = client.post("/ebooks/a/settings/sync-to-source")
    assert r.status_code == 303

    # Preset nhận giá trị mới.
    assert load_presets(db)["aixdzs"].content_selector == "#rieng"
    # Ebook về tham chiếu thuần — không giữ bản sao thừa.
    assert "content_selector" not in _crawl(db, "a")


def test_sync_to_source_khong_ghi_vao_ebook_khac(monkeypatch, tmp_path):
    """Ebook khác cùng preset ăn theo lúc load, KHÔNG bị ghi vào DB.

    Đây là thứ propagate_preset_update từng làm sai: nó ghi giá trị preset vào
    từng ebook, biến chúng thành override cứng rồi tự khoá.
    """
    from novel2epub.config import load_config

    db, client = _client(monkeypatch, tmp_path)
    before_b = _crawl(db, "b")

    client.post("/ebooks/a/settings/source", data=_form(content_selector="#rieng"))
    client.post("/ebooks/a/settings/sync-to-source")

    # b không bị ghi thêm gì...
    assert _crawl(db, "b") == before_b
    # ...nhưng vẫn thấy giá trị mới nhờ resolve live lúc load.
    assert load_config(db, "b").crawl.content_selector == "#rieng"
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Run: `pytest tests/test_routes_settings_source.py -v`
Expected: FAIL — `ImportError: cannot import name 'propagate_preset_update'` (Task 1 đã xoá nó nhưng `settings.py:321` còn import).

- [ ] **Step 3: Sửa `save_source` dùng helper chung**

`app/routes/settings.py` — thay khối lọc (dòng ~277-304, từ comment `# Nếu ebook có source, chỉ ghi field khác preset` tới `crawl = filtered`) bằng:

```python
    # Ebook gắn source chỉ lưu field nó CỐ Ý override — field trùng preset là
    # thừa và sẽ đóng băng ebook ở giá trị preset lúc ghi. `retry` không đến từ
    # preset nên luôn giữ; `toc_url` không có trong SourcePreset nên
    # strip_preset_defaults tự khắc giữ.
    cfg = deps.resolved_cfg(slug)
    source_name = getattr(cfg, "source", "")
    if source_name:
        preset = load_presets(deps.DB_PATH).get(source_name)
        if preset:
            retry = crawl.pop("retry", None)
            crawl, _removed = strip_preset_defaults(crawl, preset)
            if retry is not None:
                crawl["retry"] = retry
```

Thêm import ở đầu file (gộp vào dòng import `novel2epub.sources` sẵn có):

```python
from novel2epub.sources import load_presets, save_preset, strip_preset_defaults
```

Đọc dòng import hiện tại của file trước khi sửa — giữ nguyên các tên khác đang được import.

- [ ] **Step 4: Sửa `sync_to_source`**

Thay TOÀN BỘ hàm `sync_to_source` (dòng ~317-370) bằng:

```python
@router.post("/ebooks/{slug}/settings/sync-to-source")
def sync_to_source(slug: str):
    """Nâng override riêng của ebook thành cấu hình chung của preset.

    Sau khi đẩy field lên preset, XOÁ chính các override đó khỏi ebook: preset
    đã mang giá trị ấy nên override chỉ còn là bản sao thừa, và là thứ khiến
    ebook không còn ăn theo preset về sau.

    Không cần propagate sang ebook khác — `load_config` resolve preset live.
    """
    cfg = deps.resolved_cfg(slug)
    source_name = getattr(cfg, "source", "")
    if not source_name:
        raise HTTPException(status_code=400, detail="Ebook không có source preset.")

    presets = load_presets(deps.DB_PATH)
    preset = presets.get(source_name)
    if preset is None:
        raise HTTPException(status_code=404, detail=f"Nguồn '{source_name}' không tồn tại.")

    crawl = cfg.crawl
    changed_fields: list[str] = []

    # Field phẳng: so crawl đã resolve với preset; khác nghĩa là ebook đã override.
    for key, preset_val in preset.crawl_overrides().items():
        if key in SCRAPLING_FIELD_MAP.values():
            continue  # xử lý riêng bên dưới (tên lồng khác tên phẳng)
        ebook_val = getattr(crawl, key, None)
        if ebook_val is not None and ebook_val != preset_val:
            setattr(preset, key, ebook_val)
            changed_fields.append(key)

    # Field scrapling: crawl dùng tên lồng (`mode`), preset dùng tên phẳng
    # (`scrapling_mode`) — quy đổi qua SCRAPLING_FIELD_MAP.
    if crawl.scrapling:
        for nested_key, flat_key in SCRAPLING_FIELD_MAP.items():
            ebook_val = getattr(crawl.scrapling, nested_key, None)
            if ebook_val is not None and ebook_val != getattr(preset, flat_key, None):
                setattr(preset, flat_key, ebook_val)
                changed_fields.append(flat_key)

    if not changed_fields:
        return RedirectResponse(url=f"/ebooks/{slug}/settings", status_code=303)

    save_preset(deps.DB_PATH, preset)

    # Ebook về tham chiếu thuần: bỏ override giờ đã trùng khít preset.
    raw = _read_crawl_overrides(deps.DB_PATH, slug)
    cleaned, removed = strip_preset_defaults(raw, preset)
    if removed:
        update_ebook(deps.DB_PATH, slug, {"crawl": cleaned}, replace_crawl=True)

    logger.info(
        "[source] sync ebook=%s → preset=%s: đẩy lên %s, dọn override %s",
        slug, source_name, changed_fields, removed,
    )
    return RedirectResponse(url=f"/ebooks/{slug}/settings", status_code=303)
```

Cập nhật import đầu file:

```python
from novel2epub.sources import (
    SCRAPLING_FIELD_MAP,
    load_presets,
    save_preset,
    strip_preset_defaults,
)
```

Bỏ import cục bộ trong hàm cũ (`from novel2epub.sources import SourcePreset, save_presets, propagate_preset_update` và `from dataclasses import asdict`) — không còn dùng.

- [ ] **Step 5: Thêm `replace_crawl` vào `update_ebook` + helper đọc raw override**

`update_ebook` (`novel2epub/config_writer.py:56`) MERGE khối crawl qua
`_deep_merge_raw(current_crawl, crawl_updates)` (dòng 78-86) → nó **không thể xoá
key**. `sync_to_source` cần ghi đè nguyên khối để bỏ override thừa, nên thêm
tham số `replace_crawl`, mặc định `False` để mọi call site khác giữ nguyên hành vi.

`novel2epub/config_writer.py` — đổi chữ ký dòng 56:

```python
def update_ebook(
    path: str | Path,
    slug: str,
    updates: dict[str, Any],
    *,
    replace_crawl: bool = False,
) -> None:
    """Merge `updates` (khối "novel"/"crawl"/"output"/"source") vào row
    `ebooks.<slug>` — chỉ chạm đúng cột liên quan, ebook khác giữ nguyên.

    `replace_crawl=True`: ghi đè NGUYÊN KHỐI `crawl_overrides_json` thay vì
    merge — cách duy nhất để XOÁ một override (merge không bỏ được key).
    """
```

và thay khối crawl (dòng 78-86) bằng:

```python
        crawl_updates = updates.get("crawl")
        if isinstance(crawl_updates, dict):
            filtered = {k: v for k, v in crawl_updates.items()
                        if k not in _DEPRECATED_CRAWL_FIELDS}
            if replace_crawl:
                new_crawl = filtered
            else:
                current_crawl = json.loads(row["crawl_overrides_json"] or "{}")
                new_crawl = _deep_merge_raw(current_crawl, filtered)
            set_clauses.append("crawl_overrides_json = ?")
            params.append(json.dumps(new_crawl, ensure_ascii=False))
```

Thêm helper vào `app/routes/settings.py` (đặt ngay trên `sync_to_source`):

```python
def _read_crawl_overrides(db_path, slug: str) -> dict:
    """Đọc raw `crawl_overrides_json` của ebook (KHÔNG resolve preset)."""
    from novel2epub.db import get_thread_connection

    conn = get_thread_connection(Path(db_path).resolve())
    row = conn.execute(
        "SELECT crawl_overrides_json FROM ebooks WHERE slug = ?", (slug,)
    ).fetchone()
    return json.loads(row["crawl_overrides_json"] or "{}") if row else {}
```

Đảm bảo `import json` và `from pathlib import Path` có ở đầu `settings.py` (thêm nếu thiếu).

- [ ] **Step 6: Chạy test**

Run: `pytest tests/test_routes_settings_source.py -v`
Expected: PASS (3 test)

Rồi: `pytest tests/ -v` — Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/routes/settings.py novel2epub/config_writer.py tests/test_routes_settings_source.py
git commit -m "fix: settings không còn sinh override thừa; sync-to-source dọn sau khi đẩy

save_source so preset_vals.get('mode') trong khi preset lưu tên phẳng
'scrapling_mode' → không bao giờ khớp → mọi field scrapling luôn bị ghi
thành override. Dùng strip_preset_defaults (có SCRAPLING_FIELD_MAP).

sync-to-source: bỏ propagate, dùng save_preset, và xoá override vừa đẩy
lên preset để ebook về tham chiếu thuần.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: `deps.py` chỉ còn `DB_PATH`

**Files:**
- Modify: `app/deps.py:27-36`, `:150`, `:159`, `:163`, `:177`, `:182`
- Modify: `app/main.py:14`, `app/routes/{settings,library,ebooks,sources,automation,jobs,dashboard}.py`
- Test: `tests/test_library_bulk.py:25-27`, `tests/test_ebook_management.py:48`

**Interfaces:**
- Produces: `deps.DB_PATH: Path` — tên DUY NHẤT trỏ file DB. `deps.WORKSPACE_DIR: Path` giữ nguyên (thư mục `.n2e`, KHÁC file DB).
- Bị xoá: `WORKSPACE_PATH`, `CONFIG_PATH`, `LIBRARY_PATH`, `SOURCES_PATH`, `AUTOMATIONS_PATH`, `LIBRARY_STATE_PATH`

**Bối cảnh:** Sáu tên cho cùng một file, lại lệch kiểu (`WORKSPACE_PATH`/`CONFIG_PATH`/`LIBRARY_PATH`/`SOURCES_PATH` là `str`; `AUTOMATIONS_PATH`/`LIBRARY_STATE_PATH` là `Path`). Mọi hàm nhận đều làm `Path(path).resolve()` nên truyền `Path` an toàn. Xoá thay vì alias để lỗi lộ ra lúc import.

Số call site: `settings.py` 13, `library.py` 9, `ebooks.py` 6, `sources.py` 4, `automation.py` 4, `jobs.py` 2, `dashboard.py` 1, `main.py` 1. `logging_config.py` chỉ import `BASE_DIR` — không đụng. `cli.py` không dùng — không đụng.

- [ ] **Step 1: Sửa test trước (chúng đang monkeypatch tên sắp bị xoá)**

`tests/test_library_bulk.py:25-27` — ba dòng này monkeypatch sang các đường dẫn `.yaml` thời multi-file cũ (`WORKSPACE_PATH` và `SOURCES_PATH` trỏ hai file KHÁC nhau, trong khi thực tế cả hai là cùng một DB). Thay bằng một `DB_PATH` duy nhất:

```python
def _client(monkeypatch, tmp_path):
    from app import deps
    from app.main import app

    monkeypatch.setattr(deps, "DB_PATH", tmp_path / "novel2epub.db")
    app.state.job = _fake_job()
    return app, TestClient(app)
```

`tests/test_ebook_management.py:48` — thay:

```python
    monkeypatch.setattr(deps, "DB_PATH", tmp_path / "novel2epub.db")
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Run: `pytest tests/test_library_bulk.py tests/test_ebook_management.py -v`
Expected: FAIL — route vẫn đọc `deps.WORKSPACE_PATH` / `deps.LIBRARY_STATE_PATH` (chưa đổi) nên monkeypatch `DB_PATH` không có tác dụng; test ghi vào DB thật hoặc không tìm thấy dữ liệu.

- [ ] **Step 3: Xoá alias trong `deps.py`**

Thay dòng 27-36 bằng:

```python
WORKSPACE_DIR = DB_PATH.parent / ".n2e"
```

(Xoá cả khối comment "Tên biến giữ nguyên để route/hàm cũ…" ở dòng 27-29 — nó mô tả thứ không còn tồn tại.)

Trong chính `deps.py`, đổi các call site còn lại: dòng ~150 (`load_config(WORKSPACE_PATH)`), ~159 (`load_library(WORKSPACE_PATH)`), ~163 (`load_presets(SOURCES_PATH)`), ~177 (`return WORKSPACE_PATH`), ~182 (`load_config(WORKSPACE_PATH, slug)`) → dùng `DB_PATH`. Riêng `ebook_config_path` trả về chuỗi để hiển thị:

```python
def ebook_config_path(slug: str) -> str:
    # File gộp: mọi ebook nằm inline trong cùng file. Trả về để hiển thị.
    return str(DB_PATH)
```

Và trong `cfg()`, thông báo lỗi dùng `DB_PATH`:

```python
def cfg():
    try:
        return load_config(DB_PATH)
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=400,
            detail=f"{e} — copy novel2epub.example.yaml thành {DB_PATH} rồi chỉnh sửa.",
        ) from e
```

- [ ] **Step 4: Đổi mọi call site**

```bash
grep -rn "deps\.\(WORKSPACE_PATH\|CONFIG_PATH\|LIBRARY_PATH\|SOURCES_PATH\|AUTOMATIONS_PATH\|LIBRARY_STATE_PATH\)" --include=*.py app
```

Đổi TẤT CẢ sang `deps.DB_PATH`. **Đừng** đụng `deps.WORKSPACE_DIR` (`app/routes/sources.py:21` — thư mục `.n2e`, đúng như hiện tại).

`app/main.py:14` — sửa import:

```python
from .deps import BASE_DIR, DB_PATH
```

rồi đổi chỗ dùng `WORKSPACE_PATH` trong `main.py` sang `DB_PATH`.

- [ ] **Step 5: Xác nhận sạch**

```bash
grep -rn "WORKSPACE_PATH\|CONFIG_PATH\|LIBRARY_PATH\|SOURCES_PATH\|AUTOMATIONS_PATH\|LIBRARY_STATE_PATH" --include=*.py app novel2epub tests scripts
```
Expected: không ra dòng nào. (`novel2epub/cli.py` có `DEFAULT_CONFIG_PATH` — tên khác, không khớp pattern trên, để nguyên.)

- [ ] **Step 6: Chạy test**

Run: `pytest tests/ -v`
Expected: PASS.

- [ ] **Step 7: Khởi động app để bắt lỗi import**

```bash
python -c "from app.main import app; print('OK', len(app.routes), 'routes')"
```
Expected: `OK <n> routes` — không `ImportError`/`AttributeError`.

- [ ] **Step 8: Commit**

```bash
git add app/ tests/test_library_bulk.py tests/test_ebook_management.py
git commit -m "refactor: deps chỉ còn DB_PATH

Sáu tên cho cùng một file DB, lại lệch kiểu (bốn str, hai Path). Xoá thay
vì alias để lỗi lộ lúc import. WORKSPACE_DIR (.n2e) là thư mục khác, giữ.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: `/api/v1/toc/preview` + `meta/refresh` + form hai khối

**Files:**
- Create: `app/routes/api_v1/__init__.py`, `app/routes/api_v1/toc.py`
- Modify: `app/main.py` (include router mới)
- Modify: `app/routes/library.py:101-126` (bỏ `preview_ebook_api`), `:171` (`_write_new_ebook`), `:212-234` (`create_ebook` nhận `description`), `:264` (call site bulk)
- Modify: `novel2epub/config_writer.py:154` (`add_ebook` ghi `description`)
- Modify: `app/templates/index.html:256-336` (form), `:440-600` (JS inline)
- Test: `tests/test_api_v1_toc.py` (tạo mới), `tests/test_add_ebook_flow.py` (bỏ 3 test preview cũ, thêm test description)

**Interfaces:**
- Produces:
  - `POST /api/v1/toc/preview` — form fields `toc_url`, `scrapling_mode` (tuỳ chọn) → JSON `{meta: {title, author, description, cover_url}, source: {matched: bool, name, engine, content_selector, delay_seconds}, chapters: [{index, title, url}], chapter_count, slug}`
  - `POST /api/v1/ebooks/{slug}/meta/refresh` → JSON `{title, author, description, cover_url}` — **không ghi gì**
- Consumes: `_build_meta_crawl_cfg(toc_url, scrapling_mode)` và `slugify(value)` từ `app/routes/library.py` (Task 7 sẽ dời chúng)

**Bối cảnh:** `/library/ebooks/preview` hiện chỉ trả `chapter_count`, không trả danh sách chương → không kiểm tra được selector đúng chưa trước khi tạo ebook. Ngoài ra `create_ebook` (library.py:213) chỉ nhận `slug/name/author/toc_url` — **không có `description`**, nên mô tả user gõ ở form bị vứt âm thầm.

`PREVIEW_CHAPTER_LIMIT = 50` — chỉ trả 50 chương đầu cho preview; `chapter_count` vẫn là tổng thật.

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_api_v1_toc.py`:

```python
"""Test API preview TOC: thuần đọc, không ghi gì xuống DB."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tests.conftest import write_db_config


class _FakeChapter:
    def __init__(self, index: int, url: str, title: str):
        self.index, self.url, self.title = index, url, title


class _FakeToc:
    title = "书名"
    author = "作者"
    description = "简介"
    cover_url = "https://x/c.jpg"
    source_url = "https://aixdzs.com/d/1"
    metadata_missing = False

    def __init__(self, n: int = 3):
        self.chapters = [
            _FakeChapter(i, f"https://aixdzs.com/d/1/{i}.html", f"第{i}章")
            for i in range(1, n + 1)
        ]


class _FakeCrawler:
    def __init__(self, cfg):
        self.cfg = cfg

    def fetch_toc(self):
        return _FakeToc()

    def close(self):
        pass


def _fake_job():
    class Job:
        def status(self):
            return {
                "crawl": {"running": False, "step": "", "error": "", "log": []},
                "translate": {"running": False, "step": "", "error": "", "log": []},
            }

    return Job()


def _client(monkeypatch, tmp_path):
    db = write_db_config(
        tmp_path / "novel2epub.db",
        defaults={"translate": {"type": "none"}},
        sources={"aixdzs": {"content_selector": ".content", "delay_seconds": 2.0,
                            "domains": "aixdzs.com"}},
        ebooks={"a": {"name": "A", "source": "aixdzs",
                      "crawl": {"toc_url": "https://aixdzs.com/d/1"}}},
    )
    from app import deps

    monkeypatch.setattr(deps, "DB_PATH", db)
    from app.routes.api_v1 import toc as toc_route

    monkeypatch.setattr(toc_route, "ScraplingCrawler", _FakeCrawler)
    from app.main import app

    app.state.job = _fake_job()
    return db, TestClient(app)


def _db_dump(path: Path) -> str:
    return path.read_bytes().hex()


def test_preview_tra_danh_sach_chuong(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    r = client.post("/api/v1/toc/preview", data={"toc_url": "https://aixdzs.com/d/1"})
    assert r.status_code == 200
    body = r.json()
    assert body["chapter_count"] == 3
    assert len(body["chapters"]) == 3
    assert body["chapters"][0]["title"] == "第1章"
    assert body["chapters"][0]["url"] == "https://aixdzs.com/d/1/1.html"
    assert body["meta"]["title"] == "书名"
    assert body["meta"]["author"] == "作者"


def test_preview_detect_source_preset(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    r = client.post("/api/v1/toc/preview", data={"toc_url": "https://aixdzs.com/d/1"})
    src = r.json()["source"]
    assert src["matched"] is True
    assert src["name"] == "aixdzs"
    assert src["content_selector"] == ".content"


def test_preview_url_khong_khop_preset(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    r = client.post("/api/v1/toc/preview", data={"toc_url": "https://la.com/d/1"})
    assert r.json()["source"]["matched"] is False


def test_preview_khong_ghi_gi_xuong_db(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    before = _db_dump(db)
    client.post("/api/v1/toc/preview", data={"toc_url": "https://aixdzs.com/d/1"})
    assert _db_dump(db) == before


def test_preview_thieu_url_bao_loi(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    r = client.post("/api/v1/toc/preview", data={"toc_url": "  "})
    assert r.status_code == 400
    assert "error" in r.json()


def test_meta_refresh_tra_de_xuat_va_khong_ghi_gi(monkeypatch, tmp_path):
    db, client = _client(monkeypatch, tmp_path)
    before = _db_dump(db)
    r = client.post("/api/v1/ebooks/a/meta/refresh")
    assert r.status_code == 200
    assert r.json()["title"] == "书名"
    # Bất biến chặn bug cũ tái diễn: đề xuất, không ghi.
    assert _db_dump(db) == before
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Run: `pytest tests/test_api_v1_toc.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.routes.api_v1'`

- [ ] **Step 3: Tạo package `api_v1`**

Tạo `app/routes/api_v1/__init__.py`:

```python
"""JSON API v1 — mọi endpoint trả JSON nằm dưới `/api/v1`.

Chia theo domain thay vì dồn một file: ~50 endpoint JSON (chapters, batch,
queue, notes, glossary…) trong một module là không đọc nổi. Mỗi sub-module
export `router`; `router` ở đây gom lại và là thứ `app/main.py` include.
"""
from __future__ import annotations

from fastapi import APIRouter

from . import toc

router = APIRouter(prefix="/api/v1")
router.include_router(toc.router)
```

Tạo `app/routes/api_v1/toc.py`:

```python
"""Preview mục lục + đề xuất làm mới metadata — THUẦN ĐỌC.

Không endpoint nào ở đây được ghi xuống DB. Metadata ebook chỉ có đúng một
đường ghi là form `POST /ebooks/{slug}/settings/novel`; giữ bất biến đó là lý
do bug "fetch-toc ghi đè metadata" không thể tái diễn.
"""
from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import JSONResponse

from novel2epub.crawler import ScraplingCrawler
from novel2epub.sources import detect_preset, load_presets

from .. import deps
from ..library import _build_meta_crawl_cfg, slugify

router = APIRouter()

# Preview chỉ cần đủ để mắt người soát selector đúng chưa — không phải cả bộ.
PREVIEW_CHAPTER_LIMIT = 50


def _fetch_toc(toc_url: str, scrapling_mode: str = ""):
    crawl_cfg, _source_name = _build_meta_crawl_cfg(toc_url, scrapling_mode)
    crawler = ScraplingCrawler(crawl_cfg)
    try:
        return crawler.fetch_toc()
    finally:
        crawler.close()


@router.post("/toc/preview")
def preview_toc(toc_url: str = Form(""), scrapling_mode: str = Form("")):
    """Fetch mục lục và trả metadata + danh sách chương. KHÔNG ghi gì."""
    toc_url = toc_url.strip()
    if not toc_url:
        return JSONResponse({"error": "Thiếu URL mục lục."}, status_code=400)

    try:
        toc = _fetch_toc(toc_url, scrapling_mode.strip())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    presets = load_presets(deps.DB_PATH)
    source_name = detect_preset(toc_url, presets) or ""
    source: dict = {"matched": bool(source_name), "name": source_name}
    if source_name:
        preset = presets[source_name]
        source.update({
            "engine": preset.engine,
            "content_selector": preset.content_selector,
            "delay_seconds": preset.delay_seconds,
            "scrapling_mode": preset.scrapling_mode,
        })

    title = toc.title or ""
    return JSONResponse({
        "meta": {
            "title": title,
            "author": toc.author or "",
            "description": toc.description or "",
            "cover_url": toc.cover_url or "",
        },
        "source": source,
        "chapters": [
            {"index": ch.index, "title": ch.title, "url": ch.url}
            for ch in toc.chapters[:PREVIEW_CHAPTER_LIMIT]
        ],
        "chapter_count": len(toc.chapters),
        "slug": slugify(title or toc_url),
    })


@router.post("/ebooks/{slug}/meta/refresh")
def refresh_meta(slug: str):
    """ĐỀ XUẤT metadata mới lấy từ trang mục lục. KHÔNG ghi.

    UI hiện kết quả cạnh giá trị hiện tại; muốn áp dụng thì đi qua form
    `POST /ebooks/{slug}/settings/novel` như bình thường.
    """
    cfg = deps.resolved_cfg(slug)
    toc_url = (cfg.crawl.toc_url or "").strip()
    if not toc_url:
        raise HTTPException(status_code=400, detail="Ebook chưa có URL mục lục.")

    try:
        toc = _fetch_toc(toc_url)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    return JSONResponse({
        "title": toc.title or "",
        "author": toc.author or "",
        "description": toc.description or "",
        "cover_url": toc.cover_url or "",
    })
```

- [ ] **Step 4: Đăng ký router**

`app/main.py` — thêm `api_v1` vào khối import từ `.routes` (dòng ~17-31) và thêm include SAU các router khác:

```python
app.include_router(api_v1.router)
```

- [ ] **Step 5: Chạy test**

Run: `pytest tests/test_api_v1_toc.py -v`
Expected: PASS (6 test)

- [ ] **Step 6: `create_ebook` nhận `description`**

`app/routes/library.py` — `_write_new_ebook` (dòng 171) thêm tham số và truyền xuống; `create_ebook` (dòng 213) thêm `description: str = Form("")`.

Kiểm tra `add_ebook` trong `novel2epub/config_writer.py:154` có nhận `description` không:

```bash
grep -n "def add_ebook" -A 12 novel2epub/config_writer.py
```

Cột `description` CÓ trong bảng `ebooks` (xem `tests/conftest.py:56`) nhưng `add_ebook` hiện KHÔNG ghi nó. Thêm tham số `description: str = ""` vào `add_ebook`, đưa vào câu INSERT (cả danh sách cột, danh sách `?`, và mệnh đề `ON CONFLICT ... DO UPDATE SET description = excluded.description`).

Rồi `_write_new_ebook`:

```python
def _write_new_ebook(
    toc_url: str, slug: str, name: str, author: str,
    description: str = "", scrapling_mode: str = "",
) -> dict:
```

và truyền `description=description` vào `add_ebook(...)`.

`create_ebook`:

```python
@router.post("/library/ebooks")
def create_ebook(
    slug: str = Form(""),
    name: str = Form(""),
    author: str = Form(""),
    description: str = Form(""),
    toc_url: str = Form(""),
):
    toc_url = toc_url.strip()
    if not toc_url:
        raise HTTPException(status_code=400, detail="Thiếu URL mục lục.")

    if not name and toc_url:
        try:
            fetched = _fetch_meta(toc_url)
            name = fetched.get("name", "")
            author = author or fetched.get("author", "")
            description = description or fetched.get("description", "")
            slug = slug or fetched.get("slug", "")
        except Exception:
            pass

    result = _write_new_ebook(toc_url, slug, name, author, description)
    return RedirectResponse(url=f"/ebooks/{result['slug']}/settings", status_code=303)
```

`create_ebooks_bulk` (dòng 264) — cập nhật lời gọi cho khớp chữ ký mới:

```python
            created = _write_new_ebook(
                url, fetched.get("slug", ""), fetched.get("name", ""),
                fetched.get("author", ""), fetched.get("description", ""),
            )
```

- [ ] **Step 7: Test `description` được lưu**

`tests/test_add_ebook_flow.py:79` — `fake_add_ebook` phải nhận thêm `description`,
nếu không nó `TypeError` ngay khi route truyền tham số mới:

```python
    def fake_add_ebook(path, slug, *, name="", title="", author="",
                       description="", toc_url="", source_name="", preset=None):
        captured.update(path=str(path), slug=slug, name=name, title=title,
                        description=description)
```

Thêm test mới vào cùng file (bám đúng khuôn `test_create_ebook_calls_add_ebook`
ở dòng 72):

```python
def test_create_ebook_luu_description(monkeypatch):
    """Mô tả user gõ ở form phải tới được add_ebook, không bị vứt âm thầm."""
    from app.routes import library

    app, client = _client(monkeypatch)
    captured = {}

    def fake_add_ebook(path, slug, *, name="", title="", author="",
                       description="", toc_url="", source_name="", preset=None):
        captured.update(description=description)

    monkeypatch.setattr(library, "add_ebook", fake_add_ebook)
    monkeypatch.setattr(library, "load_presets", lambda path: {})

    res = client.post("/library/ebooks", data={
        "toc_url": "https://www.shuhaige.net/372421/",
        "name": "Tên Truyện", "author": "Tác Giả", "slug": "ten-truyen",
        "description": "Mô tả X",
    }, follow_redirects=False)

    assert res.status_code == 303
    assert captured["description"] == "Mô tả X"
```

- [ ] **Step 8: Bỏ endpoint preview cũ + dời test của nó**

Xoá `preview_ebook_api` (`app/routes/library.py:101-126`) và route
`/library/ebooks/preview`. `_fetch_meta` (dòng 65) VẪN được
`create_ebook`/`create_ebooks_bulk` dùng — giữ.

`tests/test_add_ebook_flow.py` có BA test bám endpoint vừa xoá — chúng sẽ fail
404. Xoá cả ba (dòng ~22-66: comment `# ---- preview endpoint ----`,
`test_preview_returns_metadata`, `test_preview_missing_url`,
`test_preview_fetch_error_returns_400`); `tests/test_api_v1_toc.py` ở Step 1 đã
phủ đúng các trường hợp đó cho endpoint mới (trả metadata / thiếu URL / lỗi fetch).

Sửa docstring dòng 1 cho khớp thực tế còn lại của file:

```python
"""Tests cho luồng tạo ebook mới: POST /library/ebooks (preview TOC đã chuyển
sang /api/v1/toc/preview, xem tests/test_api_v1_toc.py)."""
```

```bash
grep -rn "library/ebooks/preview" --include=*.py --include=*.html --include=*.js app tests
```
Expected: chỉ còn hit trong `index.html` — Step 9 sẽ đổi.

- [ ] **Step 9: Form hai khối + preview chương**

`app/templates/index.html` — sửa panel `data-step="2"` (dòng 279-334). Giữ nguyên các ID mà JS đang bám: `#preview-box`, `#preview-placeholder`, `#pv-cover`, `#pv-chapters`, `#slug`, `#pv-title-input`, `#pv-author-input`, `#pv-desc-input`, `#pv-row-source`, `#pv-source-name`, `#pv-source-detail`.

Thay bảng `pv-table` phẳng hiện tại bằng HAI `<fieldset>` tách bạch, cộng một khối danh sách chương. Dùng đúng class Tailwind như các fieldset sẵn có trong file (copy từ dòng 263 hoặc 280):

```html
<!-- KHỐI 1: EBOOK — dữ liệu riêng ebook này, sửa được -->
<fieldset class="...">   <!-- copy class từ fieldset dòng 280 -->
    <legend class="...">Thông tin ebook <span class="text-fg-muted">— của riêng ebook này</span></legend>
    <table class="pv-table">
        <tbody>
            <tr id="pv-row-title">
                <td class="pv-cell-label">Tên</td>
                <td class="pv-cell-value"><input type="text" id="pv-title-input" class="pv-input input input-sm w-full"></td>
            </tr>
            <tr id="pv-row-author">
                <td class="pv-cell-label">Tác giả</td>
                <td class="pv-cell-value"><input type="text" id="pv-author-input" class="pv-input input input-sm w-full"></td>
            </tr>
            <tr id="pv-row-desc">
                <td class="pv-cell-label">Mô tả</td>
                <td class="pv-cell-value"><textarea id="pv-desc-input" rows="3" class="pv-input input input-sm w-full"></textarea></td>
            </tr>
            <tr>
                <td class="pv-cell-label">Slug</td>
                <td class="pv-cell-value"><input type="text" name="slug" id="slug" class="slug-input input input-sm w-full" placeholder="tự sinh từ tên"></td>
            </tr>
        </tbody>
    </table>
</fieldset>

<!-- KHỐI 2: SOURCE — thuộc preset dùng chung, CHỈ ĐỌC -->
<fieldset class="..." id="pv-source-block">
    <legend class="...">Nguồn <span class="text-fg-muted">— dùng chung, chỉ đọc</span></legend>
    <div id="pv-row-source">
        <span id="pv-source-name" class="badge badge-info"></span>
        <span id="pv-source-detail" class="text-xs text-fg-muted dark:text-fg-muted-dark ml-1"></span>
        <a id="pv-source-link" href="/sources" class="text-xs ml-2">Sửa tại /sources →</a>
    </div>
    <div id="pv-source-none" class="text-sm" style="display:none">
        URL này chưa khớp nguồn nào. Crawl gần như chắc chắn sẽ hỏng.
        <a href="/sources" class="font-semibold">Tạo nguồn mới →</a>
    </div>
</fieldset>

<!-- Preview danh sách chương -->
<fieldset class="..." id="pv-toc-block" style="display:none">
    <legend class="...">Mục lục lấy được (<span id="pv-toc-count">0</span> chương)</legend>
    <ol id="pv-toc-list" class="text-sm max-h-48 overflow-y-auto"></ol>
    <div id="pv-toc-more" class="text-xs text-fg-muted mt-1" style="display:none"></div>
</fieldset>
```

Xoá `<div class="pv-slug">` cũ (dòng 289-291) — slug đã chuyển vào khối EBOOK. Giữ `#pv-cover` và `#pv-chapters` ở `pv-header` như cũ.

Thêm hidden input cho `description` — form đã có `#description` ở dòng 259, giữ nguyên.

- [ ] **Step 10: Cập nhật JS**

Trong script inline của `index.html` (~dòng 440-600):

Đổi endpoint (dòng ~543):

```javascript
var res = await fetch("/api/v1/toc/preview", {
```

Response shape đổi từ phẳng sang lồng — sửa chỗ đọc kết quả. Đọc kỹ đoạn xử lý hiện tại (dòng ~545-595) rồi map lại:

```javascript
// Shape mới: {meta:{...}, source:{matched,name,...}, chapters:[...], chapter_count, slug}
var meta = data.meta || {};
if (pvTitleInput) pvTitleInput.value = meta.title || "";
if (pvAuthorInput) pvAuthorInput.value = meta.author || "";
if (pvDescInput) pvDescInput.value = meta.description || "";
if (slugEl && !slugEl.value) slugEl.value = data.slug || "";

var cover = document.getElementById("pv-cover");
if (cover) {
    if (meta.cover_url) { cover.src = meta.cover_url; cover.style.display = ""; }
    else { cover.style.display = "none"; }
}

var pvChapters = document.getElementById("pv-chapters");
if (pvChapters) pvChapters.textContent = (data.chapter_count || 0) + " chương";

// Khối SOURCE — chỉ đọc
var src = data.source || {};
var rowSource = document.getElementById("pv-row-source");
var noneSource = document.getElementById("pv-source-none");
if (src.matched) {
    rowSource.style.display = "";
    noneSource.style.display = "none";
    document.getElementById("pv-source-name").textContent = src.name;
    document.getElementById("pv-source-detail").textContent =
        [src.content_selector, src.scrapling_mode].filter(Boolean).join(" · ");
} else {
    rowSource.style.display = "none";
    noneSource.style.display = "";
}

// Preview mục lục
var tocBlock = document.getElementById("pv-toc-block");
var tocList = document.getElementById("pv-toc-list");
var tocMore = document.getElementById("pv-toc-more");
tocList.innerHTML = "";
(data.chapters || []).forEach(function (ch) {
    var li = document.createElement("li");
    li.textContent = ch.title || ch.url;
    tocList.appendChild(li);
});
document.getElementById("pv-toc-count").textContent = data.chapter_count || 0;
var shown = (data.chapters || []).length;
if (data.chapter_count > shown) {
    tocMore.textContent = "… và " + (data.chapter_count - shown) + " chương nữa";
    tocMore.style.display = "";
} else {
    tocMore.style.display = "none";
}
tocBlock.style.display = (data.chapter_count > 0) ? "" : "none";
```

Đảm bảo hidden input được đồng bộ trước khi submit — tìm chỗ hiện tại gán `nameEl.value` / `authorEl.value` và thêm `description`:

```javascript
if (descriptionEl && pvDescInput) descriptionEl.value = pvDescInput.value;
```

(`descriptionEl` = `document.getElementById("description")`.)

- [ ] **Step 11: Kiểm thử tay**

```bash
uvicorn app.main:app --reload --port 8010
```

Mở `http://localhost:8010`, bấm "+ Thêm ebook", dán một URL mục lục thật, bấm "Xem trước". Kiểm:
- Danh sách chương hiện ra, số chương khớp
- Khối SOURCE hiện tên preset + link /sources, KHÔNG có ô input nào sửa được
- URL lạ → hiện "chưa khớp nguồn nào"
- Tạo ebook → mô tả được lưu (mở `/ebooks/<slug>/settings` xem)

- [ ] **Step 12: Chạy test**

Run: `pytest tests/ -v`
Expected: PASS.

- [ ] **Step 13: Commit**

```bash
git add app/routes/api_v1/ app/main.py app/routes/library.py app/templates/index.html novel2epub/config_writer.py tests/test_api_v1_toc.py tests/test_add_ebook_flow.py
git commit -m "feat: /api/v1/toc/preview + form thêm ebook chia hai khối

Preview trả cả danh sách chương để soát selector trước khi tạo. Form tách
khối EBOOK (sửa được) khỏi khối SOURCE (chỉ đọc, link sang /sources) —
đúng luật tham chiếu thuần, tránh vô tình sinh override riêng.

meta/refresh chỉ ĐỀ XUẤT, không ghi: metadata ebook giữ đúng một đường
ghi là form settings.

Sửa luôn: create_ebook không nhận description nên mô tả gõ lúc tạo bị
vứt âm thầm.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Gộp route 13 → 6 module

**Files:**
- Modify: `app/routes/ebooks.py` (nhận `library.py`)
- Modify: `app/routes/chapters.py` (nhận `glossary.py`; JSON endpoint dời sang `api_v1/`)
- Create: `app/routes/system.py` (nhận `jobs.py`, `storage.py`, `reader.py`, `automation.py`, `dashboard.py`)
- Create: `app/routes/api_v1/{chapters,batch,queue,notes,glossary,dashboard}.py`
- Delete: `app/routes/{library,glossary,jobs,storage,notes,reader,automation,dashboard}.py`
- Modify: `app/main.py`
- Test: cập nhật import trong `tests/`

**Interfaces:**
- Produces: `app/main.py` include đúng 6 router: `ebooks`, `chapters`, `sources`, `settings`, `system`, `api_v1`
- Mọi URL cũ GIỮ NGUYÊN — commit này thuần di chuyển code, không đổi hành vi

**Bối cảnh:** Đây là commit đụng nhiều file nhất nhưng rủi ro logic thấp nhất — nếu sai thì là `ImportError` lộ ngay, không âm thầm. **Không sửa logic trong task này.** Chỉ cắt–dán + đổi import.

URL JSON cũ (`/api/ebooks/...`) giữ song song với `/api/v1/ebooks/...` bằng **duplicate decorator**, KHÔNG redirect (308 với POST có thể đổi method ở một số client):

```python
@router.post("/ebooks/{slug}/batch/export")          # → /api/v1/ebooks/...
@legacy.post("/api/ebooks/{slug}/batch/export")      # URL cũ, deprecated
def export_batch(...):
    ...
```

`legacy = APIRouter()` include ở `main.py` KHÔNG có prefix.

- [ ] **Step 1: Chốt bản đồ đích trước khi động vào**

Ghi lại inventory hiện tại để đối chiếu sau:

```bash
for f in app/routes/*.py; do echo "--- $f"; grep -nE '^@router\.(get|post|put|delete)' "$f" | sed 's/@router\.//'; done > /tmp/routes-before.txt
python -c "from app.main import app; print(sorted((r.path, tuple(sorted(getattr(r,'methods',[])))) for r in app.routes))" > /tmp/urls-before.txt
wc -l /tmp/routes-before.txt
```

`/tmp/urls-before.txt` là lưới an toàn: cuối task phải khớp y hệt.

- [ ] **Step 2: Tạo `system.py`**

Tạo `app/routes/system.py` với docstring:

```python
"""Route vận hành hệ thống: job queue, log, storage, reader, automation,
dashboard — những trang không thuộc một ebook cụ thể hoặc cắt ngang nhiều ebook.

Gộp từ jobs.py, storage.py, reader.py, automation.py, dashboard.py.
"""
```

Move nguyên văn các handler render HTML + form-POST từ 5 file đó. Handler JSON (`/api/...`) KHÔNG vào đây — Step 4 đưa sang `api_v1/`.

`jobs.py` có cả hai loại — tách:
- HTML/form-POST → `system.py`: `/jobs/{step}`, `/ebooks/{slug}/jobs/*`, `/queue`, `/logs`, `/download`, `/ebooks/{slug}/cover`, `/ebooks/{slug}/download`
- JSON → `api_v1/queue.py`: `/api/status`, `/api/queue*`, `/api/logs`

- [ ] **Step 3: Gộp `library.py` → `ebooks.py`, `glossary.py` → `chapters.py`**

Move toàn bộ handler + helper. Chú ý:
- `_build_meta_crawl_cfg` và `slugify` đang được `app/routes/api_v1/toc.py` import từ `..library` (Task 6) → sau khi move, đổi thành `from ..ebooks import _build_meta_crawl_cfg, slugify`.
- Kiểm tra không tạo circular import: `api_v1/toc.py` import từ `ebooks.py`, nên `ebooks.py` KHÔNG được import từ `api_v1`.

```bash
grep -rn "from ..library import\|from .library import\|routes.library\|routes import library" --include=*.py app tests
grep -rn "from ..glossary import\|from .glossary import\|routes.glossary\|routes import glossary" --include=*.py app tests
```

- [ ] **Step 4: Tạo các sub-module `api_v1/`**

Move handler JSON theo domain:

| Từ | Sang | Endpoint |
|---|---|---|
| `chapters.py` | `api_v1/chapters.py` | `/api/ebooks/{slug}/chapters/*` (translated, translated-mt, revert-edits, delete-translation, toggle-skip, retranslate-title, parapolish, paraexplain), `/api/chapters/{index}/translated` |
| `chapters.py` | `api_v1/batch.py` | `/api/ebooks/{slug}/batch/*` (clean-raw, update-skip, translate-titles, delete-translation, suggest-glossary, ai-rewrite, export, import, translate) |
| `jobs.py` | `api_v1/queue.py` | `/api/status`, `/api/queue*`, `/api/logs` |
| `notes.py` | `api_v1/notes.py` | `/api/ebooks/{slug}/notes*` |
| `glossary.py` | `api_v1/glossary.py` | `/api/ebooks/{slug}/glossary/*` |
| `dashboard.py` | `api_v1/dashboard.py` | `/api/dashboard` |

Mỗi file theo khuôn:

```python
"""<Domain> JSON API. Path KHÔNG có prefix — `api_v1/__init__.py` gắn `/api/v1`.

`legacy` giữ URL `/api/...` cũ (deprecated, xoá sau 1 release) bằng duplicate
decorator thay vì redirect — 308 với POST có thể bị client đổi method.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()
legacy = APIRouter()
```

Với mỗi handler: path trên `router` bỏ tiền tố `/api` (vì `__init__` đã có `/api/v1`), còn `legacy` giữ nguyên path cũ đầy đủ.

Ví dụ `/api/ebooks/{slug}/notes` →

```python
@router.get("/ebooks/{slug}/notes")
@legacy.get("/api/ebooks/{slug}/notes")
def list_notes(slug: str):
    ...
```

Cập nhật `api_v1/__init__.py`:

```python
from . import batch, chapters, dashboard, glossary, notes, queue, toc

router = APIRouter(prefix="/api/v1")
for _m in (toc, chapters, batch, queue, notes, glossary, dashboard):
    router.include_router(_m.router)

# URL cũ `/api/...` — không prefix. main.py include riêng.
legacy_router = APIRouter()
for _m in (chapters, batch, queue, notes, glossary, dashboard):
    legacy_router.include_router(_m.legacy)
```

(`toc.py` là endpoint MỚI ở Task 6 — không có URL cũ, nên không có `legacy`.)

- [ ] **Step 5: Cập nhật `main.py`**

```python
from .routes import api_v1, chapters, ebooks, settings, sources, system

app.include_router(ebooks.router)
app.include_router(chapters.router)
app.include_router(sources.router)
app.include_router(settings.router)
app.include_router(system.router)
app.include_router(api_v1.router)
app.include_router(api_v1.legacy_router)
```

- [ ] **Step 6: Xoá file cũ**

```bash
git rm app/routes/library.py app/routes/glossary.py app/routes/jobs.py \
       app/routes/storage.py app/routes/notes.py app/routes/reader.py \
       app/routes/automation.py app/routes/dashboard.py
```

- [ ] **Step 7: Cập nhật import trong tests**

```bash
grep -rln "routes import \(library\|glossary\|jobs\|storage\|notes\|reader\|automation\|dashboard\)\|routes\.\(library\|glossary\|jobs\|storage\|notes\|reader\|automation\|dashboard\)" --include=*.py tests
```

Đổi từng file sang module mới. Bản đồ: `library`→`ebooks`, `glossary`→`chapters`, `jobs`/`storage`/`reader`/`automation`/`dashboard`→`system`. Test monkeypatch handler JSON → trỏ vào `app.routes.api_v1.<domain>`.

- [ ] **Step 8: Đối chiếu URL — không được mất/đổi cái nào**

```bash
python -c "from app.main import app; print(sorted((r.path, tuple(sorted(getattr(r,'methods',[])))) for r in app.routes))" > /tmp/urls-after.txt
diff /tmp/urls-before.txt /tmp/urls-after.txt
```

Expected: diff CHỈ có thêm các URL `/api/v1/...` mới. **Không** được mất URL cũ nào, không đổi method nào. Nếu mất → có handler bị bỏ sót lúc move.

- [ ] **Step 9: Chạy test + khởi động app**

Run: `pytest tests/ -v`
Expected: PASS.

```bash
python -c "from app.main import app; print('OK', len(app.routes), 'routes')"
```
Expected: `OK <n> routes`, không lỗi.

- [ ] **Step 10: Kiểm thử tay các trang chính**

```bash
uvicorn app.main:app --reload --port 8010
```

Mở và xác nhận render được: `/`, `/ebooks/<slug>`, `/sources`, `/ebooks/<slug>/settings`, `/queue`, `/logs`, `/dashboard`, `/automation`, `/storage`, `/ebooks/<slug>/read`.

- [ ] **Step 11: Commit**

```bash
git add -A app/ tests/
git commit -m "refactor: gộp 13 route file → 6 module, JSON gom về /api/v1

api_v1 là package chia theo domain, không phải một file: ~50 endpoint JSON
trong một module là không đọc nổi.

Thuần di chuyển code — không đổi logic. URL cũ giữ song song bằng duplicate
decorator (không redirect: 308 với POST có thể bị client đổi method).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Sau khi xong

- [ ] Chạy `python -m scripts.cleanup_preset_overrides --dry-run`, đọc output, rồi chạy thật để dọn dữ liệu cũ.
- [ ] Cập nhật `openspec/changes/refactor-toc-ebook-sources-api/` cho khớp, hoặc đánh dấu superseded bởi `docs/superpowers/specs/2026-07-15-toc-ebook-sources-boundary-design.md`.
- [ ] Cập nhật `CLAUDE.md`: mô tả `app/routes/` (14 route file → 6 module + `api_v1/`), và ghi luật sở hữu source↔ebook.
- [ ] Change 2 (AI cho source) và Change 3 (AI cho ebook meta) — brainstorm riêng.
