# Android 客户端接入指南

对应 2026-09-13 的 204 英语复习服务。完整字段和全部 34 个接口见 [API 参考](api-reference.md)；生成 DTO 或导入调试工具使用 [OpenAPI](openapi.json)。本指南提供网络层与播放器接入示例，不是一个已构建的 Android 工程。

## 1. 接入方式

使用 `https://204.xpliang.tech/` 作为 Retrofit base URL，保留结尾 `/`。接口声明使用 `api/…` 相对路径。系统以 Cookie 鉴权，没有 access_token/refresh_token；登录 JSON 只有 password，用户名固定 admin。

AndroidManifest.xml 声明网络权限：

```xml
<uses-permission android:name="android.permission.INTERNET" />
```

项目需要这些库，版本采用你项目中兼容的稳定版本；Retrofit 与其 converter 使用相同版本，所有 Media3 模块使用相同版本。

| Maven 坐标 | 用途 |
| --- | --- |
| `com.squareup.okhttp3:okhttp` | HTTP 与 CookieJar |
| `com.squareup.retrofit2:retrofit` | API 接口 |
| `com.squareup.retrofit2:converter-kotlinx-serialization` | JSON 转换 |
| `org.jetbrains.kotlinx:kotlinx-serialization-json` | DTO 序列化 |
| `androidx.media3:media3-exoplayer` | 播放器 |
| `androidx.media3:media3-datasource-okhttp` | 使用同一会话获取音频 |

DTO 示例使用 Kotlin serialization，还需启用与项目 Kotlin 版本一致的 `org.jetbrains.kotlin.plugin.serialization` 插件。

## 2. Cookie 与写保护

下面是可直接用于单次运行的内存 CookieJar。它按名称、域和路径更新 Cookie，处理过期/退出，发送时由 OkHttp 的匹配规则判断 HTTPS、域及路径。

```kotlin
import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.HttpUrl

class MemoryCookieJar : CookieJar {
    private data class Key(val name: String, val domain: String, val path: String)
    private val stored = linkedMapOf<Key, Cookie>()

    @Synchronized
    override fun saveFromResponse(url: HttpUrl, cookies: List<Cookie>) {
        val now = System.currentTimeMillis()
        stored.entries.removeAll { it.value.expiresAt <= now }
        for (cookie in cookies) {
            val key = Key(cookie.name, cookie.domain, cookie.path)
            if (cookie.expiresAt <= now) stored.remove(key)
            else stored[key] = cookie
        }
    }

    @Synchronized
    override fun loadForRequest(url: HttpUrl): List<Cookie> {
        val now = System.currentTimeMillis()
        stored.entries.removeAll { it.value.expiresAt <= now }
        return stored.values.filter { it.matches(url) }
    }

    @Synchronized
    fun clear() = stored.clear()
}
```

此实现进程退出后需要重新登录。正式客户端可替换成持久化 CookieJar：使用 Android Keystore 保护的密钥加密 Cookie 存储，保留 domain、path、expiresAt、secure、httpOnly 和 hostOnly 属性，恢复时清除过期项并执行相同匹配。CookieJar 回调是同步的，先在内存提供快照，再异步落盘，避免每个请求都阻塞读取 DataStore。退出要同时清理内存和持久化副本。

会话固定 14 天，不滑动续期。保存 Cookie 即可，不保存登录密码，也不要把登录体、Cookie 或 Set-Cookie 写入日志。401 时让用户重新登录，不在后台无限尝试旧密码。

所有 POST/PUT/DELETE，包括登录退出，都加固定写保护头。不要伪造 Origin/Referer：

```kotlin
import okhttp3.HttpUrl
import okhttp3.Interceptor
import okhttp3.Response

class StudyWriteInterceptor(private val origin: HttpUrl) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        val sameOrigin = request.url.scheme == origin.scheme &&
            request.url.host == origin.host && request.url.port == origin.port
        val isWrite = request.method in setOf("POST", "PUT", "DELETE")
        val outgoing = if (sameOrigin && isWrite) {
            request.newBuilder().header("X-Study-Write", "1").build()
        } else request
        return chain.proceed(outgoing)
    }
}
```

## 3. 最小 Retrofit 网络层

```kotlin
import java.util.concurrent.TimeUnit
import kotlinx.serialization.json.Json
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory

val apiOrigin = "https://204.xpliang.tech/".toHttpUrl()
val sessionCookies = MemoryCookieJar()
val apiJson = Json {
    ignoreUnknownKeys = true
    encodeDefaults = true
}

val apiHttp = OkHttpClient.Builder()
    .cookieJar(sessionCookies)
    .addInterceptor(StudyWriteInterceptor(apiOrigin))
    .retryOnConnectionFailure(false)
    .connectTimeout(15, TimeUnit.SECONDS)
    .readTimeout(120, TimeUnit.SECONDS)
    .callTimeout(150, TimeUnit.SECONDS)
    .build()

val studyApi = Retrofit.Builder()
    .baseUrl(apiOrigin)
    .client(apiHttp)
    .addConverterFactory(apiJson.asConverterFactory("application/json".toMediaType()))
    .build()
    .create(StudyApi::class.java)
```

`encodeDefaults=true` 让显式设计的默认字段也出现在 JSON 中。例如播放请求的 `complete_round_item=false` 不能因为序列化省略而被后端默认成 true。重试由业务层按操作决定，示例关闭 OkHttp 连接失败重试，避免有副作用的请求被无意重复发送。读请求可额外实现有限重试。

示例超时用于给 AI 请求留出等待空间，不是服务端完成时长保证。代理可能提前超时；超时后仍保留编辑草稿，允许取消和人工重试。不要给所有请求强制添加 `Accept: application/json`，同一个客户端还需要播放二进制音频。

核心 DTO 如下，未使用的响应字段由 ignoreUnknownKeys 跳过。完整模型可从 OpenAPI 生成；生成后仍应按本指南接入 CookieJar 和写保护头。

```kotlin
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class LoginRequest(val password: String)

@Serializable
data class UserDto(
    val id: Long,
    val username: String,
    @SerialName("display_name") val displayName: String,
    @SerialName("created_at") val createdAt: String? = null,
)

@Serializable
data class AuthResponse(val user: UserDto)

@Serializable
data class OkResponse(val ok: Boolean)

@Serializable
data class SentenceDto(
    val id: Long,
    val text: String,
    @SerialName("word_translations") val wordTranslations: Map<String, String>,
    @SerialName("word_tips") val wordTips: Map<String, String>,
    @SerialName("sentence_translation") val sentenceTranslation: String,
    @SerialName("sentence_segments") val sentenceSegments: List<String>,
    @SerialName("translation_segments") val translationSegments: List<String>,
    @SerialName("translation_pending") val translationPending: Boolean,
    @SerialName("audio_available") val audioAvailable: Boolean,
    @SerialName("audio_status") val audioStatus: String,
    @SerialName("audio_url") val audioUrl: String,
    val pronunciations: Map<String, String>,
    @SerialName("review_count") val reviewCount: Long,
    @SerialName("completion_count") val completionCount: Long,
    @SerialName("updated_at") val updatedAt: String,
    @SerialName("review_round_item_id") val roundItemId: Long? = null,
    @SerialName("review_round_item_completed") val roundItemCompleted: Boolean? = null,
)

@Serializable
data class ReviewRoundDto(
    val id: Long,
    @SerialName("started_at") val startedAt: String,
    @SerialName("expires_at") val expiresAt: String,
    val completed: Int,
    val total: Int,
    val remaining: Int,
    @SerialName("is_completed") val isCompleted: Boolean,
    @SerialName("next_round_at") val nextRoundAt: String,
    @SerialName("resume_page") val resumePage: Int = 1,
)

@Serializable
data class SentencePageDto(
    val items: List<SentenceDto>,
    val total: Int,
    val page: Int,
    @SerialName("page_size") val pageSize: Int,
    @SerialName("review_round") val reviewRound: ReviewRoundDto? = null,
)

@Serializable
data class SentenceWrite(
    val text: String,
    @SerialName("word_translations") val wordTranslations: Map<String, String>,
    @SerialName("word_tips") val wordTips: Map<String, String>,
    @SerialName("sentence_translation") val sentenceTranslation: String,
    @SerialName("sentence_segments") val sentenceSegments: List<String>,
    @SerialName("translation_segments") val translationSegments: List<String>,
)

fun SentenceDto.toWrite() = SentenceWrite(
    text, wordTranslations, wordTips, sentenceTranslation,
    sentenceSegments, translationSegments,
)

@Serializable
data class ReviewRequest(
    @SerialName("event_type") val eventType: String,
    @SerialName("complete_round_item") val completeRoundItem: Boolean,
    @SerialName("round_item_id") val roundItemId: Long?,
)

// newlyCompleted 保留写入语义；itemIsCompleted 和 reviewRound 用于恢复真实状态。
@Serializable
data class ReviewResultDto(
    val id: Long,
    @SerialName("review_count") val reviewCount: Long,
    @SerialName("completion_count") val completionCount: Long,
    @SerialName("review_round_item_completed") val newlyCompleted: Boolean,
    @SerialName("review_round_item_is_completed") val itemIsCompleted: Boolean? = null,
    @SerialName("review_round") val reviewRound: ReviewRoundDto? = null,
    @SerialName("review_round_id") val roundId: Long? = null,
    @SerialName("review_round_completed") val roundCompleted: Boolean,
    @SerialName("review_round_expired") val roundExpired: Boolean,
    @SerialName("review_round_item_id") val roundItemId: Long?,
    @SerialName("review_round_next_at") val nextRoundAt: String,
)
```

```kotlin
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Path
import retrofit2.http.Query

interface StudyApi {
    @POST("api/auth/login")
    suspend fun login(@Body body: LoginRequest): Response<AuthResponse>

    @GET("api/auth/me")
    suspend fun me(): Response<AuthResponse>

    @POST("api/auth/logout")
    suspend fun logout(): Response<OkResponse>

    @GET("api/english/sentences")
    suspend fun sentences(
        @Query("page") page: Int = 1,
        @Query("page_size") pageSize: Int = 40,
        @Query("sort") sort: String = "smart",
        @Query("round_queue") roundQueue: Boolean = false,
        @Query("resume") resume: Boolean = false,
        @Query("search") search: String = "",
    ): Response<SentencePageDto>

    @GET("api/english/sentences/{id}")
    suspend fun sentence(@Path("id") id: Long): Response<SentenceDto>

    @PUT("api/english/sentences/{id}")
    suspend fun saveSentence(
        @Path("id") id: Long,
        @Body body: SentenceWrite,
    ): Response<SentenceDto>

    @POST("api/english/sentences/{id}/review")
    suspend fun review(
        @Path("id") id: Long,
        @Body body: ReviewRequest,
    ): Response<ReviewResultDto>

    @POST("api/english/sentences/{id}/words/{word}/play")
    suspend fun wordPlay(
        @Path("id") id: Long,
        @Path("word") word: String,
    ): Response<SentenceDto>
}
```

Retrofit 的 `@Path` 默认进行编码，传原始重点词即可，不要先手工 URL 编码再交给它。词可能是短语；使用接口返回的键，不擅自改小写、分词或词形。

各代码块可按职责拆为不同 Kotlin 文件；`okhttp3.Response` 与 `retrofit2.Response` 属于不同文件中的 import，若合并同一文件请使用 import alias。

## 4. 复习的正确交互

首次进入：

```kotlin
val response = studyApi.sentences(roundQueue = true, resume = true)
if (response.isSuccessful) {
    val page = requireNotNull(response.body())
    // 用 page.page 作为实际页号，保留 page.reviewRound。
    // 本轮 LazyColumn 的 key 使用 requireNotNull(item.roundItemId)。
}
```

普通句子库列表可使用句子 ID；复习队列使用安排 ID。不要因为两个项有相同 sentence.id 就去重。页内可以包含已完成项，展示过滤不改变服务端分页；翻下一页时 `resume=false` 并使用上一响应的 page + 1。

实际开始播放时：

```kotlin
suspend fun reportSentencePlayback(item: SentenceDto): Response<ReviewResultDto> =
    studyApi.review(
        item.id,
        ReviewRequest(
            eventType = "sentence_play",
            completeRoundItem = false,
            roundItemId = item.roundItemId,
        ),
    )
```

用户完成一个安排时：

```kotlin
suspend fun completeArrangement(item: SentenceDto): Response<ReviewResultDto> =
    studyApi.review(
        item.id,
        ReviewRequest(
            eventType = "sentence_review",
            completeRoundItem = true,
            roundItemId = requireNotNull(item.roundItemId),
        ),
    )
```

请求期间禁用同一项的重复完成操作。完成请求超时后可用原安排 ID 重试；用 itemIsCompleted 和 reviewRound 恢复真实状态与完成数，newlyCompleted=false 只表示没有新增完成记录。仅合并与当前周期 ID 一致的响应，同周期乱序响应不能降低已知完成数。roundExpired=true 或兼容旧服务端时缺少状态字段，则重新获取队列。播放事件仍不能无条件重试。

退出复习页面再回来、App 恢复前台、到达 expiresAt 或非空 nextRoundAt 时刷新队列。周期天数在建轮时按冻结安排数计算为 `max(1, ceil(安排数 / 100))`；刷新和完成不会改变当前轮的 item ID、position 或期限，新增句子只进入下一周期，软删除句子从可见队列移除但不移动其他项。周期和北京时间 08:00 边界由后端决定，设备改时区不改变服务端安排。整轮可自由复习，每日完成量不受限，已有接口路径、字段和类型保持兼容。

客户端如需累计提醒，可用 startedAt、expiresAt 计算周期天数 D，按北京时间 08:00 计算今天为第 d 个学习日，建议累计 `ceil(total × d / D)` 项，再与 completed 比较显示差额或超前量。建议进度不用于禁用按钮或截断队列。

## 5. Media3 使用同一会话

```kotlin
import android.content.Context
import androidx.media3.common.MediaItem
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.okhttp.OkHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import okhttp3.HttpUrl

fun resolveMediaUrl(relative: String): HttpUrl {
    require(relative.isNotBlank())
    val resolved = requireNotNull(apiOrigin.resolve(relative))
    require(resolved.scheme == apiOrigin.scheme &&
        resolved.host == apiOrigin.host && resolved.port == apiOrigin.port)
    return resolved
}

@UnstableApi
fun createStudyPlayer(context: Context): ExoPlayer =
    ExoPlayer.Builder(context)
        .setMediaSourceFactory(
            DefaultMediaSourceFactory(OkHttpDataSource.Factory(apiHttp)),
        )
        .build()

// 在持有 player 的页面或播放服务中：
// val player = createStudyPlayer(context)
// if (sentence.audioAvailable && sentence.audioUrl.isNotBlank()) {
//     player.setMediaItem(MediaItem.fromUri(resolveMediaUrl(sentence.audioUrl).toString()))
//     player.prepare()
//     player.play()
// }
```

保留 `?v=…`，Media3 自行发送 Range 请求；不要预先 HEAD。单词音频同样用 `sentence.pronunciations[word]`。不要把完整 Set-Cookie 当作 Cookie 请求头，也不要捕获登录时的旧 Cookie 字符串永久写入播放器默认请求头；共享 CookieJar 才能及时处理重新登录和退出。

播放计数建议以“一次用户发起的播放”为单位创建本地播放意图 ID。第一次 `onIsPlayingChanged(true)` 时记录该意图已上报并发送事件；暂停恢复、缓冲结束和 Range 请求不重复上报。用户主动重播则创建新意图。上报失败或超时不自动重发，因为没有服务端幂等键；本地去重只能防重复回调，不能实现服务端恰好一次统计。

退出登录时停止播放器、清理本地 Cookie 和缓存；如果播放由前台服务持有，页面销毁不应误删服务中的播放器。按实际播放生命周期调用 `release()`。

## 6. 保存、翻译与阅读

修改时先以最新 SentenceDto.toWrite() 构造完整请求，再 copy 修改字段。新词卡结果往往只有本次词的映射，需要与原有词义/提示合并。同步修改 text 中的标记，否则保存时未标记词的映射会被修整。

`POST /translate`、`POST /translate/words` 返回草稿，调用成功后还要 PUT 保存；sentence_id 只提供上下文。句子保存成功后的缺失译文和音频可通过详情轮询刷新，建议逐渐降低频率并设置上限，不把 translation_pending 显示成确定的任务进度。

阅读文章的 `year` 是 nullable；空日期是 `""`。列表的 `today_items` 最多两篇，`/passages/today` 只返回 item。文章 PUT 会重置省略字段，包括 status；完成阅读使用 `/complete`。同步文章标注句时空 candidate_indexes 代表全部，用户未选择任何条目时应直接取消操作，不发送空数组。

## 7. 错误、时间与缓存

Retrofit 接口返回 Response<T>，先判断 isSuccessful；网络中断/取消等仍可能抛 IOException 或 CancellationException。不要吞掉协程取消。errorBody 只能消费一次，示例解析器兼容 detail 字符串、detail 数组和 error：

```kotlin
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

fun apiErrorMessage(response: retrofit2.Response<*>): String {
    val raw = response.errorBody()?.string().orEmpty()
    val obj = runCatching { apiJson.parseToJsonElement(raw) }
        .getOrNull() as? JsonObject
    val fallback = "HTTP ${response.code()}"
    return when (val detail = obj?.get("detail")) {
        is JsonPrimitive -> detail.contentOrNull ?: fallback
        is JsonArray -> detail.joinToString("；") { entry ->
            val error = entry as? JsonObject
            val location = (error?.get("loc") as? JsonArray)
                ?.joinToString(".") { (it as? JsonPrimitive)?.contentOrNull.orEmpty() }
                .orEmpty()
            val message = (error?.get("msg") as? JsonPrimitive)
                ?.contentOrNull ?: "参数不合法"
            if (location.isBlank()) message else "$location: $message"
        }.ifBlank { fallback }
        else -> (obj?.get("error") as? JsonPrimitive)?.contentOrNull ?: fallback
    }
}
```

| 情况 | App 行为 |
| --- | --- |
| 401 | 统一结束已失效的本地会话，跳到登录，保留未提交草稿 |
| 403 | 检查写保护头和 Origin，不循环登录 |
| 409 | 保留草稿，提示句子重复并读取最新数据 |
| 422 | 展示对应字段错误 |
| 429 | 读取可选 Retry-After；不存在时有限退避，用户可取消 |
| 424/503 | 保留内容并提供明确重试入口 |
| 非 JSON 网关错误 | 按 HTTP 状态提示，不展示整页代理 HTML |
| 写请求超时 | 结果未知，按具体接口先查询确认，避免盲目重放 |

新时间可用 `OffsetDateTime.parse(value).toInstant()`；空字符串转 null，历史 `yyyy-MM-dd HH:mm:ss` 按 UTC 解析。低于 API 26 使用 java.time 时配置 core library desugaring。热力图 date 是 UTC 日期，weekday 为 0=周一；直接用后端日期分组，不能按设备午夜重新切分。

缓存建议用 Room 保存展示数据和本地编辑草稿，队列项以安排 ID 唯一标识，并保留所属 round.id。服务器没有增量游标、写冲突令牌、推送或离线事件去重协议；恢复网络后重新拉取队列，不自动回放旧轮次的完成、播放和 toggle。

## 8. 联调顺序

1. 登录后确认 /auth/me 返回用户，进程重启后验证持久化 Cookie（若已实现）。
2. 用同一 Cookie 播放句子和单词音频，确认不依赖 HEAD，URL 的 v 参数保留。
3. 一次实际播放只增加一次播放计数；预加载、缓冲和恢复不增加。
4. 当前周期每句只展示一个安排；重复完成同一个安排不会增加 completion_count。
5. 翻译生成后明确保存，修改一个字段不会清空其他词义和分块。
6. 验证 401、403、422、429、空列表、空译文、未生成音频和非 JSON 超时响应。
7. 验证周期跨界/切前台刷新及北京时间 08:00 的统计日期口径。

本机开发时，Android 的 127.0.0.1 是设备本身。后端运行在模拟器宿主机时可使用 `10.0.2.2:8204`；USB 调试可通过 `adb reverse tcp:8204 tcp:8204` 转发宿主机端口。远程服务器不在这两个地址上，直接使用线上 HTTPS。只有 debug HTTP 场景需要明文网络配置与开发服务器的非 Secure Cookie；线上继续使用 HTTPS。
