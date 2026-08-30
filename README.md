# 英语复习

这是位于 `/root/sysStuByAI/204english` 的单用户英语复习工具。简短架构说明见 [`docs/architecture.md`](docs/architecture.md)。

## 安装

需要 Python 3.9+、Node.js 22 和 npm。复制配置并设置初始密码：

```bash
cp .env.example .env.local
# 编辑 .env.local，至少设置 STUDY_INITIAL_PASSWORD
bash check-env.sh
```

本机部署会创建 Python 虚拟环境、安装依赖、构建前端并启动 systemd 服务：

```bash
bash deploy.sh
```

需要本地语音模型时，在部署时设置 `STUDY_INSTALL_TTS=1`。

## 运行

开发运行：

```bash
bash start-dev.sh
bash check-health.sh
```

打开 `http://127.0.0.1:5204/`。停止开发服务：

```bash
bash stop-dev.sh
```

已部署的 systemd 服务停止命令：

```bash
bash stop-local.sh
```

## 备份

数据库使用 SQLite online backup：

```bash
bash backup-db.sh
```

命令会在 `backend/data/` 生成带时间戳的 `study.manual-backup-*.db`。音频和其他媒体位于 `backend/data/english/`，需要另外备份：

```bash
tar -czf /path/to/english-media-backup.tar.gz -C backend/data english
```

## 恢复

先停止对应服务，再恢复数据库和媒体：

```bash
bash stop-local.sh                 # 开发环境改用 bash stop-dev.sh
cp /path/to/study.manual-backup.db backend/data/study.db
tar -xzf /path/to/english-media-backup.tar.gz -C backend/data
```

恢复完成后重新运行 `bash deploy.sh` 或 `bash start-dev.sh`。
