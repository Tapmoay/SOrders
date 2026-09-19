package com.tapmoay.sorders

import android.app.Application
import com.tapmoay.sorders.core.AppContainer

class SOrdersApp : Application() {

    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        // 外观模式要**在第一次组合之前**读回来，否则首帧会先按白天渲染再跳成夜间
        com.tapmoay.sorders.ui.theme.ThemeMode.load(this)
        container = AppContainer(this)
        container.tokenStore.warmCache()
        // 高德搜索 SDK：官方要求 ServiceSettings.setApiKey 显式设置（跟 manifest 双保险）
        try {
            com.amap.api.services.core.ServiceSettings.getInstance().setApiKey(BuildConfig.AMAP_KEY)
        } catch (_: Exception) {
            // 未配置 Key / SDK 未集成时静默
        }
        // 高德 SDK 隐私合规：用户协议已展示及同意（本地开发 App 视为已同意）
        // 三个 SDK 各自有独立的隐私开关：定位/地图(AMapLocationClient)、搜索(ServiceSettings)
        try {
            com.amap.api.location.AMapLocationClient.updatePrivacyShow(this, true, true)
            com.amap.api.location.AMapLocationClient.updatePrivacyAgree(this, true)
        } catch (_: Exception) {
            // 未配置 Key / SDK 未集成时静默
        }
        try {
            com.amap.api.services.core.ServiceSettings.updatePrivacyShow(this, true, true)
            com.amap.api.services.core.ServiceSettings.updatePrivacyAgree(this, true)
        } catch (_: Exception) {
            // 未配置 Key / SDK 未集成时静默
        }
    }
}