package com.tapmoay.sorders.core

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.tapmoay.sorders.SOrdersApp
import com.tapmoay.sorders.ui.nav.Role

/**
 * 开机 / 覆盖安装后把常驻接收重新拉起来。
 *
 * 为什么需要：前台服务被杀之后 START_STICKY 能拉回一部分，但**重启手机**是拉不回来的。
 * 司机的手机天天关机充电，第二天开机如果没人重新拉起服务，
 * 表现就是「今天一整天没收到单」——而且他不知道为什么。
 *
 * 只在**登录过 + 用户开着后台接收**时才拉起：开机后凭空多一条常驻通知，
 * 任何人都会把它当成流氓软件（何况这还是个给司机用的工具）。
 */
class BootReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val action = intent.action ?: return
        // MY_PACKAGE_REPLACED：App 自己更新（本项目有 App 内更新）后也要接上
        if (action != Intent.ACTION_BOOT_COMPLETED && action != Intent.ACTION_MY_PACKAGE_REPLACED) return

        val container = (context.applicationContext as? SOrdersApp)?.container ?: return
        if (container.tokenStore.cachedToken() == null) return
        val role = Role.fromKey(container.tokenStore.cachedRole() ?: "")
        if (!container.alertPrefs.backgroundEnabled(role)) return
        AlertService.start(context)
    }
}
