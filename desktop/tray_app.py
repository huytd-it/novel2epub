#!/usr/bin/env python3
"""
novel2epub — Desktop tray app chạy nền (Windows) + build .exe không console.

- Khởi uvicorn FastAPI ở thread nền, tự chọn port rảnh nếu port mặc định bận
- Hiện icon khay hệ thống: mở Web UI, mở thư mục, autostart, thoát
- Chạy nền không console khi build --windowed / --noconsole
- Single-instance: lock file + socket fallback
- Autostart: HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
- Tự load .env: PORT / N2E_TRAY_PORT / N2E_PORT / N2E_TRAY_HOST

Thứ tự ưu tiên port:
  1. CLI --port
  2. Biến môi trường N2E_TRAY_PORT / PORT / N2E_PORT
  3. File .env cạnh exe / project root / CWD (PORT / N2E_TRAY_PORT / N2E_PORT)
  4. Mặc định 8010 -> nếu bận thì chọn ngẫu nhiên
  5. Nếu vẫn bận: pick random free port qua OS (bind 0)

Thứ tự ưu tiên host tương tự: CLI --host > N2E_TRAY_HOST / HOST > .env > 127.0.0.1

Chạy trực tiếp (dev):
    .venv\\Scripts\\python.exe desktop/tray_app.py
    .venv\\Scripts\\python.exe desktop/tray_app.py --port 8010 --no-browser
    N2E_TRAY_PORT=0 .venv\\Scripts\\python.exe desktop/tray_app.py  # random port

Build exe:
    powershell -ExecutionPolicy Bypass -File scripts/build-exe.ps1

Env (.env hoặc biến môi trường):
    NOVEL2EPUB_DB  : đường dẫn DB (mặc định <exe-dir>/novel2epub.db)
    N2E_TRAY_PORT / PORT / N2E_PORT : cổng (mặc định 8010, 0 = random)
    N2E_TRAY_HOST / HOST            : host (mặc định 127.0.0.1)
"""
from __future__ import annotations

import argparse
import logging
import os
import random
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
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_resource_dir() -> Path:
    """Nơi chứa code/resources bundle (dùng cho icon, webui)."""
    if _is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return get_base_dir()


BASE_DIR = get_base_dir()
RESOURCE_DIR = get_resource_dir()

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if str(RESOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(RESOURCE_DIR))

# ── .env loader (không cần python-dotenv) ─────────────────────────

def _parse_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return data
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # bỏ export prefix
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip("\"'").strip()
        # bỏ inline comment chưa trong quote
        # đơn giản: nếu val chứa " #", cắt
        if " #" in val:
            # chỉ cắt nếu không nằm trong quote đã strip
            val = val.split(" #", 1)[0].strip()
        if key:
            data[key] = val
    return data


def _load_dotenv() -> Path | None:
    """Tìm và load .env, set vào os.environ nếu chưa có. Trả về path đã load."""
    candidates: list[Path] = []
    # thứ tự ưu tiên: cạnh exe > project root > CWD
    try:
        candidates.append(BASE_DIR / ".env")
        candidates.append(RESOURCE_DIR / ".env")
        candidates.append(Path.cwd() / ".env")
        # khi dev: BASE_DIR là project root, nhưng frozen thì BASE_DIR là dist
        # thử thêm parent của BASE_DIR
        candidates.append(BASE_DIR.parent / ".env")
        # desktop/tray_app.py -> project root/.env đã là BASE_DIR/.env ở dev
    except Exception:
        pass

    seen: set[Path] = set()
    for p in candidates:
        try:
            rp = p.resolve()
        except Exception:
            rp = p
        if rp in seen:
            continue
        seen.add(rp)
        if rp.is_file():
            env = _parse_env_file(rp)
            for k, v in env.items():
                # không ghi đè biến đã có trong môi trường (env thật thắng .env)
                if k not in os.environ:
                    os.environ[k] = v
            return rp
    return None


_DOTENV_PATH = _load_dotenv()

# ── constants ──────────────────────────────────────────────────────

APP_NAME = "novel2epub"
LOCK_NAME = "novel2epub-tray.lock"
REG_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_VALUE_NAME = "novel2epub"

# host/port mặc định — đã được _load_dotenv bơm vào os.environ nếu .env tồn tại
_DEFAULT_HOST_RAW = os.environ.get("N2E_TRAY_HOST") or os.environ.get("HOST") or "127.0.0.1"
try:
    _PORT_RAW = os.environ.get("N2E_TRAY_PORT") or os.environ.get("PORT") or os.environ.get("N2E_PORT") or "8010"
    DEFAULT_PORT = int(str(_PORT_RAW).strip())
except (ValueError, TypeError):
    DEFAULT_PORT = 8010
DEFAULT_HOST = _DEFAULT_HOST_RAW.strip() or "127.0.0.1"

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
        if not _is_frozen():
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


# ── port helpers ───────────────────────────────────────────────────

def _is_port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _get_random_free_port(host: str) -> int:
    """Hỏi OS cấp port ngẫu nhiên (bind 0)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


def _find_random_free_port(host: str, preferred: int | None = None, tries: int = 30) -> int:
    """Ưu tiên preferred nếu rảnh, không thì thử ngẫu nhiên trong dải, cuối cùng bind 0."""
    if preferred is not None and preferred != 0:
        if _is_port_free(host, preferred):
            return preferred
    # thử random trong dải 8000-9500
    candidates = random.sample(range(8000, 9500), min(tries, 200))
    # cũng thử các port kế preferred để giữ tính tuần tự khi random fail
    if preferred and preferred != 0:
        for p in range(preferred + 1, preferred + 20):
            if p not in candidates:
                candidates.append(p)
    for p in candidates:
        if _is_port_free(host, p):
            return p
    # fallback: OS random
    try:
        return _get_random_free_port(host)
    except OSError:
        return preferred or 8010


def _resolve_port(cli_port: int | None, host: str) -> int:
    """Giải quyết port theo thứ tự: CLI > env (.env đã load) > default.
    Nếu env/cli là 0 => random. Nếu port bận => random.
    """
    raw: int | None = cli_port
    source = "cli" if cli_port is not None else "env/default"
    if raw is None:
        raw = DEFAULT_PORT
        source = ".env/env/default"
    if raw == 0:
        port = _get_random_free_port(host)
        log.info("Port yêu cầu 0 (random) -> chọn %s", port)
        return port
    if _is_port_free(host, raw):
        log.info("Port %s (%s) rảnh", raw, source)
        return raw
    # bận -> random
    new_port = _find_random_free_port(host, preferred=raw)
    log.warning("Port %s bận, tự chọn %s", raw, new_port)
    return new_port


def _resolve_host(cli_host: str | None) -> str:
    if cli_host:
        return cli_host
    # DEFAULT_HOST đã tính từ env/.env
    return DEFAULT_HOST


# ── single instance ────────────────────────────────────────────────

_lock_fp = None


def acquire_single_instance() -> bool:
    """Giữ lock file để tránh chạy 2 tray cùng lúc. Trả False nếu đã có instance."""
    global _lock_fp
    lock_path = BASE_DIR / LOCK_NAME
    try:
        import msvcrt  # type: ignore

        _lock_fp = open(lock_path, "w")
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
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # dùng port lock = actual port + 1 hoặc random
            s.bind((DEFAULT_HOST, DEFAULT_PORT + 1))
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
                if im.size[0] != size:
                    im = im.resize((size, size), Image.LANCZOS)
                if im.mode != "RGBA":
                    im = im.convert("RGBA")
                return im
            except Exception:
                continue

    im = Image.new("RGBA", (size, size), (15, 15, 15, 0))
    draw = ImageDraw.Draw(im)
    draw.rounded_rectangle([2, 2, size - 2, size - 2], radius=size // 6, fill=(99, 102, 241, 255))
    try:
        draw.text((size * 0.22, size * 0.18), "N", fill=(255, 255, 255, 255))
    except Exception:
        draw.rectangle([size // 3, size // 4, size * 2 // 3, size * 3 // 4], fill=(255, 255, 255, 255))
    return im


# ── server ─────────────────────────────────────────────────────────

_server = None
_server_thread: threading.Thread | None = None
_actual_port: int = DEFAULT_PORT
_actual_host: str = DEFAULT_HOST


def find_free_port(host: str, start: int) -> int:
    """Giữ API cũ: thử tuần tự 20 port, fallback random."""
    for p in range(start, start + 20):
        if _is_port_free(host, p):
            return p
    return _find_random_free_port(host, preferred=start)


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
    global _server, _actual_port, _actual_host
    _actual_host = host
    _actual_port = port
    # Fix cho --windowed (frozen, không console): sys.stdout/stderr là None -> uvicorn formatter gọi isatty() sẽ crash
    # dist/logs/tray.log:20 AttributeError: 'NoneType' object has no attribute 'isatty'
    if _is_frozen():
        import io

        if sys.stdout is None:
            sys.stdout = io.StringIO()  # type: ignore
        if sys.stderr is None:
            sys.stderr = io.StringIO()  # type: ignore
    db_path = os.environ.get("NOVEL2EPUB_DB") or os.environ.get("NOVEL2EPUB_FILE") or str(BASE_DIR / "novel2epub.db")
    os.environ["NOVEL2EPUB_DB"] = db_path
    try:
        from novel2epub.db import get_connection, init_schema

        dbp = Path(db_path)
        if not dbp.exists():
            log.info("DB chưa có, khởi tạo %s", dbp)
            conn = get_connection(dbp)
            try:
                init_schema(conn)
            finally:
                conn.close()
    except Exception as e:
        log.warning("DB init check failed: %s", e)

    # Ghi port thực tế ra file để external tools / lần chạy sau có thể đọc
    try:
        port_file = BASE_DIR / "logs" / "port.txt"
        port_file.parent.mkdir(parents=True, exist_ok=True)
        port_file.write_text(str(port), encoding="utf-8")
    except Exception:
        pass

    try:
        import uvicorn

        # log_config=None tránh dictConfig với ColourizedFormatter (đòi isatty); dùng warning + file log riêng
        uv_log_config = None if _is_frozen() else uvicorn.config.LOGGING_CONFIG  # type: ignore[attr-defined]
        config = uvicorn.Config(
            "app.main:app",
            host=host,
            port=port,
            log_level="warning",
            access_log=False,
            workers=1,
            log_config=uv_log_config,
        )
        _server = uvicorn.Server(config)
        try:
            _server.run()
        except OSError as e:
            msg = str(e).lower()
            if "address already in use" in msg or "10048" in msg or "10013" in msg:
                new_port = _find_random_free_port(host, preferred=port + 1)
                log.warning("Port %s bận, thử %s", port, new_port)
                uv_log_config2 = None if _is_frozen() else uvicorn.config.LOGGING_CONFIG  # type: ignore[attr-defined]
                config = uvicorn.Config("app.main:app", host=host, port=new_port, log_level="warning", access_log=False, log_config=uv_log_config2)
                _server = uvicorn.Server(config)
                _actual_port = new_port
                try:
                    (BASE_DIR / "logs" / "port.txt").write_text(str(new_port), encoding="utf-8")
                except Exception:
                    pass
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

def _get_url() -> str:
    return f"http://{_actual_host}:{_actual_port}"


def run_tray(host: str, port: int, minimized: bool, no_browser: bool):
    global _actual_port, _actual_host
    # resolve lần cuối trước khi chạy — đảm bảo random nếu bận
    resolved_port = _resolve_port(port if port != DEFAULT_PORT or port == 0 else None, host) if port else _resolve_port(None, host)
    # Nếu caller truyền port rõ ràng (từ parse_args), đã resolve ở main; nhưng để an toàn:
    # Ở đây host đã là resolved host, port đã là resolved port từ main — chỉ fallback thêm
    _actual_port = resolved_port
    _actual_host = host

    t = threading.Thread(target=start_server, args=(host, resolved_port), daemon=True, name="uvicorn")
    t.start()
    globals()["_server_thread"] = t

    def _maybe_open():
        ok = wait_for_server(host, resolved_port, timeout=25)
        # nếu start_server đã đổi port do conflict, chờ thêm actual
        if not ok and _actual_port != resolved_port:
            ok = wait_for_server(_actual_host, _actual_port, timeout=15)
        if ok and not minimized and not no_browser:
            time.sleep(0.6)
            try:
                webbrowser.open(f"http://{_actual_host}:{_actual_port}/")
            except Exception:
                pass

    threading.Thread(target=_maybe_open, daemon=True).start()

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

    def action_open(icon, item):
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
        url = _get_url() + "/"
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
        icon.menu = build_menu(icon)

    def action_quit(icon, item):
        icon.visible = False
        stop_server()
        time.sleep(0.8)
        icon.stop()
        release_single_instance()
        os._exit(0)

    def action_restart(icon, item):
        stop_server()
        time.sleep(1.0)
        nt = threading.Thread(target=start_server, args=(host, _actual_port), daemon=True)
        nt.start()
        globals()["_server_thread"] = nt

    def build_menu(icon):
        autostart_on = is_autostart_enabled()
        return pystray.Menu(
            Item(f"novel2epub  ·  {_get_url()}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            Item("Mở Web UI", action_open, default=True),
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

    tooltip = f"novel2epub — {_get_url()}"
    icon = pystray.Icon(APP_NAME, icon_image, tooltip, menu=build_menu(None))  # type: ignore
    try:
        icon.on_click = lambda ic, btn: webbrowser.open(_get_url() + "/") if str(btn) == "left" else None  # type: ignore
    except Exception:
        pass
    try:
        icon.run()
    finally:
        stop_server()
        release_single_instance()


# ── cli ────────────────────────────────────────────────────────────

def parse_args():
    # Lưu ý: default None để phân biệt user có truyền --port/--host hay không
    # description/help giữ ascii để --help không lỗi cp1252 khi redirect (Windows cmd)
    p = argparse.ArgumentParser(description="novel2epub tray - chay nen trong khay he thong (tu doc .env, tu chon port ranh)")
    p.add_argument("--host", default=None, help="host (mac dinh tu .env N2E_TRAY_HOST/HOST hoac 127.0.0.1)")
    p.add_argument("--port", type=int, default=None, help="port (mac dinh tu .env PORT/N2E_TRAY_PORT hoac 8010; 0 = random)")
    p.add_argument("--minimized", action="store_true", help="khong tu mo browser khi khoi dong")
    p.add_argument("--no-browser", action="store_true", help="khong mo browser")
    p.add_argument("--no-single-instance", action="store_true", help="cho phep chay nhieu instance")
    return p.parse_args()


def main():
    args = parse_args()

    # Resolve host/port theo thứ tự: CLI > env/.env > default, bận thì random
    host = _resolve_host(args.host)
    # args.port None => dùng DEFAULT_PORT (đã từ env/.env)
    # args.port 0 => random
    # args.port số => thử số đó, bận thì random
    if args.port is not None:
        port = _resolve_port(args.port, host)
    else:
        port = _resolve_port(None, host)

    # Ghi lại actual để các nơi khác dùng
    global _actual_port, _actual_host
    _actual_port = port
    _actual_host = host

    if not args.no_single_instance:
        if not acquire_single_instance():
            print("Da co novel2epub dang chay - mo Web UI cua instance cu.")
            # Cố mở URL của instance cũ (thử đọc logs/port.txt)
            try:
                pf = BASE_DIR / "logs" / "port.txt"
                if pf.exists():
                    old_port = int(pf.read_text(encoding="utf-8").strip())
                    webbrowser.open(f"http://{host}:{old_port}/")
                else:
                    webbrowser.open(f"http://{host}:{port}/")
            except Exception:
                try:
                    webbrowser.open(f"http://{host}:{port}/")
                except Exception:
                    pass
            sys.exit(0)

    try:
        log_dir = BASE_DIR / "logs"
        log_dir.mkdir(exist_ok=True)
        fh = logging.FileHandler(log_dir / "tray.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        # tránh duplicate handler khi reload
        root = logging.getLogger()
        if not any(isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", "") == str(fh.baseFilename) for h in root.handlers):
            logging.basicConfig(level=logging.INFO, handlers=[fh], force=False)
            # cũng add handler nếu basicConfig đã có
            if fh not in root.handlers:
                root.addHandler(fh)
        # ghi nguồn port
        dotenv_info = f" .env={_DOTENV_PATH}" if _DOTENV_PATH else " (không có .env)"
        log.info("Starting tray app at http://%s:%s (frozen=%s, base=%s)%s", host, port, _is_frozen(), BASE_DIR, dotenv_info)
    except Exception:
        logging.basicConfig(level=logging.INFO)
        log.info("Starting tray app at http://%s:%s (frozen=%s, base=%s)", host, port, _is_frozen(), BASE_DIR)

    try:
        run_tray(host, port, minimized=args.minimized, no_browser=args.no_browser)
    except KeyboardInterrupt:
        stop_server()
        release_single_instance()


if __name__ == "__main__":
    main()
