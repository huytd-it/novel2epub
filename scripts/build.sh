#!/usr/bin/env bash
# build.sh — Build production frontend -> app/webui
# Usage: ./scripts/build.sh [--skip-install]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SKIP_INSTALL=0
[[ "${1:-}" == "--skip-install" ]] && SKIP_INSTALL=1

echo "==> Build production — frontend -> app/webui"

if [[ -f .venv/bin/python && $SKIP_INSTALL -eq 0 ]]; then
  echo "==> pip install -r requirements.txt"
  .venv/bin/python -m pip install -r requirements.txt --quiet
  echo "  Python deps OK"
fi

if [[ ! -d frontend/node_modules ]]; then
  echo "==> npm install (frontend)"
  (cd frontend && npm install)
fi

echo "==> Vite build"
(cd frontend && npm run build)

if [[ -f app/webui/index.html ]]; then
  echo "  Build OK: app/webui/index.html"
  ls -lh app/webui/ | head -n 20
else
  echo "Build xong nhung khong thay app/webui/index.html" >&2
  exit 1
fi

echo ""
echo "Chay thu production: ./scripts/run.sh"
