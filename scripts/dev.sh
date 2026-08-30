#!/usr/bin/env bash
# dev.sh — Dev mode: backend 8011 + Vite 5183
# Usage: ./scripts/dev.sh [--skip-install] [--port 8011]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PORT=8011
SKIP_INSTALL=0
DB_PATH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-install) SKIP_INSTALL=1; shift ;;
    --port) PORT="$2"; shift 2 ;;
    --db) DB_PATH="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

echo "==> Kiem tra Python & venv"
if [[ ! -f .venv/bin/python ]]; then
  echo "  .venv chua co — tao moi..."
  python3 -m venv .venv
fi
PY=.venv/bin/python
$PY --version

if [[ $SKIP_INSTALL -eq 0 ]]; then
  echo "==> pip install -r requirements.txt"
  $PY -m pip install --upgrade pip --quiet
  $PY -m pip install -r requirements.txt
  $PY -m scrapling install 2>/dev/null || echo "  scrapling install skip (offline?)"
else
  echo "  --skip-install — bo qua pip install"
fi

DB_FILE="${DB_PATH:-${NOVEL2EPUB_DB:-$ROOT/novel2epub.db}}"
if [[ ! -f "$DB_FILE" ]]; then
  echo "==> DB chua co — init $DB_FILE"
  $PY scripts/init_db.py --db "$DB_FILE"
else
  echo "  DB OK: $DB_FILE"
fi

echo "==> Kiem tra frontend deps"
if [[ ! -d frontend/node_modules ]]; then
  if [[ $SKIP_INSTALL -eq 0 ]]; then
    (cd frontend && npm install)
  else
    echo "  frontend/node_modules thieu nhung --skip-install — vite co the loi"
  fi
else
  echo "  frontend/node_modules OK"
fi

echo "==> Khoi dong DEV — backend :$PORT + Vite :5183"
echo "  Backend : http://127.0.0.1:$PORT"
echo "  Vite    : http://localhost:5183/app/"
echo "  Bam Ctrl+C de dung"

# Backend background, Vite foreground; Ctrl+C kill ca 2
if [[ "$PORT" != "8011" ]]; then
  export N2E_DEV_API_TARGET="http://127.0.0.1:$PORT"
fi
$PY -m uvicorn app.main:app --reload --port "$PORT" &
BACK_PID=$!
trap 'kill $BACK_PID 2>/dev/null; wait $BACK_PID 2>/dev/null || true' EXIT INT TERM
sleep 2
(cd frontend && npm run dev)
