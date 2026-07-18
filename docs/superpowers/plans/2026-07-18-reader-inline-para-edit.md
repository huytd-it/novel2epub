# Reader Inline Paragraph Edit + AI Quick-Edit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cho phép sửa trực tiếp một đoạn dịch ngay trên trang đọc `/read` — sửa tay hoặc gửi AI biên tập nhanh (kèm chỉ dẫn tự do + bản gốc ZH), review rồi lưu vào `translated/`.

**Architecture:** Một helper thuần `replace_para` trong `novel2epub/notes.py` tái dựng chương từ một đoạn đã sửa (map index-đoạn → index-dòng, giống `apply_note_fix`). Hai endpoint JSON mới trong `app/routes/chapters.py`: `para/ai-edit` (gọi `cfg.ai.openai`, không ghi file) và `para/save` (ghi `translated/`). Frontend thêm inline editor per-paragraph vào `app/templates/reader.html`.

**Tech Stack:** Python 3.10+, FastAPI, Jinja2, pytest, vanilla JS (+ `static/diff.js` có sẵn).

## Global Constraints

- Sửa chỉ ghi `translated/`; **KHÔNG** đụng snapshot `translated_mt/` (chế độ so sánh MT/Biên tập phải giữ đúng).
- Bất biến reader: **một đoạn = một dòng không rỗng** trong `translated` (reader tách qua `split_paras` = `translated.split("\n")` giữ dòng không rỗng). Không được để một thao tác sửa làm lệch `data-para` của các đoạn sau.
- Backend AI biên tập dùng `cfg.ai.openai` (mục "AI biên tập" trong Settings), **không** phải `cfg.translate.openai`.
- AI trả kết quả vào textarea để người dùng review; **không** tự lưu.
- Đẩy lên app novel-reader vẫn thủ công qua Settings → Reader — không tự sync.
- Không sửa app novel-reader bên ngoài; không mở rộng editor 3 cột `chapter.html`.

---

### Task 1: Pure helper `replace_para` (novel2epub/notes.py)

**Files:**
- Modify: `novel2epub/notes.py` (thêm hàm `replace_para` sau `apply_note_fix`)
- Test: `tests/test_notes.py` (thêm block test `# --- replace_para ---`)

**Interfaces:**
- Consumes: không có (thuần, không I/O).
- Produces: `replace_para(translated: str, para_index: int, para_text_expected: str, new_text: str) -> tuple[str | None, str]` — trả `(translated_mới, "")` khi OK, `(None, lý_do)` khi lỗi.

- [ ] **Step 1: Write the failing tests**

Thêm vào cuối `tests/test_notes.py`:

```python
from novel2epub.notes import replace_para


# --- replace_para ---


def test_replace_para_middle_keeps_blank_lines():
    translated = "Mở đầu.\n\nRồi hắn nói một câu.\n\nKết thúc."
    new_text, err = replace_para(translated, 1, "Rồi hắn nói một câu.", "Rồi anh ta đáp.")
    assert err == ""
    assert new_text == "Mở đầu.\n\nRồi anh ta đáp.\n\nKết thúc."


def test_replace_para_first_and_last():
    translated = "A.\n\nB.\n\nC."
    first, err = replace_para(translated, 0, "A.", "A2.")
    assert err == "" and first == "A2.\n\nB.\n\nC."
    last, err = replace_para(translated, 2, "C.", "C2.")
    assert err == "" and last == "A.\n\nB.\n\nC2."


def test_replace_para_mismatch_expected_returns_error():
    translated = "A.\n\nB.\n\nC."
    new_text, err = replace_para(translated, 1, "Khác hẳn.", "B2.")
    assert new_text is None
    assert "đã thay đổi" in err


def test_replace_para_index_out_of_range_returns_error():
    translated = "A.\n\nB."
    new_text, err = replace_para(translated, 9, "A.", "x")
    assert new_text is None
    assert "Không tìm thấy" in err


def test_replace_para_multiline_new_text_collapsed_to_one_line():
    # Người dùng dán nhiều dòng → gộp về 1 dòng, không làm lệch đoạn sau.
    translated = "A.\n\nB.\n\nC."
    new_text, err = replace_para(translated, 1, "B.", "B dòng 1.\n\nB dòng 2.")
    assert err == ""
    assert new_text == "A.\n\nB dòng 1. B dòng 2.\n\nC."
    # Đoạn sau (C.) vẫn ở para_index 2
    from novel2epub.notes import split_paras
    assert split_paras(new_text)[2] == "C."


def test_replace_para_empty_new_text_rejected():
    translated = "A.\n\nB.\n\nC."
    new_text, err = replace_para(translated, 1, "B.", "   \n  ")
    assert new_text is None
    assert "trống" in err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_notes.py -k replace_para -v`
Expected: FAIL — `ImportError: cannot import name 'replace_para'`.

- [ ] **Step 3: Implement `replace_para`**

Thêm vào cuối `novel2epub/notes.py`:

```python
def replace_para(
    translated: str,
    para_index: int,
    para_text_expected: str,
    new_text: str,
) -> tuple[str | None, str]:
    """Thay TOÀN BỘ một đoạn (đoạn-không-rỗng thứ `para_index`) bằng `new_text`.

    Thao tác theo DÒNG trên văn bản gốc (giữ nguyên dòng trống): map index
    đoạn-không-rỗng → index dòng gốc, đúng cách reader tách đoạn. Kiểm tra
    `para_text_expected` khớp dòng hiện tại trước khi ghi để chống ghi đè khi
    bản dịch đã đổi sau lúc mở editor.

    `new_text` nhiều dòng bị gộp về MỘT dòng (nối bằng khoảng trắng) để giữ bất
    biến "một đoạn = một dòng" mà reader dựa vào — tránh làm lệch `para_index`
    của các đoạn sau. Đoạn rỗng bị từ chối (sẽ biến mất và lệch index).

    Trả (văn_bản_mới, "") khi thành công, (None, lý_do) khi thất bại.
    """
    lines = translated.split("\n")
    para_line_indexes = [i for i, line in enumerate(lines) if line.strip()]
    if not isinstance(para_index, int) or not (0 <= para_index < len(para_line_indexes)):
        return None, "Không tìm thấy đoạn — bản dịch đã thay đổi."

    line_idx = para_line_indexes[para_index]
    if lines[line_idx] != para_text_expected:
        return None, "Bản dịch đã thay đổi — tải lại trang."

    cleaned = " ".join(seg.strip() for seg in new_text.splitlines() if seg.strip())
    if not cleaned:
        return None, "Đoạn không được để trống."

    lines[line_idx] = cleaned
    return "\n".join(lines), ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_notes.py -k replace_para -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add novel2epub/notes.py tests/test_notes.py
git commit -m "feat: add replace_para pure helper for inline paragraph edit"
```

---

### Task 2: `para/save` endpoint (app/routes/chapters.py)

**Files:**
- Modify: `app/routes/chapters.py` (thêm import `replace_para`; thêm route `para/save` gần các route `/api/ebooks/{slug}/chapters/{index}/...`)
- Test: `tests/test_routes_para_edit.py` (file mới)

**Interfaces:**
- Consumes: `novel2epub.notes.replace_para` (Task 1); `Storage.read_translated/write_translated/has_translated`; `deps.resolved_cfg`.
- Produces: `POST /api/ebooks/{slug}/chapters/{index}/para/save` — form `para_index:int`, `para_text:str`, `new_text:str`; trả `{"saved": true, "para": <str>}` (200) hoặc 409/400/404.

- [ ] **Step 1: Write the failing tests**

Tạo `tests/test_routes_para_edit.py`:

```python
"""Test API sửa đoạn tại chỗ trên trang đọc (app/routes/chapters.py)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import deps
from novel2epub.config import (
    Config,
    CrawlConfig,
    NovelConfig,
    OutputConfig,
    TranslateConfig,
)
from novel2epub.storage import Chapter, Manifest, Storage


def _cfg(tmp_path):
    return Config(
        novel=NovelConfig(slug="t"),
        crawl=CrawlConfig(toc_url="http://x/book/", delay_seconds=0),
        translate=TranslateConfig(type="none", delay_seconds=0),
        output=OutputConfig(data_dir=str(tmp_path)),
    )


def _seed(tmp_path, *, translated="A.\n\nB.\n\nC.", raw=None, mt=None):
    storage = Storage(tmp_path, "t")
    ch = Chapter(index=7, url="http://x/7")
    storage.save_manifest(Manifest(slug="t", chapters=[ch]))
    if translated is not None:
        storage.write_translated(ch, translated)
    if raw is not None:
        storage.write_raw(ch, raw)
    if mt is not None:
        storage.write_translated_mt(ch, mt)
    return storage, ch


def _client(tmp_path, monkeypatch, cfg):
    monkeypatch.setattr(deps, "library", lambda: type("L", (), {"ebooks": {}})())
    monkeypatch.setattr(deps, "cfg", lambda: cfg)
    monkeypatch.setattr(deps, "resolved_cfg", lambda slug: cfg)
    from app.main import app
    return TestClient(app)


def test_para_save_happy_path_keeps_mt_snapshot(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    storage, ch = _seed(tmp_path, mt="A.\n\nB.\n\nC.")
    client = _client(tmp_path, monkeypatch, cfg)

    res = client.post(
        "/api/ebooks/t/chapters/7/para/save",
        data={"para_index": 1, "para_text": "B.", "new_text": "B đã sửa."},
    )
    assert res.status_code == 200, res.text
    assert res.json()["saved"] is True
    assert storage.read_translated(ch) == "A.\n\nB đã sửa.\n\nC."
    # Snapshot MT KHÔNG đổi
    assert storage.read_translated_mt(ch) == "A.\n\nB.\n\nC."


def test_para_save_stale_conflict(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _storage, _ch = _seed(tmp_path)
    client = _client(tmp_path, monkeypatch, cfg)

    res = client.post(
        "/api/ebooks/t/chapters/7/para/save",
        data={"para_index": 1, "para_text": "Đoạn cũ khác.", "new_text": "x"},
    )
    assert res.status_code == 409
    assert "thay đổi" in res.json()["detail"]


def test_para_save_empty_rejected(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _storage, _ch = _seed(tmp_path)
    client = _client(tmp_path, monkeypatch, cfg)

    res = client.post(
        "/api/ebooks/t/chapters/7/para/save",
        data={"para_index": 1, "para_text": "B.", "new_text": "   "},
    )
    assert res.status_code == 409
    assert "trống" in res.json()["detail"]


def test_para_save_unknown_chapter_404(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    _seed(tmp_path)
    client = _client(tmp_path, monkeypatch, cfg)

    res = client.post(
        "/api/ebooks/t/chapters/999/para/save",
        data={"para_index": 0, "para_text": "A.", "new_text": "x"},
    )
    assert res.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_routes_para_edit.py -v`
Expected: FAIL — 404 cho tất cả (route chưa tồn tại) / assertion sai.

- [ ] **Step 3: Implement the route**

Trong `app/routes/chapters.py`, thêm import ở đầu (cạnh `from .glossary import _append_glossary_entry`):

```python
from novel2epub.notes import replace_para
```

Thêm route (đặt sau `api_ebook_chapter_revert_edits`, dùng chung helper `_load_chapter_json_or_404` đã có):

```python
@router.post("/api/ebooks/{slug}/chapters/{index}/para/save")
def api_ebook_chapter_para_save(
    slug: str,
    index: int,
    para_index: int = Form(...),
    para_text: str = Form(...),
    new_text: str = Form(...),
):
    """Ghi một đoạn đã sửa tay vào `translated/` — sửa tại chỗ trên trang đọc.

    `para_text` là đoạn gốc lúc mở editor: khớp thì mới ghi (chống ghi đè khi
    bản dịch đã đổi). KHÔNG đụng snapshot `translated_mt/`.
    """
    storage, _manifest, ch = _load_chapter_json_or_404(slug, index)
    if not storage.has_translated(ch):
        raise HTTPException(status_code=409, detail="Chương không còn bản dịch.")
    translated = storage.read_translated(ch)
    new_translated, err = replace_para(translated, para_index, para_text, new_text)
    if new_translated is None:
        raise HTTPException(status_code=409, detail=err)
    storage.write_translated(ch, new_translated)
    # Đoạn đã chuẩn hoá (gộp dòng) để client render lại đúng.
    from novel2epub.notes import split_paras
    return JSONResponse({"saved": True, "para": split_paras(new_translated)[para_index]})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_routes_para_edit.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add app/routes/chapters.py tests/test_routes_para_edit.py
git commit -m "feat: add para/save endpoint for inline paragraph edit"
```

---

### Task 3: `para/ai-edit` endpoint + prompt (app/routes/chapters.py)

**Files:**
- Modify: `app/routes/chapters.py` (refactor `_call_openai` để nhận `openai_cfg`; cập nhật 2 caller cũ; thêm `_PARA_EDIT_PROMPT`; thêm route `para/ai-edit`)
- Test: `tests/test_routes_para_edit.py` (thêm test AI, monkeypatch `openai_run_chat`)

**Interfaces:**
- Consumes: `app.routes.chapters.openai_run_chat` (đã import là `from novel2epub.openai_client import run_chat as openai_run_chat`); `cfg.ai.openai`; `Storage.read_raw/has_raw`, `Storage.read_translated`.
- Produces: `POST /api/ebooks/{slug}/chapters/{index}/para/ai-edit` — form `para_index:int`, `text:str`, `instruction:str=""`; trả `{"edited": <str>}` (200), 400 (chưa cấu hình AI), 502 (AI lỗi).

- [ ] **Step 1: Write the failing tests**

Thêm vào `tests/test_routes_para_edit.py`:

```python
from app.routes import chapters as chapters_route


def _cfg_ai(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.ai.openai.base_url = "http://ai.local/v1"  # bật guard "đã cấu hình AI"
    return cfg


def test_para_ai_edit_uses_ai_backend_and_zh_context(tmp_path, monkeypatch):
    cfg = _cfg_ai(tmp_path)
    # raw có CÙNG số đoạn với translated (3) → ZH đoạn 1 được đính kèm
    _seed(tmp_path, translated="A.\n\nB.\n\nC.", raw="甲。\n\n乙。\n\n丙。")
    client = _client(tmp_path, monkeypatch, cfg)

    captured = {}

    def fake_run_chat(openai_cfg, prompt):
        captured["cfg"] = openai_cfg
        captured["prompt"] = prompt
        return "B đã biên tập."

    monkeypatch.setattr(chapters_route, "openai_run_chat", fake_run_chat)

    res = client.post(
        "/api/ebooks/t/chapters/7/para/ai-edit",
        data={"para_index": 1, "text": "B.", "instruction": "xưng anh/em"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["edited"] == "B đã biên tập."
    # Dùng ĐÚNG backend AI biên tập, không phải translate
    assert captured["cfg"] is cfg.ai.openai
    # ZH đoạn tương ứng + chỉ dẫn có trong prompt
    assert "乙。" in captured["prompt"]
    assert "xưng anh/em" in captured["prompt"]


def test_para_ai_edit_no_zh_when_para_count_differs(tmp_path, monkeypatch):
    cfg = _cfg_ai(tmp_path)
    # raw 2 đoạn ≠ translated 3 đoạn → bỏ ZH
    _seed(tmp_path, translated="A.\n\nB.\n\nC.", raw="甲。\n\n乙。")
    client = _client(tmp_path, monkeypatch, cfg)

    captured = {}

    def fake_run_chat(openai_cfg, prompt):
        captured["prompt"] = prompt
        return "sửa"

    monkeypatch.setattr(chapters_route, "openai_run_chat", fake_run_chat)
    res = client.post(
        "/api/ebooks/t/chapters/7/para/ai-edit",
        data={"para_index": 1, "text": "B."},
    )
    assert res.status_code == 200
    assert "乙。" not in captured["prompt"]
    assert "(không có)" in captured["prompt"]


def test_para_ai_edit_requires_ai_config(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)  # ai.openai rỗng (không base_url, không api_key)
    _seed(tmp_path)
    client = _client(tmp_path, monkeypatch, cfg)
    res = client.post(
        "/api/ebooks/t/chapters/7/para/ai-edit",
        data={"para_index": 1, "text": "B."},
    )
    assert res.status_code == 400
    assert "AI" in res.json()["detail"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_routes_para_edit.py -k ai_edit -v`
Expected: FAIL — 404 (route chưa có).

- [ ] **Step 3: Refactor `_call_openai` + add prompt + route**

Trong `app/routes/chapters.py`, đổi `_call_openai` để nhận `openai_cfg` trực tiếp:

```python
def _call_openai(openai_cfg, prompt: str) -> str:
    result = openai_run_chat(openai_cfg, prompt).strip()
    lines = result.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()
```

Cập nhật 2 caller cũ trong cùng file (đổi `cfg` → `cfg.translate.openai`):
- Trong `api_ebook_chapter_parapolish`:
  `polished = _call_openai(cfg.translate.openai, _POLISH_PROMPT.format(...))`
- Trong `api_ebook_chapter_paraexplain`:
  `explanation = _call_openai(cfg.translate.openai, prompt.format(text=text))`

Thêm prompt mới (cạnh `_POLISH_PROMPT`):

```python
_PARA_EDIT_PROMPT = """Bạn là biên tập viên truyện dịch Trung → Việt.
Hãy BIÊN TẬP LẠI đoạn văn Việt sau cho mượt, tự nhiên, dễ hiểu hơn.
Tham khảo bản gốc Trung (nếu có) để giữ đúng nghĩa.

Yêu cầu thêm từ người biên tập: {instruction}

Nguyên tắc:
- Giữ nguyên nội dung, KHÔNG thêm bớt hay giải thích
- Chỉ trả về đoạn văn đã biên tập, KHÔNG kèm lời dẫn hay code fence

--- Bản gốc (Trung) ---
{text_zh}

--- Đoạn cần biên tập ---
{text}"""

_DEFAULT_PARA_INSTRUCTION = "Biên tập cho tự nhiên, giữ nguyên nội dung."
```

Thêm route (sau `api_ebook_chapter_parapolish`):

```python
@router.post("/api/ebooks/{slug}/chapters/{index}/para/ai-edit")
def api_ebook_chapter_para_ai_edit(
    slug: str,
    index: int,
    para_index: int = Form(...),
    text: str = Form(...),
    instruction: str = Form(""),
):
    """Biên tập 1 đoạn bằng AI (backend `cfg.ai.openai`) — KHÔNG ghi file.

    Tự đính kèm bản gốc ZH của đoạn khi số đoạn của raw KHỚP translated
    (alignment best-effort; lệch số đoạn thì biên tập VI-only).
    """
    cfg = deps.resolved_cfg(slug)
    if not cfg.ai.openai.api_key and not cfg.ai.openai.base_url:
        raise HTTPException(
            status_code=400,
            detail="Chưa cấu hình AI biên tập (mục AI trong Settings).",
        )
    storage, _manifest, ch = _load_chapter_json_or_404(slug, index)

    from novel2epub.notes import split_paras
    text_zh = ""
    if storage.has_raw(ch):
        raw_paras = split_paras(storage.read_raw(ch))
        translated_paras = split_paras(storage.read_translated(ch)) if storage.has_translated(ch) else []
        if len(raw_paras) == len(translated_paras) and 0 <= para_index < len(raw_paras):
            text_zh = raw_paras[para_index]

    prompt = _PARA_EDIT_PROMPT.format(
        instruction=(instruction.strip() or _DEFAULT_PARA_INSTRUCTION),
        text_zh=text_zh or "(không có)",
        text=text,
    )
    try:
        edited = _call_openai(cfg.ai.openai, prompt)
        return JSONResponse({"edited": edited})
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_routes_para_edit.py -v`
Expected: PASS (tất cả — cả nhóm save ở Task 2 lẫn ai-edit).

Chạy thêm để chắc không vỡ caller cũ:
Run: `pytest tests/test_chapter_api.py tests/test_chapter_three_column.py -v`
Expected: PASS (không đổi hành vi parapolish/paraexplain).

- [ ] **Step 5: Commit**

```bash
git add app/routes/chapters.py tests/test_routes_para_edit.py
git commit -m "feat: add para/ai-edit endpoint using ai.openai backend"
```

---

### Task 4: Inline editor UI trên trang đọc (reader.html)

**Files:**
- Modify: `app/templates/reader.html` (CSS inline editor; nút ✎ per-paragraph; khối `<script>` mới cho luồng sửa)

**Interfaces:**
- Consumes: `POST .../para/ai-edit` (Task 3), `POST .../para/save` (Task 2); biến template có sẵn `slug`, `ch.index`, `has_translated`; `static/diff.js` (`n2eDiff.wordDiff`, `n2eDiff.renderWordDiffInto`).
- Produces: (chỉ UI, không có interface cho task sau).

**Ghi chú alignment client↔server:** mỗi `<p class="reader-para" data-para="N">` có `N` = index đoạn-không-rỗng, KHỚP `para_index` mà server dùng. Text đoạn lấy qua hàm `paraText(p)` có sẵn (bỏ nút copy). Đây chính là `para_text` gửi khi lưu.

- [ ] **Step 1: Thêm CSS cho inline editor**

Trong khối `<style>` của `reader.html` (thêm cạnh `.para-copy-btn`):

```css
.para-edit-btn { position: absolute; right: -2rem; top: 1.4em; opacity: 0; font-size: 0.75rem; padding: 0.15rem; background: none; border: none; cursor: pointer; color: var(--tw-fg-muted, #71717a); transition: opacity 0.15s; }
.dark .para-edit-btn { color: var(--tw-fg-muted-dark, #a1a1aa); }
.reader-para:hover .para-edit-btn { opacity: 0.6; }
.para-edit-btn:hover { opacity: 1 !important; }
.para-editor { margin: 0.4rem 0 0.9rem; border: 1px solid var(--tw-brand-600, #059669); border-radius: 8px; padding: 0.5rem; background: var(--tw-surface-muted, #f4f4f5); font-family: system-ui, sans-serif; font-size: 0.95rem; }
.dark .para-editor { background: var(--tw-surface-muted-dark, #27272a); }
.para-editor textarea { width: 100%; min-height: 5rem; font: inherit; padding: 0.4rem; border-radius: 6px; border: 1px solid var(--tw-border, #e4e4e7); background: var(--tw-surface-light, #fff); color: var(--tw-fg-light, #18181b); resize: vertical; }
.dark .para-editor textarea { background: var(--tw-surface-dark, #18181b); color: var(--tw-fg-dark, #fafafa); border-color: var(--tw-border-dark, #3f3f46); }
.para-editor input.para-instr { width: 100%; margin-top: 0.4rem; font: inherit; font-size: 0.85rem; padding: 0.35rem; border-radius: 6px; border: 1px solid var(--tw-border, #e4e4e7); background: var(--tw-surface-light, #fff); color: var(--tw-fg-light, #18181b); }
.dark .para-editor input.para-instr { background: var(--tw-surface-dark, #18181b); color: var(--tw-fg-dark, #fafafa); border-color: var(--tw-border-dark, #3f3f46); }
.para-editor-actions { display: flex; gap: 0.4rem; justify-content: flex-end; margin-top: 0.4rem; flex-wrap: wrap; }
.para-editor-actions button { font-size: 0.8rem; padding: 0.3rem 0.8rem; border-radius: 6px; border: 1px solid var(--tw-border, #e4e4e7); background: var(--tw-surface-light, #fff); color: var(--tw-fg-light, #18181b); cursor: pointer; }
.dark .para-editor-actions button { background: var(--tw-surface-dark, #18181b); color: var(--tw-fg-dark, #fafafa); border-color: var(--tw-border-dark, #3f3f46); }
.para-editor-actions button.primary { background: var(--tw-brand-600, #059669); border-color: var(--tw-brand-600, #059669); color: #fff; }
.para-editor-actions button:disabled { opacity: 0.5; cursor: wait; }
.para-editor-diff { margin-top: 0.4rem; font-size: 0.85rem; }
.para-editor-diff del { background: var(--tw-status-err-light, #ffe1e1); text-decoration: line-through; }
.dark .para-editor-diff del { background: var(--tw-status-err-dark, #3a1a1a); }
.para-editor-diff ins { background: var(--tw-status-ok-light, #def7df); text-decoration: none; }
.dark .para-editor-diff ins { background: var(--tw-status-ok-dark, #1a3a1a); }
```

- [ ] **Step 2: Thêm nút ✎ vào mỗi đoạn**

Trong vòng lặp render đoạn, đổi dòng `<p class="reader-para" ...>` để có thêm nút edit (đặt cạnh nút copy):

Tìm:
```html
<p class="reader-para" data-para="{{ loop.index0 }}">{{ para }}<button type="button" class="para-copy-btn" title="Copy đoạn" data-para="{{ loop.index0 }}">&#128203;</button></p>
```
Thay bằng:
```html
<p class="reader-para" data-para="{{ loop.index0 }}">{{ para }}<button type="button" class="para-copy-btn" title="Copy đoạn" data-para="{{ loop.index0 }}">&#128203;</button><button type="button" class="para-edit-btn" title="Sửa đoạn" data-para="{{ loop.index0 }}">&#9998;</button></p>
```

- [ ] **Step 3: Thêm script luồng sửa đoạn**

Thêm khối `<script>` mới NGAY TRƯỚC `{% endif %}` cuối cùng của `{% block scripts %}` (sau khối notes/compare, trong nhánh `{% if has_translated %}`). Script này độc lập, tự query DOM:

```html
<script>
// Sửa đoạn tại chỗ: sửa tay + AI biên tập nhanh (review rồi lưu). Ghi translated/.
(function() {
    const SLUG = {{ slug | tojson }};
    const INDEX = {{ ch.index | tojson }};
    const content = document.getElementById('reader-content');
    let openEditor = null;  // { para, original, dirty }

    function paraText(para) {
        return Array.from(para.childNodes)
            .filter(n => !(n.nodeType === 1 && n.tagName === 'BUTTON'))
            .map(n => n.textContent).join('');
    }

    async function api(path, form) {
        const res = await fetch(path, { method: 'POST', body: form });
        let data = null;
        try { data = await res.json(); } catch (e) {}
        if (!res.ok) throw new Error((data && data.detail) || `HTTP ${res.status}`);
        return data;
    }

    function closeEditor() {
        if (!openEditor) return;
        const { para, editor } = openEditor;
        editor.remove();
        para.hidden = false;
        openEditor = null;
    }

    function tryCloseEditor() {
        if (!openEditor) return true;
        if (openEditor.dirty && !confirm('Bỏ thay đổi chưa lưu ở đoạn đang mở?')) return false;
        closeEditor();
        return true;
    }

    function openParaEditor(para) {
        if (openEditor && openEditor.para === para) return;
        if (!tryCloseEditor()) return;
        const paraIndex = +para.dataset.para;
        const original = paraText(para);

        const editor = document.createElement('div');
        editor.className = 'para-editor';
        const ta = document.createElement('textarea');
        ta.value = original;
        const instr = document.createElement('input');
        instr.type = 'text'; instr.className = 'para-instr';
        instr.placeholder = 'Chỉ dẫn cho AI (để trống = biên tập mặc định)';
        const diff = document.createElement('div');
        diff.className = 'para-editor-diff';
        const actions = document.createElement('div');
        actions.className = 'para-editor-actions';
        const aiBtn = document.createElement('button');
        aiBtn.type = 'button'; aiBtn.textContent = 'AI biên tập';
        const saveBtn = document.createElement('button');
        saveBtn.type = 'button'; saveBtn.className = 'primary'; saveBtn.textContent = 'Lưu';
        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button'; cancelBtn.textContent = 'Hủy';
        actions.append(aiBtn, saveBtn, cancelBtn);
        editor.append(ta, instr, diff, actions);

        ta.addEventListener('input', () => { openEditor.dirty = ta.value !== original; });

        aiBtn.addEventListener('click', async () => {
            aiBtn.disabled = true; aiBtn.textContent = 'Đang gửi AI…';
            const form = new FormData();
            form.set('para_index', paraIndex);
            form.set('text', ta.value);
            form.set('instruction', instr.value.trim());
            try {
                const data = await api(`/api/ebooks/${encodeURIComponent(SLUG)}/chapters/${INDEX}/para/ai-edit`, form);
                diff.innerHTML = '';
                if (window.n2eDiff) {
                    const [, r] = n2eDiff.wordDiff(ta.value, data.edited);
                    n2eDiff.renderWordDiffInto(diff, r);
                }
                ta.value = data.edited;
                openEditor.dirty = ta.value !== original;
                toast('AI đã trả bản biên tập — xem lại rồi Lưu', 'success');
            } catch (e) {
                toast(e.message, 'error');
            } finally {
                aiBtn.disabled = false; aiBtn.textContent = 'AI biên tập';
            }
        });

        saveBtn.addEventListener('click', async () => {
            saveBtn.disabled = true;
            const form = new FormData();
            form.set('para_index', paraIndex);
            form.set('para_text', original);
            form.set('new_text', ta.value);
            try {
                const data = await api(`/api/ebooks/${encodeURIComponent(SLUG)}/chapters/${INDEX}/para/save`, form);
                para.firstChild.textContent = data.para;  // node text đầu là nội dung đoạn
                openEditor.dirty = false;
                closeEditor();
                toast('Đã lưu đoạn', 'success');
            } catch (e) {
                saveBtn.disabled = false;
                toast(e.message, 'error');
            }
        });

        cancelBtn.addEventListener('click', () => { openEditor.dirty = false; closeEditor(); });

        para.hidden = true;
        para.after(editor);
        openEditor = { para, editor, dirty: false };
        ta.focus();
    }

    content.addEventListener('click', (e) => {
        const btn = e.target.closest('.para-edit-btn');
        if (!btn) return;
        e.stopPropagation();
        openParaEditor(btn.closest('.reader-para'));
    });
})();
</script>
```

- [ ] **Step 4: Verify in browser (manual)**

Khởi động dev server và kiểm tra thực tế:

Run (qua preview_start, KHÔNG dùng Bash chạy server): mở `name` dev server của app (uvicorn `app.main:app` port 8010 — thêm vào `.claude/launch.json` nếu chưa có).

Kiểm tra trên `/ebooks/<slug>/read/<index>` của một chương ĐÃ dịch:
1. Hover một đoạn → thấy nút ✎; bấm → hiện inline editor với text đoạn.
2. Sửa tay → **Lưu** → đoạn hiển thị text mới; reload trang → vẫn còn (đã ghi `translated/`).
3. Bấm **AI biên tập** (cần cấu hình `ai.openai`) → textarea đổi thành bản AI + diff hiện; **Lưu** → cập nhật.
4. Mở đoạn khác khi đang sửa dở → hỏi xác nhận.
5. Bật chế độ so sánh (nút ⇄) → cột MT vẫn giữ bản dịch máy gốc (không bị đè bởi đoạn vừa sửa).
6. `read_console_messages` → không có lỗi JS.

- [ ] **Step 5: Commit**

```bash
git add app/templates/reader.html
git commit -m "feat: inline paragraph edit + AI quick-edit on reader page"
```

---

## Ghi chú kiểm thử tổng thể

Chạy toàn bộ suite liên quan trước khi kết thúc:
```bash
pytest tests/test_notes.py tests/test_routes_para_edit.py tests/test_routes_notes.py tests/test_chapter_api.py -v
```
Expected: PASS toàn bộ.
