# AGENTS.md

## 仓库边界

- 本仓库 `/root/english` 是独立的单用户英语复习系统。
- Business backend code belongs in `backend/app/english/`.
- Business frontend code belongs in `frontend/src/english/`.
- Business scripts belong in `backend/scripts/english/`.
- `platform/` is local infrastructure for this repository, never an external shared package.
- `shell/` may compose only this repository's business adapters.
- Never import from `/root/pro-study-platform`, `/root/math`, `/root/cs408`, or any legacy `/root/pro-study-platform-*` directory.
- Never add symlinks to code, data, environments, media, or configuration outside this repository.
- Do not add another subject directory or system switcher.
- Similar behavior in another system must be implemented and reviewed here independently.

## 目录

- `backend/app/platform/`：本仓库的本地基础设施。
- `backend/app/english/`：英语业务代码。
- `backend/scripts/english/`：英语业务脚本。
- `frontend/src/platform/`：前端基础设施。
- `frontend/src/english/`：英语界面和交互。

## 端口

- Backend: `127.0.0.1:8103`
- Frontend: `127.0.0.1:5103/english/` (public entry: `http://193.112.97.187/english/`)

## 复习周期调度约定

- 复习周期固定为 7 天，按北京时间每天 08:00 作为边界；数据库中以 UTC 00:00 存储该边界。
- 到达周期边界时，系统必须自动结束旧周期、重新排序并生成新安排，不得依赖复习页面的请求才触发。
- 后端进程启动时先补偿错过的边界，运行期间由后台调度器定期检查；请求路径仅作为重启或调度延迟时的补偿保障。
- 如当前周期提前全部完成，保留完成状态；新周期在完成时刻之后的下一个北京时间 08:00 开始，不立即开始。
- 新周期的句子集按周期开始时刻快照确定；周期中途新增的句子进入下一个周期，不回写当前周期。
- 前端根据当前周期的到期时间或提前完成后的下一个边界自动刷新，因此页面长时间保持打开时也能切换安排。
- 对旧版本按“首次访问时创建”的活动周期，可校正其固定起止时间但保留既有进度；不在没有明确决策时重建历史安排。

## Verification

Run in order:

1. `cd backend && python3 -m compileall -q app scripts`
2. `cd backend && python3 scripts/check_module_boundaries.py`
3. `cd frontend && npm test`
4. `cd frontend && npm run build`
5. `cd backend && .venv/bin/python scripts/reliability_check.py`
6. `git diff --check`
7. `curl -fsS http://127.0.0.1:8103/api/health`
