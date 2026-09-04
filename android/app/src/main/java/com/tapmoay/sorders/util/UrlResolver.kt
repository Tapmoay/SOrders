package com.tapmoay.sorders.util

import com.tapmoay.sorders.BuildConfig

/** 后端返回 /static/... 相对路径，拼上 API_BASE_URL 成完整地址 */
fun resolveStaticUrl(path: String?): String? {
    if (path.isNullOrBlank()) return null
    return if (path.startsWith("http")) path
    else com.tapmoay.sorders.core.ApiEndpoint.baseUrl.trimEnd('/') + "/" + path.trimStart('/')
}