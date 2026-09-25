package com.tapmoay.sorders.core

import com.tapmoay.sorders.BuildConfig
import com.tapmoay.sorders.data.remote.api.*
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.HttpException
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import java.io.IOException
import java.net.SocketTimeoutException
import java.util.concurrent.TimeUnit

/** 统一业务异常：message 直接可展示给用户 */
class ApiException(
    message: String,
    val code: Int = -1,
    cause: Throwable? = null,
) : Exception(message, cause)

/** 后端全部 REST 路由都在 /api/v1/ 下 */
const val API_PREFIX = "api/v1/"

object ApiClient {

    val json = Json {
        ignoreUnknownKeys = true
        coerceInputValues = true
        explicitNulls = false
        encodeDefaults = true
    }

    fun create(tokenStore: TokenStore, onSessionExpired: () -> Unit = {}): ApiBundle {
        val interceptor = HttpLoggingInterceptor().apply {
            level = if (BuildConfig.DEBUG_LOG) HttpLoggingInterceptor.Level.BODY
            else HttpLoggingInterceptor.Level.NONE
            // ⛔ 日志里**不许出现会话令牌**（2026-09-19 全项目报告 P0-2，high）：
            //    这个日志拦截器加在下面的 Auth 拦截器**之后**，所以它看到的请求**已经带上**
            //    `Authorization: Bearer <JWT>` —— 一条 `adb logcat -s okhttp.OkHttpClient`
            //    就能把派单员的令牌读走（24 小时有效）。
            //    ⚠️ `redactHeader` 只管**请求/响应头**，管不到**请求体**：登录口令在 body 里，
            //    那条只能靠"生产不发 debug 包"根治（release 的 `DEBUG_LOG = false`，
            //    见 `app/build.gradle.kts` 的 release 块）。
            redactHeader("Authorization")
            redactHeader("Cookie")
        }
        val client = OkHttpClient.Builder()
            .dns(NetworkDns.dns)
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .writeTimeout(60, TimeUnit.SECONDS)
            .addInterceptor { chain ->
                val token = tokenStore.cachedToken()
                val req = chain.request().newBuilder()
                    .apply {
                        if (!token.isNullOrBlank()) {
                            header("Authorization", "Bearer " + token)
                        }
                        header("Accept", "application/json")
                    }
                    .build()
                val resp = chain.proceed(req)
                if (resp.code == 401 && token != null && !req.url.encodedPath.contains("auth/")) {
                    onSessionExpired()
                }
                resp
            }
            .addInterceptor(interceptor)
            .build()

        val retrofit = Retrofit.Builder()
            .baseUrl(ApiEndpoint.baseUrl.trimEnd('/') + "/" + API_PREFIX)
            .client(client)
            // 报告 §15 ②：把「这一行审计是 AI 写的」这件事带上去。
            // ⛔ 必须走 callFactory（见 OriginAwareCallFactory 的说明）——
            //    写成 addInterceptor 的话线程不对，头会永远是 null 且不报任何错。
            .callFactory(OriginAwareCallFactory(client))
            .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
            .build()

        return ApiBundle(
            authApi = retrofit.create(AuthApi::class.java),
            userApi = retrofit.create(UserApi::class.java),
            orderApi = retrofit.create(OrderApi::class.java),
            shipperApi = retrofit.create(ShipperApi::class.java),
            placeApi = retrofit.create(PlaceApi::class.java),
            unitConversionsApi = retrofit.create(UnitConversionsApi::class.java),
            ledgerApi = retrofit.create(LedgerApi::class.java),
            shipperLedgerApi = retrofit.create(ShipperLedgerApi::class.java),
            notificationApi = retrofit.create(NotificationApi::class.java),
            productApi = retrofit.create(ProductApi::class.java),
            arrearsApi = retrofit.create(ArrearsApi::class.java),
            orderTemplateApi = retrofit.create(OrderTemplateApi::class.java),
            supplierApi = retrofit.create(SupplierApi::class.java),
            inventoryApi = retrofit.create(InventoryApi::class.java),
            priceRuleApi = retrofit.create(PriceRuleApi::class.java),
            freightTemplateApi = retrofit.create(FreightTemplateApi::class.java),
            driverBillingRuleApi = retrofit.create(DriverBillingRuleApi::class.java),
            freightSettlementApi = retrofit.create(FreightSettlementApi::class.java),
            reportApi = retrofit.create(ReportApi::class.java),
            accountingApi = retrofit.create(AccountingApi::class.java),
            systemApi = retrofit.create(SystemApi::class.java),
            usageApi = retrofit.create(UsageApi::class.java),
            fileApi = retrofit.create(FileApi::class.java),
            rawApi = retrofit.create(RawApi::class.java),
        )
    }

    /** 把任意异常转成 ApiException（UI 可直接展示 message） */
    fun toApiException(e: Throwable): ApiException = when (e) {
        is ApiException -> e
        is SocketTimeoutException -> ApiException("连接超时，请检查网络", code = -2, cause = e)
        is IOException -> ApiException("网络连接失败：" + (e.message ?: "无法连接服务器"), code = -3, cause = e)
        is HttpException -> {
            val body = e.response()?.errorBody()?.string()
            val detail = parseDetail(body)
            ApiException(httpMessage(e.code(), detail), code = e.code(), cause = e)
        }
        else -> ApiException(e.message ?: "未知错误", code = -1, cause = e)
    }

    /**
     * HTTP 错误码 + 后端给的 `detail` → 一句**能照着判断**的中文。
     *
     * ### 为什么必须有它（2026-09-21 两次踩同一个坑）
     * 原来这里直接把 `detail` 甩出去。于是：
     * · 后端**路由不存在**时 FastAPI 回的是 `{"detail":"Not Found"}` → 屏幕上就是一行**英文**。
     *   真事：手机上派单员「退货申请」显示红字 `Not Found`，用户读成"连接失败/没找到"，
     *   而真相是"服务端还没发版"——排查方向被带偏了整整一轮。
     * · 后端 **500** 时 `detail` 常常是空的 → 界面上没有可用信息，用户只能反复重试。
     *   （`IOException` 那条才是真正的"网络连接失败"，两者必须分得开。）
     *
     * ### 规矩：后端自己写的中文一律原样透出
     * 那些是**业务拒绝**（"这张退货申请已经办完了，不能办理"、"逐单核销需绑定订单"），
     * 是用户唯一能照着改的话，翻译一遍只会变差。
     */
    internal fun httpMessage(code: Int, detail: String?): String {
        val zh = detail?.takeIf { d -> d.any { it in '\u4e00'..'\u9fa5' } }
        if (zh != null) return zh
        return when {
            code == 404 ->
                "服务器上还没有这个功能（接口不存在，404）。" +
                    "如果 App 是刚更新的，多半是服务端还没更新到这个版本。"
            code >= 500 ->
                "服务器出错了（$code），不是网络问题。请稍后重试；一直这样就把它告诉管理员。"
            code == 401 || code == 403 -> "登录已失效或没有这个权限（$code），请重新登录后再试。"
            !detail.isNullOrBlank() -> "请求失败（$code）：$detail"
            else -> "请求失败（$code）"
        }
    }

    /**
     * 从错误体里抠出一句**能照着改**的话。
     *
     * ### 为什么 Pydantic 的英文原文不能直接给用户
     * 后端 422 的 `detail` 是一个数组，每项形如
     * `{"loc":["body","order_ids"],"msg":"List should have at most 100 items","type":"too_long"}`。
     * 直接显示 `msg` 的结果是用户在手机上看到一句英文（"List should have at most 100 items"），
     * 既不知道是哪个字段，也不知道该改成多少——而这类 422 恰恰**全都能自助修好**
     * （选太多了、手机号少一位、拆单份数超了）。
     *
     * 所以这里把最常见的几类校验翻成人话（**带字段名与上限**），认不出来的一律给一句
     * 能行动的中文兜底，绝不把英文原文甩给用户。
     */
    private fun parseDetail(body: String?): String? {
        if (body.isNullOrBlank()) return null
        return try {
            val obj = json.parseToJsonElement(body)
            val d = (obj as? kotlinx.serialization.json.JsonObject)?.get("detail")
            when (d) {
                is kotlinx.serialization.json.JsonPrimitive -> d.content.takeIf { it.isNotBlank() }
                is kotlinx.serialization.json.JsonArray -> {
                    val first = d.firstOrNull() as? kotlinx.serialization.json.JsonObject
                    val raw = first?.get("msg")?.toString()?.trim('"')
                    humanizeValidation(raw)
                }
                else -> null
            }
        } catch (_: Exception) { null }
    }

    /** Pydantic 的 `msg`（英文）→ 一句中文。见 [parseDetail] 的注释。 */
    internal fun humanizeValidation(msg: String?): String? {
        val m = msg?.trim().orEmpty()
        if (m.isEmpty()) return "提交的内容不符合要求，请检查后重试"
        val zh = m.contains(Regex("[\\u4e00-\\u9fa5]"))
        if (zh) return m  // 后端自己写的中文（自定义校验器）原样用
        return when {
            m.startsWith("List should have at most") -> {
                val n = Regex("\\d+").find(m)?.value
                "一次最多只能选 ${n ?: "规定数量的"} 项，请少选一些再提交"
            }
            m.startsWith("List should have at least") -> {
                val n = Regex("\\d+").find(m)?.value
                "至少要选 ${n ?: "规定数量的"} 项"
            }
            m.contains("String should match pattern") -> "格式不对（例如手机号要 11 位数字），请检查后重试"
            m.contains("String should have at least") -> "内容太短了，请填写完整"
            m.contains("String should have at most") -> "内容太长了，请精简一些"
            m.contains("Input should be greater than or equal to") -> "数值太小了（不能小于允许的下限）"
            m.contains("Input should be less than or equal to") -> "数值太大了（超过允许的上限）"
            m.contains("Field required") -> "有必填项没有填"
            m.contains("Input should be a valid") -> "填写的内容格式不对，请检查后重试"
            else -> "提交的内容不符合要求，请检查后重试"
        }
    }
}

data class ApiBundle(
    val authApi: AuthApi,
    val userApi: UserApi,
    val orderApi: OrderApi,
    val shipperApi: ShipperApi,
    /** 共享地点库（导航信息）：不按人分区，三种角色共用一张表。 */
    val placeApi: PlaceApi,
    /**
     * 单位换算（一车 = 8 方，2026-09-24）。
     *
     * ⚠️ 全库共用一张表（不是按人分区）：货主下的单与派单员看的同一张单必须是同一个数。
     */
    val unitConversionsApi: UnitConversionsApi,
    val ledgerApi: LedgerApi,
    /** 货主**自己那一本账**（批发商给下游货主的核销）：与 [ledgerApi] 是两本账，见接口注释。 */
    val shipperLedgerApi: ShipperLedgerApi,
    val notificationApi: NotificationApi,
    val productApi: ProductApi,
    val arrearsApi: ArrearsApi,
    /** 预订单（订单模板，2026-09-22）。 */
    val orderTemplateApi: OrderTemplateApi,
    val supplierApi: SupplierApi,
    val inventoryApi: InventoryApi,
    val priceRuleApi: PriceRuleApi,
    val freightTemplateApi: FreightTemplateApi,
    val driverBillingRuleApi: DriverBillingRuleApi,
    val freightSettlementApi: FreightSettlementApi,
    val reportApi: ReportApi,
    val accountingApi: AccountingApi,
    val systemApi: SystemApi,
    /** 常用度：只清**我自己**的计数（「我的 → 基础设置 → 重置计数」）。 */
    val usageApi: UsageApi,
    /** AI 助手「挂载文件」：上传表格让服务端读成文本（不保存文件）。 */
    val fileApi: FileApi,
    /** 动态 GET（只给 AI 通用读工具用，路径来自编译期白名单，见 [RawApi]）。 */
    val rawApi: RawApi,
)

/**
 * 把 [ClientOrigin] 记下的来源变成一个请求头（报告 §15 ② 的 `AI_write_confirmed`）。
 *
 * ## ⛔ 为什么挂在 `callFactory` 上，而不是 `addInterceptor`
 * OkHttp 的**应用拦截器跑在 dispatcher 线程**上（`enqueue` 之后由线程池执行），
 * 而 [ClientOrigin] 是 ThreadLocal —— 拦截器那条线程上根本读不到它。
 * `Call.Factory.newCall()` 则是在**调用者线程**上同步调用的（Retrofit 的 suspend 桥接里
 * 就是协程当前线程），所以只有这里读得到。
 *
 * ⚠️ 这个区别不是"风格"问题：写成 `addInterceptor` 编译得过、请求也发得出去，
 *    只是那个头永远是 null —— 而"少一个头"不会报任何错，只会让
 *    `sorders_ai_write_confirmed_today` 恒为 0，看起来像"最近没人用 AI 写东西"。
 */
internal class OriginAwareCallFactory(
    private val delegate: okhttp3.Call.Factory,
) : okhttp3.Call.Factory {

    override fun newCall(request: okhttp3.Request): okhttp3.Call {
        // 不在 AI 写入的那一段里时**原样透传**（不加头 → 后端按 human 记）。
        val origin = ClientOrigin.current() ?: return delegate.newCall(request)
        return delegate.newCall(
            request.newBuilder().header(ClientOrigin.HEADER, origin).build(),
        )
    }
}