---
memory_level: 1
scope: maps.operations
load_policy: task-routed-and-before-completion
load_when:
  - environment, dependencies, scripts or health checks
  - build, verification, TTS, backup or deployment
  - final verification after code or runtime configuration changes
sources:
  - .env.example
  - README.md
  - backend/requirements.txt
  - backend/tts-requirements.txt
  - frontend/package.json
  - start-dev.sh
  - stop-dev.sh
  - check-env.sh
  - backup-db.sh
  - deploy.sh
  - backend/scripts/reliability_check.py
  - backend/scripts/check_memory.py
  - backend/scripts/generate_memory_evidence.py
source_fingerprint: 08a8c260293d35c9ab1736d0d8cf7a45f8c387de9da793584750391cac70a74f
---

# Operations Map

## 本地运行

```bash
bash start-dev.sh
bash check-health.sh
bash stop-dev.sh
```

`start-dev.sh` 按需创建 `backend/.venv`、安装依赖并启动 Uvicorn `8103` 与 Vite `5103`。健康端点是 `http://127.0.0.1:8103/api/health`，前端入口是 `http://127.0.0.1:5103/english/`。

环境变量全集及引用位置见 [配置证据](../evidence/config-map.md)。

本地 HTTP 设置 `STUDY_COOKIE_INSECURE=1`；公网必须是 HTTPS、Secure Cookie 和非零登录限流。`deploy.sh` 主动拒绝非本机 HTTP origin 和 HTTPS 下的不安全 Cookie。当前 IP 网关的 443 端口未提供 TLS，升级网关前不能作为安全正式入口。

## 数据、TTS 与部署

- `bash backup-db.sh` 使用 SQLite online backup API。
- 常规语音使用 Edge TTS；Kokoro 额外依赖在 `backend/tts-requirements.txt`。
- `bash deploy.sh` 构建前后端并更新两个本仓库 systemd 服务；生产前端由 `scripts/local_frontend_proxy.py` 托管并反代 `/api`。
- 公共网关是外部边界，本仓库能在没有网关代码时独立运行。

音频细节见 [音频](../domains/audio.md)，数据库与备份理由见 [SQLite 决策](../decisions/0002-sqlite-only.md)。

## Memory 维护

API、Schema 或配置变化后运行：

```bash
cd backend
python3 scripts/generate_memory_evidence.py
python3 scripts/check_memory.py
```

人工档案复核完成后才使用 `python3 scripts/check_memory.py --refresh-fingerprints`。

## 完整验证

```bash
(cd backend && python3 -m compileall -q app scripts)
(cd backend && python3 scripts/check_module_boundaries.py)
(cd backend && python3 scripts/check_memory.py)
(cd frontend && npm test)
(cd frontend && npm run build)
(cd backend && .venv/bin/python scripts/reliability_check.py)
git diff --check
curl -fsS http://127.0.0.1:8103/api/health
```
