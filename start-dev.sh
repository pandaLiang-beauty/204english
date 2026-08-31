#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${STUDY_PROJECT_ROOT:-/root/sysStuByAI/204english}"
if [[ -f "$ROOT_DIR/.env.local" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env.local"
  set +a
fi
if [[ -f "$ROOT_DIR/.env.secrets.local" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env.secrets.local"
  set +a
fi

BACKEND_HOST="${STUDY_BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${STUDY_BACKEND_PORT:-8204}"
FRONTEND_HOST="${STUDY_FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${STUDY_FRONTEND_PORT:-5204}"
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
backend_pid=$!
# 原来这里用 ss -ltnp 反查 pid，但这台机器没装 ss（只有 netstat），于是永远查不到，
# 脚本会在这步报 "backend failed to start" 退出、前端根本起不来。改成直接用 $!（非交互
# shell 没有作业控制，setsid 不会再 fork，$! 就是真身），就绪与否交给 curl 探活。
# curl 必须带 --noproxy '*'：/root/.curlrc 里配的代理是坏的，否则一律返回 000。
for _ in $(seq 1 60); do
  curl --noproxy '*' -fs -o /dev/null "http://$BACKEND_HOST:$BACKEND_PORT/api/health" && break
  sleep 0.5
done
ps -p "$backend_pid" >/dev/null 2>&1 || { echo "backend failed to start（见 backend/server.log）" >&2; exit 1; }
echo "$backend_pid" > "$ROOT_DIR/backend/server.pid"

cd "$ROOT_DIR/frontend"
setsid npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" > server.log 2>&1 < /dev/null &
frontend_pid=$!
for _ in $(seq 1 60); do
  curl --noproxy '*' -fs -o /dev/null "http://$FRONTEND_HOST:$FRONTEND_PORT/" && break
  sleep 0.5
done
ps -p "$frontend_pid" >/dev/null 2>&1 || { echo "frontend failed to start（见 frontend/server.log）" >&2; exit 1; }
echo "$frontend_pid" > "$ROOT_DIR/frontend/server.pid"

echo "english: backend http://$BACKEND_HOST:$BACKEND_PORT, frontend http://$FRONTEND_HOST:$FRONTEND_PORT/"
