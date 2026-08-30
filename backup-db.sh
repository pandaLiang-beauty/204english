#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${STUDY_PROJECT_ROOT:-/root/english}"
cd "$ROOT_DIR"

if [[ -f "$ROOT_DIR/.env.local" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env.local"
  set +a
fi

python_bin="$ROOT_DIR/backend/.venv/bin/python"
if [[ ! -x "$python_bin" ]]; then
  if [[ -x /root/miniconda3/bin/python3 ]]; then
    python_bin=/root/miniconda3/bin/python3
  else
    python_bin="$(command -v python3)"
  fi
fi

cd "$ROOT_DIR/backend"
"$python_bin" - <<'PY'
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from app.platform.db import DB_PATH

stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
backup_path = DB_PATH.with_name(f"study.manual-backup-{stamp}.db")

source = sqlite3.connect(DB_PATH)
try:
    target = sqlite3.connect(backup_path)
    try:
        source.backup(target)
    finally:
        target.close()
finally:
    source.close()

print(backup_path)
PY
