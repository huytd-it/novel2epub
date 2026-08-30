#!/usr/bin/env bash
# run.sh — Chay production (uvicorn 8010, phuc vu SPA + Jinja2)
# Usage: ./scripts/run.sh [--port 8010] [--host 127.0.0.1] [--no-build] [--reload]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PORT=8010
HOST_ADDR=127.0.0.1
NO_BUILD=0
RELOAD=0
DB_PATH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --host) HOST_ADDR="$2"; shift 2 ;;
    --no-build) NO_BUILD=1; shift ;;
    --reload) RELOAD=1; shift ;;
    --db) DB_PATH="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

PY=.venv/bin/python
if [[ ! -f "$PY" ]]; then
  echo ".venv chua co — tao moi + pip install" >&2
  python3 -m venv .venv
  PY=.venv/bin/python
  $PY -m pip install -r requirements.txt
fi

DB_FILE="${DB_PATH:-${NOVEL2EPUB_DB:-$ROOT/novel2epub.db}}"
if [[ ! -f "$DB_FILE" ]]; then
  echo "==> DB chua co — init $DB_FILE"
  $PY scripts/init_db.py --db "$DB_FILE"
else
  echo "  DB: $DB_FILE"
fi

if [[ ! -f app/webui/index.html && $NO_BUILD -eq 0 ]]; then
  echo "  Chua co app/webui/index.html — build frontend..."
  [[ -d frontend/node_modules ]] || (cd frontend && npm install)
  (cd frontend && npm run build)
elif [[ ! -f app/webui/index.html ]]; then
  echo "  Canh bao: chua build frontend — SPA /app se 404"
else
  echo "  SPA bundle: app/webui/index.html OK"
fi

echo "==> Khoi dong production — http://$HOST_ADDR:$PORT"
echo "  SPA  : http://$HOST_ADDR:$PORT/app/"
echo "  Jinja: http://$HOST_ADDR:$PORT/"
echo "  Docs : http://$HOST_ADDR:$PORT/docs"

ARGS=(-m uvicorn app.main:app --host "$HOST_ADDR" --port "$PORT")
[[ $RELOAD -eq 1 ]] && ARGS+=(--reload)
exec $PY "${ARGS[@]}"
