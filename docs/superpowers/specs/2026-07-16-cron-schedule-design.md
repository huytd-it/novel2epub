# Thiết kế: Lịch automation kiểu cron + cài đặt nhanh Windows/Linux

Ngày: 2026-07-16
Trạng thái: đã duyệt (brainstorming với người dùng)

## Bối cảnh & mục tiêu

Lịch automation hiện tại dùng cú pháp tự chế `manual` | `daily@HH:MM` |
`continuous[@N]` với 3 lỗi đã xác nhận bằng cách chạy thử:

1. `daily@25:00` (giờ ngoài phạm vi) ném `ValueError` thoát khỏi `_is_due`,
   hủy cả vòng `_tick` — mọi automation đứng sau cái hỏng không bao giờ được
   xét, lặp lại mỗi 30 giây.
2. `continuous@0` / `continuous@-5` → luôn đến hạn → enqueue lại mỗi vòng
   poll (vòng lặp nóng). Luồng bulk-create có kẹp `max(1, N)` nhưng form
   `/automation` thì không.
3. Route nhận `schedule` là string tự do, không validate: `Daily@03:00`,
   `contineous@30`, `daily@3` được lưu nhưng không bao giờ chạy, UI vẫn hiện
   enabled — chết im lặng.

Mục tiêu: thay hẳn cú pháp cũ bằng **cron 5 trường chuẩn** (validate chặt,
sửa cả 3 lỗi trên), thêm **nút preset** trong UI, và **CLI `service install`**
đăng ký web server chạy nền khi khởi động máy trên Windows/Linux.

## Các quyết định đã chốt (với người dùng)

- Cron 5 trường đầy đủ qua thư viện **croniter**, thay hẳn cú pháp cũ,
  migration tự động.
- Lỡ mốc lịch (máy tắt): **chạy bù tối đa 1 lần** khi server bật lại,
  không dồn đống.
- Logic đến hạn **stateless** từ `last_run_at` (không thêm cột
  `next_run_at`).
- Cài đặt nhanh = nút preset trong UI **và** CLI
  `python -m novel2epub service install`.

## 1. Cú pháp lịch mới

`Automation.schedule` chỉ còn 2 dạng:

- `"manual"` — chỉ chạy khi bấm tay.
- Biểu thức cron 5 trường `phút giờ ngày tháng thứ`, ví dụ:
  - `*/30 * * * *` — mỗi 30 phút
  - `0 3 * * *` — 3h sáng hàng ngày
  - `0 3 * * 0` — 3h sáng Chủ nhật

Parse/validate bằng `croniter` (thêm `croniter>=2.0` vào `requirements.txt`).

Hàm mới trong `novel2epub/automation.py`:

```python
def validate_schedule(s: str) -> bool:
    """True nếu s == "manual" hoặc là biểu thức cron 5 trường hợp lệ."""
```

Cả 2 route ghi lịch đều validate, sai trả **HTTP 400**:

- `POST /automation` và `POST /automation/{id}/update`
  (`app/routes/automation.py`)
- `POST /library/ebooks/bulk` (`app/routes/library.py`)

## 2. Scheduler (`app/scheduler.py`)

### Logic đến hạn

```python
def _is_due(automation, now) -> bool:
    if not automation.enabled or automation.schedule == "manual":
        return False
    base = automation.last_run_at or automation.created_at  # ISO string → datetime
    return croniter(automation.schedule, base).get_next(datetime) <= now
```

- Chạy bù tối đa 1 lần: sau khi chạy, `last_run_at` = giờ hoàn thành → các
  mốc lỡ trước đó tự triệt tiêu.
- Xóa `_is_due_daily`, `_is_due_continuous`,
  `_DEFAULT_CONTINUOUS_COOLDOWN_MINUTES`.

### Cột mới `created_at`

- Thêm `("automations", "created_at", "TEXT NOT NULL DEFAULT ''")` vào
  `_ADDED_COLUMNS` trong `novel2epub/db.py` (+ khai báo trong
  `CREATE TABLE`); backfill: hàng cũ có `created_at` rỗng được điền = thời
  điểm migrate (lần `load_automations` đầu tiên sau nâng cấp).
- `add_automation` set `created_at = datetime.now().isoformat()`.
- Automation mới tạo chạy lần đầu ở **mốc cron kế tiếp sau `created_at`**,
  không chạy ngay. Riêng bulk-create gọi `scheduler.run_now(id)` tường minh
  ngay sau khi tạo để giữ UX "cào ngay lập tức" hiện tại.

### Chống lỗi lan (sửa lỗi 1)

`_tick` bọc try/except quanh **từng automation**:

```python
for automation in load_automations(...).values():
    try:
        if not _is_due(automation, now):
            continue
        ...
    except Exception:
        logger.exception("Lỗi đánh giá automation %s (%s)", automation.id, automation.ebook)
```

Một automation dữ liệu hỏng chỉ bị bỏ qua (có log đích danh), không giết
vòng poll.

## 3. Migration lịch cũ

Chạy trong `load_automations` khi gặp giá trị không phải `manual`/cron hợp lệ
(idempotent — giá trị đã là cron thì không đụng; có ghi lại DB khi đổi):

| Giá trị cũ | Giá trị mới |
|---|---|
| `daily@HH:MM` (hợp lệ) | `MM HH * * *` |
| `continuous` | `*/30 * * * *` |
| `continuous@N`, 1 ≤ N ≤ 59 | `*/N * * * *` |
| `continuous@N`, N ≥ 60 | `0 */H * * *`, H = round(N/60) kẹp 1..23 |
| Còn lại (kể cả `daily@25:00`, `continuous@0`, typo) | `manual` + log warning |

Ngữ nghĩa đổi nhẹ (đã chấp nhận): `continuous@30` = "nghỉ 30 phút sau khi
xong", còn `*/30` = mốc đồng hồ :00/:30. Guard `has_pending_step` sẵn có vẫn
chống chạy chồng khi job kéo dài qua mốc kế.

## 4. UI

### Form automation (`app/templates/automation.html`)

- Hàng nút preset phía trên ô schedule; bấm là điền biểu thức vào ô text
  (ô vẫn sửa tay tự do):
  - Mỗi 15 phút → `*/15 * * * *`
  - Mỗi 30 phút → `*/30 * * * *`
  - Mỗi giờ → `0 * * * *`
  - Hàng ngày 03:00 → `0 3 * * *`
  - Hàng tuần CN 03:00 → `0 3 * * 0`
  - Thủ công → `manual`
- Placeholder/hint đổi sang mô tả cron 5 trường.

### Danh sách automation

Thêm cột "Chạy kế tiếp": server tính lúc render bằng
`croniter(schedule, last_run_at or created_at).get_next(datetime)`;
`manual`/disabled hiện `—`.

### Bulk create (`app/templates/index.html` + `app/routes/library.py`)

- Ô `cooldown_minutes` thay bằng `<select>` preset cron (cùng danh sách
  trên, trừ Thủ công), mặc định `*/30 * * * *`.
- Route: bỏ tham số `cooldown_minutes`, nhận `cron: str = Form("*/30 * * * *")`,
  validate bằng `validate_schedule`, sai trả 400.

## 5. CLI `service` — chạy server nền khi khởi động máy

Module mới `novel2epub/service.py`, subcommand mới trong `cli.py`:

```
python -m novel2epub service install   [--port 8010] [--host 127.0.0.1]
python -m novel2epub service uninstall
python -m novel2epub service status
```

Tự nhận diện OS (`sys.platform`):

### Windows (Task Scheduler)

- `install`: sinh launcher `start_server.cmd` ở gốc project (cd vào
  project, dùng python của venv hiện tại chạy
  `-m uvicorn app.main:app --host H --port P`), rồi
  `schtasks /Create /TN novel2epub /SC ONLOGON /TR "<đường dẫn cmd>" /F`.
- `status`: `schtasks /Query /TN novel2epub`.
- `uninstall`: `schtasks /Delete /TN novel2epub /F` (+ xóa launcher).

### Linux (systemd user service)

- `install`: ghi `~/.config/systemd/user/novel2epub.service`
  (`ExecStart` = python venv + uvicorn, `WorkingDirectory` = gốc project,
  `Restart=on-failure`, `WantedBy=default.target`), rồi
  `systemctl --user daemon-reload` + `systemctl --user enable --now
  novel2epub`. In gợi ý `loginctl enable-linger $USER` nếu muốn chạy khi
  chưa đăng nhập.
- `status`: `systemctl --user status novel2epub --no-pager`.
- `uninstall`: `disable --now` + xóa unit file + `daemon-reload`.

### Thiết kế cho test được

Phần sinh nội dung tách thành hàm thuần (nhận path/host/port, trả string /
list lệnh), phần thực thi (`subprocess.run`, ghi file) mỏng nhất có thể:

```python
def render_cmd_launcher(project_dir, python_exe, host, port) -> str
def render_systemd_unit(project_dir, python_exe, host, port) -> str
def schtasks_args(action, launcher_path=None) -> list[str]
def systemctl_args(action) -> list[list[str]]
```

OS khác (macOS...) → in thông báo chưa hỗ trợ, exit code 1.

## 6. Kiểm thử

- `tests/test_automation.py` (viết lại phần schedule):
  - `validate_schedule`: hợp lệ (`manual`, `*/30 * * * *`, `0 3 * * 0`),
    không hợp lệ (`daily@03:00` sau migration, `61 * * * *`, `abc`, ``,
    `Daily@03:00`).
  - `_is_due`: đến hạn/chưa đến hạn quanh mốc cron; chạy bù đúng 1 lần khi
    lỡ nhiều mốc; never-run dùng `created_at`; disabled/manual không bao giờ
    đến hạn.
  - `_tick` không chết khi 1 automation có schedule rác trong DB (ghi thẳng
    DB bypass validation).
- Migration: đủ 5 dòng bảng mapping, idempotent (chạy 2 lần không đổi thêm).
- Route: create/update/bulk với lịch sai trả 400; lịch đúng lưu nguyên văn.
- `tests/test_service.py` (mới): nội dung launcher/unit file đúng
  (WorkingDirectory, ExecStart, host/port); `schtasks_args`/`systemctl_args`
  đúng; `install` gọi subprocess với args mong đợi (mock `subprocess.run`);
  OS không hỗ trợ → lỗi rõ ràng.
- Cập nhật `README.md` (mục automation + mục cài đặt nhanh chạy nền) và
  docstring/comment trong `novel2epub/automation.py`.

## Ngoài phạm vi

- Không hỗ trợ cú pháp `@daily`/`@hourly` (croniter hiểu nhưng UI không
  quảng bá — validate vẫn cho qua vì là cron hợp lệ với croniter).
- Không thêm cột `next_run_at` (đã chọn stateless).
- Không hỗ trợ giây (cron 6 trường) hay timezone riêng per-automation
  (dùng giờ local của máy như hiện tại).
- Không làm service cho macOS (launchd) — in "chưa hỗ trợ".
