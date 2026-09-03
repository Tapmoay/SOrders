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
        }
        val client = OkHttpClient.Builder()
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
            .baseUrl(BuildConfig.API_BASE_URL.trimEnd('/') + "/" + API_PREFIX)
            .client(client)
            .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
            .build()

        return ApiBundle(
            authApi = retrofit.create(AuthApi::class.java),
            userApi = retrofit.create(UserApi::class.java),
            orderApi = retrofit.create(OrderApi::class.java),
            shipperApi = retrofit.create(ShipperApi::class.java),
            ledgerApi = retrofit.create(LedgerApi::class.java),
            notificationApi = retrofit.create(NotificationApi::class.java),
            productApi = retrofit.create(ProductApi::class.java),
            arrearsApi = retrofit.create(ArrearsApi::class.java),
            inventoryApi = retrofit.create(InventoryApi::class.java),
            priceRuleApi = retrofit.create(PriceRuleApi::class.java),
            freightTemplateApi = retrofit.create(FreightTemplateApi::class.java),
            freightSettlementApi = retrofit.create(FreightSettlementApi::class.java),
            reportApi = retrofit.create(ReportApi::class.java),
            accountingApi = retrofit.create(AccountingApi::class.java),
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
            ApiException(detail ?: ("请求失败(" + e.code() + ")"), code = e.code(), cause = e)
        }
        else -> ApiException(e.message ?: "未知错误", code = -1, cause = e)
    }

    private fun parseDetail(body: String?): String? {
        if (body.isNullOrBlank()) return null
        return try {
            val obj = json.parseToJsonElement(body)
            val d = (obj as? kotlinx.serialization.json.JsonObject)?.get("detail")
            when (d) {
                is kotlinx.serialization.json.JsonPrimitive -> d.content.takeIf { it.isNotBlank() }
                is kotlinx.serialization.json.JsonArray -> d.firstOrNull()?.let {
                    (it as? kotlinx.serialization.json.JsonObject)?.get("msg")?.toString()
                        ?.trim('"') ?: "参数错误"
                } ?: "参数错误"
                else -> null
            }
        } catch (_: Exception) { null }
    }
}

data class ApiBundle(
    val authApi: AuthApi,
    val userApi: UserApi,
    val orderApi: OrderApi,
    val shipperApi: ShipperApi,
    val ledgerApi: LedgerApi,
    val notificationApi: NotificationApi,
    val productApi: ProductApi,
    val arrearsApi: ArrearsApi,
    val inventoryApi: InventoryApi,
    val priceRuleApi: PriceRuleApi,
    val freightTemplateApi: FreightTemplateApi,
    val freightSettlementApi: FreightSettlementApi,
    val reportApi: ReportApi,
    val accountingApi: AccountingApi,
)