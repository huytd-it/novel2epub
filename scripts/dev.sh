#!/usr/bin/env bash
# dev.sh — Dev mode: backend + Vite SPA
# Tu dong lay port tu .env hoac random
# Usage: ./scripts/dev.sh [--skip-install] [--port 8011] [--env-file .env]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PORT=""
SKIP_INSTALL=0
DB_PATH=""
ENV_FILE=".env"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-install) SKIP_INSTALL=1; shift ;;
    --port) PORT="$2"; shift 2 ;;
    --db) DB_PATH="$2"; shift 2 ;;
    --env-file) ENV_FILE="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

parse_env_file(){ local f="$1" k="$2"; [[ -f "$f" ]] || return 1; grep -E "^[[:space:]]*(export[[:space:]]+)?${k}[[:space:]]*=" "$f" 2>/dev/null | tail -n1 | sed -E "s/^[[:space:]]*(export[[:space:]]+)?${k}[[:space:]]*=[[:space:]]*//" | sed -E "s/^[\"']//;s/[\"'].*$//" | tr -d "\"'" | xargs 2>/dev/null || true; }
find_free_port(){ python3 -c "import socket,random,sys;h=sys.argv[1];p=int(sys.argv[2]);
def f(x):
 import socket as s
 s=socket.socket(s.AF_INET,s.SOCK_STREAM);s.settimeout(0.5)
 try:s.bind((h,x));s.close();return True
 except:return False
if p and f(p):print(p);sys.exit(0)
for _ in range(30):
 x=random.randint(8000,9500)
 if f(x):print(x);sys.exit(0)
import socket as sk;s=sk.socket(sk.AF_INET,sk.SOCK_STREAM);s.bind((h,0));print(s.getsockname()[1])" "$1" "$2" 2>/dev/null; }

# Resolve port
if [[ -z "$PORT" ]]; then
  for k in N2E_TRAY_PORT PORT N2E_PORT; do v="${!k:-}"; [[ -n "$v" ]] && PORT="$v" && break; done
  if [[ -z "$PORT" ]]; then
    for f in "$ENV_FILE" "$ROOT/.env" ".env"; do v=$(parse_env_file "$f" "N2E_TRAY_PORT" || true); [[ -n "$v" ]] && PORT="$v" && break; v=$(parse_env_file "$f" "PORT" || true); [[ -n "$v" ]] && PORT="$v" && break; done
  fi
  PORT="${PORT:-8011}"
fi
FREE=$(find_free_port "127.0.0.1" "$PORT" 2>/dev/null || echo "$PORT")
if [[ "$FREE" != "$PORT" ]]; then echo "  Port $PORT ban -> $FREE"; PORT="$FREE"; fi
echo "  Port: $PORT"

echo "==> Kiem tra Python & venv"
if [[ ! -f .venv/bin/python ]]; then echo "  .venv chua co — tao moi..."; python3 -m venv .venv; fi
PY=.venv/bin/python; $PY --version
if [[ $SKIP_INSTALL -eq 0 ]]; then
  echo "==> pip install"; $PY -m pip install --upgrade pip --quiet; $PY -m pip install -r requirements.txt; $PY -m scrapling install 2>/dev/null || echo "  scrapling skip"
else echo "  --skip-install"; fi

DB_FILE="${DB_PATH:-${NOVEL2EPUB_DB:-$ROOT/novel2epub.db}}"
if [[ ! -f "$DB_FILE" ]]; then echo "==> DB chua co — init $DB_FILE"; $PY scripts/init_db.py --db "$DB_FILE"; else echo "  DB: $DB_FILE"; fi

echo "==> Kiem tra frontend"
if [[ ! -d frontend/node_modules ]]; then
  if [[ $SKIP_INSTALL -eq 0 ]]; then (cd frontend && npm install); else echo "  thieu node_modules nhung --skip-install"; fi
else echo "  frontend/node_modules OK"; fi

echo "==> Dev — backend :$PORT + Vite :5183 (SPA only)"
echo "  Backend : http://127.0.0.1:$PORT"
echo "  SPA dev : http://localhost:5183/app/"
echo "  Bam Ctrl+C de dung"
if [[ "$PORT" != "8011" ]]; then export N2E_DEV_API_TARGET="http://127.0.0.1:$PORT"; fi
$PY -m uvicorn app.main:app --reload --port "$PORT" --host 127.0.0.1 &
BACK_PID=$!
trap 'kill $BACK_PID 2>/dev/null; wait $BACK_PID 2>/dev/null || true' EXIT INT TERM
sleep 2
(cd frontend && npm run dev)
