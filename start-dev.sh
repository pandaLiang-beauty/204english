#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${STUDY_PROJECT_ROOT:-/root/english}"
if [[ -f "$ROOT_DIR/.env.local" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env.local"
  set +a
fi

BACKEND_HOST="${STUDY_BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${STUDY_BACKEND_PORT:-8103}"
FRONTEND_HOST="${STUDY_FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${STUDY_FRONTEND_PORT:-5103}"
export STUDY_BACKEND_HOST="$BACKEND_HOST"
export STUDY_BACKEND_PORT="$BACKEND_PORT"
export STUDY_FRONTEND_HOST="$FRONTEND_HOST"
export STUDY_FRONTEND_PORT="$FRONTEND_PORT"
export STUDY_LOCAL_BACKEND="${STUDY_LOCAL_BACKEND:-http://$BACKEND_HOST:$BACKEND_PORT}"
export STUDY_PUBLIC_ORIGIN="${STUDY_PUBLIC_ORIGIN:-http://$FRONTEND_HOST:$FRONTEND_PORT}"
export STUDY_ALLOWED_ORIGINS="${STUDY_ALLOWED_ORIGINS:-$STUDY_PUBLIC_ORIGIN}"
export STUDY_COOKIE_INSECURE="${STUDY_COOKIE_INSECURE:-1}"

select_python() {
  if [[ -n "${STUDY_PYTHON:-}" ]]; then
    echo "$STUDY_PYTHON"
  elif [[ -x /root/miniconda3/bin/python3 ]]; then
    echo /root/miniconda3/bin/python3
  else
    command -v python3
  fi
}

if [[ ! -x "$ROOT_DIR/backend/.venv/bin/python" ]]; then
  "$(select_python)" -m venv "$ROOT_DIR/backend/.venv"
  "$ROOT_DIR/backend/.venv/bin/python" -m pip install -q --upgrade pip wheel
  "$ROOT_DIR/backend/.venv/bin/pip" install -q -r "$ROOT_DIR/backend/requirements.txt"
fi
if [[ ! -d "$ROOT_DIR/frontend/node_modules" ]]; then
  (cd "$ROOT_DIR/frontend" && npm ci)
fi

cd "$ROOT_DIR/backend"
setsid .venv/bin/python -m uvicorn app.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" > server.log 2>&1 < /dev/null &
for _ in $(seq 1 40); do
  backend_pid="$(ss -ltnp 2>/dev/null | awk -v addr="$BACKEND_HOST:$BACKEND_PORT" 'index($0, addr) && match($0, /pid=[0-9]+/) { print substr($0, RSTART + 4, RLENGTH - 4); exit }')"
  [[ -n "$backend_pid" ]] && break
  sleep 0.25
done
[[ -n "${backend_pid:-}" ]] || { echo "backend failed to start" >&2; exit 1; }
echo "$backend_pid" > "$ROOT_DIR/backend/server.pid"

cd "$ROOT_DIR/frontend"
setsid npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" > server.log 2>&1 < /dev/null &
for _ in $(seq 1 40); do
  frontend_pid="$(ss -ltnp 2>/dev/null | awk -v addr="$FRONTEND_HOST:$FRONTEND_PORT" 'index($0, addr) && match($0, /pid=[0-9]+/) { print substr($0, RSTART + 4, RLENGTH - 4); exit }')"
  [[ -n "$frontend_pid" ]] && break
  sleep 0.25
done
[[ -n "${frontend_pid:-}" ]] || { echo "frontend failed to start" >&2; exit 1; }
echo "$frontend_pid" > "$ROOT_DIR/frontend/server.pid"

echo "english: backend http://$BACKEND_HOST:$BACKEND_PORT, frontend http://$FRONTEND_HOST:$FRONTEND_PORT/english/"
