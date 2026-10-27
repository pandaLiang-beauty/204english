# 204 英语复习 API 文档

核对日期：2026-09-13。对应当前 `English Review` 后端（应用版本 `1.0.0`），覆盖全部 **34 个 HTTP 操作**。面向原生 Android 客户端，也适用于其他 HTTP 客户端。

- [OpenAPI 3.1 文件](openapi.json)：包含请求约束、响应模型、示例、Cookie 鉴权和写保护请求头，可导入支持 OpenAPI 3.1 的 Apifox、Postman 等工具。
- [Android 接入指南](android-client-guide.md)：OkHttp、Retrofit、Media3、会话保存、复习交互和错误处理。
- [HTTP 请求示例](api-examples.http)：逐条运行的完整接口示例。

本文依据 `backend/app/platform/api.py`、`auth.py`、`security.py` 及 `backend/app/english/` 的实际实现整理。OpenAPI 的响应模型是根据序列化代码补充的文档描述，后端目前没有为这些响应逐一声明 Pydantic `response_model`。示例使用虚构学习内容；验证时使用临时数据库，AI 和 TTS 由替身提供，没有写入线上数据或调用真实模型。

## 目录

1. [地址与通用约定](#conventions)
2. [错误与限流](#errors)
3. [健康检查与登录](#auth)
4. [句子模型与增删改查](#sentences)
5. [复习队列、完成和播放记录](#review)
6. [重点词操作](#focus)
7. [AI 翻译](#translation)
8. [阅读文章](#passages)
9. [音色、生成与音频文件](#audio)
10. [统计与热力图](#stats)
11. [客户端工作流与同步约束](#workflows)
12. [接口索引](#index)

<a id="conventions"></a>
## 1. 地址与通用约定

| 用途 | 地址 |
| --- | --- |
| 线上 origin / Retrofit base URL | `https://204.xpliang.tech/` |
| 平台接口 | `https://204.xpliang.tech/api/…` |
| 英语接口 | `https://204.xpliang.tech/api/english/…` |
| 服务器本机后端 | `http://127.0.0.1:8204/` |
| 后端自带 Swagger UI | `http://127.0.0.1:8204/docs` |
| 后端原始 OpenAPI | `http://127.0.0.1:8204/openapi.json` |

线上入口目前只代理 `/api/` 到后端。已核对线上 `/openapi.json` 返回前端 HTML，因此客户端开发请导入本目录的 [openapi.json](openapi.json)，或直连本机后端获取原始规范。原始规范的响应字段较少，本目录文件补充了完整响应结构。接口路径没有 `/v1` 前缀。

### 请求头

| 请求头 | 要求 |
| --- | --- |
| `Content-Type: application/json` | 有 JSON 请求体时使用 |
| `Cookie: english_study_session=…` | 除健康检查、登录外均需登录；退出可在未登录时调用 |
| `X-Study-Write: 1` | **所有 POST、PUT、DELETE 都必需，包括登录与退出** |
| `Origin` / `Referer` | 原生 Android 可以不发送；如果发送，来源必须在服务端允许列表内 |
| `Range: bytes=…` | 可选，音频分段读取 |

会话 Cookie 名默认是 `english_study_session`，可由服务端配置更改；客户端应解析 `Set-Cookie`，避免写死整条 Cookie。没有 Bearer Token、JWT 或刷新令牌接口。`X-Study-Write` 是固定值，不需要先调用接口获取。

### JSON、字段与时间

- 成功响应默认都是 **HTTP 200**，包括创建和删除；没有统一的 `code/message/data` 外层。
- 对象 ID 在 Kotlin 中建议使用 `Long`。对象字典如 `word_translations` 使用 `Map<String, String>`。
- `PUT` 使用完整可写对象语义。省略的字段会取请求模型默认值，可能清空译文、词义、来源、年份或重置状态。先读取，再合并修改，最后提交完整可写字段。
- 请求体只使用本文列出的可写字段。计数、音频地址、创建时间、队列安排等由服务端管理。
- 未生成的文本、URL、日期通常为 `""`，集合通常为 `{}` / `[]`。`year`、没有今日文章时的 `item/today`、部分复习结果的安排 ID 则可以是 `null`。字段缺失与 `null` 不要混为一谈。
- 新业务时间通常是 UTC ISO 8601，如 `2026-09-13T00:00:00+00:00`。用户 `created_at` 和历史数据也可能是 SQLite 格式 `2026-09-13 06:00:00`，应按 UTC 兼容解析；空字符串表示没有时间。
- 统计按 **UTC 日期**归档，即北京时间每天 **08:00** 换日。不要按手机本地零点重新划分服务端热力图。
- `audio_url`、`pronunciations` 中的值均为 origin 相对路径。按 `https://204.xpliang.tech/` 解析，保留完整 `?v=…`；不要拼到 `/api/english/` 后面。
- 接收端应容忍新增响应字段。排序算法和诊断对象可扩展，不作为客户端计算规则。

<a id="errors"></a>
## 2. 错误与限流

常规错误：

```json
{"detail":"Not authenticated"}
```

参数校验错误，`detail` 是数组：

```json
{
  "detail": [
    {
      "type": "less_than_equal",
      "loc": ["query", "page_size"],
      "msg": "Input should be less than or equal to 200",
      "input": "201",
      "ctx": {"le": 200}
    }
  ]
}
```

接口限流也可能使用另一个外层：

```json
{"error":"Rate limit exceeded: 10 per 1 minute"}
```

| HTTP 状态 | 含义与客户端处理 |
| --- | --- |
| `400` | 业务输入不合法、无可同步标注、音色无效/未安装、翻译服务未配置等；展示可读原因 |
| `401` | 未登录、会话过期或登录密码错误；业务接口遇到此状态后重新登录 |
| `403` | 缺少写保护头或来源不允许；修正请求头，重复登录不能解决 |
| `404` | 句子、文章、音频不存在或已软删除；音频也可能尚未生成或已过期 |
| `405` | 请求方法不支持，例如对当前音频路由发送 `HEAD` |
| `409` | 修改句子后与已有句子重复；读取冲突对象并由用户决定如何处理 |
| `416` | 音频 `Range` 越界；响应带 `Content-Range`，不按 JSON 解析 |
| `422` | 请求体、查询参数或路径类型校验失败；定位 `detail[].loc` |
| `424` | AI 调用/结果校验失败；保留编辑内容并允许用户重试 |
| `429` | 登录、翻译或试听限流，或 AI 上游限额；有 `Retry-After` 时优先遵守 |
| `503` | 试听音频生成失败 |

文件响应的非法 Range 可能返回 `400 text/plain`，越界返回 `416`；代理超时等也可能返回非 JSON。错误解析应先检查 Content-Type，兜底显示 HTTP 状态和简短说明。

| 限制 | 当前默认行为 |
| --- | --- |
| 密码错误 | 用户名与客户端 IP 组合在 600 秒内最多失败 5 次，后续登录 `429`；服务端可配置 |
| `POST /api/english/translate` | 每 IP 每分钟 10 次 |
| `POST /api/english/translate/words` | 每 IP 每分钟 10 次，与整句翻译分别计数 |
| `POST /api/english/audio/previews` | 每 IP 每分钟 15 次 |

登录限流返回 `Retry-After: 秒数` 和中文 `detail`。接口限流返回 `error`，当前未保证有 `Retry-After`。AI 上游的 `429` 也可能是 `detail`。上述限制不等同于 AI 上游实际可用额度；局域网共用公网 IP 的客户端可能共享限额。

<a id="auth"></a>
## 3. 健康检查与登录

### GET `/api/health`

无需登录，无参数。返回：

```json
{"status":"ok"}
```

表示 HTTP 服务可响应，不是数据库、翻译服务或语音生成的完整可用性检查。

### POST `/api/auth/login`

请求头必需 `X-Study-Write: 1`。请求体：

```json
{"password":"用户输入的密码"}
```

`password` 必填，类型 `string`。系统是单用户，用户名固定为 `admin`，**不要添加用户名输入或注册流程**。

响应示例：

```json
{
  "user": {
    "id": 1,
    "username": "admin",
    "display_name": "管理员",
    "created_at": "2026-09-13 06:00:00"
  }
}
```

| User 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | integer | 用户 ID |
| `username` | string | 当前为 `admin` |
| `display_name` | string | 展示名称 |
| `created_at` | string | 登录响应包含；`/auth/me` 不返回此字段 |

同时接收：

```http
Set-Cookie: english_study_session=<opaque-session>; HttpOnly; Max-Age=1209600; Path=/; SameSite=lax; Secure
```

会话有效期固定 **14 天**；不会因普通请求自动续期。客户端保存 Cookie，无需保存密码。生产环境默认 `Secure`，仅对 HTTPS 发送；本机 HTTP 开发需由开发服务器显式配置不安全 Cookie，并仅在 Android debug 环境开放明文流量。

特有错误：密码错误 `401 {"detail":"密码错误"}`；超限 `429`。通用 `403/422` 同样适用。

### GET `/api/auth/me`

需要 Cookie，无参数。返回 `{"user":{"id":1,"username":"admin","display_name":"管理员"}}`。启动或恢复 App 时可用于校验持久化会话。失败 `401`。

### POST `/api/auth/logout`

无请求体，需要写保护头；发送当前 Cookie 以删除对应服务端会话。返回 `{"ok":true}`，同时删除 Cookie。未登录、会话已过期也返回 `200`。

客户端退出时停止播放并清理本地会话及对应用户缓存。只删除本地 Cookie 不等于服务端会话已注销。

<a id="sentences"></a>
## 4. 句子模型与增删改查

### Sentence 响应模型

所有句子详情、创建、修改、词播放和标注操作返回同一个基础对象；列表及复习接口会增加字段。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `id` | integer | 句子 ID |
| `text` | string | 带 `**重点词或短语**` 标记的原文 |
| `word_translations` | object<string,string> | 重点词到释义文本；新生成内容含中文本义、句中义和简明英文解释，尚无词义时值为 `""` |
| `word_tips` | object<string,string> | 重点词到用法提示，可缺少部分词 |
| `word_play_counts` | object<string,integer> | 各重点词的播放计数 |
| `word_play_total` | integer | 历史词音播放累计；取消重点词或删除句子不减少累计统计 |
| `focus_word_play_total` | integer | 当前重点词的播放计数总和；排序仍使用当前重点词计数 |
| `sentence_translation` | string | 整句译文，未生成时 `""` |
| `sentence_segments` | string[] | 英文阅读分块 |
| `translation_segments` | string[] | 与英文按下标对应的中文分块 |
| `translation_pending` | boolean | 缺整句译文或任一重点词词义为空；**不是后台任务状态** |
| `audio_available` | boolean | 当前文本与目标音色对应的音频文件可用 |
| `audio_status` | string | `missing` / `pending` / `ready` / `failed` |
| `audio_provider`、`audio_voice` | string | 已记录的句子音频引擎与音色，可能与当前目标不同 |
| `audio_provider_override`、`audio_voice_override` | string | 单句覆盖值，未覆盖时 `""` |
| `audio_effective_provider`、`audio_effective_voice` | string | 当前单句实际应使用的引擎和音色 |
| `audio_uses_global` | boolean | 是否跟随全局音色 |
| `audio_needs_regeneration` | boolean | 当前目标音频需要生成或重新生成 |
| `audio_error` | string | 最近语音生成错误，正常时 `""` |
| `audio_generated_at` | string | 语音生成时间，未生成时 `""` |
| `audio_url` | string | 可用句子音频地址，否则 `""`；包含版本查询参数 |
| `pronunciations` | object<string,string> | 已有文件的重点词到发音 URL；不要自己推算文件名 |
| `word_audio_provider`、`word_audio_voice` | string | 单词发音引擎与音色，与整句音色设置独立 |
| `word_audio_count` | integer | 当前可返回的单词发音文件数量 |
| `review_count` | integer | **整句播放次数** |
| `completion_count` | integer | 完成复习安排的累计次数 |
| `deleted_at` | string | 软删除时间，正常对象为 `""` |
| `created_at`、`updated_at` | string | 创建、最后更新时间 |
| `word_network` | object，可缺省 | 词网络提示，主要在列表和队列中返回 |
| `algorithm` | object，可缺省 | 智能排序指标，主要在 smart 列表和队列中返回 |

播放按钮应依据 `audio_available && audio_url.isNotBlank()`；不能只判断 `audio_status == "ready"`。全局音色改变后，旧文件可能仍记录为 ready，但已经不匹配目标音色。

重点词的英文解释复用现有字符串，例如 `"approachable": "本义：平易近人的；句中：平易近人；英文：friendly and easy to talk to"`。接口路径、请求参数和响应字段类型不变，`word_translations` 仍为 `Map<String, String>`，`items[].translation` 仍为字符串；客户端直接展示整段即可。历史中文释义仍可读取和保存，不会仅因缺少英文解释就变成 `translation_pending`。网页编辑页可用已有的「生成翻译」操作补充英文解释，保存后生效，已有中文释义和整句译文保留。

2026-09-15 已一次性[补齐现有 710 句、2333 个重点词的英文解释](english-definitions-backfill-20260915.md)。客户端重新读取句子即可显示，无需调整接口或逐条生成。

`word_network` 字段：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `word_weakness_boost` | number | 薄弱词带来的优先级增量 |
| `context_diversity_boost` | number | 多语境练习增量 |
| `word_mastery_penalty` | number | 已掌握词的降权 |
| `linked_words` | object[] | 当前最多 5 个关联词 |
| `linked_words[].key`、`surface` | string | 归一化词键、展示词形 |
| `linked_words[].linked_sentences` | integer | 关联句子数 |
| `linked_words[].weakness`、`edge_need` | number | 薄弱程度、该语境的复习需求 |

`algorithm` 字段包括数值型 `score`、`base_score`、`familiarity`、`review_need`、`exposure`、`word_signal`、`peak`、`corpus_average_exposure`，整型 `corpus_count`，字符串 `peak_mode`，上表结构的 `word_network`，以及可缺省的 `fatigue_adjusted_score`。这些字段只用于解释服务端排序；并非全部限定在 0—1，客户端不要据此重新排列当前复习安排。

### SentenceWrite 请求模型

创建、修改及批量创建中的单个 `items[]` 使用此结构。

| 字段 | 类型 | 必填 | 默认/约束 |
| --- | --- | --- | --- |
| `text` | string | 是 | 1—12000 字符，不能全为空白 |
| `word_translations` | object<string,string> | 否 | `{}` |
| `word_tips` | object<string,string> | 否 | `{}` |
| `sentence_translation` | string | 否 | `""`，最多 12000 字符 |
| `sentence_segments` | string[] | 否 | `[]` |
| `translation_segments` | string[] | 否 | `[]` |

```json
{
  "text": "Progress depends on **consistent** practice.",
  "word_translations": {"consistent": "持续的"},
  "word_tips": {"consistent": "在这里形容练习持续、稳定。"},
  "sentence_translation": "进步离不开持续的练习。",
  "sentence_segments": ["Progress depends on", "consistent practice."],
  "translation_segments": ["进步离不开", "持续的练习。"]
}
```

`text` 的标记决定重点词。保存时会修整对应映射：新标记可获得空词义，未标记词的词义、提示和计数会被移除。不要只往 `word_translations` 添加键而不更新原文标记。去掉标记也可能降低当前词计数总和，历史播放事件仍保留。

### GET `/api/english/sentences`

| Query 参数 | 类型 | 默认 | 约束/说明 |
| --- | --- | --- | --- |
| `page` | integer | `1` | ≥1 |
| `page_size` | integer | `40` | 1—200 |
| `search` | string | `""` | 搜索原文、整句译文和词义；全数字同时匹配句子 ID |
| `q` | string | `""` | `search` 为空时使用的别名 |
| `sort` | string | `smart` | 见下表 |
| `include_deleted` | boolean | `false` | 包含软删除句子 |
| `round_queue` | boolean | `false` | 满足条件时读取持久化复习安排 |
| `resume` | boolean | `false` | 仅在复习队列模式中跳到首个未完成安排所在页 |

| sort | 行为 |
| --- | --- |
| `smart` / `default` / `peak-familiarity` | 智能排序 |
| `latest` / `created-desc` | 创建时间从新到旧 |
| `oldest` / `created-asc` | 创建时间从旧到新 |
| `id-asc` / `id-desc` | ID 升序/降序 |
| `missing-audio` | 缺失或过期音频排前面，**不是仅筛选缺音频项** |
| `least-reviewed` / 其他值 | 整句播放数、词播放总数、ID 依次升序 |

普通响应：`{items: Sentence[], total: integer, page: integer, page_size: integer}`。`total` 是匹配的句子数，越界页可返回空数组。

只有同时满足 `round_queue=true`、智能排序、无 `search/q`、`include_deleted=false` 时，才返回复习队列及 `review_round`。详情见下一节；其他组合返回普通列表。

### GET `/api/english/sentences/{sentence_id}`

路径参数 `sentence_id: integer`。返回 `Sentence`；不存在或已删除返回 `404 {"detail":"句子不存在"}`。详情没有 `include_deleted` 参数。

### POST `/api/english/sentences`

请求体 `SentenceWrite`，返回 `Sentence`。创建后按服务端配置安排缺失翻译、词发音及整句音频生成，不保证响应时已经完成。

服务端按去除 `**`、归一化弯引号、空白和大小写后的原文去重。命中已有未删除句子时会合并重点词并返回已有 ID，没有 `reused` 字段；不会把同一句当作新的句子。若已有整句译文为空，可用本次非空译文补齐。成功状态仍为 `200`。

### PUT `/api/english/sentences/{sentence_id}`

请求体 `SentenceWrite`，返回更新后的 `Sentence`。需要提交希望保留的全部可写字段。

改变实际英文而继续提交原先未修改的翻译内容时，服务端会清理已经失效的译文/词义并安排补译；实际原文或目标音色改变也可能触发音频更新。仅调整重点词标记通常可保留现有译文和整句音频，仍应使用服务端返回结果刷新界面。

错误：`404` 不存在；与其他句子重合 `409 {"detail":"相同句子已存在：#2"}`；字段校验 `422`。

### DELETE `/api/english/sentences/{sentence_id}`

无请求体，返回 `{"ok":true}`。软删除，保留历史计数和事件；普通列表、详情和音频不再提供该句。重复删除返回 `404`。目前没有恢复接口。

### POST `/api/english/sentences/bulk`

```json
{
  "items": [
    {"text":"Progress depends on **consistent** practice."},
    {"text":"A **consistent** routine can help."}
  ]
}
```

`items` 必填，1—2000 个 `SentenceWrite`，事务内保存。返回：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `items` | Sentence[] | 对应输入项的保存结果；重复句子可能返回相同 ID |
| `created` | integer | 新增数量 |
| `reused` | integer | 复用数量 |

复用项合并重点词；**批量复用分支不会用提交的整句译文替换/补齐已有译文**，需修改译文时调用 PUT。提交后会安排缺失内容生成；校验失败 `422`，业务输入错误 `400`。

<a id="review"></a>
## 5. 复习队列、完成和播放记录

### 获取本轮安排

```http
GET /api/english/sentences?sort=smart&round_queue=true&resume=true&page_size=40
```

响应在普通分页对象上增加 `review_round`，每个 `items[]` 在 `Sentence` 上增加下表字段。列表键使用 `review_round_item_id`，因为完成记录绑定的是本轮安排项。

| 队列项额外字段 | 类型 | 说明 |
| --- | --- | --- |
| `review_round_item_id` | integer | 本轮安排 ID；提交完成时使用 |
| `review_round_position` | integer | 本轮从 1 开始的安排位置 |
| `review_repeat_index` | integer | 该句本轮第几次出现，当前固定为 1 |
| `review_repeat_total` | integer | 该句本轮总安排次数，当前固定为 1 |
| `review_exposure` | number | 生成安排时保存的接触度指标 |
| `review_round_item_completed` | boolean | 该安排当前是否已完成 |

`review_round`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | integer | 复习周期 ID，与安排 ID 不同 |
| `started_at` | string | 周期开始时间 |
| `expires_at` | string | 周期到期时间；建轮时按冻结安排数确定，之后不随句子集合变化 |
| `completed` | integer | 已完成安排数量 |
| `total` | integer | 当前未删除句子的安排总数 |
| `remaining` | integer | 剩余安排数量 |
| `is_completed` | boolean | 非空周期是否已全部完成；空周期为 false |
| `next_round_at` | string | 提前完成后的下轮开始时间，尚无时 `""` |
| `available` | integer | 当前可见安排数，目前等同 `total` |
| `available_remaining` | integer | 当前可见未完成安排数，目前等同 `remaining` |
| `resume_page` | integer | 首个未完成安排所在页；无未完成项时为 1 |

分页外层 `total` 也是**安排数量**。队列页会包含已完成项，客户端可以在展示时隐藏，但不能用隐藏后的数量推算服务器页数。`resume=true` 时使用服务端返回的 `page`；创建新周期时强制返回第 1 页，其他队列请求的页号会被限制在现有页范围内。

周期规则：周期天数在建轮时按冻结安排数计算为 `max(1, ceil(安排数 / 100))`，每句每轮只安排一次。100 是规划依据，**不是每日完成上限**；整轮始终可见，可自由多做、少做或提前完成。北京时间 08:00 为边界。服务端后台自动推进到期周期，读取队列也会补偿调度延迟。刷新、完成、后台调度和重启都不会改变当前轮的 item ID、position、完成状态或到期时间；周期中新增句子只进入下一周期。软删除句子从可见队列和进度中排除，但不会移动其他安排。提前完成时等到完成时刻之后的下一个北京时间 08:00 才开启新周期。App 恢复前台、到达 `expires_at` / 非空 `next_round_at` 或收到过期结果时应重新获取队列。

建议进度只作提醒，沿用以上字段，不增加接口字段：以 `started_at` 到 `expires_at` 的天数为 D，按北京时间 08:00 计算今天为第 d 个学习日（1—D），截至今天建议累计完成 `ceil(review_round.total × d / D)` 项。与 `completed` 比较，显示还差多少或已超前多少；最后一天的建议累计数等于本轮总数。当前轮冻结，历史周期不变。

新周期排序以紧邻上一轮为参考。上一轮缺席或未完成的句子优先，上一轮已完成的句子随后；组内按 `5 × 上一轮曝光分 - 上一轮之前历史曝光分` 降序，同分按句子 ID 升序。曝光分沿用整句播放权重 1.0、重点词播放权重 0.2 和 `g(c) = (1 - 0.35^c) / (1 - 0.35)`。历史曝光必须先从累计播放次数中扣除上一轮播放次数，再应用衰减。播放和完成事件在 `metadata_json` 中记录 `round_id`、`round_item_id`。

### GET `/api/english/flow/queue`

Query：`limit: integer = 20`，范围 1—100。

返回 `{supported: true, stats: Stats, items: QueueSentence[], total, page, page_size, review_round}`。相当于统计加上 `smart + round_queue + resume` 队列入口，`page_size=limit`；恢复时 `page` 可能不是 1。该接口无 page 参数，要继续翻页请用 `/sentences`。

### POST `/api/english/sentences/{sentence_id}/review`

同一个接口处理两种不同事件，Android 应始终发送明确请求体。

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `event_type` | string | `sentence_review` | `sentence_play` 播放；`sentence_review` 完成复习 |
| `complete_round_item` | boolean | `true` | 完成模式是否提交安排完成 |
| `round_item_id` | integer/null | `null` | 非空时 ≥1；取自队列的 `review_round_item_id` |

整句音频实际开始播放后，上报一次：

```json
{
  "event_type": "sentence_play",
  "complete_round_item": false,
  "round_item_id": 101
}
```

用户点击“完成这次复习”后：

```json
{
  "event_type": "sentence_review",
  "complete_round_item": true,
  "round_item_id": 101
}
```

| 事件 | 整句播放计数 | 完成计数 | 安排完成状态 |
| --- | --- | --- | --- |
| `sentence_play` | +1 | 不变 | 不变，即使误传 `complete_round_item=true` |
| `sentence_review` 且完成成功 | 不变 | +1 | 完成指定安排 |
| `sentence_review` 且 `complete_round_item=false` | 不变 | 不变 | 不变 |
| 重复完成同一安排 | 不变 | 不变 | 保持已完成 |

返回 `Sentence`，再增加：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `review_round_item_completed` | boolean | **本次请求是否新完成一个安排**，与队列里同名字段的含义不同 |
| `review_round_item_is_completed` | boolean/缺省 | 完成请求对应安排的真实状态；重复提交已完成安排仍为 true。播放事件不返回此字段 |
| `review_round` | object/null | 完成请求后的周期进度快照，字段同队列的 `review_round`，但不含 `resume_page`；无法确定时为 null |
| `review_round_id` | integer/null | 本次核对的周期 ID |
| `review_round_completed` | boolean | 完成请求核对后，本轮是否全部完成；重复提交也返回真实状态 |
| `review_round_expired` | boolean | 本次尝试完成时周期已过期，或指定安排已不属于当前周期 |
| `review_round_item_id` | integer/null | 完成的安排 ID，或回显传入 ID；无 ID 时可能为 null |
| `review_round_next_at` | string | 整轮已完成时的下轮时间；重试不会推迟它，否则 `""` |

重复完成仍可能是 **200 + `review_round_item_completed=false`**，此时用 `review_round_item_is_completed` 和 `review_round` 恢复真实完成状态及累计进度。只有响应周期 ID 与当前页面周期一致时才能合并；同周期乱序响应不能回退已知完成数。`review_round_expired=true` 或新状态字段缺失时刷新队列，不能仅凭 200 或 ID 回显判断成功。

请求体缺省、`null` 或 `{}` 会默认尝试完成；不传安排 ID 会选择该句当前最早未完成安排。未知 `event_type` 会被当作 `sentence_review`。为避免完成错误安排，客户端始终传合法枚举、明确布尔值及原安排 ID。

句子不存在返回 `404`。播放事件不去重，不能在超时后无条件重发；完成请求携带相同安排 ID 可防止重复计数，但跨轮仍需重新核对。

<a id="focus"></a>
## 6. 重点词操作

### POST `/api/english/sentences/{sentence_id}/words/{word}/play`

无请求体。`word` 使用当前重点词键，作为一个路径段正确 URL 编码；短语中的空格应编码为 `%20`，不要用表单编码的 `+`。

该接口**记录单词播放**，返回更新后的 `Sentence`，不是音频文件。先用 `pronunciations[word]` 播放，实际开始播放后才上报。预加载和重复缓冲回调不应重复上报。

错误：未知重点词 `400 {"detail":"word is not a focus word in this sentence"}`，句子不存在 `404`。同一请求多次发送会多次计数。

### POST `/api/english/sentences/{sentence_id}/focus-word`

```json
{"word":"consistent","action":"mark"}
```

| 字段 | 类型 | 必填 | 默认/约束 |
| --- | --- | --- | --- |
| `word` | string | 是 | 1—255 字符，选择原文已有词或短语 |
| `action` | string | 否 | `toggle`；可用 `mark`、`unmark`、`toggle` |

`mark` 给首个匹配处添加标记，`unmark` 移除该词匹配的标记和相应词义/提示/计数；`toggle` 切换，未知 action 也按 toggle。返回更新后的 `Sentence`，每次成功调用都会记录一次标注事件。

应从原文选择词，并以返回的 `text` 和映射刷新 UI；匹配不到原文时不能仅凭 200 认定成功插入标记。新词词义可能为空。此接口本身不提交翻译或音频生成任务；需要补词义时调用 `/translate/words`，将结果合并后用句子 PUT 保存，后续生成遵从保存流程。

错误：空/无效词 `400`，句子不存在 `404`，字段校验 `422`。重试 toggle 可能反向切换；有明确目标状态时优先发送 mark/unmark，并避免重复上报事件。

<a id="translation"></a>
## 7. AI 翻译

这两个接口都是同步生成接口。**返回的是草稿，不会保存到句子；即使传入 `sentence_id` 也不会保存。**

### POST `/api/english/translate`

| 字段 | 类型 | 必填 | 默认/约束 |
| --- | --- | --- | --- |
| `text` | string | 是 | 1—12000 字符 |
| `words` | string[]/null | 否 | `null`；待制词卡的词或短语 |
| `sentence_id` | integer/null | 否 | `null`；非空 ≥1，仅用于查找邻句上下文 |

```json
{
  "text":"Progress depends on **consistent** practice.",
  "words":["consistent"],
  "sentence_id":1
}
```

`words` 省略或为 null 时从 `**…**` 范围中按英文单词提取；短语要完整制卡时请显式传完整短语。传 `[]` 表示不生成词卡，只做整句翻译与分块。服务端修剪词首尾空白/标点、忽略大小写去重，最多处理 40 项；此接口的输入数组本身没有 40 项校验上限。

`sentence_id` 只有在已保存原文与请求 `text` 完全一致时才用于补充有限的邻句上下文；不存在或文本不一致时忽略上下文，不返回 404。翻译源文会移除重点标记和含中文的方括号注释，保留英文原文内容。

返回 `TranslationDraft`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `items` | WordTranslationItem[] | 词卡数组 |
| `word_translations` | object<string,string> | 重点词词义映射 |
| `word_tips` | object<string,string> | 重点词提示映射 |
| `word_evidence_required` | boolean | 此结果是否要求词卡带双语证据 |
| `sentence_translation` | string | 整句中文译文 |
| `sentence_segments` | string[] | 英文分块 |
| `translation_segments` | string[] | 中文分块 |
| `quality_audit` | object | 可扩展的质量诊断，不作为业务状态机 |

`WordTranslationItem` 有必备 `word: string`、`translation: string`，以及可缺省的 `tip: string`、`source_quote: string`、`translation_quote: string`。后两者分别是英文、中文证据片段。

新生成的 `translation` 和对应 `word_translations[word]` 使用同一条 `本义：…；句中：…；英文：…` 文本。英文部分使用简单英语解释当前句中的词义；不会新增 `english_definition` 响应字段。

```json
{
  "items": [{
    "word":"consistent",
    "translation":"本义：一贯的，持续的；句中：持续的；英文：done regularly in the same way",
    "tip":"在这里形容练习持续、稳定。",
    "source_quote":"consistent practice",
    "translation_quote":"持续的练习"
  }],
  "word_translations":{"consistent":"本义：一贯的，持续的；句中：持续的；英文：done regularly in the same way"},
  "word_tips":{"consistent":"在这里形容练习持续、稳定。"},
  "word_evidence_required":true,
  "sentence_translation":"进步离不开持续的练习。",
  "sentence_segments":["Progress depends on","consistent practice."],
  "translation_segments":["进步离不开","持续的练习。"],
  "quality_audit":{}
}
```

若不能安全细分，允许整句只返回一块，不能据此判定生成失败。对历史数据的分块长度不一致情况应回退显示整句。

### POST `/api/english/translate/words`

仅生成词卡，保留客户端已有整句译文。

| 字段 | 类型 | 必填 | 默认/约束 |
| --- | --- | --- | --- |
| `text` | string | 是 | 1—12000 字符 |
| `words` | string[] | 是 | **1—40 项** |
| `sentence_translation` | string | 否 | `""`，最多 12000 字符；建议提供已确认译文作为依据 |
| `sentence_id` | integer/null | 否 | `null`，非空 ≥1；上下文规则同上 |

返回 `{items: WordTranslationItem[], word_translations: map, word_tips: map}`，没有整句译文、分块或 `quality_audit` 字段。全部输入词被清理为空时可返回空数组和空映射。

共同错误：未配置翻译服务 `400 {"detail":"English translation AI provider is not configured"}`；AI 请求或输出校验失败一般 `424`；限额或限流 `429`；参数 `422`。服务端生成可能经过多阶段请求，没有固定完成时长。当前本地前端代理的上游超时为 120 秒，外部代理也可能更早终止；客户端延长超时不能改变代理限制。

保存草稿时将需要的映射、译文和分块合并到完整 `SentenceWrite`，再 POST 创建或 PUT 修改。不要只把 TranslationDraft 原样发送：它没有可写请求中必需的 `text`，且可能只包含本次新词的映射。

<a id="passages"></a>
## 8. 阅读文章

### Passage 模型

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id`、`user_id` | integer | 文章、所属用户 ID |
| `title` | string | 标题 |
| `source_label` | string | 来源名称 |
| `source_url` | string | 来源 URL，可为 `""` |
| `year` | integer/null | 年份，1900—2200 或 null |
| `exam_type` | string | 通常 `english1`、`english2` 或 `""`；非严格枚举 |
| `passage_type` | string | `reading_a`、`cloze`、`reading_b`、`translation`、`custom` |
| `body_text` | string | 保存的全文，可含 `**重点词/短语**` 标记 |
| `status` | string | `new`、`reading`、`done` |
| `selected_sentence_ids` | integer[] | 已关联到句子库的句子 ID |
| `completed_at` | string | 首次完成时间，未完成时 `""` |
| `deleted_at` | string | 软删除时间，正常时 `""` |
| `created_at`、`updated_at` | string | 创建、更新时间 |

当前响应**不包含**候选句数组、精读分析或 `intensive` 对象。

创建/更新使用 `PassageWrite`：

| 字段 | 类型 | 必填 | 默认/约束 |
| --- | --- | --- | --- |
| `title`、`source_label` | string | 否 | `""`，各最多 500 字符 |
| `source_url` | string | 否 | `""`，最多 2000 字符 |
| `year` | integer/null | 否 | `null`；请求体内超出 1900—2200 会归一化为 null |
| `exam_type` | string | 否 | `""`，最多 80 字符；已知别名归一化，其他值可保留并截断到 40 字符 |
| `passage_type` | string | 否 | `custom`，最多 80 字符；已知别名归一化，未知值变成 custom |
| `body_text` | string | 是 | 1—120000 字符，不能全为空白 |
| `status` | string | 否 | `new`；未知值归一化为 new |

### GET `/api/english/passages`

| Query 参数 | 类型 | 默认 | 约束/说明 |
| --- | --- | --- | --- |
| `page` | integer | `1` | ≥1 |
| `page_size` | integer | `20` | 1—100 |
| `status` | string | `""` | 空为全部；new/reading/done，未知非空值按 new 筛选 |
| `passage_type` | string | `""` | 空为全部；未知非空值按 custom 筛选 |
| `exam_type` | string | `""` | 试卷类型，通常 english1/english2 |
| `year` | integer，可省略 | 无 | 1900—2200，查询参数越界是 422 |
| `search` | string | `""` | 搜索标题、来源标签、文章类型及正文 |
| `include_deleted` | boolean | `false` | 是否包含软删除文章 |

返回：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `items` | Passage[] | 当前页文章，顺序由服务端训练排序决定 |
| `total`、`page`、`page_size` | integer | 总数、页号、页大小 |
| `today` | Passage/null | 今日推荐首篇 |
| `today_items` | Passage[] | 今日推荐，最多 2 篇 |

推荐从**本次筛选后的完整结果集**选取，不只从当前页选取。一般优先 reading_a，并尽量各选一篇英语一/英语二；当日已完成文章可继续保留在今日推荐中。不要把 `today_items` 等同于“未完成列表”。

### GET `/api/english/passages/today`

无参数，返回 `{"item": Passage}` 或 `{"item": null}`，是未附加筛选的今日推荐首篇。需要两篇时使用列表接口的 `today_items`。

### GET `/api/english/passages/{passage_id}`

返回 `Passage`。不存在、非当前用户所属或已删除返回 `404 {"detail":"阅读文章不存在"}`。

### POST `/api/english/passages`

请求体 `PassageWrite`，返回 `Passage`。示例：

```json
{
  "title":"Practice and progress",
  "source_label":"示例阅读",
  "source_url":"",
  "year":2026,
  "exam_type":"english2",
  "passage_type":"reading_a",
  "body_text":"Progress depends on **consistent** practice.\n\nSmall steps build **confidence**.",
  "status":"new"
}
```

创建时始终是 `new`，即使请求传入 reading/done。仅保存文章，不会自动同步句子；没有文章去重协议，超时后重发可能重复创建。

### PUT `/api/english/passages/{passage_id}`

请求体 `PassageWrite`，返回 `Passage`。完整替换可写内容，省略 metadata 会清空，省略 status 会重置 new。已关联的句子 ID 和首次完成时间不由该请求修改。

把 status 改为 done **不会填写 `completed_at`**；记录完成使用下面的 `/complete`。对正文新增的标注要再次同步才进入句子库。

### DELETE `/api/english/passages/{passage_id}`

无请求体，返回 `{"ok":true}`。软删除文章，不连带删除已同步到句子库的句子。重复删除 `404`；没有文章恢复接口。

### POST `/api/english/passages/{passage_id}/sync-sentences`

把**已保存正文中含重点词标记的句子**同步到句子库。可选请求体：

```json
{"candidate_indexes":[0,2]}
```

`candidate_indexes` 为整数数组。**省略请求体、传 null、`{}` 或 `[]` 都表示同步全部候选**，不能用空数组表示“一个也不选”。

候选索引是从 0 开始的“含标记且去重后的候选数组”位置，不是原文所有句子的下标。服务端按空段落和 `. ! ? 。！？` 分句，保留包含 `**…**` 的句子，按归一化原文去重并保持顺序。当前没有候选预览接口；Android 首版建议提供“同步全部标注句”。若实现部分选择，需要与服务端分句、标记识别、去重算法一致，并确保预览后正文没有被其他操作改动。

重复索引去重，负数和越界索引忽略；非空数组中没有任何有效索引时 `400`。包含缩写、句内标点等文本时，服务端的规则分句未必与 Android 的语言分句器一致。

返回：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `passage` | Passage | 更新后的文章 |
| `sentences` | Sentence[] | 本次同步得到的句子 |
| `inserted` | integer | 新增句子数 |
| `reused` | integer | 复用已有句子数 |

将新 ID 追加到 `selected_sentence_ids` 并去重，不删除之前关联。未完成文章变为 reading，已完成文章保持 done。安排缺失翻译/发音/句子音频生成；新增句子要到下个复习周期进入安排。

错误：`400 {"detail":"文章还没有手工标注句子"}`、`400 {"detail":"no valid sentence candidates selected"}`，或文章不存在 `404`。

### POST `/api/english/passages/{passage_id}/complete`

无请求体，返回 `Passage`。设置 done，并在首次完成时写入 completed_at；重复调用保留首次完成时间，更新时间可改变。文章不存在 `404`。文章完成不等于句子复习完成，不增加句子播放或完成次数。

创建/更新文章的空白正文错误为 `400 {"detail":"body_text is required"}`，字段长度/类型错误为 `422`。

<a id="audio"></a>
## 9. 音色、生成与音频文件

### GET `/api/english/audio/settings`

返回 `AudioSettings`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `global` | object | 全局句子音色，见下方 |
| `voices` | Voice[] | 服务端音色目录，按返回值构建选择器 |
| `sample_text` | string | 当前试听文本，如 relatively |
| `sentences` | object | 未删除句子的音频设置统计 |
| `sentences.total` | integer | 句子总数 |
| `sentences.overridden` | integer | 有独立音色的句子数 |
| `sentences.following_global` | integer | 跟随全局的句子数 |
| `sentences.pending` | integer | 状态为 pending 的句子数；不是实时任务进度 |

`global` 包含 `provider: string`、`voice: string`、`source: "environment" | "database"`、`updated_at: string`。来源为环境默认值时 updated_at 可为空。

`Voice` 的全部字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `provider` | string | 当前 edge 或 kokoro |
| `voice` | string | 音色标识，如 en-US-JennyNeural |
| `name` | string | 展示名，如 Jenny |
| `accent` | string | 口音标签，如 美式/英式 |
| `gender` | string | 声线标签 |
| `grade` | string | 目录提供的评级，没有时为空 |
| `description` | string | 音色简介 |
| `available` | boolean | 当前部署是否具备使用条件 |

不要把全部 Kokoro 音色视为已经安装，也不要硬编码声线列表。available 表示本地可用条件，不保证外部 TTS 服务一定请求成功。

### PUT `/api/english/audio/settings`

```json
{"provider":"edge","voice":"en-US-JennyNeural"}
```

使用 `AudioSelection` 请求模型：`provider: string = ""`（≤40 字符）、`voice: string = ""`（≤120 字符）、`use_global: boolean = false`。在本接口中必须提供有效 provider/voice，use_global 不参与全局设置。

返回 `AudioSettings`。此操作保存全局偏好，改变跟随全局句子的目标音色；**不会直接为已有句子批量生成新音频**。需要应用到已有句子时再调用 `/apply`。错误 `400`：`不支持这个英语音色` / `这个音色尚未安装`。

### POST `/api/english/audio/settings/apply`

无请求体。按全局目标音色为需要更新的句子安排后台生成，跳过有单句覆盖的对象，也跳过已有且匹配当前目标的文件。

返回 `{queued: integer, unchanged: integer, following_global: integer, global: GlobalAudioSettings}`。`queued` 只表示本次安排数量，不代表生成完成；没有任务 ID 或进度订阅接口。

### PUT `/api/english/sentences/{sentence_id}/audio-settings`

同样使用 `AudioSelection`。指定单句音色：

```json
{"provider":"edge","voice":"en-US-AriaNeural","use_global":false}
```

恢复跟随全局：

```json
{"use_global":true}
```

返回 `Sentence`。需要时自动安排整句音频生成。use_global 为 true 时忽略 provider/voice 并清除覆盖。错误：音色 `400`，句子 `404`，参数 `422`。

### POST `/api/english/audio/previews`

```json
{"provider":"edge","voice":"en-US-JennyNeural"}
```

provider 必填、1—40 字符；voice 必填、1—120 字符。同步生成或复用试听后返回：

```json
{
  "provider":"edge",
  "voice":"en-US-JennyNeural",
  "audio_url":"/api/english/audio/previews/edge/en-US-JennyNeural?v=1789257600",
  "cached":true
}
```

`cached` 当前在成功响应中总为 true，表示试听文件已可获取，**不能据此判断本次是否命中已有缓存**。生成失败 `503 {"detail":"音色试听生成失败，请稍后重试"}`；无效音色 `400`；限流 `429`。

### GET `/api/english/audio/previews/{provider}/{voice}`

读取已生成试听文件；不会隐式生成。需要 Cookie。不存在返回 `404 {"detail":"试听音频不存在"}`。正常按文件类型返回 `audio/wav` 或 `audio/mpeg`。

### GET `/api/english/audio/{sentence_id}`

读取当前文本与目标音色对应的整句音频，需要 Cookie。**路径是 `/audio/{sentence_id}`**，不是 `/sentences/{sentence_id}/audio`。

成功返回文件，Content-Type 为 `audio/wav` 或 `audio/mpeg`；不可用、已过期或句子已删除返回 `404 {"detail":"音频不存在"}`。应优先使用句子返回的 audio_url，避免手拼并误用旧缓存。

### GET `/api/english/pronunciations/{sentence_id}/{filename}`

读取单词发音文件，需要 Cookie，成功 Content-Type 为 `audio/mpeg`。filename 是不透明的文件名，直接使用 pronunciations 中的 URL。不存在返回 `404 {"detail":"单词音频不存在"}`。

### 媒体共同规则

三类 GET 都是二进制响应。当前后端 FileResponse 支持 `Range`，合法区间返回 `206`、`Accept-Ranges: bytes`、`Content-Range`；普通请求 `200`。本次在隔离后端验证了分段响应，线上代理仍需实际播放器联调。响应可含 `Content-Length`、`Last-Modified`、`ETag`、`Content-Disposition: attachment; filename=…`。**未声明 HEAD 路由，当前 HEAD 返回 405**，不要依赖 HEAD 预检。

`?v=…` 是 URL 缓存版本；按原值保留，不用客户端重算时间戳。媒体 GET 不记录学习次数，应在播放器实际开始后分别调用整句/单词播放事件接口。Android 的 Media3 数据源要使用与 API 相同的 CookieJar；JSON 接口能访问而播放器 401，通常是 Cookie 没有传到媒体请求。

生成完成后获取句子详情可看到 audio_available、audio_url、pronunciations 的变化。translation_pending、pending 和 queued 不是持久化任务队列的进度承诺；后台失败可能一直缺内容。客户端采用有上限的轮询，保留人工重试入口。

<a id="stats"></a>
## 10. 统计与热力图

### GET `/api/english/stats`

Query：`include_word_network: boolean = true`。false 时**省略** word_network 字段，适合轻量刷新。

返回 `Stats`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `total` | integer | 所有句子数，含软删除 |
| `active` | integer | 未删除句子数 |
| `with_audio` | integer | 未删除且数据库音频元数据完整/ready 的数量；不逐一核验文件或当前目标音色 |
| `sentence_reviews` | integer | 句子保存的整句播放计数总和，含软删除 |
| `sentence_completions` | integer | 句子保存的复习完成计数总和，含软删除 |
| `word_reviews` | integer | 句子保存的重点词播放总数，含软删除 |
| `tracked` | ReviewTotals | 从历史事件表统计的累计值 |
| `legacy` | ReviewTotals | 保存的累计计数减去可追踪事件数，最低为 0 |
| `today` | TodayStats | UTC 当日统计 |
| `word_network` | WordNetworkSummary，可缺省 | 全部有效句子的词网络概况 |

`ReviewTotals` 包含 `sentence_reviews`、`sentence_completions`、`word_reviews`、`total_reviews`，均为 integer。**total_reviews = 整句播放 + 单词播放，不含复习完成或标注事件**。去掉重点词会清理对应的句子词计数，因此保存的计数与历史事件不一定始终相等；客户端分别使用服务器提供的口径。

`TodayStats`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `reviewed_sentences` | integer | 当日有完成事件的不同句子数，同句多次完成只算一个 |
| `sentence_reviews` | integer | 当日整句播放次数 |
| `sentence_completions` | integer | 当日完成安排次数 |
| `word_reviews` | integer | 当日单词播放次数 |
| `focus_toggles` | integer | 当日标注操作次数 |

`WordNetworkSummary`：`word_peak: number`、`cross_sentence_words: integer`、`weak_words: WeakWord[]`（当前最多 8 项）。WeakWord 的全部字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `key` | string | 归一化词键 |
| `surfaces` | string[] | 常见展示词形，当前最多 4 个 |
| `linked_sentences` | integer | 关联句子数 |
| `contexts` | integer | 语境数 |
| `played_edges` | integer | 已有播放接触的语境数 |
| `total_play_count` | integer | 词播放次数 |
| `avg_exposure` | number | 平均接触度 |
| `familiarity` | number | 熟悉度 |
| `weakness` | number | 薄弱程度 |

### GET `/api/english/heatmap`

Query：`days: integer = 119`，7—370。返回按日期升序的完整窗口，零活动日期也包含在内。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `days` | HeatmapDay[] | 每日数据 |
| `start_date`、`end_date` | string | 窗口起止 UTC 日期，YYYY-MM-DD，含两端 |
| `window_days` | integer | 窗口天数 |
| `max_count` | integer | 窗口内单日 total 最大值 |
| `active_days` | integer | 窗口内 total > 0 的天数 |
| `total_reviews` | integer | **窗口内**整句播放 + 单词播放 |
| `tracked_sentence_reviews`、`tracked_word_reviews`、`tracked_total_reviews` | integer | **全历史**可追踪播放事件数，与窗口无关 |
| `legacy_sentence_reviews`、`legacy_word_reviews`、`legacy_total_reviews` | integer | 未被事件记录覆盖的历史播放计数 |
| `lifetime_sentence_reviews`、`lifetime_word_reviews`、`lifetime_total_reviews` | integer | 保存的累计播放计数，包含软删除句子 |
| `current_streak` | integer | 从今日倒推的连续活跃天数，受窗口限制；今日无播放则为 0 |
| `longest_streak` | integer | 此窗口内最长连续活跃天数 |

`HeatmapDay`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `date` | string | UTC 日期 |
| `weekday` | integer | 0=周一，…，6=周日 |
| `sentence_reviews` | integer | 当日整句播放数 |
| `word_reviews` | integer | 当日单词播放数 |
| `focus_toggles` | integer | 当日标注操作数 |
| `total` | integer | 整句播放 + 单词播放 |

完成复习和标注不会增加 total 或点亮热力图。Android 图表直接采用返回的日期和计数，避免将英文复习的“完成”与“播放”混算。

<a id="workflows"></a>
## 11. 客户端工作流与同步约束

### 最小连通示例

本节命令在支持 curl 的终端执行。创建仅当前用户可读的临时 Cookie 文件；登录 JSON 文件由开发者填写，包含 `{"password":"…"}`，不要提交到仓库。

```bash
umask 077
api_cookie_file=$(mktemp)
api_base='https://204.xpliang.tech'

curl -fsS -c "$api_cookie_file" \
  -H 'Content-Type: application/json' \
  -H 'X-Study-Write: 1' \
  --data-binary @login.local.json \
  "$api_base/api/auth/login"

curl -fsS -b "$api_cookie_file" \
  "$api_base/api/auth/me"

curl -fsS -b "$api_cookie_file" \
  "$api_base/api/english/sentences?sort=smart&round_queue=true&resume=true&page_size=40"
```

从队列读取句子 ID 和安排 ID，再替换示例中的 `1` 与 `101`：

```bash
curl -fsS -b "$api_cookie_file" \
  -H 'Content-Type: application/json' \
  -H 'X-Study-Write: 1' \
  --data '{"event_type":"sentence_review","complete_round_item":true,"round_item_id":101}' \
  "$api_base/api/english/sentences/1/review"

curl -fsS -b "$api_cookie_file" -c "$api_cookie_file" \
  -H 'X-Study-Write: 1' -X POST \
  "$api_base/api/auth/logout"

rm -f "$api_cookie_file"
```

### 建议实现顺序

1. 登录并保存 Cookie，`/auth/me` 校验会话；401 后统一转到登录并保留未提交草稿。
2. 获取普通句子列表、详情、阅读列表，完成分页和空值处理。
3. 获取复习队列，以安排 ID 管理列表项；整句/词音频使用同一会话，实际播放后单独上报事件。
4. 实现明确的“完成”按钮，保存返回结果并刷新队列；切前台或周期到期时恢复服务器安排。
5. 实现标注、翻译草稿与完整 PUT 保存，随后按需刷新生成状态。
6. 加入文章同步、音色设置、统计与热力图。

### 异步生成与重试

保存句子/批量/同步等响应意味着数据已保存；生成仍可能进行中。可在页面可见时以逐步放慢的间隔读取详情，例如 2、4、8 秒，然后停止自动轮询并提供手动刷新。退出页面要取消轮询；这些时间是客户端建议，不是后端 SLA。

| 操作 | 断网/超时后处理 |
| --- | --- |
| 列表、详情、媒体 GET | 可有限重试；复习队列 GET 可能触发周期补偿，应采用最新响应 |
| 翻译草稿/试听 | 允许用户重试，但会消耗限额；保留旧草稿，不无限自动调用 |
| 完成指定安排 | 先查询队列确认，可重试同一安排 ID，不能换 ID 重放 |
| 整句/单词播放计数 | 没有幂等键，超时代表结果未知；不要自动重发或离线批量回灌 |
| 标注 toggle | 可能反向切换；重新读取，再发送明确目标状态 |
| 创建文章 | 没有去重键，先核对列表，避免重复创建 |
| PUT 保存 | 先保留本地草稿并核对最新服务端内容；不要覆盖另一端更新 |

### 当前能力边界

当前系统单用户，没有注册、修改密码 API、用户管理、音频上传、恢复软删除、历史事件列表、复习历史轮次列表、手动重建周期、算法设置 API、WebSocket、推送、增量同步游标、ETag 写冲突检测或通用幂等键。不要根据前端内部函数名或历史测试路径推测额外 API。

支持本地缓存展示，但没有完整离线同步协议。多端编辑采取最后一次保存生效，`updated_at` 只可辅助发现变化，服务端不会据它拒绝覆盖。复习安排必须以服务端返回为准，Android 不自行生成下一轮。客户端不得包含服务端 AI 密钥；翻译统一通过现有 API 调用。

<a id="index"></a>
## 12. 接口索引

除健康/登录外都使用会话；退出允许无会话。所有写操作均需要 `X-Study-Write: 1`。

| # | 方法 | 路径 | 功能 |
| --- | --- | --- | --- |
| 1 | GET | `/api/health` | 健康检查 |
| 2 | POST | `/api/auth/login` | 密码登录 |
| 3 | POST | `/api/auth/logout` | 退出会话 |
| 4 | GET | `/api/auth/me` | 当前用户 |
| 5 | GET | `/api/english/stats` | 统计 |
| 6 | GET | `/api/english/heatmap` | 热力图 |
| 7 | GET | `/api/english/audio/settings` | 音色目录与设置 |
| 8 | PUT | `/api/english/audio/settings` | 保存全局音色 |
| 9 | POST | `/api/english/audio/settings/apply` | 应用全局音色生成 |
| 10 | POST | `/api/english/audio/previews` | 生成试听 |
| 11 | GET | `/api/english/audio/previews/{provider}/{voice}` | 试听文件 |
| 12 | GET | `/api/english/sentences` | 句子列表或复习队列 |
| 13 | POST | `/api/english/sentences` | 创建/复用句子 |
| 14 | GET | `/api/english/flow/queue` | 恢复队列与统计 |
| 15 | POST | `/api/english/translate` | 整句翻译草稿 |
| 16 | POST | `/api/english/translate/words` | 词卡草稿 |
| 17 | GET | `/api/english/passages` | 阅读列表及今日推荐 |
| 18 | POST | `/api/english/passages` | 创建文章 |
| 19 | GET | `/api/english/passages/today` | 今日首篇 |
| 20 | GET | `/api/english/passages/{passage_id}` | 文章详情 |
| 21 | PUT | `/api/english/passages/{passage_id}` | 保存文章 |
| 22 | DELETE | `/api/english/passages/{passage_id}` | 删除文章 |
| 23 | POST | `/api/english/passages/{passage_id}/sync-sentences` | 同步标注句 |
| 24 | POST | `/api/english/passages/{passage_id}/complete` | 完成阅读 |
| 25 | GET | `/api/english/sentences/{sentence_id}` | 句子详情 |
| 26 | PUT | `/api/english/sentences/{sentence_id}` | 保存句子 |
| 27 | DELETE | `/api/english/sentences/{sentence_id}` | 删除句子 |
| 28 | POST | `/api/english/sentences/bulk` | 批量新增/复用 |
| 29 | PUT | `/api/english/sentences/{sentence_id}/audio-settings` | 单句音色 |
| 30 | POST | `/api/english/sentences/{sentence_id}/review` | 记录播放/完成 |
| 31 | POST | `/api/english/sentences/{sentence_id}/words/{word}/play` | 记录词播放 |
| 32 | POST | `/api/english/sentences/{sentence_id}/focus-word` | 重点词标注 |
| 33 | GET | `/api/english/audio/{sentence_id}` | 句子音频 |
| 34 | GET | `/api/english/pronunciations/{sentence_id}/{filename}` | 重点词音频 |
