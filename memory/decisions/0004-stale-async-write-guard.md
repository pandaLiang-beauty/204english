---
memory_level: 3
scope: decisions.stale-async-write-guard
load_policy: rationale-only
load_when:
  - changing background translation or write-back SQL
  - adding asynchronous enrichment to editable records
  - debugging translation overwritten after an edit
sources:
  - backend/app/english/api.py
  - backend/app/english/repository.py
  - backend/app/english/translation_generation.py
  - frontend/src/english/useEnglishSentenceList.js
  - backend/scripts/english/reliability_check.py
source_fingerprint: cb474940cbb95a0db654a4f4f56867da560170d7d97d6ec1408b7c4804aa8076
---

# Decision 0004: Guard Asynchronous Write-Back With Source Identity

## Status

Accepted.

## Context

句子创建或编辑提交后，翻译在后台继续执行。用户可能在模型返回前再次修改原文；如果任务只凭 sentence id 写回，旧翻译会覆盖新内容，并可能把旧重点词重新带回记录。

## Decision

API 排队时把 sentence id 与当时的完整 `text` 一起传给后台任务。任务执行前检查当前原文；最终写回先取得 SQLite immediate write transaction，再读取当前正文和重点词，并以 `id + expected_text + not deleted` 更新。这样同时避免旧正文写回和 SELECT/UPDATE 之间的 map 丢更新。

浏览器显式翻译在发请求前快照完整 draft。响应返回时只有 draft 仍与快照相同才应用结果；用户在等待期间改正文、翻译、分块或重点词都会让旧结果被忽略。

写回采用 merge-missing：已有用户内容优先，只补空字段；重点词结果限制在当前允许集合内。原文修改时 repository 主动清除没有被用户同步修改的旧翻译和分块，使新任务可以重新补齐。

## Consequences

- 后台任务允许静默放弃过期结果，这是正确行为，不应重试旧 payload。
- 用户明确编辑的翻译不能被自动补全覆盖。
- 后端 expected text 与前端 draft revision 是两道独立保护，不能用其中一道替代另一道。
- 新增任何针对可编辑实体的异步 enrich 流程，都应携带稳定 source identity 或 revision，并在最终写入条件中验证，而不只在任务开始时验证。
- Reliability 必须同时证明错误 expected text 不写入、正确 expected text 能写入、过期重点词不会回流。
