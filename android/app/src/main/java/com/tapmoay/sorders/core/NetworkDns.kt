package com.tapmoay.sorders.core

import com.tapmoay.sorders.BuildConfig
import okhttp3.Dns
import okhttp3.OkHttpClient
import java.net.InetAddress
import java.net.URI
import java.net.UnknownHostException

/**
 * 网络 DNS 解析兜底：
 * 系统 DNS 解析失败时（如部分 Android 模拟器环境 DNS 异常），
 * 将 API 域名固定解析到构建配置的 IP（local.properties -> api_fallback_ip），
 * URL 仍保持 https://域名 语义，TLS SNI 与证书校验均按域名进行，不被破坏。
 * 真机系统 DNS 正常时走系统解析，永不触发兜底。
 */
object NetworkDns {

    private val apiHost: String? = runCatching { URI(BuildConfig.API_BASE_URL).host }.getOrNull()

    val dns: Dns = object : Dns {
        override fun lookup(hostname: String): List<InetAddress> {
            return try {
                Dns.SYSTEM.lookup(hostname)
            } catch (e: UnknownHostException) {
                val ip = BuildConfig.DNS_FALLBACK_IP
                if (ip.isNotBlank() && hostname.equals(apiHost, ignoreCase = true)) {
                    listOf(InetAddress.getByName(ip))
                } else {
                    throw e
                }
            }
        }
    }

    /** Socket.IO 底层走 OkHttp（polling / websocket），需注入带覆写 DNS 的 client；
     * 探测 /health 也用本 client（快速失败：连接 4s / 读 8s） */
    val okHttp: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .dns(dns)
            .connectTimeout(4, java.util.concurrent.TimeUnit.SECONDS)
            .readTimeout(8, java.util.concurrent.TimeUnit.SECONDS)
            .build()
    }
}
