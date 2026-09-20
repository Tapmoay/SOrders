package com.tapmoay.sorders.core

import com.tapmoay.sorders.BuildConfig
import android.os.Build

/** 后端 API 地址统一出口：
 * 优先连接构建配置 api_base_url（当前=生产服务器 https://sorders.top）；
 * 模拟器在服务器不可达时自动回退本机后端 http://10.0.2.2:8000（兜底开发联调）。
 * 探测结果进程内缓存（首次访问时探测，服务器可达时约 200ms）。
 */
object ApiEndpoint {

    @Volatile
    private var _resolved: String? = null

    val baseUrl: String
        get() {
            _resolved?.let { return it }
            val primary = BuildConfig.API_BASE_URL
            val resolved = when {
                primary.startsWith("http://10.0.2.2") -> primary // 显式本地联调配置：不探测
                probe(primary) -> primary
                // ⚠️ 兜底**只给 debug**（2026-09-19 全项目报告 C-1）：
                //    发布包一旦允许"服务器不可达就退回本机 http://10.0.2.2:8000"，
                //    ① 它会去连一个连不上的明文地址（发布包已经 `cleartextTrafficPermitted=false`）；
                //    ② 更要紧的是语义：真机上的正式版**不许**因为探测失败就换一个后端 ——
                //       那会让界面显示另一套数据而用户毫不知情。
                BuildConfig.DEBUG && isEmulator() -> "http://10.0.2.2:8000"
                else -> primary
            }
            _resolved = resolved
            return resolved
        }

    /** 服务器可达性探测（/health 接口，2.5s 超时） */
    private fun probe(url: String): Boolean {
        return try {
            val req = okhttp3.Request.Builder()
                .url(url.trimEnd('/') + "/health")
                .get()
                .build()
            NetworkDns.okHttp.newCall(req).execute().use { resp ->
                resp.code in 200..499 // 含 401/404 都说明服务在线
            }
        } catch (e: Exception) {
            android.util.Log.e("ApiEndpoint", "probe failed for " + url + " : " + e)
            false
        }
    }

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
