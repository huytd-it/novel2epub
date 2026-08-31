#!/usr/bin/env bash
# build.sh — Build SPA production frontend -> app/webui (SPA only)
# Tu dong kiem tra moi truong
# Usage: ./scripts/build.sh [--skip-install]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SKIP_INSTALL=0
[[ "${1:-}" == "--skip-install" ]] && SKIP_INSTALL=1

echo "==> Build SPA — frontend -> app/webui"
echo "  Root: $ROOT"

# Python check
if command -v python3 >/dev/null 2>&1; then PY=python3; elif command -v python >/dev/null 2>&1; then PY=python; else echo "  [!] Khong tim thay Python - chi build frontend"; PY=""; fi
if [[ -n "$PY" ]]; then
  echo "  [OK] Python $($PY -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')") ($PY)"
  if [[ -f .venv/bin/python && $SKIP_INSTALL -eq 0 ]]; then
    echo "==> pip install -r requirements.txt"
    .venv/bin/python -m pip install -r requirements.txt --quiet && echo "  [OK] Python deps OK" || echo "  [!] pip install loi"
  fi
fi

# Node check
if ! command -v node >/dev/null 2>&1; then echo "Can Node.js >=18"; exit 1; fi
echo "  [OK] Node $(node --version) / npm $(npm --version)"

if [[ ! -d frontend/node_modules ]]; then
  echo "==> npm install (frontend)"
  (cd frontend && npm install)
fi

echo "==> Vite build"
(cd frontend && npm run build)

if [[ -f app/webui/index.html ]]; then
  echo "  [OK] Build OK: app/webui/index.html"
  ls -lh app/webui/ | head -n 20
else
  echo "Build xong nhung khong thay app/webui/index.html" >&2
  exit 1
fi

echo ""
echo "Chay thu: ./scripts/run.sh"
echo "Hoac build exe: ./scripts/build-exe.sh"
