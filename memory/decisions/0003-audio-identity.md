---
memory_level: 3
scope: decisions.audio-identity
load_policy: rationale-only
load_when:
  - changing audio filenames, hashes, providers or voices
  - debugging stale or mismatched sentence audio
  - changing global and per-sentence voice inheritance
sources:
  - backend/app/english/repository.py
  - backend/app/english/audio_generation.py
  - backend/app/english/schema.py
  - frontend/src/english/useEnglishAudio.js
  - backend/scripts/english/reliability_check.py
source_fingerprint: 71c766208a94c7ec1aa471ea98c5fd72e9beff26284f8e995564ad2828bc15ab
---

# Decision 0003: Content-Addressed Sentence Audio Identity

## Status

Accepted.

## Context

句子正文可编辑，整句声音还受 provider 和 voice 影响。仅以 sentence id 命名或只检查文件存在，会在文字或音色变化后继续播放语义过期的文件；全局音色和单句 override 又要求不同继承行为。

## Decision

有效音频身份由去除 Markdown 加粗后的正文、provider 和 voice 共同计算 SHA-1。数据库分别保存：

- 已生成文件的 `audio_provider`、`audio_voice`、`audio_hash` 和状态。
- 可选的 `audio_provider_override`、`audio_voice_override`。
- 全局 `english_audio_settings`；不存在时使用环境配置。

序列化时重新计算目标身份，并同时检查文件、ready 状态、已存 provider/voice 和 hash。任何不一致都设置 `audio_needs_regeneration`，同时返回 `audio_available=false` 和空 URL；下载端点也拒绝旧文件。生成使用临时文件和 atomic replace，只有新文件成功后才能成为 ready。

## Consequences

- 改正文、全局音色或单句 override 都能可靠使旧音频失效，旧文件存在也不能继续播放。
- 跟随全局的句子在 apply 时批量排队；有 override 的句子不受全局应用影响。
- 文件 URL 加版本参数，浏览器 Blob 缓存必须在新资源到位后替换并释放旧 URL。
- 旧文件名缺失显式 metadata 时允许从命名模式推断 provider/voice，以兼容已有媒体；新写入应保存完整字段。
- 启动时只为 hash 为空且文件名身份匹配当前选择的旧文件补算 hash；已有非空错误 hash 或无法证明身份的 ready 文件必须进入 pending，而不是被迁移代码直接认可。

不能用“文件存在”替代身份比较，也不能在生成失败后继续标记 ready。
