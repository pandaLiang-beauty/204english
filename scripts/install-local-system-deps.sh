#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${STUDY_PROJECT_ROOT:-/root/english}"

need_command() {
  command -v "$1" >/dev/null 2>&1
}

install_with_yum() {
  yum --disablerepo='*' --enablerepo=os,updates,extras install -y "$@"
}

install_with_apt() {
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y "$@"
}

echo "Installing host dependencies for local deployment..."

if need_command yum; then
  packages=()
  need_command pdfinfo || packages+=(poppler-utils)
  need_command pdftotext || packages+=(poppler-utils)
  need_command pdftoppm || packages+=(poppler-utils)
  if ((${#packages[@]})); then
    install_with_yum "${packages[@]}"
  fi
elif need_command apt-get; then
  packages=()
  if ! need_command pdfinfo || ! need_command pdftotext || ! need_command pdftoppm; then
    packages+=(poppler-utils)
  fi
  if ((${#packages[@]})); then
    install_with_apt "${packages[@]}"
  fi
else
  echo "No supported package manager found. Install poppler-utils manually." >&2
  exit 1
fi

if [[ -x /root/miniconda3/bin/python3 ]]; then
  /root/miniconda3/bin/python3 - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 9) else 1)
PY
else
  python3 - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 9) else 1)
PY
fi

need_command node || {
  echo "Node.js is missing. Install Node.js 22 before running deploy.sh." >&2
  exit 1
}
need_command npm || {
  echo "npm is missing. Install Node.js 22/npm before running deploy.sh." >&2
  exit 1
}

echo "Host dependency check complete for $ROOT_DIR."
