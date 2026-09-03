package com.tapmoay.sorders.util

import android.content.Context
import android.content.Intent
import android.net.Uri

/**
 * 唤起高德 App 导航（androidamap:// route 协议，与 Web 端 amapNav.ts 对齐）。
 * 未安装高德 App 时回退到高德 H5 导航页（带上目的地坐标）。
 */
fun openAmapNavigation(context: Context, lng: String?, lat: String?, name: String?) {
    val dLng = lng?.toDoubleOrNull()
    val dLat = lat?.toDoubleOrNull()
    if (dLng == null || dLat == null) {
        openAmapWeb(context, null, null, null)
        return
    }
    val dName = java.net.URLEncoder.encode(name?.takeIf { it.isNotBlank() } ?: "目的地", "UTF-8")
    val scheme = "androidamap://route?sourceApplication=sorders&dev=0&t=0" +
        "&dlat=" + dLat + "&dlon=" + dLng + "&dname=" + dName + "&style=0"
    try {
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(scheme))
        if (intent.resolveActivity(context.packageManager) != null) {
            context.startActivity(intent)
            return
        }
    } catch (_: Exception) {
        // 高德 App 不存在 / 启动异常 -> 走 H5 回退
    }
    openAmapWeb(context, dLng.toString(), dLat.toString(), name)
}

private fun openAmapWeb(context: Context, lng: String?, lat: String?, name: String?) {
    val base = "https://uri.amap.com/navigation?mode=car&policy=1&src=sorders&coordinate=gaode&callnative=1"
    val url = if (lng != null && lat != null) {
        val dName = java.net.URLEncoder.encode(name?.takeIf { it.isNotBlank() } ?: "目的地", "UTF-8")
        base + "&to=" + lat + "," + lng + "," + dName
    } else base
    try {
        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
    } catch (_: Exception) {
        // 无浏览器可用时静默，避免崩溃
    }
}
