---
memory_level: 3
scope: decisions.sqlite-only
load_policy: rationale-only
load_when:
  - schema or SQL changes
  - SQLite transactions, migration or backup behavior
  - considering another database driver
sources:
  - backend/app/platform/db.py
  - backend/app/english/schema.py
  - backend/requirements.txt
  - backup-db.sh
  - deploy.sh
  - backend/scripts/platform/reliability_check.py
source_fingerprint: 3ffb7964ce8a5b1f056dfc201f7c7f83ce087aad9e6a11767d0b51f8f3aa69b5
---

# Decision 0002: SQLite Only

## Status

Accepted. Supersedes the earlier optional PostgreSQL design on 2026-08-11.

## Context

系统服务一个学习者，当前语料和数据库规模很小。双数据库支持带来了连接池、SQL 翻译、两份 schema、额外依赖、备份分支和测试矩阵，却没有实际部署收益。

## Decision

SQLite `backend/data/study.db` 是唯一数据库。Platform connection layer 启用 foreign keys、WAL、busy timeout 与 normal synchronous。业务 SQL 直接使用 SQLite 参数和事务语义；关键 read-modify-write 在读取前执行 `BEGIN IMMEDIATE`。

Platform 只创建 `users` 和 `sessions`，English 创建全部 `english_*` 活动表。新安装不创建通用题库、训练、作答、计时或 review card schema。

旧数据库里的历史平台表暂不自动 DROP。它们不再被运行时代码访问，物理清理必须作为显式、已备份的维护动作。

## Consequences

- 删除 psycopg、连接池、placeholder 翻译、PostgreSQL schema 和 `STUDY_DATABASE_URL`。
- `backup-db.sh` 只使用 SQLite online backup API。
- 并发正确性以 SQLite 单写者模型验证；可靠性检查用多线程请求证明 JSON 计数不丢失。
- 若未来确有另一数据库需求，必须以新的明确决策、迁移方案和真实负载证据重新引入，不能悄悄恢复兼容分支。
