---
memory_level: 0
scope: project
load_policy: always
sources:
  - AGENTS.md
  - README.md
  - .env.example
  - start-dev.sh
  - deploy.sh
source_fingerprint: ca5d72dffdbad9c3bda255dc2e5a9a6b23bb50f98f5faa5c2d2b8ff38ee2e4cc
---

# English Project Memory

## 加载协议

每次任务先读取本文件；它只提供稳定核心和路由，不替代 `AGENTS.md`。不要预加载整个 `memory/`：先判断任务范围，再读取对应 L1 地图；由地图继续指向 L2 领域档案和必要的 L3 决策或证据。

修改相关源码前必须读取命中的领域档案。跨层任务可以组合多条路线；完成代码或运行配置变更前必须读取 [运维地图](memory/maps/operations.md) 的验证章节。

## 始终携带的事实

- `/root/english` 是独立英语学习系统，必须能独立安装、运行、部署、备份和删除。
- 本系统只服务仓库所有者本人，是个人单用户工具；登录与 `user_id` 用于保护入口和记录个人学习活动，不代表多租户产品需求。
- 登录界面只接收密码，内部固定使用唯一 `admin` 账户；公网必须使用 HTTPS、Secure Cookie 和失败限流。
- 英语按“使用形成熟悉度”设计：整句复习、重点词播放和跨句接触是核心信号；不要默认引入“忘记 / 模糊 / 掌握”等逐句自评来打断连续复习，轮次内顺序冻结用于保持连贯性。
- 业务代码归属：后端 `backend/app/english/`，前端 `frontend/src/english/`，业务脚本 `backend/scripts/english/`。
- `platform/` 是仓库私有基础设施，依赖方向为 `english -> platform`；系统没有通用学习 Shell 或学科注册层。
- 数据库固定为 SQLite `backend/data/study.db`；不维护 PostgreSQL 方言或通用学习平台 schema。
- 禁止依赖其他学科或旧平台仓库，禁止外部软链接、其他学科目录、系统切换器和 Docker Compose。
- 密钥只放在 gitignored 的 `.env.local`；配置合同以 `.env.example` 为准。
- 运行身份：后端 `127.0.0.1:8103`，前端 `127.0.0.1:5103/english/`，Cookie `english_study_session`，SQLite `backend/data/study.db`。

## L1 任务路由

| 任务信号 | 首先读取 |
| --- | --- |
| FastAPI、模块归属、接口、认证、后台任务、跨层调用 | [后端地图](memory/maps/backend.md) |
| Vue、页面、组件、路由、状态、交互、浏览器请求 | [前端地图](memory/maps/frontend.md) |
| 表、字段、SQL、迁移、事务、SQLite | [数据地图](memory/maps/data.md) |
| 环境变量、依赖、脚本、构建、测试、TTS、部署、备份 | [运维地图](memory/maps/operations.md) |

常见端到端业务通常同时读取后端和前端地图；涉及持久化再加数据地图。纯说明性任务不加载无关分支。

## 新鲜度规则

- L1-L3 人工档案列出事实来源并保存源码指纹。校验报告 stale 时，只复核被点名的档案和来源，然后刷新指纹。
- `memory/evidence/` 是源码机械生成的精确清单，不手工修改。
- Memory 记录入口、数据流、不变量、失败行为和设计原因；源码仍是具体实现的最终事实来源。
- 不记录密钥、临时任务进度、worktree 快照、一次性排障输出或逐函数源码摘要。
