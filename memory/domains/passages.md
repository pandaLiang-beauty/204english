---
memory_level: 2
scope: domains.passages
load_policy: feature-routed
load_when:
  - passage list, today selection, filters or completion
  - rich-text annotation, autosave or passage-to-sentence sync
  - public exam passage import
sources:
  - backend/app/english/api.py
  - backend/app/english/passages.py
  - backend/app/english/repository.py
  - frontend/src/StudyApp.vue
  - frontend/src/english/EnglishFlow.vue
  - frontend/src/english/usePassageEditor.js
  - frontend/src/english/passageMarkdown.js
  - frontend/src/english/RichMarkedTextEditor.vue
  - backend/scripts/english/import_english_kaoyan_passages.py
  - backend/scripts/english/reliability_check.py
source_fingerprint: 98161072ea0a34818099d6ad48de8e2c711929781d2187dec9506b77b9fe86f8
---

# Passage Training

## 状态模型

`english_passages` 按 Session 用户隔离。状态为 `new`、`reading`、`done`；类型为 `reading_a`、`cloze`、`reading_b`、`translation`、`custom`。正文保留 Markdown，`**...**` 表示重点词；删除使用 `deleted_at`。

## 今日文章

筛选、训练顺序和今日选择由后端决定。今日最多两篇，先保留今天完成项，即使两篇属于同一考试类型也不能被新文章替换；存在空位时再尽量按英语一/英语二从 reading/new 补齐。`/passages/today` 查询全部有效文章后交给同一选择器，因此今天刚完成的文章不会消失。

## 编辑与保存

`usePassageEditor.js` 管理 contenteditable 标注、文章信息表单和 900ms 自动保存。失败时保留 dirty 状态与本地正文；已有文章的标题、来源、类型和原始正文修改必须与标注走同一保护链。

`EnglishFlow` 暴露 `flushPendingChanges` 和 dirty 状态；`StudyApp` 在路由切换和退出前等待 flush，失败则停留。未保存的新文章不能自动写入，站内离开时要求显式确认放弃，浏览器关闭时 dirty 状态触发原生离开确认。卸载钩子中的 best-effort flush 不是主数据保护路径。

## 同步到句子库

后端只从含加粗词的句子生成候选，规范化去重后复用或创建 `english_sentences`，把 ids 合并到文章记录，并在提交后触发翻译和音频任务。

## 必须保持

- 用户隔离、候选去重、复用计数和软删除边界。
- 切换文章、筛选、翻页、完成、路由或退出前等待保存。
- 文章信息表单修改不能静默丢失；新文章草稿只能在保存或确认放弃后离开。
- 今天完成项继续出现在当日选择中。
- 导入公开 PDF 时先 dry-run 和抽样，不覆盖已标注正文。
