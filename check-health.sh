#!/usr/bin/env bash
set -euo pipefail

BACKEND_HOST="${STUDY_BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${STUDY_BACKEND_PORT:-8103}"
FRONTEND_HOST="${STUDY_FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${STUDY_FRONTEND_PORT:-5103}"

curl --retry 3 --retry-delay 1 -fsS "http://$BACKEND_HOST:$BACKEND_PORT/api/health"
printf '\n'
curl --retry 3 --retry-delay 1 -fsS "http://$FRONTEND_HOST:$FRONTEND_PORT/api/health"
printf '\n'
