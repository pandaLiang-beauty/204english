#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${STUDY_PROJECT_ROOT:-/root/sysStuByAI/204english}"

if [[ -f "$ROOT_DIR/.env.local" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env.local"
  set +a
fi

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

missing=0
warn=0

ok() {
  echo -e "${GREEN}✓ $1${NC}"
}

warning() {
  echo -e "${YELLOW}⚠ $1${NC}"
  warn=1
}

bad() {
  echo -e "${RED}✗ $1${NC}"
  missing=1
}

select_python() {
  if [[ -n "${STUDY_PYTHON:-}" ]]; then
    echo "$STUDY_PYTHON"
    return
  fi
  if [[ -x /root/miniconda3/bin/python3 ]]; then
    echo /root/miniconda3/bin/python3
    return
  fi
  command -v python3 || true
}

echo "检查本机部署环境..."

python_bin="$(select_python)"
if [[ -n "$python_bin" ]] && "$python_bin" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 9) else 1)
PY
then
  ok "Python 可用: $("$python_bin" --version 2>&1)"
else
  bad "Python 不可用或版本低于 3.9。CentOS 7 系统 Python 3.6 不能运行本项目。"
fi

if command -v npm >/dev/null 2>&1; then
  ok "npm 可用: $(npm --version)"
else
  bad "npm 不存在，需要 Node.js 22/npm。"
fi

if command -v node >/dev/null 2>&1; then
  ok "Node 可用: $(node --version)"
else
  bad "node 不存在，需要 Node.js 22。"
fi

if command -v nginx >/dev/null 2>&1; then
  ok "nginx 可用（可选）"
else
  ok "nginx 未安装；将使用本机 Python 前端服务托管静态文件并反代 /api/"
fi

if command -v pdfinfo >/dev/null 2>&1 && command -v pdftotext >/dev/null 2>&1 && command -v pdftoppm >/dev/null 2>&1; then
  ok "poppler PDF 工具可用"
else
    warning "poppler-utils 未完整安装；英语文章 PDF 导入需要 pdfinfo/pdftotext/pdftoppm。"
fi

if [[ -f "$ROOT_DIR/.env.local" ]]; then
  ok ".env.local 存在"
else
  warning ".env.local 不存在；AI、公网 Origin、初始密码等需要通过环境变量提供。"
fi

ok "数据库模式: SQLite (backend/data/study.db)"

public_origin="${STUDY_PUBLIC_ORIGIN:-}"
if [[ "$public_origin" == http://* && "$public_origin" != http://127.0.0.1:* && "$public_origin" != http://localhost:* ]]; then
  bad "公网 STUDY_PUBLIC_ORIGIN 必须使用 HTTPS。"
fi

for var in STUDY_AI_BASE_URL STUDY_AI_API_KEY STUDY_AI_MODEL STUDY_INITIAL_PASSWORD; do
  if [[ -n "${!var:-}" ]]; then
    ok "$var 已设置"
  else
    warning "$var 未设置"
  fi
done

echo ""
if [[ "$missing" -eq 1 ]]; then
  echo -e "${RED}本机部署环境检查失败。${NC}"
  exit 1
fi
if [[ "$warn" -eq 1 ]]; then
  echo -e "${YELLOW}本机部署环境可继续，但存在警告。${NC}"
else
  echo -e "${GREEN}本机部署环境检查通过。${NC}"
fi
