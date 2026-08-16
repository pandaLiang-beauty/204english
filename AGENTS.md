# AGENTS.md

## Scope

This repository is the standalone 英语 study system at `/root/english`. It must remain independently installable, runnable, deployable, backable up, and removable.

## Hard boundaries

- Business backend code belongs in `backend/app/english/`.
- Business frontend code belongs in `frontend/src/english/`.
- Business scripts belong in `backend/scripts/english/`.
- `platform/` is local infrastructure for this repository, never an external shared package.
- `shell/` may compose only this repository's business adapters.
- Never import from `/root/pro-study-platform`, `/root/math`, `/root/cs408`, or any legacy `/root/pro-study-platform-*` directory.
- Never add symlinks to code, data, environments, media, or configuration outside this repository.
- Do not add another subject directory or system switcher.
- Similar behavior in another system must be implemented and reviewed here independently.

## Runtime

- Backend: `127.0.0.1:8103`
- Frontend: `127.0.0.1:5103/english/` (public entry: `http://193.112.97.187/english/`)
- Session cookie: `english_study_session`
- SQLite: `backend/data/study.db`
- Services: `pro-study-platform-english-backend`, `pro-study-platform-english-frontend`

Secrets live only in this repository's gitignored `.env.local`.

## Project memory

- Start every task by reading `memory.md`, then load only the L1-L3 files selected by its routing rules.
- Before changing a feature, read its routed domain memory. Source code remains authoritative for exact implementation.
- When a change affects ownership, data flow, invariants, routes, schema, configuration, or operations, update the relevant memory and generated evidence.
- Validate memory with `cd backend && python3 scripts/check_memory.py`. Refresh source fingerprints only after reviewing the affected documents.

## Verification

Run in order:

1. `cd backend && python3 -m compileall -q app scripts`
2. `cd backend && python3 scripts/check_module_boundaries.py`
3. `cd backend && python3 scripts/check_memory.py`
4. `cd frontend && npm run build`
5. `cd backend && .venv/bin/python scripts/reliability_check.py`
6. `git diff --check`
7. `curl -fsS http://127.0.0.1:8103/api/health`

Use host scripts and systemd. Docker Compose is not part of this standalone system.
