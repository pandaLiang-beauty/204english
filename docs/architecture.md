# Architecture

这是一个单用户英语复习应用，前端和后端都只服务英语业务。

- `backend/app/english/`：英语 API、复习队列、句子、文章、翻译和音频。
- `frontend/src/english/`：英语页面、导航和交互状态。
- `backend/app/platform/` 与 `frontend/src/platform/`：本仓库内部的基础设施。
- 数据库只有 SQLite，入口分别是 `backend/app/main.py` 和前端 `App.vue`。

依赖方向是 `english -> platform`。本仓库不依赖其他项目，不包含通用学科切换层。
