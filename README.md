# 英语复习

这是位于 `/root/sysStuByAI/204english` 的单用户英语复习工具。简短架构说明见 [`docs/architecture.md`](docs/architecture.md)。

## 安装

需要 Python 3.9+、Node.js 22 和 npm。复制配置并设置初始密码：

```bash
cp .env.example .env.local
# 编辑 .env.local，至少设置 STUDY_INITIAL_PASSWORD
cp .env.secrets.example .env.secrets.local
# 编辑 .env.secrets.local，填写英语 AI 网关、模型和密钥
bash check-env.sh
```

英语翻译 AI 只有一个配置来源：`.env.secrets.local`。它在 `.env.local` 之后加载，
其中的 `STUDY_ENGLISH_AI_BASE_URL`、`STUDY_ENGLISH_AI_MODEL` 和密钥必须成组维护；
不要再设置旧的 `STUDY_AI_*`，也不要在 `.env.local` 重复设置英语 AI 变量。

`BASE_URL` 填到 `/v1`，不要包含 `/chat/completions`。请求频率用
`STUDY_ENGLISH_AI_REQUESTS_PER_MINUTE` 控制（0 表示不主动节流）；对于每分钟最多
20 次请求的网关，建议设为 18。`STUDY_ENGLISH_AI_MAX_RETRIES` 为瞬态错误重试次数，
默认 2，允许 0—3；鉴权、模型不存在等错误不自动重试。节流在同一后端进程的所有
翻译线程间共享。不要同时用相同密钥运行多个满速评测进程。

本机部署会创建 Python 虚拟环境、安装依赖、构建前端并启动 systemd 服务：

```bash
bash deploy.sh
```

需要本地语音模型时，在部署时设置 `STUDY_INSTALL_TTS=1`。

## 翻译质量评测

翻译先生成语义要点和初稿，再独立终审；终审失败不会冒充已完成。
对于已复现错误的复杂并列结构，终审从英文结构独立重译，不照着有问题的草稿替换词语。
词卡读取中文定稿，其英文、中文证据必须能在输入中找到。少量明确的短语用法由本地参考表约束，避免将
`slot` 单独教成“老虎机”。分块通过双语原文短语定位切点，由程序截取文本，不让模型
数 token 或改写分块译文；没有安全对齐边界时保留整句一块。
引文不合格时只重做对应词卡，最多修复两次，不反复改写已经正确的词卡。
词卡区分单词、固定短语、邻接修饰语与否定范围；例如 `sustainable` 在否定句中
仍表示“可持续的”，不能因为整句是否定就反向解释该词。

从项目根目录运行可复现的随机只读评测：

```bash
(
  set -a
  source .env.local
  source .env.secrets.local
  set +a
  cd backend
  .venv/bin/python scripts/english/evaluate_translation_pipeline.py \
    --sample-size 100 --seed 20260907 --workers 2 --retries 0
)
```

报告位于 `backend/data/audits/`，包含样本 ID、随机种子、模型和代码指纹、译文、词卡、
双语分块及失败候选。脚本不会将候选写入学习数据库。`success` 只表示调用及本地
校验成功，不证明没有语义错误；仍需对照原文人工复核，不能把旧译文或模型自评分
当作标准答案。修改流水线后应创建新报告，避免混合不同版本的结果。

本次模型切换及逐句复核结果见 [DeepSeek Flash 翻译实测记录](docs/translation-flash-evaluation.md)。

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
