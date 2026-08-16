---
memory_level: 3
scope: decisions.standalone-system
load_policy: rationale-only
load_when:
  - moving code across platform and english
  - sharing code or data with another repository
  - changing deployment topology or adding another subject
sources:
  - AGENTS.md
  - README.md
  - docs/architecture.md
  - backend/scripts/check_module_boundaries.py
  - backend/app/main.py
  - frontend/src/english/navigation.js
source_fingerprint: 6ddcd70278329262aed62905631a9fbe2c4c3ede7a6e9b0027ef6d555aea952a
---

# Decision 0001: Standalone English System

## Status

Accepted and enforced.

## Context

英语系统只服务仓库所有者本人，并曾与通用平台或其他学科存在相似能力。共享目录、绝对导入、外部数据库/媒体路径和系统切换器会让部署、备份、故障和删除重新耦合，即使表面上减少了重复代码。

## Decision

`/root/english` 拥有运行所需的全部代码、依赖、配置模板、数据、媒体和宿主机脚本。Platform 是本仓库最小基础设施，不是外部共享包；系统没有通用 Shell。系统只呈现英语，不包含其他学科目录或切换 UI，也不因认证基础设施而扩展成多用户产品。

禁止：

- 导入 `/root/pro-study-platform`、`/root/math`、`/root/cs408` 或旧平级目录。
- 用软链接共享代码、环境、配置、数据或媒体。
- 为复用相似行为直接连接其他项目 API/数据库。
- 用 Docker Compose 取代当前宿主机脚本与 systemd 合同。

`backend/scripts/check_module_boundaries.py` 把目录、导入、endpoint、绝对路径、软链接和写保护约束变成可执行检查。

## Consequences

相似基础设施可能在多个独立仓库中重复，但每个系统可以单独升级、停止、备份和移除。需要引入相似功能时，以本项目需求重新实现和评审，不能把另一个系统当运行时依赖。

只有用户明确改变独立部署目标时才重新讨论这项决策；普通重构不得放宽边界检查来绕过它。
