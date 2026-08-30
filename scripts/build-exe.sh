#!/usr/bin/env bash
# build-exe.sh - Đóng gói novel2epub thành exe/binary chạy nền (Linux/macOS)
# Usage:
#   ./scripts/build-exe.sh
#   ./scripts/build-exe.sh --no-window --onefile
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ONEFILE=1
WINDOWED=0
SKIP_BUILD=0
SKIP_INSTALL=0
PORT=8010

while [[ $# -gt 0 ]]; do
  case "$1" in
    --onefile) ONEFILE=1; shift ;;
    --onedir) ONEFILE=0; shift ;;
    --windowed|--no-window) WINDOWED=1; shift ;;
    --console) WINDOWED=0; shift ;;
    --skip-build) SKIP_BUILD=1; shift ;;
    --skip-install) SKIP_INSTALL=1; shift ;;
    --port) PORT="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

VENV_PY="$ROOT/.venv/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  echo "Tạo .venv ..."
  python3 -m venv .venv
fi
if [[ "$SKIP_INSTALL" == 0 ]]; then
  echo "==> pip install"
  "$VENV_PY" -m pip install -q -r requirements.txt pystray pillow pyinstaller
fi

if [[ ! -f "app/webui/index.html" && "$SKIP_BUILD" == 0 ]]; then
  echo "==> vite build"
  (cd frontend && npm install && npm run build)
fi

ICON=""
for c in "frontend/src-tauri/icons/icon.png" "desktop/icon.png"; do
  if [[ -f "$c" ]]; then ICON="$c"; break; fi
done

echo "==> PyInstaller"
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
  app.routes.ebooks app.routes.chapters app.routes.glossary app.routes.jobs
  novel2epub.config novel2epub.db novel2epub.storage novel2epub.pipeline
  uvicorn.logging uvicorn.loops.auto uvicorn.protocols.http.auto uvicorn.protocols.websockets.auto
  jinja2.ext yaml PIL pystray
)
for h in "${HIDDEN[@]}"; do ARGS+=(--hidden-import "$h"); done

if [[ -d "app/webui" ]]; then ARGS+=(--add-data "app/webui:app/webui"); fi
if [[ -d "frontend/src-tauri/icons" ]]; then ARGS+=(--add-data "frontend/src-tauri/icons:frontend/src-tauri/icons"); fi
if [[ -d "app/templates" ]]; then ARGS+=(--add-data "app/templates:app/templates"); fi
if [[ -f "novel2epub.example.yaml" ]]; then ARGS+=(--add-data "novel2epub.example.yaml:."); fi
if [[ -f "sources.yaml" ]]; then ARGS+=(--add-data "sources.yaml:."); fi

"$VENV_PY" -m PyInstaller "${ARGS[@]}"

if [[ "$ONEFILE" == 1 ]]; then
  echo "OK: dist/novel2epub-tray ($(du -h dist/novel2epub-tray | cut -f1))"
else
  echo "OK: dist/novel2epub-tray/"
fi
echo "Chạy: ./dist/novel2epub-tray --help"
