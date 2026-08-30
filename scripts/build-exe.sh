#!/usr/bin/env bash
# build-exe.sh - Đóng gói novel2epub thành exe/binary chạy nền (Linux/macOS)
# - Tự kiểm tra môi trường (Python >=3.10, Node >=18, pip, venv) và cài đặt đầy đủ
# - Tự động lấy port từ .env / biến môi trường, nếu không có hoặc bận thì chọn ngẫu nhiên
# - Build SPA rồi đóng gói PyInstaller (--windowed = không console trên Windows)
#
# Usage:
#   ./scripts/build-exe.sh
#   ./scripts/build-exe.sh --port 8010
#   ./scripts/build-exe.sh --random-port
#   ./scripts/build-exe.sh --onedir --windowed
#   ./scripts/build-exe.sh --skip-build --skip-install
#   ./scripts/build-exe.sh --env-file .env
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ONEFILE=1
WINDOWED=0
SKIP_BUILD=0
SKIP_INSTALL=0
INSTALL_BROWSERS=0
PORT=""
HOST_ADDR=""
RANDOM_PORT=0
ENV_FILE=".env"
ICON=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --onefile) ONEFILE=1; shift ;;
    --onedir) ONEFILE=0; shift ;;
    --windowed|--no-window) WINDOWED=1; shift ;;
    --console) WINDOWED=0; shift ;;
    --skip-build) SKIP_BUILD=1; shift ;;
    --skip-install) SKIP_INSTALL=1; shift ;;
    --install-browsers) INSTALL_BROWSERS=1; shift ;;
    --random-port) RANDOM_PORT=1; shift ;;
    --port) PORT="$2"; shift 2 ;;
    --host) HOST_ADDR="$2"; shift 2 ;;
    --env-file) ENV_FILE="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; echo "Usage: $0 [--port 8010] [--random-port] [--host 127.0.0.1] [--onedir] [--windowed] [--skip-build] [--skip-install] [--env-file .env]"; exit 1 ;;
  esac
done

echo "==> Kiểm tra môi trường"

# Python
if command -v python3 >/dev/null 2>&1; then PY=python3
elif command -v python >/dev/null 2>&1; then PY=python
else echo "✘ Không tìm thấy Python (cần >=3.10)"; exit 1
fi
PY_VER=$($PY -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 10 ]]; }; then
  echo "✘ Yêu cầu Python >=3.10, hiện tại $PY_VER"
  exit 1
fi
echo "  ✔ Python $PY_VER ($PY)"

# Node
if command -v node >/dev/null 2>&1; then
  NODE_VER=$(node --version 2>/dev/null || echo "")
  NPM_VER=$(npm --version 2>/dev/null || echo "")
  NODE_MAJOR=$(echo "$NODE_VER" | tr -d 'v' | cut -d. -f1)
  if [[ -n "$NODE_MAJOR" && "$NODE_MAJOR" -lt 18 ]]; then
    echo "  ! Node $NODE_VER < 18 — khuyến nghị Node 18+ (vẫn thử build)"
  else
    echo "  ✔ Node $NODE_VER / npm $NPM_VER"
  fi
  NODE_OK=1
else
  echo "  ! Không tìm thấy Node.js — build SPA sẽ bỏ qua"
  NODE_OK=0
fi

# pip
if ! $PY -m pip --version >/dev/null 2>&1; then
  echo "✘ pip không khả dụng — chạy: $PY -m ensurepip --upgrade"
  exit 1
fi
echo "  ✔ pip OK"

# ── Resolve PORT / HOST ──────────────────────────────────────────

# helper: đọc .env
parse_env_file() {
  local file="$1"
  local key="$2"
  if [[ ! -f "$file" ]]; then return 1; fi
  # lấy dòng cuối cùng khớp KEY=...
  local val
  val=$(grep -E "^[[:space:]]*(export[[:space:]]+)?${key}[[:space:]]*=" "$file" 2>/dev/null | tail -n1 | sed -E "s/^[[:space:]]*(export[[:space:]]+)?${key}[[:space:]]*=[[:space:]]*//" | sed -E "s/^[\"']//;s/[\"'].*$//;s/[[:space:]]*#.*$//" | tr -d "\"'" | xargs 2>/dev/null || true)
  if [[ -n "$val" ]]; then echo "$val"; return 0; fi
  return 1
}

find_free_port() {
  local host="${1:-127.0.0.1}"
  local preferred="${2:-0}"
  $PY -c "
import socket, random, sys
host=sys.argv[1]
preferred=int(sys.argv[2]) if len(sys.argv)>2 else 0
def is_free(p):
    import socket as s
    sock=s.socket(s.AF_INET, s.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        sock.bind((host,p)); sock.close(); return True
    except: return False
if preferred and preferred!=0 and is_free(preferred):
    print(preferred)
    sys.exit(0)
for _ in range(30):
    p=random.randint(8000,9500)
    if is_free(p):
        print(p); sys.exit(0)
# fallback OS random
import socket as sk
s=sk.socket(sk.AF_INET, sk.SOCK_STREAM)
s.bind((host,0))
print(s.getsockname()[1])
" "$host" "$preferred" 2>/dev/null
}

# Host
if [[ -z "$HOST_ADDR" ]]; then
  if [[ -n "${N2E_TRAY_HOST:-}" ]]; then HOST_ADDR="$N2E_TRAY_HOST"
  elif [[ -n "${HOST:-}" ]]; then HOST_ADDR="$HOST"
  else
    for f in "$ENV_FILE" "$ROOT/.env" ".env"; do
      v=$(parse_env_file "$f" "N2E_TRAY_HOST" 2>/dev/null || true)
      if [[ -n "$v" ]]; then HOST_ADDR="$v"; break; fi
      v=$(parse_env_file "$f" "HOST" 2>/dev/null || true)
      if [[ -n "$v" ]]; then HOST_ADDR="$v"; break; fi
    done
  fi
  HOST_ADDR="${HOST_ADDR:-127.0.0.1}"
fi

# Port
PORT_SOURCE=""
if [[ -n "$PORT" && "$PORT" != "0" ]]; then
  PORT_SOURCE="tham số --port"
elif [[ "$RANDOM_PORT" == 1 ]]; then
  PORT=$(find_free_port "$HOST_ADDR" 0)
  PORT_SOURCE="random (--random-port)"
else
  # thử env var
  ENV_PORT="${N2E_TRAY_PORT:-${PORT:-${N2E_PORT:-}}}"
  ENV_PORT_SOURCE="env var"
  if [[ -z "$ENV_PORT" ]]; then
    for f in "$ENV_FILE" "$ROOT/.env" ".env"; do
      v=$(parse_env_file "$f" "N2E_TRAY_PORT" 2>/dev/null || true)
      if [[ -n "$v" ]]; then ENV_PORT="$v"; ENV_PORT_SOURCE=".env ($f)"; break; fi
      v=$(parse_env_file "$f" "PORT" 2>/dev/null || true)
      if [[ -n "$v" ]]; then ENV_PORT="$v"; ENV_PORT_SOURCE=".env ($f)"; break; fi
      v=$(parse_env_file "$f" "N2E_PORT" 2>/dev/null || true)
      if [[ -n "$v" ]]; then ENV_PORT="$v"; ENV_PORT_SOURCE=".env ($f)"; break; fi
    done
  fi
  if [[ -n "$ENV_PORT" && "$ENV_PORT" != "0" ]]; then
    FREE=$(find_free_port "$HOST_ADDR" "$ENV_PORT")
    if [[ "$FREE" == "$ENV_PORT" ]]; then
      PORT="$ENV_PORT"
      PORT_SOURCE="$ENV_PORT_SOURCE"
    else
      PORT="$FREE"
      PORT_SOURCE="$ENV_PORT_SOURCE bận $ENV_PORT -> random $FREE"
    fi
  else
    PORT=$(find_free_port "$HOST_ADDR" 0)
    PORT_SOURCE="random (không có PORT trong env/.env)"
    # tạo .env nếu chưa có
    if [[ ! -f "$ROOT/.env" ]]; then
      echo "N2E_TRAY_PORT=$PORT" > "$ROOT/.env"
      echo "N2E_TRAY_HOST=$HOST_ADDR" >> "$ROOT/.env"
      echo "  ✔ Đã tạo .env với PORT=$PORT"
      PORT_SOURCE="$PORT_SOURCE + ghi .env"
    fi
  fi
fi

# Nếu PORT ban đầu là tham số nhưng bận -> random
if [[ "$PORT_SOURCE" == "tham số --port" ]]; then
  FREE=$(find_free_port "$HOST_ADDR" "$PORT")
  if [[ "$FREE" != "$PORT" ]]; then
    echo "  ! Port $PORT bận -> chọn $FREE"
    PORT="$FREE"
    PORT_SOURCE="tham số bận -> random $FREE"
  fi
fi

# RandomPort ép buộc
if [[ "$RANDOM_PORT" == 1 && -n "${PORT:-}" ]]; then
  # đã xử lý ở trên
  :
fi

echo "  Port: $PORT ($PORT_SOURCE)"
echo "  Host: $HOST_ADDR"
export N2E_TRAY_PORT="$PORT"
export N2E_TRAY_HOST="$HOST_ADDR"

# ── venv & deps ──────────────────────────────────────────────────

VENV_PY="$ROOT/.venv/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  echo "  ! .venv chưa có — tạo mới"
  $PY -m venv .venv
  echo "  ✔ Đã tạo .venv"
else
  echo "  ✔ venv: $VENV_PY"
fi

if [[ "$SKIP_INSTALL" == 0 ]]; then
  echo "==> Cập nhật pip / cài deps Python"
  "$VENV_PY" -m pip install --upgrade pip setuptools wheel -q
  echo "  ✔ pip/wheel OK"
  "$VENV_PY" -m pip install -q -r requirements.txt
  echo "  ✔ requirements.txt OK"
  "$VENV_PY" -m pip install -q pystray pillow pyinstaller
  echo "  ✔ pystray/pillow/pyinstaller OK"
  if [[ "$INSTALL_BROWSERS" == 1 ]]; then
    echo "==> Cài browser cho Scrapling"
    "$VENV_PY" -m scrapling install 2>&1 || true
  fi
else
  echo "  ! SkipInstall — kiểm tra pyinstaller"
  if ! "$VENV_PY" -m pip show pyinstaller >/dev/null 2>&1; then
    echo "==> Thiếu pyinstaller — cài bổ sung"
    "$VENV_PY" -m pip install -q pystray pillow pyinstaller
  fi
  echo "  ✔ Deps OK (skip)"
fi

# ── SPA ──────────────────────────────────────────────────────────

if [[ ! -f "app/webui/index.html" && "$SKIP_BUILD" == 0 && "$NODE_OK" == 1 ]]; then
  echo "==> Build SPA -> app/webui (vite)"
  (cd frontend && npm install && npm run build)
  echo "  ✔ Vite build OK"
elif [[ -f "app/webui/index.html" ]]; then
  echo "  ✔ SPA bundle sẵn: app/webui/index.html"
elif [[ "$NODE_OK" == 0 ]]; then
  echo "  ! Bỏ qua build SPA (thiếu Node) — /app sẽ 404"
else
  echo "  ! Bỏ qua build SPA (--skip-build)"
fi

# Icon
for c in "frontend/src-tauri/icons/icon.png" "desktop/icon.png" "frontend/src-tauri/icons/icon.ico"; do
  if [[ -f "$c" ]]; then ICON="$c"; break; fi
done
if [[ -n "$ICON" ]]; then echo "  ✔ Icon: $ICON"; else echo "  ! Không tìm thấy icon — dùng mặc định"; fi

# ── PyInstaller ──────────────────────────────────────────────────

echo "==> PyInstaller (chạy ngầm: windowed=$WINDOWED)"
rm -rf dist build

ARGS=(
  "desktop/tray_app.py"
  --name "novel2epub-tray"
  --clean --noconfirm --log-level WARN
)
if [[ "$ONEFILE" == 1 ]]; then ARGS+=(--onefile); else ARGS+=(--onedir); fi
if [[ "$WINDOWED" == 1 ]]; then ARGS+=(--windowed); else ARGS+=(--console); fi
if [[ -n "$ICON" ]]; then ARGS+=(--icon "$ICON"); fi

HIDDEN=(
  app.main app.deps app.job app.queue app.scheduler app.logging_config
  app.routes.ebooks app.routes.chapters app.routes.characters app.routes.glossary app.routes.jobs app.routes.idioms
  app.routes.library app.routes.notes app.routes.opds app.routes.reader app.routes.settings app.routes.sources
  app.routes.storage app.routes.tailscale app.routes.webui app.routes.wireguard app.routes.dashboard app.routes.automation
  novel2epub.config novel2epub.db novel2epub.storage novel2epub.pipeline novel2epub.crawler novel2epub.translator novel2epub.epub_builder novel2epub.sources
  uvicorn.logging uvicorn.loops.auto uvicorn.protocols.http.auto uvicorn.protocols.websockets.auto uvicorn.lifespan.on
  jinja2.ext yaml PIL pystray
)
for h in "${HIDDEN[@]}"; do ARGS+=(--hidden-import "$h"); done

if [[ -d "app/webui" ]]; then ARGS+=(--add-data "app/webui:app/webui"); fi
if [[ -d "frontend/src-tauri/icons" ]]; then ARGS+=(--add-data "frontend/src-tauri/icons:frontend/src-tauri/icons"); fi
if [[ -f "novel2epub.example.yaml" ]]; then ARGS+=(--add-data "novel2epub.example.yaml:."); fi
if [[ -f "sources.yaml" ]]; then ARGS+=(--add-data "sources.yaml:."); fi
if [[ -f ".env" ]]; then ARGS+=(--add-data ".env:."); fi

echo "  pyinstaller ${ARGS[*]}"
echo "  PORT=$PORT HOST=$HOST_ADDR"

"$VENV_PY" -m PyInstaller "${ARGS[@]}"

if [[ "$ONEFILE" == 1 ]]; then
  if [[ -f "dist/novel2epub-tray" ]]; then
    echo "✔ Build OK: dist/novel2epub-tray ($(du -h dist/novel2epub-tray | cut -f1)) — chạy ngầm"
  elif [[ -f "dist/novel2epub-tray.exe" ]]; then
    echo "✔ Build OK: dist/novel2epub-tray.exe — chạy ngầm"
  else
    echo "✘ Không tìm thấy binary sau build"; exit 1
  fi
else
  echo "✔ Build OK: dist/novel2epub-tray/"
fi
echo "  Port tự chọn: $PORT ($PORT_SOURCE)"
echo "  Mở UI: http://${HOST_ADDR}:$PORT/app/"
echo "  Chạy: ./dist/novel2epub-tray --help"
echo "        ./dist/novel2epub-tray --minimized   (chạy nền)"
echo "  Đổi port: sửa .env (N2E_TRAY_PORT=...) hoặc: ./dist/novel2epub-tray --port 0  (random)"
echo ""
echo "Hoàn tất."
