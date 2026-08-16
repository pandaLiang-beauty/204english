---
memory_level: 1
scope: maps.backend
load_policy: task-routed
load_when:
  - FastAPI or HTTP API
  - backend ownership or dependency direction
  - authentication, AI transport or background tasks
sources:
  - backend/app/main.py
  - backend/app/platform/api.py
  - backend/app/platform/auth.py
  - backend/app/platform/db.py
  - backend/app/english/api.py
  - backend/scripts/check_module_boundaries.py
source_fingerprint: 9da6a09a0bdc66fc5b2e6a66459b23e3f9cc0da0016a95a6032aee10149bcb99
---

# Backend Map

## 组合与依赖

`backend/app/main.py` 创建唯一 FastAPI 应用，只挂载本仓库的 Platform 基础接口和 English 业务接口。

```text
app/main.py
├── app/platform    # SQLite、认证、安全、限流、AI HTTP transport
└── app/english     # 英语复习业务
```

依赖方向是 `english -> platform`；Platform 不得导入 English。系统没有通用学习 Shell、学科注册层、聊天或其他学科接口。启动时依次初始化最小认证 schema、英语 schema，修复旧重点词/音频元数据，再初始化唯一管理员、清理过期会话并恢复待生成音频。

## 请求链

1. Platform HTTP 层处理 CORS、单密码登录、Session、写来源保护和登录失败限流。
2. `app/english/api.py` 在 `/api/english` 下校验 payload、当前用户和写来源。
3. 业务读写进入 English repository 或专用模块；翻译与音频的耗时生成使用后台任务。
4. 翻译模型只由本仓库环境配置选择，不接受浏览器请求级图片模型或通用任务 profile。

精确端点见 [API 证据](../evidence/api-map.md)。

## 业务入口路由

| 任务 | 继续读取 |
| --- | --- |
| 句子 CRUD、重点词、翻译生成或质量 | [句子与翻译](../domains/sentences-translation.md) |
| 智能排序、复习轮次、事件或统计 | [复习与排序](../domains/review-ranking.md) |
| 阅读文章、标注或同步句子 | [文章训练](../domains/passages.md) |
| Edge/Kokoro、音色、缓存或生成状态 | [音频](../domains/audio.md) |
| 登录、Cookie、CORS 或限流 | [认证](../domains/auth.md) |

## 修改守则

- 新增写路由必须同时依赖 `get_current_user` 和 `verify_write_origin`；登录、登出按认证语义组合。
- AI provider 异常必须转换为受控用户消息，内部诊断只进日志。
- 后台 best-effort 任务不能让已经成功的写请求失败，但必须留下可恢复状态。
- 调整目录、依赖或部署拓扑前读取 [独立系统决策](../decisions/0001-standalone-system.md)。
- API 或模块结构变化后重新生成 L3 证据并运行边界检查。
