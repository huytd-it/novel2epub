#!/usr/bin/env python3
"""
novel2epub — Desktop tray app chạy nền (Windows).

- Khởi uvicorn FastAPI ở thread nền (127.0.0.1:8010)
- Hiện icon khay hệ thống: mở Web UI, mở thư mục, autostart, thoát
- Chạy nền không console khi build --windowed/--noconsole
- Single-instance: bind socket 8010 + lock file
- Autostart: HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run

Chạy trực tiếp (dev):
    .venv\\Scripts\\python.exe desktop/tray_app.py
    .venv\\Scripts\\python.exe desktop/tray_app.py --port 8010 --no-browser

Build exe:
    powershell -ExecutionPolicy Bypass -File scripts/build-exe.ps1

Env:
    NOVEL2EPUB_DB  : đường dẫn DB (mặc định <exe-dir>/novel2epub.db hoặc <project>/novel2epub.db)
    N2E_TRAY_PORT  : cổng (mặc định 8010)
    N2E_TRAY_HOST  : host (mặc định 127.0.0.1)
"""
from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

# ── paths ──────────────────────────────────────────────────────────

def _is_frozen() -> bool:
    return getattr(sys, "frozen", False)

def get_base_dir() -> Path:
    """Thư mục gốc chứa DB, data, logs.
    - frozen (PyInstaller): thư mục chứa .exe
    - dev: project root (cha của desktop/)
    """
    if _is_frozen():
        # sys.executable = .../novel2epub-tray.exe
        # _MEIPASS là nơi chứa bundle, nhưng DB phải ở cạnh exe để persist
        return Path(sys.executable).resolve().parent
    # desktop/tray_app.py -> project root
    return Path(__file__).resolve().parent.parent

def get_resource_dir() -> Path:
    """Nơi chứa code/resources bundle (dùng cho icon, webui)."""
    if _is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return get_base_dir()

BASE_DIR = get_base_dir()
RESOURCE_DIR = get_resource_dir()

# Đảm bảo base_dir lên sys.path để import app/novel2epub khi frozen
# (PyInstaller đã bundle, nhưng dev cần)
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if str(RESOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(RESOURCE_DIR))

# ── constants ──────────────────────────────────────────────────────

APP_NAME = "novel2epub"
DEFAULT_HOST = os.environ.get("N2E_TRAY_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("N2E_TRAY_PORT", "8010"))
APP_URL = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
LOCK_NAME = "novel2epub-tray.lock"
REG_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_VALUE_NAME = "novel2epub"

log = logging.getLogger("tray")

# ── autostart (Windows registry) ───────────────────────────────────

def _is_windows() -> bool:
    return sys.platform.startswith("win")

def is_autostart_enabled() -> bool:
    if not _is_windows():
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_KEY, 0, winreg.KEY_READ) as k:
            winreg.QueryValueEx(k, REG_VALUE_NAME)
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return False

def set_autostart(enable: bool) -> bool:
    """Bật/tắt khởi động cùng Windows. Trả True nếu thành công."""
    if not _is_windows():
        return False
    try:
        import winreg

        exe = Path(sys.executable).resolve() if _is_frozen() else (BASE_DIR / ".venv" / "Scripts" / "pythonw.exe")
        # Khi dev chưa có pythonw, fallback python
        if not _is_frozen():
            # Tạo lệnh chạy ẩn: pythonw + tray_app.py --minimized
            # Nếu không có pythonw, dùng python
            if not exe.exists():
                exe = Path(sys.executable).resolve()
            cmd = f'"{exe}" "{Path(__file__).resolve()}" --minimized'
        else:
            cmd = f'"{Path(sys.executable).resolve()}" --minimized'

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_KEY, 0, winreg.KEY_WRITE) as k:
            if enable:
                winreg.SetValueEx(k, REG_VALUE_NAME, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(k, REG_VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError as e:
        log.warning("autostart failed: %s", e)
        return False

# ── single instance ────────────────────────────────────────────────

_lock_fp = None

def acquire_single_instance() -> bool:
    """Giữ lock file để tránh chạy 2 tray cùng lúc. Trả False nếu đã có instance."""
    global _lock_fp
    lock_path = BASE_DIR / LOCK_NAME
    try:
        # Dùng exclusive open; nếu đã tồn tại và đang bị giữ, sẽ fail trên Windows
        import msvcrt  # type: ignore

        _lock_fp = open(lock_path, "w")
        # Thử lock 1 byte đầu
        try:
            msvcrt.locking(_lock_fp.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore
        except OSError:
            _lock_fp.close()
            _lock_fp = None
            return False
        _lock_fp.write(str(os.getpid()))
        _lock_fp.flush()
        return True
    except ImportError:
        # non-Windows fallback: socket bind
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind((DEFAULT_HOST, DEFAULT_PORT + 1))
            # giữ socket sống trong global
            globals()["_lock_socket"] = s
            return True
        except OSError:
            return False
    except OSError:
        return False

def release_single_instance():
    global _lock_fp
    if _lock_fp:
        try:
            import msvcrt  # type: ignore

            try:
                msvcrt.locking(_lock_fp.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore
            except OSError:
                pass
            _lock_fp.close()
        except Exception:
            pass
        _lock_fp = None
    try:
        (BASE_DIR / LOCK_NAME).unlink(missing_ok=True)
    except Exception:
        pass

# ── icon image ─────────────────────────────────────────────────────

def load_icon_image(size: int = 64):
    """Tải icon cho pystray. Ưu tiên icon.ico cạnh exe, fallback vẽ."""
    from PIL import Image, ImageDraw  # type: ignore

    candidates = [
        RESOURCE_DIR / "frontend" / "src-tauri" / "icons" / "icon.ico",
        RESOURCE_DIR / "app" / "webui" / "icon.png",
        BASE_DIR / "frontend" / "src-tauri" / "icons" / "icon.ico",
        BASE_DIR / "desktop" / "icon.ico",
        Path(sys.executable).parent / "icon.ico" if _is_frozen() else None,
    ]
    for p in candidates:
        if p and p.exists():
            try:
                im = Image.open(p)
                # ICO có nhiều size, chọn size gần nhất
                if im.size[0] != size:
                    im = im.resize((size, size), Image.LANCZOS)
                # Đảm bảo RGBA
                if im.mode != "RGBA":
                    im = im.convert("RGBA")
                return im
            except Exception:
                continue

    # Fallback: vẽ icon chữ N2E
    im = Image.new("RGBA", (size, size), (15, 15, 15, 0))
    draw = ImageDraw.Draw(im)
    # nền bo tròn
    draw.rounded_rectangle([2, 2, size - 2, size - 2], radius=size // 6, fill=(99, 102, 241, 255))
    # chữ N (đơn giản)
    try:
        # cố gắng dùng font mặc định
        draw.text((size * 0.22, size * 0.18), "N", fill=(255, 255, 255, 255))
    except Exception:
        draw.rectangle([size // 3, size // 4, size * 2 // 3, size * 3 // 4], fill=(255, 255, 255, 255))
    return im

# ── server ─────────────────────────────────────────────────────────

_server = None
_server_thread: threading.Thread | None = None

def find_free_port(host: str, start: int) -> int:
    for p in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            try:
                s.bind((host, p))
                return p
            except OSError:
                continue
    return start

def wait_for_server(host: str, port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.4)
    return False

def start_server(host: str, port: int):
    global _server
    # Đặt env DB nếu chưa có — để app/deps.py nhận đúng file cạnh exe
    db_path = os.environ.get("NOVEL2EPUB_DB") or os.environ.get("NOVEL2EPUB_FILE") or str(BASE_DIR / "novel2epub.db")
    os.environ["NOVEL2EPUB_DB"] = db_path
    # Đảm bảo DB tồn tại (init nếu chưa)
    try:
        from novel2epub.db import get_connection, init_schema

        dbp = Path(db_path)
        need_init = not dbp.exists()
        if need_init:
            log.info("DB chưa có, khởi tạo %s", dbp)
            # init_schema sẽ tạo file
            conn = get_connection(dbp)
            try:
                init_schema(conn)
            finally:
                conn.close()
    except Exception as e:
        log.warning("DB init check failed: %s", e)

    # Khởi uvicorn
    try:
        import uvicorn

        # Tắt reload, log gọn khi chạy nền
        config = uvicorn.Config(
            "app.main:app",
            host=host,
            port=port,
            log_level="warning",
            access_log=False,
            workers=1,
        )
        _server = uvicorn.Server(config)

        # Chạy blocking trong thread này
        # Nếu port bận, thử port kế
        try:
            _server.run()
        except OSError as e:
            if "address already in use" in str(e).lower() or "10048" in str(e):
                new_port = find_free_port(host, port + 1)
                log.warning("Port %s bận, thử %s", port, new_port)
                config = uvicorn.Config("app.main:app", host=host, port=new_port, log_level="warning", access_log=False)
                _server = uvicorn.Server(config)
                # cập nhật URL toàn cục cho menu "Mở Web UI"
                globals()["_actual_port"] = new_port
                _server.run()
            else:
                raise
    except SystemExit:
        pass
    except Exception as e:
        log.exception("server crashed: %s", e)

def stop_server():
    global _server
    if _server:
        try:
            _server.should_exit = True
        except Exception:
            pass
        _server = None

# ── tray ───────────────────────────────────────────────────────────

_actual_port = DEFAULT_PORT

def _get_url() -> str:
    return f"http://{DEFAULT_HOST}:{_actual_port}"

def run_tray(host: str, port: int, minimized: bool, no_browser: bool):
    global _actual_port
    _actual_port = port

    # Khởi server thread
    t = threading.Thread(target=start_server, args=(host, port), daemon=True, name="uvicorn")
    t.start()
    globals()["_server_thread"] = t

    # Chờ server sẵn sàng rồi mở browser (nếu không minimized)
    def _maybe_open():
        ok = wait_for_server(host, port, timeout=25)
        if ok and not minimized and not no_browser:
            # delay nhỏ để SPA load
            time.sleep(0.6)
            try:
                webbrowser.open(f"http://{host}:{port}/app/")
            except Exception:
                pass

    threading.Thread(target=_maybe_open, daemon=True).start()

    # Lazy import pystray để --help không cần cài
    try:
        import pystray  # type: ignore
        from pystray import MenuItem as Item  # type: ignore
    except ImportError:
        log.error("Thiếu pystray. Cài: pip install pystray pillow")
        print("Thiếu pystray. Cài: pip install pystray pillow", file=sys.stderr)
        print("Vẫn chạy server ở", _get_url(), "- bấm Ctrl+C để dừng.")
        try:
            while t.is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            stop_server()
        return

    icon_image = load_icon_image(64)

    # ——— actions ———
    def action_open(icon, item):
        webbrowser.open(_get_url() + "/app/")

    def action_open_jinja(icon, item):
        webbrowser.open(_get_url() + "/")

    def action_open_folder(icon, item):
        path = BASE_DIR
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except AttributeError:
            webbrowser.open(path.as_uri())
        except Exception:
            webbrowser.open(path.as_uri())

    def action_copy_url(icon, item):
        url = _get_url() + "/app/"
        try:
            import tkinter  # type: ignore

            r = tkinter.Tk()
            r.withdraw()
            r.clipboard_clear()
            r.clipboard_append(url)
            r.update()
            r.destroy()
        except Exception:
            print(url)

    def action_toggle_autostart(icon, item):
        cur = is_autostart_enabled()
        set_autostart(not cur)
        # Cập nhật lại menu (pystray cần rebuild)
        icon.menu = build_menu(icon)

    def action_quit(icon, item):
        icon.visible = False
        stop_server()
        # Cho server chút thời gian tắt
        time.sleep(0.8)
        icon.stop()
        release_single_instance()
        os._exit(0)

    def action_restart(icon, item):
        stop_server()
        time.sleep(1.0)
        # Khởi lại thread
        nt = threading.Thread(target=start_server, args=(host, _actual_port), daemon=True)
        nt.start()
        globals()["_server_thread"] = nt

    def build_menu(icon):
        autostart_on = is_autostart_enabled()
        return pystray.Menu(
            Item(f"novel2epub  ·  {_get_url()}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            Item("Mở Web UI (SPA)", action_open, default=True),
            Item("Mở Jinja2 (/ )", action_open_jinja),
            Item("Mở thư mục dữ liệu", action_open_folder),
            Item("Sao chép URL", action_copy_url),
            pystray.Menu.SEPARATOR,
            Item(
                "Khởi động cùng Windows  ✓" if autostart_on else "Khởi động cùng Windows",
                action_toggle_autostart,
                checked=lambda _: is_autostart_enabled(),
            ),
            Item("Khởi động lại server", action_restart),
            pystray.Menu.SEPARATOR,
            Item("Thoát", action_quit),
        )

    # Tooltip
    tooltip = f"novel2epub — {_get_url()}"

    icon = pystray.Icon(APP_NAME, icon_image, tooltip, menu=build_menu(None))  # type: ignore

    # Double-click mở web UI (Windows)
    try:
        icon.on_click = lambda ic, btn: webbrowser.open(_get_url() + "/app/") if str(btn) == "left" else None  # type: ignore
    except Exception:
        pass

    # Xử lý khi đóng: không thoát mà giữ tray (icon.run là blocking)
    try:
        icon.run()
    finally:
        stop_server()
        release_single_instance()

# ── cli ────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="novel2epub tray - chay nen trong khay he thong")
    p.add_argument("--host", default=DEFAULT_HOST, help="host (mac dinh 127.0.0.1)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help="port (mac dinh 8010)")
    p.add_argument("--minimized", action="store_true", help="khong tu mo browser khi khoi dong")
    p.add_argument("--no-browser", action="store_true", help="khong mo browser")
    p.add_argument("--no-single-instance", action="store_true", help="cho phep chay nhieu instance")
    return p.parse_args()

def main():
    args = parse_args()

    # Single instance guard
    if not args.no_single_instance:
        if not acquire_single_instance():
            # Da co instance: mo browser toi instance cu roi thoat
            print("Da co novel2epub dang chay - mo Web UI cua instance cu.")
            try:
                webbrowser.open(f"http://{args.host}:{args.port}/app/")
            except Exception:
                pass
            sys.exit(0)

    # Logging ra file khi chạy nền (không console)
    try:
        log_dir = BASE_DIR / "logs"
        log_dir.mkdir(exist_ok=True)
        fh = logging.FileHandler(log_dir / "tray.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logging.basicConfig(level=logging.INFO, handlers=[fh], force=False)
    except Exception:
        logging.basicConfig(level=logging.INFO)

    log.info("Starting tray app at http://%s:%s (frozen=%s, base=%s)", args.host, args.port, _is_frozen(), BASE_DIR)

    # Bẫy Ctrl+C khi chạy console
    try:
        run_tray(args.host, args.port, minimized=args.minimized, no_browser=args.no_browser)
    except KeyboardInterrupt:
        stop_server()
        release_single_instance()

if __name__ == "__main__":
    main()
