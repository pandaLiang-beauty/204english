#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${STUDY_PROJECT_ROOT:-/root/english}"
BACKEND_PORT="${STUDY_BACKEND_PORT:-8103}"
FRONTEND_PORT="${STUDY_FRONTEND_PORT:-5103}"

for pid_file in "$ROOT_DIR/backend/server.pid" "$ROOT_DIR/frontend/server.pid"; do
  if [[ -s "$pid_file" ]]; then
    pid="$(tr -cd '0-9' < "$pid_file")"
    if [[ -n "$pid" ]] && ps -p "$pid" >/dev/null 2>&1; then
      kill "$pid"
      echo "stopped $pid"
    fi
    rm -f "$pid_file"
  fi
done

pkill -f "[.]venv/bin/python -m uvicorn app.main:app --host .* --port $BACKEND_PORT" 2>/dev/null || true
pkill -f "[v]ite .*--port $FRONTEND_PORT" 2>/dev/null || true
