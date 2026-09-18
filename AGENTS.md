# AGENTS.md

## 仓库边界

- 本仓库 `/root/sysStuByAI/204english` 是独立的单用户英语复习系统。
- Business backend code belongs in `backend/app/english/`.
- Business frontend code belongs in `frontend/src/english/`.
- Business scripts belong in `backend/scripts/english/`.
- `platform/` is local infrastructure for this repository, never an external shared package.
- `shell/` may compose only this repository's business adapters.
- Never import from `/root/pro-study-platform`, `/root/sysStuByAI/302math`, `/root/sysStuByAI/408cs`, or any legacy `/root/pro-study-platform-*` directory.
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

- Backend: `127.0.0.1:8204`
- Frontend: `127.0.0.1:5204/` (public entry: `https://204.xpliang.tech/`)

## 复习周期调度约定

- 复习周期天数为 `max(1, ceil(本轮初始安排数 / 100))`，重复出现分别计数；1041 项为 11 天。100 仅用于计算周期和建议进度，不限制每日完成量，不逐日解锁队列。
- 按北京时间每天 08:00 作为学习日边界；数据库中以 UTC 00:00 存储该边界。界面按周期均摊，提示截至今天建议累计完成、实际完成及差额，允许自由提前或延后复习。
- 到达周期边界时，系统必须自动结束旧周期、重新排序并生成新安排，不得依赖复习页面的请求才触发。
- 后端进程启动时先补偿错过的边界，运行期间由后台调度器定期检查；请求路径仅作为重启或调度延迟时的补偿保障。
- 如当前周期提前全部完成，保留完成状态；新周期在完成时刻之后的下一个北京时间 08:00 开始，不立即开始。
- 新周期的句子集按周期开始时刻快照确定；周期中途新增的句子进入下一个周期，不回写当前周期。
- 前端根据当前周期的到期时间或提前完成后的下一个边界自动刷新，因此页面长时间保持打开时也能切换安排。
- 周期天数根据冻结的初始安排数确定；周期中新增或软删除句子、完成进度变化不移动本轮到期时间。
- 旧的 7 天活动周期迁移时，仅按初始安排数调整到期时间，保留起始时间、安排 ID、顺序和既有进度；不重建历史安排。

## Verification

Run in order:

1. `cd backend && python3 -m compileall -q app scripts`
2. `cd backend && python3 scripts/check_module_boundaries.py`
3. `cd frontend && npm test`
4. `cd frontend && npm run build`
5. `cd backend && .venv/bin/python scripts/reliability_check.py`
6. `git diff --check`
7. `curl -fsS http://127.0.0.1:8204/api/health`
