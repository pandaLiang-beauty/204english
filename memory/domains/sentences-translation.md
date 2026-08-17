---
memory_level: 2
scope: domains.sentences-translation
load_policy: feature-routed
load_when:
  - sentence create, edit, delete, bulk import or focus words
  - AI translation, segments, quality checks or translation repair
sources:
  - backend/app/english/api.py
  - backend/app/english/repository.py
  - backend/app/english/translator.py
  - backend/app/english/translation_generation.py
  - backend/app/english/translation_quality.py
  - backend/app/platform/ai_transport.py
  - frontend/src/english/useEnglishSentenceList.js
  - frontend/src/english/SentenceEditor.vue
  - backend/scripts/english/reliability_check.py
source_fingerprint: 24323eeaf20c4483221368db6e09603f83d6086ef427ec202de142c89d26e209
---

# Sentences And Translation

## 职责与表示

句子库以 `english_sentences` 为核心。`text` 用 Markdown `**word**` 标记重点词；翻译、提示、播放次数和双语分块存为 JSON TEXT。序列化集中在 `repository.serialize_sentence`。

句子身份由去除加粗、统一引号/空白并 casefold 后的文本决定。有效身份唯一；创建和批量导入遇到同身份时复用记录并合并重点词，编辑冲突返回 409。

创建和更新都拒绝 trim 后为空的正文；软删除记录不能再通过更新接口恢复或改写。单词播放事件只接受当前句子实际加粗的重点词，避免累计和事件事实被任意 URL 参数污染。

## 写入数据流

```text
API payload
  -> coherent focus state
  -> create/update/reuse english_sentences
  -> response serialize_sentence
  -> background: missing translation + word audio + sentence audio
```

删除是软删除。原文变化且用户没有同步改翻译时，旧整句翻译和分块清空；重点词 map 只保留仍存在的当前加粗词。启动一致性修复会清理升级前遗留的非加粗 key、tip 和播放计数。

关键 read-modify-write 使用 SQLite `BEGIN IMMEDIATE`，避免重点词 map、播放计数和异步补全互相覆盖。

## 翻译管线

English translator 直接读取 `STUDY_ENGLISH_AI_*`，缺省时回退 `STUDY_AI_*`；没有浏览器请求级 task profile 或图片模型选择。温度、输出长度和超时配置解析失败时转换为受控 `AIProviderError`，不能裸抛配置异常。

主流程先生成整句翻译、英中分块和重点词释义，再由第二次模型调用 review/repair。本地质量闸门只接受结构与语义规则通过的候选。

后台写回携带 expected text，最终在 SQLite 写锁内重新读取当前正文与重点词，只补缺失字段。前端显式翻译同时快照完整 draft；请求期间任何用户编辑都会让旧响应被忽略。理由见 [异步旧写保护](../decisions/0004-stale-async-write-guard.md)。

普通保存同样快照完整 draft，并在请求期间禁用全部编辑控件；若仍检测到新修改，响应只更新服务端基线，编辑器保持打开且本地草稿继续标记为待保存。

## 必须保持

- 英文和中文分块数量一致，英文块按原文顺序完整覆盖。
- 重点词 key 规范化比较，响应保留适合显示的 surface。
- 原文变化同时影响翻译身份和 [音频身份](audio.md)。
- AI 未配置或输出不合格时保留 pending/原数据，不能写半结构化结果。
- 空正文、已删除句写入和非重点词播放必须在业务边界被拒绝。
- Reliability 至少覆盖成功、provider 失败、质量拒绝、旧写回和并发 map 更新。
