# Cron Schedule + Service Install Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thay cú pháp lịch automation tự chế (`daily@HH:MM`/`continuous@N`) bằng cron 5 trường chuẩn (croniter) có validate + migration, thêm nút preset trong UI, và CLI `service install` đăng ký web server chạy nền trên Windows/Linux.

**Architecture:** `validate_schedule`/`migrate_schedule` là hàm thuần trong `novel2epub/automation.py`; scheduler tính đến hạn stateless bằng `croniter(expr, last_run_at or created_at).get_next() <= now`; migration tự động chạy trong `load_automations` (idempotent, ghi lại DB khi đổi); `novel2epub/service.py` tách phần sinh nội dung (hàm thuần, test được) khỏi phần thực thi (`subprocess.run` mỏng).

**Tech Stack:** Python 3.10+, croniter>=2.0 (mới), FastAPI, SQLite (bảng `automations`), pytest.

Spec: `docs/superpowers/specs/2026-07-16-cron-schedule-design.md`

## Global Constraints

- Thêm dependency duy nhất: `croniter>=2.0` trong `requirements.txt`.
- `schedule` hợp lệ = `"manual"` hoặc biểu thức cron croniter chấp nhận. Route ghi lịch sai → HTTP 400.
- Lỡ mốc lịch → chạy bù tối đa 1 lần (stateless từ `last_run_at`).
- Comment/docstring viết tiếng Việt theo phong cách codebase hiện tại.
- Chạy test bằng `./.venv/Scripts/python.exe -m pytest` (máy dev Windows).
- Ngoài phạm vi: macOS launchd, timezone per-automation, cron 6 trường, cột `next_run_at`.

---

### Task 1: `validate_schedule` + dependency croniter

**Files:**
- Modify: `requirements.txt` (thêm croniter sau dòng `pytest>=8.0.0`)
- Modify: `novel2epub/automation.py`
- Test: `tests/test_automation.py`

**Interfaces:**
- Produces: `validate_schedule(s: str) -> bool` — True nếu `s == "manual"` hoặc là cron croniter chấp nhận. Task 3, 5, 6 dùng hàm này.

- [ ] **Step 1: Cài croniter**

Thêm vào `requirements.txt` (sau dòng `pytest>=8.0.0`):

```
croniter>=2.0
```

Run: `./.venv/Scripts/python.exe -m pip install "croniter>=2.0"`
Expected: cài thành công, `python -c "from croniter import croniter; print(croniter.is_valid('*/30 * * * *'))"` in `True`.

- [ ] **Step 2: Viết test fail**

Thêm vào cuối `tests/test_automation.py`:

```python
# ---------- validate_schedule ----------


def test_validate_schedule_accepts_manual_and_cron():
    from novel2epub.automation import validate_schedule

    assert validate_schedule("manual") is True
    assert validate_schedule("*/30 * * * *") is True
    assert validate_schedule("0 3 * * *") is True
    assert validate_schedule("0 3 * * 0") is True


def test_validate_schedule_rejects_legacy_and_garbage():
    from novel2epub.automation import validate_schedule

    assert validate_schedule("daily@03:00") is False
    assert validate_schedule("continuous@30") is False
    assert validate_schedule("61 * * * *") is False
    assert validate_schedule("abc") is False
    assert validate_schedule("") is False
    assert validate_schedule("Manual") is False
```

- [ ] **Step 3: Chạy test, xác nhận fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_automation.py -k validate_schedule -v`
Expected: FAIL — `ImportError: cannot import name 'validate_schedule'`

- [ ] **Step 4: Implement**

Trong `novel2epub/automation.py`, thêm import và hàm (sau dòng `STEPS = (...)`):

```python
from croniter import croniter


def validate_schedule(s: str) -> bool:
    """True nếu `s` là lịch hợp lệ: "manual" hoặc biểu thức cron croniter
    chấp nhận (5 trường chuẩn; croniter cũng nhận @daily/6 trường — vẫn coi
    là hợp lệ vì scheduler xử lý được)."""
    if s == "manual":
        return True
    return croniter.is_valid(s)
```

(import `from croniter import croniter` đặt cạnh các import ngoài khác, trên `from .db import get_thread_connection`.)

- [ ] **Step 5: Chạy test, xác nhận pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_automation.py -k validate_schedule -v`
Expected: 2 PASS

- [ ] **Step 6: Commit**

```bash
git add requirements.txt novel2epub/automation.py tests/test_automation.py
git commit -m "feat: validate_schedule — lịch automation là manual hoặc cron 5 trường (croniter)"
```

---

### Task 2: Cột `created_at` cho automation

**Files:**
- Modify: `novel2epub/db.py` (CREATE TABLE automations + `_ADDED_COLUMNS`)
- Modify: `novel2epub/automation.py` (dataclass, add/save/load)
- Test: `tests/test_automation.py`

**Interfaces:**
- Produces: `Automation.created_at: str` (ISO datetime, luôn được `add_automation` set). Task 3 backfill hàng cũ, Task 4 dùng làm base tính đến hạn.

- [ ] **Step 1: Viết test fail**

Thêm vào `tests/test_automation.py` (khu roundtrip đầu file):

```python
def test_add_automation_sets_created_at(tmp_path):
    path = tmp_path / "automations.yaml"
    a = add_automation(path, "myebook", ["build"])
    assert a.created_at != ""
    loaded = load_automations(path)
    assert loaded[a.id].created_at == a.created_at
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_automation.py::test_add_automation_sets_created_at -v`
Expected: FAIL — `AttributeError: 'Automation' object has no attribute 'created_at'`

- [ ] **Step 3: Implement**

`novel2epub/db.py` — trong `CREATE TABLE IF NOT EXISTS automations`, thêm dòng sau `last_run_stats_json ...` (nhớ thêm dấu phẩy dòng trên):

```sql
        last_run_stats_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT ''
```

và thêm vào `_ADDED_COLUMNS`:

```python
    # v3: lịch cron — base tính "đến hạn" cho automation chưa từng chạy
    ("automations", "created_at", "TEXT NOT NULL DEFAULT ''"),
```

`novel2epub/automation.py`:

1. Dataclass `Automation` — thêm field cuối:

```python
    created_at: str = ""  # ISO datetime lúc tạo — base tính đến hạn khi chưa từng chạy
```

2. `add_automation` — set khi tạo (thêm import `from datetime import datetime`):

```python
    automation = Automation(
        id=new_id, ebook=ebook, steps=list(steps), schedule=schedule,
        created_at=datetime.now().isoformat(),
    )
```

3. `load_automations` — đọc cột: thêm `created_at=r["created_at"],` vào constructor.

4. `save_automations` — INSERT thêm cột:

```python
                INSERT INTO automations
                    (id, ebook, steps_json, schedule, enabled,
                     last_run_at, last_run_outcome, last_run_error, last_run_stats_json,
                     created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
```

và tuple values thêm `a.created_at` cuối cùng.

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_automation.py -v`
Expected: tất cả PASS (test cũ không hỏng — field mới có default).

- [ ] **Step 5: Commit**

```bash
git add novel2epub/db.py novel2epub/automation.py tests/test_automation.py
git commit -m "feat: cột created_at cho automation (base tính đến hạn cron)"
```

---

### Task 3: `migrate_schedule` + tự migration trong `load_automations`

**Files:**
- Modify: `novel2epub/automation.py`
- Test: `tests/test_automation.py`

**Interfaces:**
- Consumes: `validate_schedule` (Task 1), `created_at` (Task 2).
- Produces: `migrate_schedule(s: str) -> str` (thuần); `load_automations` trả về schedule đã migrate + `created_at` đã backfill, ghi lại DB khi có thay đổi. Sau task này DB không bao giờ trả ra lịch cú pháp cũ.

- [ ] **Step 1: Viết test fail**

Thêm vào `tests/test_automation.py`:

```python
# ---------- migrate_schedule ----------


def test_migrate_schedule_mapping():
    from novel2epub.automation import migrate_schedule

    assert migrate_schedule("daily@03:00") == "0 3 * * *"
    assert migrate_schedule("daily@23:59") == "59 23 * * *"
    assert migrate_schedule("continuous") == "*/30 * * * *"
    assert migrate_schedule("continuous@15") == "*/15 * * * *"
    assert migrate_schedule("continuous@59") == "*/59 * * * *"
    assert migrate_schedule("continuous@60") == "0 */1 * * *"
    assert migrate_schedule("continuous@120") == "0 */2 * * *"
    assert migrate_schedule("continuous@5000") == "0 */23 * * *"  # kẹp 23h


def test_migrate_schedule_garbage_falls_back_to_manual():
    from novel2epub.automation import migrate_schedule

    assert migrate_schedule("daily@25:00") == "manual"
    assert migrate_schedule("daily@10:99") == "manual"
    assert migrate_schedule("continuous@0") == "manual"
    assert migrate_schedule("continuous@-5") == "manual"
    assert migrate_schedule("contineous@30") == "manual"
    assert migrate_schedule("Daily@03:00") == "manual"
    assert migrate_schedule("") == "manual"


def test_migrate_schedule_keeps_valid_values():
    from novel2epub.automation import migrate_schedule

    assert migrate_schedule("manual") == "manual"
    assert migrate_schedule("*/30 * * * *") == "*/30 * * * *"


def test_load_automations_migrates_legacy_schedule_and_backfills_created_at(tmp_path):
    import json

    from novel2epub.db import get_thread_connection

    path = tmp_path / "automations.yaml"
    conn = get_thread_connection(path)
    with conn:
        conn.execute(
            "INSERT INTO automations (id, ebook, steps_json, schedule, enabled,"
            " last_run_at, last_run_outcome, last_run_error, last_run_stats_json, created_at)"
            " VALUES (?, ?, ?, ?, 1, '', '', '', '{}', '')",
            ("legacy-id", "e", json.dumps(["build"]), "continuous@30"),
        )
    loaded = load_automations(path)
    assert loaded["legacy-id"].schedule == "*/30 * * * *"
    assert loaded["legacy-id"].created_at != ""
    # đã ghi lại DB — load lần 2 không đổi gì thêm (idempotent)
    row = conn.execute("SELECT schedule, created_at FROM automations WHERE id='legacy-id'").fetchone()
    assert row["schedule"] == "*/30 * * * *"
    persisted_created = row["created_at"]
    loaded2 = load_automations(path)
    assert loaded2["legacy-id"].schedule == "*/30 * * * *"
    assert loaded2["legacy-id"].created_at == persisted_created
```

- [ ] **Step 2: Sửa test roundtrip cũ dùng cú pháp legacy**

`tests/test_automation.py::test_add_and_load_automation_roundtrip` hiện dùng `schedule="daily@03:00"` và assert nguyên văn — sau migration sẽ fail. Đổi 2 dòng:

```python
    a = add_automation(path, "myebook", ["fetch-toc", "build"], schedule="0 3 * * *")
    ...
    assert loaded[a.id].schedule == "0 3 * * *"
```

- [ ] **Step 3: Chạy test, xác nhận fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_automation.py -k migrate -v`
Expected: FAIL — `ImportError: cannot import name 'migrate_schedule'`

- [ ] **Step 4: Implement**

`novel2epub/automation.py` — thêm (sau `validate_schedule`):

```python
import logging
import re

logger = logging.getLogger("novel2epub.automation")

_LEGACY_DAILY = re.compile(r"^daily@(\d{1,2}):(\d{1,2})$")
_LEGACY_CONTINUOUS = re.compile(r"^continuous(?:@(-?\d+))?$")


def migrate_schedule(s: str) -> str:
    """Đổi lịch cú pháp cũ (daily@HH:MM / continuous[@N]) sang cron 5 trường.

    Giá trị đã hợp lệ giữ nguyên; không nhận diện được (kể cả daily@25:00,
    continuous@0, typo) → "manual" + log warning. Idempotent."""
    if validate_schedule(s):
        return s
    m = _LEGACY_DAILY.match(s)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return f"{mm} {hh} * * *"
        logger.warning("Lịch cũ không hợp lệ %r → manual", s)
        return "manual"
    m = _LEGACY_CONTINUOUS.match(s)
    if m:
        n = int(m.group(1)) if m.group(1) else 30
        if n < 1:
            logger.warning("Lịch cũ không hợp lệ %r → manual", s)
            return "manual"
        if n <= 59:
            return f"*/{n} * * * *"
        return f"0 */{min(23, max(1, round(n / 60)))} * * *"
    logger.warning("Lịch không nhận diện được %r → manual", s)
    return "manual"
```

(gộp `import logging`, `import re` lên khối import đầu file.)

Viết lại `load_automations`:

```python
def load_automations(db_path: str | Path) -> dict[str, Automation]:
    """Đọc toàn bộ automation; tiện thể migrate lịch cú pháp cũ sang cron và
    backfill `created_at` còn trống (ghi lại DB khi có thay đổi — idempotent)."""
    conn = get_thread_connection(db_path)
    rows = conn.execute("SELECT * FROM automations").fetchall()
    result: dict[str, Automation] = {}
    changed = False
    for r in rows:
        schedule = migrate_schedule(r["schedule"])
        created_at = r["created_at"] or datetime.now().isoformat()
        if schedule != r["schedule"] or created_at != r["created_at"]:
            changed = True
        result[r["id"]] = Automation(
            id=r["id"],
            ebook=r["ebook"],
            steps=json.loads(r["steps_json"] or '["build"]'),
            schedule=schedule,
            enabled=bool(r["enabled"]),
            last_run_at=r["last_run_at"],
            last_run_outcome=r["last_run_outcome"],
            last_run_error=r["last_run_error"],
            last_run_stats=json.loads(r["last_run_stats_json"] or "{}"),
            created_at=created_at,
        )
    if changed:
        save_automations(db_path, result)
    return result
```

Cập nhật luôn comment dataclass dòng 24:

```python
    # "manual" | biểu thức cron 5 trường (vd "*/30 * * * *") — cú pháp cũ
    # daily@HH:MM / continuous[@N] được load_automations tự migrate
    schedule: str = "manual"
```

- [ ] **Step 5: Chạy test, xác nhận pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_automation.py -v`
Expected: tất cả PASS (test `_is_due` legacy vẫn pass vì scheduler chưa đổi — Automation construct trực tiếp không qua load).

- [ ] **Step 6: Commit**

```bash
git add novel2epub/automation.py tests/test_automation.py
git commit -m "feat: migrate lịch cũ daily@/continuous@ sang cron trong load_automations"
```

---

### Task 4: Scheduler cron — `_is_due` mới, `_tick` chống lỗi lan, helper `next_run_at`

**Files:**
- Modify: `app/scheduler.py:36-82` (xóa `_DEFAULT_CONTINUOUS_COOLDOWN_MINUTES`, `_is_due_daily`, `_is_due_continuous`; viết lại `_is_due`; thêm `next_run_at`), `app/scheduler.py:177-184` (`_tick`)
- Test: `tests/test_automation.py` (viết lại khu `---------- _is_due ----------`, dòng 52-125)

**Interfaces:**
- Consumes: `Automation.created_at` (Task 2), lịch đã là cron sau load (Task 3).
- Produces: `_is_due(automation, now) -> bool` (ném ValueError nếu cron rác — `_tick` tự bắt); `next_run_at(automation, now=None) -> datetime | None` (None nếu manual/disabled/cron rác) — Task 5 dùng cho cột "Chạy kế tiếp".

- [ ] **Step 1: Viết lại test `_is_due`**

Thay TOÀN BỘ khu `# ---------- _is_due ----------` trong `tests/test_automation.py` (từ `test_manual_schedule_never_due` đến hết `test_continuous_disabled_never_due`) bằng:

```python
# ---------- _is_due (cron) ----------

T0 = datetime(2026, 7, 16, 12, 0, 0)


def test_manual_schedule_never_due():
    a = Automation(id="x", ebook="e", schedule="manual", created_at=T0.isoformat())
    assert _is_due(a, T0 + timedelta(days=1)) is False


def test_disabled_automation_never_due():
    a = Automation(id="x", ebook="e", schedule="*/30 * * * *", enabled=False,
                   created_at=T0.isoformat())
    assert _is_due(a, T0 + timedelta(days=1)) is False


def test_cron_due_after_next_mark_since_last_run():
    a = Automation(id="x", ebook="e", schedule="*/30 * * * *", last_run_at=T0.isoformat())
    assert _is_due(a, T0 + timedelta(minutes=29)) is False
    assert _is_due(a, T0 + timedelta(minutes=30)) is True


def test_cron_daily_equivalent():
    a = Automation(id="x", ebook="e", schedule="0 9 * * *",
                   last_run_at=datetime(2026, 7, 16, 9, 0, 5).isoformat())
    assert _is_due(a, datetime(2026, 7, 16, 23, 0)) is False   # mốc kế = 9h mai
    assert _is_due(a, datetime(2026, 7, 17, 9, 0)) is True


def test_cron_missed_marks_catch_up_once():
    # lỡ nhiều mốc (máy tắt 3 ngày) → đến hạn ngay; sau khi chạy (last_run_at
    # = giờ xong) thì mốc kế mới lại là tương lai → chỉ bù 1 lần
    a = Automation(id="x", ebook="e", schedule="*/30 * * * *",
                   last_run_at=(T0 - timedelta(days=3)).isoformat())
    assert _is_due(a, T0) is True
    a.last_run_at = T0.isoformat()
    assert _is_due(a, T0 + timedelta(minutes=5)) is False


def test_never_run_uses_created_at_as_base():
    a = Automation(id="x", ebook="e", schedule="*/30 * * * *", created_at=T0.isoformat())
    assert _is_due(a, T0 + timedelta(minutes=5)) is False
    assert _is_due(a, T0 + timedelta(minutes=30)) is True


def test_never_run_without_created_at_is_due():
    # hàng tiền-migration (không created_at, chưa chạy lần nào) → coi như đến hạn
    a = Automation(id="x", ebook="e", schedule="*/30 * * * *")
    assert _is_due(a, T0) is True


def test_is_due_raises_on_garbage_cron():
    import pytest

    a = Automation(id="x", ebook="e", schedule="not a cron", created_at=T0.isoformat())
    with pytest.raises(Exception):
        _is_due(a, T0)


def test_tick_survives_one_garbage_automation(tmp_path, monkeypatch):
    # 1 automation dữ liệu rác không được chặn các automation sau trong cùng
    # vòng poll. Lưu ý: schedule rác đã bị load_automations migrate → "manual"
    # nên phải dùng last_run_at rác (migration không đụng) để ép exception
    # trong _is_due (datetime.fromisoformat nổ ValueError).
    import json

    from novel2epub.db import get_thread_connection

    path = tmp_path / "automations.yaml"
    conn = get_thread_connection(path)
    with conn:
        for aid, last_run in [("bad", "không-phải-ISO"), ("good", (T0 - timedelta(hours=2)).isoformat())]:
            conn.execute(
                "INSERT INTO automations (id, ebook, steps_json, schedule, enabled,"
                " last_run_at, last_run_outcome, last_run_error, last_run_stats_json, created_at)"
                " VALUES (?, ?, ?, '*/30 * * * *', 1, ?, '', '', '{}', ?)",
                (aid, f"ebook-{aid}", json.dumps(["build"]), last_run, T0.isoformat()),
            )
    queue = JobQueue(workers={"crawl": 1, "translate": 1})
    sched = AutomationScheduler(path, tmp_path, queue, poll_seconds=1000)
    ran = []
    monkeypatch.setattr(sched, "run_now", lambda aid: ran.append(aid))
    sched._tick()
    assert ran == ["good"]
```

Lưu ý: giữ nguyên các test khu `run_automation_steps` và `run_now` phía dưới.

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_automation.py -v`
Expected: các test cron mới FAIL (`_is_due` cũ không hiểu cron — ví dụ `*/30 * * * *` không startswith continuous/daily → False), `test_tick_survives...` FAIL.

- [ ] **Step 3: Implement**

`app/scheduler.py`:

1. Thêm import: `from croniter import croniter` (cạnh import datetime).
2. XÓA: `_DEFAULT_CONTINUOUS_COOLDOWN_MINUTES`, `_is_due_daily`, `_is_due_continuous`.
3. Viết lại `_is_due`:

```python
def _is_due(automation: Automation, now: datetime) -> bool:
    """Đến hạn = đã qua mốc cron kế tiếp kể từ lần chạy cuối (hoặc từ lúc tạo
    nếu chưa từng chạy) → lỡ nhiều mốc chỉ chạy bù đúng 1 lần. Cron rác ném
    ValueError — `_tick` bắt và bỏ qua automation đó."""
    if not automation.enabled or automation.schedule == "manual":
        return False
    base_iso = automation.last_run_at or automation.created_at
    if not base_iso:
        return True  # hàng tiền-migration, chưa chạy lần nào → chạy luôn
    base = datetime.fromisoformat(base_iso)
    return croniter(automation.schedule, base).get_next(datetime) <= now
```

4. Thêm helper cho UI (sau `_is_due`):

```python
def next_run_at(automation: Automation, now: datetime | None = None) -> datetime | None:
    """Mốc chạy kế tiếp để hiển thị — None nếu manual/tắt/cron rác. Mốc đã
    qua (đang chờ chạy bù) vẫn trả về nguyên vẹn."""
    if not automation.enabled or automation.schedule == "manual":
        return None
    base_iso = automation.last_run_at or automation.created_at
    try:
        base = datetime.fromisoformat(base_iso) if base_iso else (now or datetime.now())
        return croniter(automation.schedule, base).get_next(datetime)
    except (ValueError, KeyError):
        return None
```

5. Viết lại `_tick` — try/except quanh TỪNG automation:

```python
    def _tick(self) -> None:
        now = datetime.now()
        for automation in load_automations(self.automations_path).values():
            try:
                if not _is_due(automation, now):
                    continue
                if self.queue.has_pending_step("automation", automation.ebook):
                    continue
                self.run_now(automation.id)
            except Exception:  # noqa: BLE001 - 1 automation hỏng không được chặn các cái sau
                logger.exception(
                    "Lỗi đánh giá automation %s (ebook=%s, schedule=%r)",
                    automation.id, automation.ebook, automation.schedule,
                )
```

6. Cập nhật docstring module (dòng 1-6): thay "chạy theo lịch" mô tả cũ nếu nhắc daily/continuous bằng "lịch cron 5 trường (xem spec cron-schedule)".

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_automation.py -v`
Expected: tất cả PASS.

- [ ] **Step 5: Commit**

```bash
git add app/scheduler.py tests/test_automation.py
git commit -m "feat: scheduler tính đến hạn bằng cron (croniter), tick chống lỗi lan"
```

---

### Task 5: Route automation validate 400 + UI preset + cột "Chạy kế tiếp"

**Files:**
- Modify: `app/routes/automation.py`
- Modify: `app/templates/automation.html`
- Test: `tests/test_automation_routes.py` (mới)

**Interfaces:**
- Consumes: `validate_schedule` (Task 1), `next_run_at` (Task 4).
- Produces: `POST /automation` và `POST /automation/{id}/update` trả 400 khi lịch sai; `automation_page` truyền thêm `next_runs: dict[str, str]` (id → chuỗi `"%Y-%m-%d %H:%M"` hoặc `""`) cho template.

- [ ] **Step 1: Viết test fail**

Tạo `tests/test_automation_routes.py`:

```python
"""Tests route /automation: validate lịch cron, hiển thị chạy-kế-tiếp."""
from __future__ import annotations

from fastapi.testclient import TestClient

from novel2epub.automation import add_automation, load_automations


def _client(monkeypatch, tmp_path):
    from app import deps
    from app.main import app

    monkeypatch.setattr(deps, "WORKSPACE_PATH", str(tmp_path / "novel2epub.yaml"))
    monkeypatch.setattr(deps, "SOURCES_PATH", str(tmp_path / "sources.yaml"))
    monkeypatch.setattr(deps, "AUTOMATIONS_PATH", tmp_path / "automations.yaml")
    return app, TestClient(app)


def test_create_rejects_invalid_schedule(monkeypatch, tmp_path):
    app, client = _client(monkeypatch, tmp_path)
    res = client.post("/automation", data={
        "ebook": "e", "steps": ["build"], "schedule": "daily@03:00",
    })
    assert res.status_code == 400
    assert load_automations(tmp_path / "automations.yaml") == {}


def test_create_accepts_cron_schedule(monkeypatch, tmp_path):
    app, client = _client(monkeypatch, tmp_path)
    res = client.post("/automation", data={
        "ebook": "e", "steps": ["build"], "schedule": "*/30 * * * *",
    }, follow_redirects=False)
    assert res.status_code == 303
    automations = load_automations(tmp_path / "automations.yaml")
    assert len(automations) == 1
    assert next(iter(automations.values())).schedule == "*/30 * * * *"


def test_update_rejects_invalid_schedule(monkeypatch, tmp_path):
    app, client = _client(monkeypatch, tmp_path)
    a = add_automation(tmp_path / "automations.yaml", "e", ["build"], "*/30 * * * *")
    res = client.post(f"/automation/{a.id}/update", data={
        "steps": ["build"], "schedule": "not-a-cron", "enabled": "true",
    })
    assert res.status_code == 400
    loaded = load_automations(tmp_path / "automations.yaml")
    assert loaded[a.id].schedule == "*/30 * * * *"


def test_page_shows_next_run(monkeypatch, tmp_path):
    app, client = _client(monkeypatch, tmp_path)
    add_automation(tmp_path / "automations.yaml", "e", ["build"], "0 3 * * *")
    res = client.get("/automation")
    assert res.status_code == 200
    assert "03:00" in res.text  # cột "Chạy kế tiếp" hiện mốc 3h sáng kế tiếp
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_automation_routes.py -v`
Expected: `test_create_rejects_invalid_schedule` FAIL (303 thay vì 400), `test_update_rejects_invalid_schedule` FAIL, `test_page_shows_next_run` FAIL.

- [ ] **Step 3: Implement route**

`app/routes/automation.py`:

1. Mở rộng import: thêm `validate_schedule` vào dòng import từ `novel2epub.automation`, thêm `from datetime import datetime` và `from ..scheduler import next_run_at`.
2. Helper + dùng trong cả create lẫn update:

```python
def _require_valid_schedule(schedule: str) -> None:
    if not validate_schedule(schedule):
        raise HTTPException(
            status_code=400,
            detail=f"Lịch không hợp lệ: {schedule!r} — dùng 'manual' hoặc cron 5 trường, ví dụ '*/30 * * * *'.",
        )
```

`automation_create` và `automation_update`: gọi `_require_valid_schedule(schedule)` ngay trước khi ghi.

3. `automation_page` — truyền next_runs:

```python
@router.get("/automation")
def automation_page(request: Request):
    automations = load_automations(deps.AUTOMATIONS_PATH)
    now = datetime.now()
    next_runs = {}
    for a in automations.values():
        nxt = next_run_at(a, now)
        next_runs[a.id] = nxt.strftime("%Y-%m-%d %H:%M") if nxt else ""
    return deps.templates.TemplateResponse(
        request,
        "automation.html",
        {"automations": automations.values(), "ebooks": _ebook_slugs(),
         "steps": STEPS, "next_runs": next_runs},
    )
```

- [ ] **Step 4: Implement template**

`app/templates/automation.html`:

1. Header bảng — thêm sau `<th ...>Lịch</th>`:

```html
                <th data-dt-sort class="text-left">Chạy kế tiếp</th>
```

2. Body — thêm sau ô `<td ...><code ...>{{ a.schedule }}</code></td>`:

```html
            <td class="px-3 py-2">{{ next_runs[a.id] or '—' }}</td>
```

3. Dòng rỗng: `colspan="7"` → `colspan="8"`.
4. Form thêm automation — thay khối `form-group` của "Lịch chạy" (input + span hint) bằng:

```html
                    <div class="form-group my-2"><label class="label">Lịch chạy</label>
                        <div class="flex flex-wrap gap-1.5 mb-1" id="schedule-presets">
                            <button type="button" class="btn btn-sm btn-secondary" data-cron="*/15 * * * *">Mỗi 15p</button>
                            <button type="button" class="btn btn-sm btn-secondary" data-cron="*/30 * * * *">Mỗi 30p</button>
                            <button type="button" class="btn btn-sm btn-secondary" data-cron="0 * * * *">Mỗi giờ</button>
                            <button type="button" class="btn btn-sm btn-secondary" data-cron="0 3 * * *">Hàng ngày 03:00</button>
                            <button type="button" class="btn btn-sm btn-secondary" data-cron="0 3 * * 0">CN 03:00</button>
                            <button type="button" class="btn btn-sm btn-secondary" data-cron="manual">Thủ công</button>
                        </div>
                        <input type="text" name="schedule" value="manual" placeholder="manual hoặc cron 5 trường: phút giờ ngày tháng thứ" class="input">
                        <span class="text-xs text-fg-muted dark:text-fg-muted-dark">Cron 5 trường, ví dụ <code>*/30 * * * *</code> = mỗi 30 phút, <code>0 3 * * *</code> = 3h sáng hàng ngày.</span>
                    </div>
```

5. Script cuối trang (trong `<script>` sẵn có, sau listener `add-automation-btn`):

```javascript
document.querySelectorAll("#schedule-presets [data-cron]").forEach(function (btn) {
    btn.addEventListener("click", function () {
        document.querySelector('#add-automation-modal input[name="schedule"]').value = btn.dataset.cron;
    });
});
```

6. Mô tả trang (dòng 9): đổi "…chạy theo lịch hàng ngày hoặc bấm tay…" thành "…chạy theo lịch cron hoặc bấm tay…".

- [ ] **Step 5: Chạy test, xác nhận pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_automation_routes.py -v`
Expected: 4 PASS.

- [ ] **Step 6: Commit**

```bash
git add app/routes/automation.py app/templates/automation.html tests/test_automation_routes.py
git commit -m "feat: validate lịch cron ở route automation + preset UI + cột chạy kế tiếp"
```

---

### Task 6: Bulk create dùng cron + chạy ngay lần đầu

**Files:**
- Modify: `app/routes/library.py:237-282`
- Modify: `app/templates/index.html` (khối bulk ~dòng 224-231, JS ~dòng 636-669)
- Test: `tests/test_library_bulk.py`

**Interfaces:**
- Consumes: `validate_schedule` (Task 1); `request.app.state.scheduler.run_now(id)` (sẵn có).
- Produces: `POST /library/ebooks/bulk` nhận `cron: str = Form("*/30 * * * *")` thay `cooldown_minutes`; mỗi ebook tạo kèm automation được `run_now` ngay (giữ UX cào ngay lập tức — automation mới giờ chỉ tự chạy từ mốc cron kế tiếp).

- [ ] **Step 1: Cập nhật test**

`tests/test_library_bulk.py`:

1. `_client` — thêm fake scheduler ghi nhận run_now (sau `app.state.job = _fake_job()`):

```python
    class _FakeScheduler:
        def __init__(self):
            self.ran = []

        def run_now(self, automation_id):
            self.ran.append(automation_id)
            return "job-id"

    app.state.scheduler = _FakeScheduler()
```

2. `test_bulk_create_happy_path_three_urls` — đổi assert schedule:

```python
        assert a.schedule == "*/30 * * * *"
```

và thêm cuối test:

```python
    assert sorted(app.state.scheduler.ran) == sorted(automations.keys())
```

3. Thêm 2 test mới:

```python
def test_bulk_create_accepts_custom_cron(monkeypatch, tmp_path):
    from app.routes import library

    app, client = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(library, "_fetch_meta", lambda url, preset_name="": _meta_for(url))

    res = client.post("/library/ebooks/bulk", data={
        "toc_urls": "https://a.com/truyen-a",
        "cron": "0 3 * * *",
    })
    assert res.status_code == 200
    automations = load_automations(tmp_path / "automations.yaml")
    assert next(iter(automations.values())).schedule == "0 3 * * *"


def test_bulk_create_rejects_invalid_cron(monkeypatch, tmp_path):
    from app.routes import library

    app, client = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(library, "_fetch_meta", lambda url, preset_name="": _meta_for(url))

    res = client.post("/library/ebooks/bulk", data={
        "toc_urls": "https://a.com/truyen-a",
        "cron": "continuous@30",
    })
    assert res.status_code == 400
    assert load_automations(tmp_path / "automations.yaml") == {}
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_library_bulk.py -v`
Expected: happy-path FAIL (schedule vẫn `continuous@30`... thực ra sau Task 3 load trả `*/30 * * * *` — nhưng `app.state.scheduler.ran` rỗng → FAIL), 2 test mới FAIL.

- [ ] **Step 3: Implement**

`app/routes/library.py`:

1. Import: thêm `validate_schedule` vào dòng `from novel2epub.automation import ...`; đảm bảo `Request` có trong import fastapi.
2. Viết lại signature + validate + run_now:

```python
@router.post("/library/ebooks/bulk")
def create_ebooks_bulk(
    request: Request,
    toc_urls: str = Form(...),
    enable_continuous: bool = Form(True),
    cron: str = Form("*/30 * * * *"),
):
    """Nhập hàng loạt tối đa 5 URL mục lục: tạo ebook + (tùy chọn) bật automation
    (cào → dịch → xoá Hán → build) theo lịch cron; chạy ngay lần đầu sau khi tạo.

    Mỗi URL xử lý độc lập — 1 URL lỗi không chặn các URL còn lại.
    """
    urls = [u.strip() for u in toc_urls.splitlines() if u.strip()]
    if not urls:
        raise HTTPException(status_code=400, detail="Thiếu URL mục lục.")
    if len(urls) > MAX_BULK_URLS:
        raise HTTPException(status_code=400, detail=f"Tối đa {MAX_BULK_URLS} URL mỗi lần nhập.")
    if enable_continuous and (cron == "manual" or not validate_schedule(cron)):
        raise HTTPException(status_code=400, detail=f"Lịch cron không hợp lệ: {cron!r}")
```

(xóa dòng `cooldown_minutes = max(1, cooldown_minutes)`.)

3. Trong vòng for, thay khối `if enable_continuous:` bằng:

```python
        if enable_continuous:
            automation = add_automation(deps.AUTOMATIONS_PATH, slug, list(CONTINUOUS_STEPS), cron)
            scheduler = getattr(request.app.state, "scheduler", None)
            if scheduler is not None:
                scheduler.run_now(automation.id)  # chạy ngay lần đầu — lịch cron chỉ tự nổ từ mốc kế tiếp
```

`app/templates/index.html`:

4. Thay label "Lặp lại mỗi ... phút" (dòng 228-230) bằng:

```html
                        <label class="inline-flex items-center gap-2 text-sm">Lịch
                            <select id="bulk-cron" class="select input-sm">
                                <option value="*/15 * * * *">Mỗi 15 phút</option>
                                <option value="*/30 * * * *" selected>Mỗi 30 phút</option>
                                <option value="0 * * * *">Mỗi giờ</option>
                                <option value="0 3 * * *">Hàng ngày 03:00</option>
                                <option value="0 3 * * 0">Hàng tuần CN 03:00</option>
                            </select>
                        </label>
```

5. JS: đổi `var bulkCooldown = document.getElementById("bulk-cooldown");` thành `var bulkCron = document.getElementById("bulk-cron");` và `formData.append("cooldown_minutes", ...)` thành:

```javascript
                formData.append("cron", bulkCron.value || "*/30 * * * *");
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_library_bulk.py -v`
Expected: tất cả PASS.

- [ ] **Step 5: Commit**

```bash
git add app/routes/library.py app/templates/index.html tests/test_library_bulk.py
git commit -m "feat: bulk create dùng lịch cron + run_now ngay sau khi tạo automation"
```

---

### Task 7: `service.py` — hàm thuần sinh launcher/unit/lệnh

**Files:**
- Create: `novel2epub/service.py`
- Test: `tests/test_service.py` (mới)

**Interfaces:**
- Produces (Task 8 dùng):
  - `TASK_NAME = "novel2epub"`
  - `render_cmd_launcher(project_dir: Path, python_exe: str, host: str, port: int) -> str`
  - `render_systemd_unit(project_dir: Path, python_exe: str, host: str, port: int) -> str`
  - `schtasks_args(action: str, launcher_path: Path | None = None) -> list[str]` — action ∈ install/status/uninstall
  - `systemctl_args(action: str) -> list[list[str]]` — mỗi phần tử là 1 lệnh

- [ ] **Step 1: Viết test fail**

Tạo `tests/test_service.py`:

```python
"""Tests novel2epub/service.py: sinh launcher/systemd unit/lệnh đăng ký (thuần),
và service_main gọi đúng lệnh theo OS (mock subprocess)."""
from __future__ import annotations

from pathlib import Path

from novel2epub.service import (
    TASK_NAME,
    render_cmd_launcher,
    render_systemd_unit,
    schtasks_args,
    systemctl_args,
)


def test_render_cmd_launcher():
    out = render_cmd_launcher(Path(r"D:\Projects\novel2epub"), r"D:\v\python.exe", "127.0.0.1", 8010)
    assert 'cd /d "D:\\Projects\\novel2epub"' in out
    assert '"D:\\v\\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8010' in out


def test_render_systemd_unit():
    out = render_systemd_unit(Path("/opt/n2e"), "/opt/n2e/.venv/bin/python", "0.0.0.0", 9000)
    assert "WorkingDirectory=/opt/n2e" in out
    assert "ExecStart=/opt/n2e/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 9000" in out
    assert "Restart=on-failure" in out
    assert "WantedBy=default.target" in out


def test_schtasks_args():
    launcher = Path(r"D:\Projects\novel2epub\start_server.cmd")
    assert schtasks_args("install", launcher) == [
        "schtasks", "/Create", "/TN", TASK_NAME, "/SC", "ONLOGON",
        "/TR", f'"{launcher}"', "/F",
    ]
    assert schtasks_args("status") == ["schtasks", "/Query", "/TN", TASK_NAME]
    assert schtasks_args("uninstall") == ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]


def test_systemctl_args():
    assert systemctl_args("install") == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", TASK_NAME],
    ]
    assert systemctl_args("status") == [["systemctl", "--user", "status", TASK_NAME, "--no-pager"]]
    assert systemctl_args("uninstall") == [
        ["systemctl", "--user", "disable", "--now", TASK_NAME],
        ["systemctl", "--user", "daemon-reload"],
    ]
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'novel2epub.service'`

- [ ] **Step 3: Implement**

Tạo `novel2epub/service.py`:

```python
"""Đăng ký web server chạy nền khi khởi động máy — Windows Task Scheduler /
Linux systemd user service (xem spec cron-schedule). Phần sinh nội dung là
hàm thuần (test không đụng OS); phần thực thi subprocess nằm ở service_main."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TASK_NAME = "novel2epub"


def project_dir() -> Path:
    """Gốc repo (chứa app/ + novel2epub/)."""
    return Path(__file__).resolve().parent.parent


def render_cmd_launcher(project_dir: Path, python_exe: str, host: str, port: int) -> str:
    """Nội dung start_server.cmd — Task Scheduler không set được cwd nên
    launcher tự cd vào project trước khi chạy uvicorn."""
    return (
        "@echo off\r\n"
        f'cd /d "{project_dir}"\r\n'
        f'"{python_exe}" -m uvicorn app.main:app --host {host} --port {port}\r\n'
    )


def render_systemd_unit(project_dir: Path, python_exe: str, host: str, port: int) -> str:
    return f"""[Unit]
Description=novel2epub web server

[Service]
WorkingDirectory={project_dir}
ExecStart={python_exe} -m uvicorn app.main:app --host {host} --port {port}
Restart=on-failure

[Install]
WantedBy=default.target
"""


def schtasks_args(action: str, launcher_path: Path | None = None) -> list[str]:
    if action == "install":
        return ["schtasks", "/Create", "/TN", TASK_NAME, "/SC", "ONLOGON", "/TR", f'"{launcher_path}"', "/F"]
    if action == "status":
        return ["schtasks", "/Query", "/TN", TASK_NAME]
    if action == "uninstall":
        return ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]
    raise ValueError(f"action không hợp lệ: {action!r}")


def systemctl_args(action: str) -> list[list[str]]:
    if action == "install":
        return [
            ["systemctl", "--user", "daemon-reload"],
            ["systemctl", "--user", "enable", "--now", TASK_NAME],
        ]
    if action == "status":
        return [["systemctl", "--user", "status", TASK_NAME, "--no-pager"]]
    if action == "uninstall":
        return [
            ["systemctl", "--user", "disable", "--now", TASK_NAME],
            ["systemctl", "--user", "daemon-reload"],
        ]
    raise ValueError(f"action không hợp lệ: {action!r}")
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_service.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add novel2epub/service.py tests/test_service.py
git commit -m "feat: service.py — sinh launcher cmd/systemd unit/lệnh đăng ký (hàm thuần)"
```

---

### Task 8: `service_main` + CLI subcommand `service`

**Files:**
- Modify: `novel2epub/service.py`
- Modify: `novel2epub/cli.py` (thêm parser sau khối `restore_parser` ~dòng 143; dispatch sau khối `if args.command == "list"` ~dòng 166)
- Test: `tests/test_service.py`

**Interfaces:**
- Consumes: các hàm thuần Task 7.
- Produces: `service_main(action: str, host: str = "127.0.0.1", port: int = 8010) -> int`; CLI `python -m novel2epub service install|uninstall|status [--host] [--port]`.

- [ ] **Step 1: Viết test fail**

Thêm vào `tests/test_service.py`:

```python
import types

from novel2epub import service


def _fake_run(calls, returncode=0):
    def run(args, **kwargs):
        calls.append(args)
        return types.SimpleNamespace(returncode=returncode, stdout="", stderr="")

    return run


def test_service_install_windows_writes_launcher_and_registers(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "project_dir", lambda: tmp_path)
    monkeypatch.setattr(service.sys, "platform", "win32")
    monkeypatch.setattr(service.subprocess, "run", _fake_run(calls))

    rc = service.service_main("install", host="127.0.0.1", port=8010)
    assert rc == 0
    launcher = tmp_path / "start_server.cmd"
    assert launcher.exists()
    assert "-m uvicorn app.main:app --host 127.0.0.1 --port 8010" in launcher.read_text(encoding="utf-8")
    assert calls == [service.schtasks_args("install", launcher)]


def test_service_uninstall_windows_removes_launcher(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "project_dir", lambda: tmp_path)
    monkeypatch.setattr(service.sys, "platform", "win32")
    monkeypatch.setattr(service.subprocess, "run", _fake_run(calls))
    (tmp_path / "start_server.cmd").write_text("x", encoding="utf-8")

    rc = service.service_main("uninstall")
    assert rc == 0
    assert not (tmp_path / "start_server.cmd").exists()
    assert calls == [service.schtasks_args("uninstall")]


def test_service_install_linux_writes_unit_and_enables(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "project_dir", lambda: tmp_path)
    monkeypatch.setattr(service.sys, "platform", "linux")
    monkeypatch.setattr(service.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(service.subprocess, "run", _fake_run(calls))

    rc = service.service_main("install", host="0.0.0.0", port=9000)
    assert rc == 0
    unit = tmp_path / ".config" / "systemd" / "user" / "novel2epub.service"
    assert unit.exists()
    assert "--host 0.0.0.0 --port 9000" in unit.read_text(encoding="utf-8")
    assert calls == service.systemctl_args("install")


def test_service_uninstall_linux_removes_unit(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "project_dir", lambda: tmp_path)
    monkeypatch.setattr(service.sys, "platform", "linux")
    monkeypatch.setattr(service.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(service.subprocess, "run", _fake_run(calls))
    unit = tmp_path / ".config" / "systemd" / "user" / "novel2epub.service"
    unit.parent.mkdir(parents=True)
    unit.write_text("x", encoding="utf-8")

    rc = service.service_main("uninstall")
    assert rc == 0
    assert not unit.exists()
    assert calls == service.systemctl_args("uninstall")


def test_service_unsupported_platform(monkeypatch, capsys):
    monkeypatch.setattr(service.sys, "platform", "darwin")
    rc = service.service_main("install")
    assert rc == 1
    assert "Chưa hỗ trợ" in capsys.readouterr().err


def test_service_status_passes_returncode_through(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "project_dir", lambda: tmp_path)
    monkeypatch.setattr(service.sys, "platform", "win32")
    monkeypatch.setattr(service.subprocess, "run", _fake_run(calls, returncode=1))
    assert service.service_main("status") == 1
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_service.py -v`
Expected: 6 test mới FAIL — `AttributeError: module 'novel2epub.service' has no attribute 'service_main'`

- [ ] **Step 3: Implement `service_main`**

Thêm vào cuối `novel2epub/service.py`:

```python
def _run(args: list[str]) -> int:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)
    return result.returncode


def service_main(action: str, host: str = "127.0.0.1", port: int = 8010) -> int:
    """install/uninstall/status server nền theo OS. Trả exit code."""
    proj = project_dir()
    python_exe = sys.executable
    if sys.platform == "win32":
        launcher = proj / "start_server.cmd"
        if action == "install":
            launcher.write_text(render_cmd_launcher(proj, python_exe, host, port), encoding="utf-8")
            rc = _run(schtasks_args("install", launcher))
            if rc == 0:
                print(f"Đã đăng ký Task Scheduler '{TASK_NAME}' (chạy khi đăng nhập) → {launcher}")
            return rc
        if action == "uninstall":
            rc = _run(schtasks_args("uninstall"))
            launcher.unlink(missing_ok=True)
            return rc
        return _run(schtasks_args("status"))
    if sys.platform.startswith("linux"):
        unit_path = Path.home() / ".config" / "systemd" / "user" / f"{TASK_NAME}.service"
        if action == "install":
            unit_path.parent.mkdir(parents=True, exist_ok=True)
            unit_path.write_text(render_systemd_unit(proj, python_exe, host, port), encoding="utf-8")
            for args in systemctl_args("install"):
                rc = _run(args)
                if rc != 0:
                    return rc
            print(f"Đã bật systemd user service '{TASK_NAME}' → {unit_path}")
            print("Gợi ý: chạy khi chưa đăng nhập cần `loginctl enable-linger $USER`.")
            return 0
        if action == "uninstall":
            rc = 0
            cmds = systemctl_args("uninstall")
            rc = _run(cmds[0])
            unit_path.unlink(missing_ok=True)
            rc2 = _run(cmds[1])
            return rc or rc2
        return _run(systemctl_args("status")[0])
    print(f"Chưa hỗ trợ cài service trên {sys.platform} (mới có Windows/Linux).", file=sys.stderr)
    return 1
```

- [ ] **Step 4: Wire CLI**

`novel2epub/cli.py`:

1. Sau khối `restore_parser` (~dòng 143), thêm:

```python
    service_parser = sub.add_parser(
        "service",
        help="Đăng ký web server chạy nền khi khởi động máy (Windows Task Scheduler / Linux systemd)",
    )
    service_parser.add_argument("action", choices=["install", "uninstall", "status"])
    service_parser.add_argument("--host", default="127.0.0.1", help="Host uvicorn (mặc định 127.0.0.1)")
    service_parser.add_argument("--port", type=int, default=8010, help="Port uvicorn (mặc định 8010)")
```

2. Sau khối `if args.command == "list":` (~dòng 166), thêm dispatch (trước backup/restore, không cần config):

```python
    if args.command == "service":
        from .service import service_main

        return service_main(args.action, args.host, args.port)
```

- [ ] **Step 5: Chạy test + smoke CLI, xác nhận pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_service.py -v`
Expected: tất cả PASS.

Run: `./.venv/Scripts/python.exe -m novel2epub service status`
Expected: exit code ≠ crash — in output schtasks (task chưa tồn tại → thông báo lỗi schtasks là bình thường, không traceback).

- [ ] **Step 6: Commit**

```bash
git add novel2epub/service.py novel2epub/cli.py tests/test_service.py
git commit -m "feat: CLI service install/uninstall/status — chạy server nền Windows/Linux"
```

---

### Task 9: Docs + chạy toàn bộ test

**Files:**
- Modify: `README.md` (~dòng 246-248 + thêm mục chạy nền)
- Modify: `CLAUDE.md` (mục `app/scheduler.py`)

**Interfaces:** không — task tài liệu + verify.

- [ ] **Step 1: README**

Thay bullet Automation (dòng 246-248):

```markdown
- **Automation** — chuỗi bước (fetch-toc → crawl-new → translate-pending →
  cleanup-han → build → publish-reader) chạy theo lịch cron 5 trường
  (`*/30 * * * *`, `0 3 * * *`...) hoặc bấm tay; lịch cũ `daily@HH:MM`/
  `continuous@N` tự migrate. Lỡ mốc (máy tắt) → chạy bù 1 lần khi bật lại.
```

Thêm mục mới (sau mục "Tính năng chính", trước "Quy trình cho truyện mới"):

```markdown
### Chạy nền khi khởi động máy

```sh
python -m novel2epub service install     # Windows: Task Scheduler (khi đăng nhập); Linux: systemd user service
python -m novel2epub service status
python -m novel2epub service uninstall
```

Tùy chọn `--host`/`--port` (mặc định `127.0.0.1:8010`). Linux muốn chạy khi
chưa đăng nhập: `loginctl enable-linger $USER`.
```

- [ ] **Step 2: CLAUDE.md**

Cập nhật dòng mô tả `app/scheduler.py`: thay "…enqueues due automations' steps…" phần lịch bằng "lịch cron 5 trường (croniter), stateless từ `last_run_at`/`created_at`, chạy bù tối đa 1 lần; legacy `daily@`/`continuous@` migrate trong `load_automations`". Thêm 1 dòng cho `novel2epub/service.py` — CLI `service install|uninstall|status` (Task Scheduler / systemd user).

- [ ] **Step 3: Chạy TOÀN BỘ test**

Run: `./.venv/Scripts/python.exe -m pytest tests/ -v`
Expected: tất cả PASS, không có failure/error nào.

- [ ] **Step 4: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: cron schedule + service install cho automation"
```
