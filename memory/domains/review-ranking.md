---
memory_level: 2
scope: domains.review-ranking
load_policy: feature-routed
load_when:
  - review queue, smart sorting, familiarity or focus-word network
  - review rounds, events, heatmap or English statistics
sources:
  - backend/app/english/repository.py
  - backend/app/english/ranking.py
  - backend/app/english/review_rounds.py
  - backend/app/english/stats.py
  - backend/app/english/api.py
  - frontend/src/english/useEnglishSentenceList.js
  - frontend/src/english/useEnglishAudio.js
  - backend/scripts/english/reliability_check.py
source_fingerprint: c99a650f4427838bde908c39733bf4adc7f19811861771cd0b9c8775c540cbd0
---

# Review And Ranking

## 产品语义

熟悉度来自整句复习、重点词播放和跨句上下文接触，不是学习者逐句自评的记忆等级。核心流不加入“忘记 / 模糊 / 掌握”按钮；轮次内顺序冻结以保持连续使用。

## 智能排序

Smart list 对全部有效句子计算熟悉度，再把顺序冻结到当前 round。曝光量结合整句复习和带衰减的重点词播放；跨句词网络结合弱度、上下文多样性、边熟练度和未见加成，并惩罚近期重点词重叠。

参数集中在 `SMART_REVIEW_SETTINGS`，前端不复制算法。非 smart 模式只服务句库查看。

## 复习轮次

每个用户最多一个 active round。轮次有效七个学习日，顺序写入固定 position；新增句子追加到末尾，不重排已有项目。软删除句子不计总数或完成数。

浏览器首次进入或显式刷新时从后端给出的首个未完成页续接；普通翻页和重载仍过滤所有已完成 item，如果当前页已经耗尽则自动跳到首个未完成页。自然播放结束已经记录 `sentence_play` 并完成 item 后，主按钮只进入下一句，不再追加一次手动复习事件。

复习队列只接纳整句音频身份当前且状态为 `ready` 的句子。`pending`、`failed`、`missing` 或文件/身份失效的句子不加入新 round；已经在 round 中的句子因正文编辑变为 pending 时，只暂时从可用队列隐藏，不完成 item、不删除原 position。音频重新 ready 后，只有用户手动刷新或重新进入复习页才恢复到原位置；页面不轮询或自动刷新队列。round 的 `total/completed/remaining` 保留完整轮次口径，`available/available_remaining` 表示本次请求中音频可用的子集。

## 事实与累计

每次 `sentence_review`、自然结束的 `sentence_play`、`word_play` 和重点词切换都写 `english_review_events`。句子 `review_count`、`word_play_total` 和 JSON map 同事务更新，并保留事件系统上线前的历史累计。

事件是持续统计的事实源；统计响应把 `tracked` 与 `legacy` baseline 分开。系统不维护未被消费的 due review card，也不记录通用页面停留时长。

复习页的即时摘要使用不构建跨句网络的轻量统计；句库和统计页仍请求完整网络摘要。排序本身继续使用完整跨句网络，不受界面隐藏或轻量统计影响。

软删除只把句子移出活动列表、排序和轮次，不抹除学习历史。终身累计继续包含已删除句子的 aggregate，与仍然保留的 review events 使用同一生命周期口径。

前端对同一句的整句事件串行提交；后端对计数写入使用 SQLite 原子更新或 immediate transaction。每个事件都必须累计，不能因请求重叠丢失。

## 必须保持

- `today.reviewed_sentences <= today.sentence_reviews`。
- round position、完成时间和 review event 必须事务一致；重复事件不重复完成 item。
- 只有当前 round 中真实存在的 item 才能返回已完成；复习页使用 active round 的固定顺序，每次智能队列加载都隐藏已完成项并跳过耗尽页。
- 非 ready 整句音频不得出现在复习队列；正文编辑导致音频失效后必须立即离队，并保持该 round item 未完成及 position 不变。
- 音频状态变化不得自动重载复习队列；ready 句只在用户显式刷新或重新进入时加入或恢复。
- 已由自然播放完成的 item 点击“下一句”不能再写一条 `sentence_review`。
- 搜索、查看删除项或非 smart 排序不得创建或推进 round。
- 修改排序参数时验证弱词网络、未复习句和同词疲劳的相对顺序。
