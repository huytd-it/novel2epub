#!/usr/bin/env bash
# run.sh — Chay production SPA (uvicorn, 1 port cho ca API + WebUI)
# Tu dong lay port tu .env hoac random
# Usage: ./scripts/run.sh [--port 8010] [--host 127.0.0.1] [--no-build] [--reload] [--env-file .env]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PORT=""
HOST_ADDR=""
NO_BUILD=0
RELOAD=0
DB_PATH=""
ENV_FILE=".env"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --host) HOST_ADDR="$2"; shift 2 ;;
    --no-build) NO_BUILD=1; shift ;;
    --reload) RELOAD=1; shift ;;
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

# Resolve host/port tu .env
if [[ -z "$HOST_ADDR" ]]; then
  for k in N2E_TRAY_HOST HOST; do v="${!k:-}"; [[ -n "$v" ]] && HOST_ADDR="$v" && break; done
  if [[ -z "$HOST_ADDR" ]]; then for f in "$ENV_FILE" "$ROOT/.env" ".env"; do v=$(parse_env_file "$f" "N2E_TRAY_HOST" || true); [[ -n "$v" ]] && HOST_ADDR="$v" && break; v=$(parse_env_file "$f" "HOST" || true); [[ -n "$v" ]] && HOST_ADDR="$v" && break; done; fi
  HOST_ADDR="${HOST_ADDR:-127.0.0.1}"
fi
if [[ -z "$PORT" ]]; then
  for k in N2E_TRAY_PORT PORT N2E_PORT; do v="${!k:-}"; [[ -n "$v" ]] && PORT="$v" && break; done
  if [[ -z "$PORT" ]]; then for f in "$ENV_FILE" "$ROOT/.env" ".env"; do v=$(parse_env_file "$f" "N2E_TRAY_PORT" || true); [[ -n "$v" ]] && PORT="$v" && break; v=$(parse_env_file "$f" "PORT" || true); [[ -n "$v" ]] && PORT="$v" && break; done; fi
  if [[ -z "$PORT" ]]; then PORT=$(find_free_port "$HOST_ADDR" 0); [[ ! -f "$ROOT/.env" ]] && echo "N2E_TRAY_PORT=$PORT" > "$ROOT/.env" && echo "N2E_TRAY_HOST=$HOST_ADDR" >> "$ROOT/.env" && echo "  [OK] Da tao .env PORT=$PORT"; fi
else
  FREE=$(find_free_port "$HOST_ADDR" "$PORT" 2>/dev/null || echo "$PORT")
  if [[ "$FREE" != "$PORT" ]]; then echo "  Port $PORT ban -> $FREE"; PORT="$FREE"; fi
fi
# ban -> random
if [[ -n "$PORT" ]]; then FREE=$(find_free_port "$HOST_ADDR" "$PORT" 2>/dev/null || echo "$PORT"); [[ "$FREE" != "$PORT" ]] && echo "  Port $PORT ban -> $FREE" && PORT="$FREE"; fi
export N2E_TRAY_PORT="$PORT"; export N2E_TRAY_HOST="$HOST_ADDR"

PY=.venv/bin/python
if [[ ! -f "$PY" ]]; then echo ".venv chua co — tao moi"; python3 -m venv .venv; PY=.venv/bin/python; $PY -m pip install -r requirements.txt --quiet; fi

DB_FILE="${DB_PATH:-${NOVEL2EPUB_DB:-$ROOT/novel2epub.db}}"
if [[ ! -f "$DB_FILE" ]]; then echo "==> DB chua co — init $DB_FILE"; $PY scripts/init_db.py --db "$DB_FILE"; else echo "  [OK] DB: $DB_FILE"; fi

if [[ ! -f app/webui/index.html && $NO_BUILD -eq 0 ]]; then
  echo "  Chua co app/webui/index.html — build frontend..."
  [[ -d frontend/node_modules ]] || (cd frontend && npm install)
  (cd frontend && npm run build)
elif [[ ! -f app/webui/index.html ]]; then echo "  [!] Chua build frontend — SPA /app se 404"; else echo "  [OK] SPA bundle OK"; fi

echo "==> Production SPA — http://$HOST_ADDR:$PORT"
echo "  SPA  : http://$HOST_ADDR:$PORT/app/"
echo "  Docs : http://$HOST_ADDR:$PORT/docs"
echo "  .env : $ENV_FILE -> $PORT"

ARGS=(-m uvicorn app.main:app --host "$HOST_ADDR" --port "$PORT")
[[ $RELOAD -eq 1 ]] && ARGS+=(--reload)
exec $PY "${ARGS[@]}"
