#!/usr/bin/env bash
set -euo pipefail

BACKEND_SERVICE="${STUDY_BACKEND_SERVICE_NAME:-pro-study-platform-english-backend}"
FRONTEND_SERVICE="${STUDY_FRONTEND_SERVICE_NAME:-pro-study-platform-english-frontend}"

systemctl stop "$FRONTEND_SERVICE" 2>/dev/null || true
systemctl stop "$BACKEND_SERVICE" 2>/dev/null || true
echo "stopped: $BACKEND_SERVICE, $FRONTEND_SERVICE"
