# Desktop tray — exe chạy nền

## Tổng quan

`desktop/tray_app.py` là launcher chạy nền cho Windows:

- Khởi **uvicorn FastAPI** ở thread nền (`127.0.0.1:8010`)
- Hiện **icon khay hệ thống** (pystray): mở Web UI, mở thư mục data, bật/tắt autostart, thoát
- **Single-instance**: exe thứ 2 sẽ mở browser tới instance cũ rồi thoát
- **Autostart**: ghi `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` + shortcut Startup (không cần admin)
- **Không console** khi build `--windowed` (`--noconsole`)

Ngoài ra **Tauri desktop** (`frontend/src-tauri`) cũng đã được nâng cấp: đóng cửa sổ = ẩn xuống khay, click tray để hiện/ẩn, single-instance, autostart qua `tauri-plugin-autostart`.

## Chạy dev (không cần build)

```powershell
# Cài deps tray (chỉ lần đầu)
.venv\Scripts\pip install pystray pillow

# Chạy nền ở khay
.venv\Scripts\python.exe desktop/tray_app.py

# Chạy nền nhưng không tự mở browser
.venv\Scripts\python.exe desktop/tray_app.py --minimized

# Tùy chọn cổng
.venv\Scripts\python.exe desktop/tray_app.py --port 8010
```

Menu khay:

- **Mở Web UI (SPA)** → `http://127.0.0.1:8010/app/`
- **Mở Jinja2** → `http://127.0.0.1:8010/`
- **Mở thư mục dữ liệu** → thư mục chứa `novel2epub.db`
- **Khởi động cùng Windows** → toggle HKCU Run
- **Thoát** → dừng server và thoát

Log khi chạy nền: `logs/tray.log` cạnh exe/DB.

## Build exe (PyInstaller)

```powershell
# Build one-file, không console, kèm SPA bundle
powershell -ExecutionPolicy Bypass -File scripts/build-exe.ps1

# Tùy chọn
powershell -ExecutionPolicy Bypass -File scripts/build-exe.ps1 -NoWindow:$false  # giữ console để debug
powershell -ExecutionPolicy Bypass -File scripts/build-exe.ps1 -OneFile:$false   # onedir (khởi động nhanh hơn)
powershell -ExecutionPolicy Bypass -File scripts/build-exe.ps1 -SkipBuild        # bỏ qua vite build
```

Kết quả:

- `dist/novel2epub-tray.exe` (one-file, ~30-50 MB)
- `dist/novel2epub-tray.zip` (để chia sẻ)

Chạy thử:

```powershell
dist\novel2epub-tray.exe --help
dist\novel2epub-tray.exe --minimized
```

## Autostart khi đăng nhập

### Cách 1: Tray exe (khuyên dùng, không cần admin)

```powershell
# Sau khi build
powershell -ExecutionPolicy Bypass -File setup-autostart.ps1 -ExePath "D:\Projects\novel2epub\dist\novel2epub-tray.exe"

# Gỡ
powershell -ExecutionPolicy Bypass -File setup-autostart.ps1 -Remove
```

Script sẽ ghi `HKCU\...\Run\novel2epub = "C:\...\novel2epub-tray.exe" --minimized` và tạo shortcut trong `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`.

Toggle trực tiếp trong tray menu cũng được.

### Cách 2: Task Scheduler (cần admin, fallback)

```powershell
powershell -ExecutionPolicy Bypass -File setup-autostart.ps1 -UseTaskScheduler
```

### Cách 3: Tauri autostart (nếu dùng Tauri build)

Trong Tauri app, dùng JS:

```ts
import { enable, disable, isEnabled } from '@tauri-apps/plugin-autostart';
await enable(); // hoặc disable()
```

## Tauri desktop (tray + nền)

```powershell
cd frontend
npm run tauri:dev     # dev
npm run tauri:build   # build installer (cần Rust)
```

Hành vi mới:

- Đóng cửa sổ → ẩn xuống khay (không thoát)
- Click trái tray → toggle hiện/ẩn
- Menu tray: Hiện / Ẩn / Thoát
- Single-instance: mở exe lần 2 sẽ focus cửa sổ cũ
- Autostart: tắt mặc định, bật qua plugin autostart

## Env

- `NOVEL2EPUB_DB` — đường dẫn DB (mặc định `<exe-dir>/novel2epub.db`)
- `N2E_TRAY_PORT` — cổng (mặc định 8010)
- `N2E_TRAY_HOST` — host (mặc định 127.0.0.1)

## Xử lý sự cố

| Triệu chứng | Cách xử lý |
|---|---|
| Double-click exe không thấy gì | Kiểm tra khay hệ thống (góc phải taskbar, nút `^`), log ở `logs/tray.log` |
| Port 8010 bận | Tray tự thử port kế (8011...), hoặc chạy `novel2epub-tray.exe --port 8011` |
| Icon không hiện | Cài lại `pystray pillow`, hoặc chạy với console để xem lỗi: `build-exe.ps1 -NoWindow:$false` |
| Autostart không chạy | Kiểm tra `HKCU\...\Run\novel2epub` bằng `regedit`, hoặc Startup folder |
| Antivirus chặn | Thêm exception cho `novel2epub-tray.exe` |
