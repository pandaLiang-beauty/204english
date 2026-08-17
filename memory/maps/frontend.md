---
memory_level: 1
scope: maps.frontend
load_policy: task-routed
load_when:
  - Vue pages, components, composables or state
  - browser routing, navigation or HTTP behavior
  - responsive interaction, audio playback or editors
sources:
  - frontend/src/App.vue
  - frontend/src/StudyApp.vue
  - frontend/src/router.js
  - frontend/src/english/navigation.js
  - frontend/src/english/EnglishTopNav.vue
  - frontend/src/english/EnglishFlow.vue
  - frontend/src/english/useEnglishSentenceList.js
  - frontend/src/english/useEnglishAudio.js
  - frontend/src/english/keyboardShortcuts.js
  - frontend/src/english/api.js
  - frontend/src/platform/http.js
source_fingerprint: a4f4299030f549ae0fb8ceb12a43cfc321a1e9fd5c5476c0e68f33b015aa1754
---

# Frontend Map

## 应用结构

Vue 3 + Vite 应用直接呈现英语复习，不经过系统注册、`activeSystem`、track 选择或通用统计 Shell。

```text
App.vue                 # 登录态
└── StudyApp.vue        # 路由协调、切页/退出前 flush
    ├── EnglishTopNav
    └── EnglishFlow
```

`frontend/src/english/navigation.js` 是唯一导航定义，公开基路径固定为 `/english/`。`StudyApp.vue` 在切页和退出前等待文章自动保存；浏览器关闭时若仍有 dirty 内容会触发原生离开确认。已有文章的信息表单和正文标注都进入同一 dirty/保存链；未保存的新文章在站内导航时必须显式确认放弃。

文章和句子保存都会冻结可编辑控件并快照请求正文。响应只在当前草稿仍等于快照时关闭或替换编辑器；等待期间出现的新修改必须继续留在本地 dirty 状态。

## 英语界面结构

| 关注点 | 主要位置 | 领域记忆 |
| --- | --- | --- |
| 句子列表、分页、创建、编辑、翻译、复习 | `useEnglishSentenceList.js`、`SentenceEditor.vue` | [句子与翻译](../domains/sentences-translation.md)、[复习与排序](../domains/review-ranking.md) |
| 文章筛选、标注、自动保存、同步 | `usePassageEditor.js`、`passageMarkdown.js` | [文章训练](../domains/passages.md) |
| 整句/单词播放和 Blob URL 生命周期 | `useEnglishAudio.js` | [音频](../domains/audio.md) |
| 登录、Cookie 请求、主题 | `frontend/src/platform/` | [认证](../domains/auth.md) |

## HTTP 约定

所有请求经 `frontend/src/platform/http.js::request`：自动加 `/english` 前缀、携带 Cookie，非 GET/HEAD 请求加 `X-Study-Write: 1`。业务 endpoint 集中在 `frontend/src/english/api.js`；浏览器不再发送通用 AI task/vision headers。复习页只请求不含跨句网络的轻量统计，热力图仅在统计页加载；句库和统计页才加载音色配置。

## 修改守则

- 服务端拥有排序、权限和持久化规则；前端只管理交互状态、显示和请求协调。
- 复习页只保留本轮/今日摘要、播放、完成并下一句、翻译、重点词和按需展开的纠错编辑；搜索、排序、音频配置和热力图分别位于句库或统计页面。正文纠错保存后会自动触发翻译与整句音频更新；音频 pending 的句子立即离开当前列表，复习模式不运行状态轮询，ready 后由用户手动刷新或重新进入。
- 复习快捷键不依赖视口宽度；句卡内按钮获得焦点后仍可继续使用，只有文本输入、编辑器及句卡外的交互控件保留原生按键行为。
- 切页、退出或更换文章前必须等待自动保存；失败时停留在当前状态。
- 销毁或替换音频缓存时必须释放 Object URL。
- 跨多个 mode 的状态才留在 `EnglishFlow.vue`；独立行为优先进入 composable 或组件。
- 新路由或 API 变化后重新生成证据并核对生产 `/english/` 基路径。
