#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${STUDY_PROJECT_ROOT:-/root/sysStuByAI/204english}"
BACKEND_HOST="${STUDY_BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${STUDY_BACKEND_PORT:-8103}"
FRONTEND_HOST="${STUDY_FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${STUDY_FRONTEND_PORT:-5103}"
PUBLIC_BASE_PATH="${STUDY_PUBLIC_BASE_PATH:-/english}"
BACKEND_SERVICE="${STUDY_BACKEND_SERVICE_NAME:-pro-study-platform-english-backend}"
FRONTEND_SERVICE="${STUDY_FRONTEND_SERVICE_NAME:-pro-study-platform-english-frontend}"
BACKEND_SERVICE_PATH="${STUDY_BACKEND_SERVICE_PATH:-/etc/systemd/system/$BACKEND_SERVICE.service}"
FRONTEND_SERVICE_PATH="${STUDY_FRONTEND_SERVICE_PATH:-/etc/systemd/system/$FRONTEND_SERVICE.service}"

if [[ -f "$ROOT_DIR/.env.local" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env.local"
  set +a
fi

BACKEND_HOST="${STUDY_BACKEND_HOST:-$BACKEND_HOST}"
BACKEND_PORT="${STUDY_BACKEND_PORT:-$BACKEND_PORT}"
FRONTEND_HOST="${STUDY_FRONTEND_HOST:-$FRONTEND_HOST}"
FRONTEND_PORT="${STUDY_FRONTEND_PORT:-$FRONTEND_PORT}"
PUBLIC_BASE_PATH="${STUDY_PUBLIC_BASE_PATH:-$PUBLIC_BASE_PATH}"
PUBLIC_ORIGIN="${STUDY_PUBLIC_ORIGIN:-http://$FRONTEND_HOST:$FRONTEND_PORT}"
if [[ "$PUBLIC_ORIGIN" == https://* ]]; then
  COOKIE_INSECURE="${STUDY_COOKIE_INSECURE:-0}"
else
  COOKIE_INSECURE="${STUDY_COOKIE_INSECURE:-1}"
fi
if [[ "$PUBLIC_ORIGIN" == http://* && "$PUBLIC_ORIGIN" != http://127.0.0.1:* && "$PUBLIC_ORIGIN" != http://localhost:* ]]; then
  echo "public STUDY_PUBLIC_ORIGIN must use HTTPS: $PUBLIC_ORIGIN" >&2
  exit 1
fi
if [[ "$PUBLIC_ORIGIN" == https://* && "$COOKIE_INSECURE" == "1" ]]; then
  echo "STUDY_COOKIE_INSECURE must be 0 for an HTTPS deployment" >&2
  exit 1
fi
export STUDY_BACKEND_HOST="$BACKEND_HOST"
export STUDY_BACKEND_PORT="$BACKEND_PORT"
export STUDY_FRONTEND_HOST="$FRONTEND_HOST"
export STUDY_FRONTEND_PORT="$FRONTEND_PORT"
export STUDY_PUBLIC_ORIGIN="$PUBLIC_ORIGIN"
export STUDY_ALLOWED_ORIGINS="${STUDY_ALLOWED_ORIGINS:-$PUBLIC_ORIGIN}"
export STUDY_COOKIE_INSECURE="$COOKIE_INSECURE"
export STUDY_LOCAL_BACKEND="http://$BACKEND_HOST:$BACKEND_PORT"

select_python() {
  if [[ -n "${STUDY_PYTHON:-}" ]]; then
    echo "$STUDY_PYTHON"
  elif [[ -x /root/miniconda3/bin/python3 ]]; then
    echo /root/miniconda3/bin/python3
  else
    command -v python3
  fi
}

[[ -d "$ROOT_DIR/backend/app" && -d "$ROOT_DIR/frontend/src" ]] || {
  echo "incomplete project: $ROOT_DIR" >&2
  exit 1
}

cd "$ROOT_DIR/backend"
"$(select_python)" -m compileall -q app scripts
if [[ ! -x .venv/bin/python ]]; then
  "$(select_python)" -m venv .venv
fi
.venv/bin/python -m pip install -q --upgrade pip wheel
.venv/bin/pip install -q -r requirements.txt
if [[ "${STUDY_INSTALL_TTS:-0}" == "1" && -f tts-requirements.txt ]]; then
  .venv/bin/pip install -q -r tts-requirements.txt
  .venv/bin/python scripts/english/install_english_kokoro_voices.py
fi

cd "$ROOT_DIR/frontend"
npm ci
npm run build

cat > "$BACKEND_SERVICE_PATH" <<EOF
[Unit]
Description=Pro Study English Backend
After=network.target

[Service]
Type=simple
WorkingDirectory=$ROOT_DIR/backend
EnvironmentFile=-$ROOT_DIR/.env.local
Environment=PYTHONUNBUFFERED=1
Environment=STUDY_BACKEND_HOST=$BACKEND_HOST
Environment=STUDY_BACKEND_PORT=$BACKEND_PORT
Environment=STUDY_FRONTEND_PORT=$FRONTEND_PORT
Environment=STUDY_PUBLIC_ORIGIN=$PUBLIC_ORIGIN
Environment=STUDY_ALLOWED_ORIGINS=${STUDY_ALLOWED_ORIGINS}
Environment=STUDY_COOKIE_INSECURE=${STUDY_COOKIE_INSECURE}
Environment=STUDY_SESSION_COOKIE=${STUDY_SESSION_COOKIE:-english_study_session}
ExecStart=$ROOT_DIR/backend/.venv/bin/python -m uvicorn app.main:app --host $BACKEND_HOST --port $BACKEND_PORT
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

cat > "$FRONTEND_SERVICE_PATH" <<EOF
[Unit]
Description=Pro Study English Frontend
After=$BACKEND_SERVICE.service
Wants=$BACKEND_SERVICE.service

[Service]
Type=simple
WorkingDirectory=$ROOT_DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=$ROOT_DIR/backend/.venv/bin/python $ROOT_DIR/scripts/local_frontend_proxy.py --root $ROOT_DIR/frontend/dist --backend http://$BACKEND_HOST:$BACKEND_PORT --host $FRONTEND_HOST --port $FRONTEND_PORT --base-path $PUBLIC_BASE_PATH
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$BACKEND_SERVICE" "$FRONTEND_SERVICE" >/dev/null
systemctl restart "$BACKEND_SERVICE"
systemctl restart "$FRONTEND_SERVICE"

for _ in $(seq 1 30); do
  curl -fsS "http://$BACKEND_HOST:$BACKEND_PORT/api/health" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS "http://$BACKEND_HOST:$BACKEND_PORT/api/health"
printf '\n'
curl -fsS "http://$FRONTEND_HOST:$FRONTEND_PORT/api/health"
printf '\n'
echo "deployed english: http://$FRONTEND_HOST:$FRONTEND_PORT$PUBLIC_BASE_PATH/ (gateway: $PUBLIC_ORIGIN$PUBLIC_BASE_PATH/)"
