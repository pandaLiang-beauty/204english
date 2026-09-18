# Architecture

这是一个单用户英语复习应用，前端和后端都只服务英语业务。

- `backend/app/english/`：英语 API、复习队列、句子、文章、翻译和音频。
- `frontend/src/english/`：英语页面、导航和交互状态。
- `backend/app/platform/` 与 `frontend/src/platform/`：本仓库内部的基础设施。
- 数据库只有 SQLite，入口分别是 `backend/app/main.py` 和前端 `App.vue`。

依赖方向是 `english -> platform`。本仓库不依赖其他项目，不包含通用学科切换层。

复习周期由冻结的安排总数（含重复项）决定：`max(1, ceil(安排数 / 100))` 天，1041 项为 11 天。`review_rounds.py` 管理期限与进度，`repository.py` 按每轮快照补偿错过的边界；北京时间 08:00 仍为切换时间。整轮始终开放，不限制每天完成量。

前端 `ReviewRoundPacing.vue` 使用已有的周期时间和完成数显示累计建议、实际进度与差额，并在学习日切换时更新提示。提示按整个周期均摊，不改变 API 字段，也不参与服务端完成校验。旧活动周期仅调整到期时间，保留原有安排和进度。
