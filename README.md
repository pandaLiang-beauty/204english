# 英语复习

这是位于 `/root/english` 的独立、单用户英语复习工具。它只处理句子、重点词、阅读文章、翻译、音频、复习轮次和英语统计，不包含学科切换、通用题库、训练队列、聊天或多用户管理。

登录只保护公网入口和个人学习记录。界面只要求密码，内部固定使用唯一的 `admin` 账户。

## 设计

熟悉度来自实际使用：整句复习、整句播放、重点词播放和跨句上下文接触。核心复习流不要求逐句选择“忘记 / 模糊 / 掌握”；每轮顺序冻结，避免复习过程中频繁跳序。

```text
/root/english/
├── backend/app/platform/   # 本仓库的 SQLite、认证、安全和 AI HTTP 传输
├── backend/app/english/    # 英语业务、API、排序、翻译、文章和音频
├── backend/scripts/english/
├── frontend/src/platform/  # 登录、主题和 HTTP 基础设施
└── frontend/src/english/   # 英语导航、界面和交互状态
```

依赖方向是 `english -> platform`。不得导入其他仓库，不得建立外部软链接，也不得添加其他学科或系统切换器。

## 本地运行

运行身份固定为：

- 后端：`127.0.0.1:8103`
- 前端：`127.0.0.1:5103/english/`
- Cookie：`english_study_session`
- SQLite：`backend/data/study.db`
- systemd：`pro-study-platform-english-backend`、`pro-study-platform-english-frontend`

根据 `.env.example` 创建 gitignored 的 `.env.local`，至少设置 `STUDY_INITIAL_PASSWORD`。开发环境使用本地 HTTP，因此允许不安全 Cookie：

```bash
bash start-dev.sh
bash check-health.sh
bash stop-dev.sh
```

## 公网安全

公网部署必须使用 HTTPS、Secure Cookie 和登录失败限流。`deploy.sh` 会拒绝非本机的 HTTP `STUDY_PUBLIC_ORIGIN`，也会拒绝 HTTPS 配置下的 `STUDY_COOKIE_INSECURE=1`。

当前兼容入口 `http://193.112.97.187/english/` 的 443 端口尚未提供 TLS，因此不能视为安全的正式登录入口。应先在独立网关配置 HTTPS，再设置：

```dotenv
STUDY_PUBLIC_ORIGIN=https://your-domain.example
STUDY_ALLOWED_ORIGINS=https://your-domain.example
STUDY_COOKIE_INSECURE=0
STUDY_LOGIN_MAX_FAILURES=5
STUDY_LOGIN_WINDOW_SECONDS=600
```

网关属于外部部署边界；本仓库不依赖其代码即可在本机运行。

## 数据与备份

系统只支持 SQLite。新数据库只创建 `users`、`sessions` 和 `english_*` 表。旧数据库中已有的通用平台表可能继续保留为只读历史残留，但运行时代码不会创建或访问它们；清理前必须先备份。

媒体位于 `backend/data/english/`。使用 SQLite online backup 制作一致性备份：

```bash
bash backup-db.sh
```

部署与停止：

```bash
bash deploy.sh
bash stop-local.sh
```

首次安装 Kokoro 及 28 个英语音色：

```bash
STUDY_INSTALL_TTS=1 bash deploy.sh
```

## 项目记忆

`memory.md` 是维护入口，它按任务路由到 `memory/maps/`、`memory/domains/`、`memory/decisions/` 和生成证据。

```bash
cd backend
python3 scripts/generate_memory_evidence.py
python3 scripts/check_memory.py
```

## 验证

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
