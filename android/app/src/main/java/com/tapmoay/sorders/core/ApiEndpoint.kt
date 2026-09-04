package com.tapmoay.sorders.core

import com.tapmoay.sorders.BuildConfig
import android.os.Build

/** 后端 API 地址统一出口：
 * - 模拟器自动走 10.0.2.2（宿主机映射，不依赖物理 IP，永不超时）
 * - 真机使用 local.properties 的 api_base_url（需与电脑局域网 IP 一致）
 */
object ApiEndpoint {
    val baseUrl: String
        get() = if (isEmulator()) "http://10.0.2.2:8000" else BuildConfig.API_BASE_URL

    fun isEmulator(): Boolean {
        val fp = Build.FINGERPRINT ?: ""
        return fp.contains("generic", true) ||
            fp.contains("emulator", true) ||
            fp.contains("vbox", true) ||
            (Build.MODEL ?: "").contains("Emulator", true) ||
            (Build.MODEL ?: "").contains("Android SDK", true) ||
            (Build.MODEL ?: "").startsWith("sdk_gphone", true) ||
            (Build.PRODUCT ?: "").startsWith("sdk", true)
    }
}
