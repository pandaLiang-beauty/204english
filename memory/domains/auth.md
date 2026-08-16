---
memory_level: 2
scope: domains.authentication
load_policy: feature-routed
load_when:
  - login, logout, sessions or cookies
  - CORS, write protection, proxy trust or login throttling
sources:
  - backend/app/platform/auth.py
  - backend/app/platform/api.py
  - backend/app/platform/security.py
  - frontend/src/App.vue
  - frontend/src/platform/http.js
  - frontend/src/platform/api.js
  - frontend/src/platform/components/LoginView.vue
  - backend/scripts/platform/reliability_check.py
source_fingerprint: 936e9ddbdc9858d202f41391479063a4cc67280175c677fc07ac163cd3189e50
---

# Authentication

## 单用户登录

系统只有内部 `admin` 账户。首次启动若账户不存在，必须由 `STUDY_INITIAL_PASSWORD` 创建；界面和登录 payload 只接收密码，不提供用户名、注册或用户管理。

密码使用带随机 salt 的 PBKDF2-SHA256。Session id 是随机 token，默认有效 14 天，Cookie 为 HttpOnly、SameSite=Lax，名称 `english_study_session`。除本地开发显式设置 `STUDY_COOKIE_INSECURE=1` 外，Cookie 必须 Secure。

登录失败按固定账户和可信客户端 IP 限流，默认 10 分钟内 5 次。启动清理过期 Session；业务 API 只从 Cookie 解析当前用户，不接受客户端 user id。

## 写请求保护

浏览器为非 GET/HEAD 请求添加 `X-Study-Write: 1`。后端同时要求此 header，并在 Origin/Referer 存在时校验本地 origin、`STUDY_PUBLIC_ORIGIN` 和 `STUDY_ALLOWED_ORIGINS`。

只有可信代理 CIDR 的 peer 才能让 `X-Forwarded-For` 影响限流 IP。CORS 允许凭据时只使用显式 origin 集合。

本仓库前端代理会删除请求自带的 `X-Forwarded-For`、`X-Real-IP` 和 `X-Forwarded-Proto`，再用其直接 peer 重建转发头。后端从右向左跳过可信代理并选择最近的非可信地址，不能直接采用客户端可控的最左值。

## 部署安全

非本机公网 origin 必须是 HTTPS，且 Cookie 不能设置为 insecure。`deploy.sh` 和 reliability 都执行这一合同。仓库不能自行替外部 IP 网关取得证书；网关没有 TLS 时应停止把该地址视为正式登录入口。

## 必须保持

- 响应和日志不泄露 password hash、session id 或 API key。
- 所有带 `user_id` 的资源使用当前 Session 用户；这是个人数据边界。
- 新增写 API 必须有登录依赖与写来源保护。
- 修改代理信任、登录限流、Cookie 或 OpenAPI 写保护时更新 platform reliability。
