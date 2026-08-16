---
memory_level: 1
scope: maps.data
load_policy: task-routed
load_when:
  - schema, SQL, migrations or indexes
  - SQLite behavior, persistence ownership or transactions
  - data backup or legacy table cleanup
sources:
  - backend/app/platform/db.py
  - backend/app/english/schema.py
  - backend/app/english/repository.py
  - backend/app/english/passages.py
  - backend/app/english/stats.py
source_fingerprint: 622d0e5020d51303d85d97527706c010a6f06e3e9c6288b2b7f0d4e1dccbf3f8
---

# Data Map

## SQLite 合同

`backend/app/platform/db.py` 是唯一连接层，数据库固定为 `backend/data/study.db`。连接启用 foreign keys、WAL、30 秒 busy timeout 和 normal synchronous；关键 read-modify-write 流程先 `BEGIN IMMEDIATE`，避免单写者模型下丢更新。

系统不支持 PostgreSQL，不维护 placeholder 翻译、连接池、双方言 schema 或 `STUDY_DATABASE_URL`。

## Schema 所有权

- Platform 只创建 `users`、`sessions`。
- English schema 位于 `backend/app/english/schema.py`，业务表使用 `english_` 前缀。
- Schema 初始化后，English repository 运行幂等一致性修复：清理非当前加粗词 map，并补齐或重新排队旧音频 metadata。
- 新安装不创建题目、视频、训练、作答、活动计时或 review card 表。
- 升级后的旧 SQLite 文件可能仍保留上述历史表；运行时代码不读取或写入它们。物理清理前必须先用 online backup 备份。

精确活动 schema 见 [Schema 证据](../evidence/schema-map.md)。

## 领域数据路由

| 表或状态 | 所有者 |
| --- | --- |
| `english_sentences` 及翻译 JSON | [句子与翻译](../domains/sentences-translation.md) |
| review events、rounds、items | [复习与排序](../domains/review-ranking.md) |
| `english_passages` | [文章训练](../domains/passages.md) |
| `english_audio_settings` 与句子音频字段 | [音频](../domains/audio.md) |
| `users`、`sessions` | [认证](../domains/auth.md) |

## 修改守则

- Schema 变化必须同步更新基础定义、旧库幂等升级、生成证据和临时库可靠性检查。
- 带 `user_id` 的查询必须使用当前登录用户；这是个人数据边界，不是多租户需求。
- JSON TEXT 字段经集中 helper 解析和规范化，不在 API 或前端拼 SQL 表示。
- 软删除记录默认不得进入有效列表、排序、今日任务和复习轮次。
- 迁移前先备份；不要直接复制运行中的 SQLite 文件。
