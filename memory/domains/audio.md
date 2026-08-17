---
memory_level: 2
scope: domains.audio
load_policy: feature-routed
load_when:
  - sentence or word audio generation and playback
  - Edge TTS, Kokoro, voice catalog, previews or settings
  - audio cache, status recovery or media files
sources:
  - backend/app/english/repository.py
  - backend/app/english/audio_generation.py
  - backend/app/english/api.py
  - frontend/src/english/useEnglishAudio.js
  - frontend/src/english/useEnglishSentenceList.js
  - frontend/src/english/EnglishFlow.vue
  - backend/scripts/english/generate_english_audio.py
  - backend/scripts/english/generate_english_voice_previews.py
  - backend/scripts/english/reliability_check.py
source_fingerprint: 4ed66a064e81f1225f199893be32f9bfbd497019bb67b7559382fcbe6bdd73bb
---

# Audio

## 两类音频

- 重点词固定使用 Edge TTS，保存在 `backend/data/english/audio/pronunciations/`；播放成功后记录 `word_play`。
- 整句支持 Edge 或 Kokoro，保存在 `backend/data/english/audio/`。Kokoro 模型与 voice 文件位于本仓库数据目录。

## 身份与状态

整句身份是 `plain text + provider + voice` 的 SHA-1。全局设置在 `english_audio_settings`；句子可有 provider/voice override。

身份选择理由见 [音频身份决策](../decisions/0003-audio-identity.md)。

状态为 `missing`、`pending`、`ready`、`failed`。序列化同时检查文件、ready、已存 provider/voice 和 hash。任一不一致都会设置 `audio_needs_regeneration=true`，并且必须返回 `audio_available=false`、空 `audio_url`；音频下载端点同样返回 404。旧文件可留到新文件成功生成，但绝不能继续播放。

启动迁移会先检查有效句子：旧文件名能够证明 provider/voice 与当前选择一致且旧 hash 为空时，补齐显式 metadata 和当前 hash；已有非空错误 hash、身份不符、文件缺失或空文件的 ready 记录改为 pending。后台恢复随后处理 pending/failed/missing，避免 ready 记录永久卡死。

生成先写临时文件再 atomic replace。后台错误留下 failed 状态与清洗后的错误，不让已成功的句子写请求失败。

## 浏览器生命周期

`useEnglishAudio.js` 在滑动窗口内预取 Blob URL；替换、暂停、列表更新或卸载时释放缓存。原生 `ended` 每次写一个 `sentence_play`；手动暂停不写事件。整句事件与手动 `+1` 分别进入逐句串行队列。

正文更新使整句音频进入 pending 后，复习页立即停止并释放该句缓存、从当前队列移除，并禁止音频状态定时器重载复习列表。生成完成不会主动改变用户的复习位置；用户手动刷新或重新进入复习页后，ready 句才重新可见。句子更新后台任务优先生成整句音频，再处理重点词音频和自动翻译，以缩短回到可复习状态的等待。

## 必须保持

- ready 必须对应存在、非空且身份当前的文件。
- `stats.with_audio` 只计入同时具备 ready、非空路径和非空 hash 的有效记录。
- 路径只使用受控 basename/slug，下载接口不能目录穿越。
- 文本/provider/voice 改变后旧文件不可序列化或下载为可用资源。
- pending、failed、missing 或身份失效的整句不得进入复习队列；ready 状态不得触发复习页自动刷新。
- 单词计数、整句播放和手动复习并发时，每个事件都必须保留。
