package com.tapmoay.sorders.core

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.core.app.NotificationManagerCompat

/**
 * 「手机上到底允不允许我们发通知」＋ 把用户领到那个开关 —— **全 App 唯一一份**。
 *
 * 台账 L-26 第⑤条（用户 2026-10-06，ref **m01132**）：「这个一定要有的这个权限，我们
 * **如果权限不足的话，我们就给他开**」；动机不是"少响一声"，而是用户原话
 * 「因为会出现非常严重的情况 …… 就是**我欠我自己的钱**……这样**账会乱掉**的，
 * **绝对是不允许的**」—— 派单 / 消息漏在通知栏外，司机不知道自己被派了单，
 * 货主也不知道司机接没接，最后错的是账。
 *
 * ## 为什么要有这一份
 * 在这之前，"有没有通知权限"只被**被动**读过三处，三处都不拦人：
 * - `ui/home/RoleHomeScreen.kt` 启动时申请一次 `POST_NOTIFICATIONS`（API 33+），
 *   用户点了"不允许"就再也没有下文；
 * - `core/AlertService.kt` 前台服务把常驻通知写成一句「通知权限没开，现在只会在 App 里显示」，
 *   而那条通知本身就发不出去（没权限）——等于没说；
 * - `ui/profile/AlertSettingsScreen.kt` 在自己的页面里读一次、弹一张卡片，
 *   可不进「我的 → 消息提醒」的用户一辈子看不到它。
 *
 * 用户要的是"**给他开**"，所以这一次把**读状态**与**跳设置页**收口到这一份：
 * 首页进门的硬提示（`ui/home/RoleHomeScreen.kt`）与设置页那张卡片走同一套判定，
 * ⛔ 谁都不许再抄第二份（抄出来的第二份一旦漏了下面的"看门狗"，两个入口就会互相矛盾）。
 *
 * ## 判据
 * - 读的是 `NotificationManagerCompat.areNotificationsEnabled()`，**不是** `POST_NOTIFICATIONS`
 *   这一个运行时权限：API 33 以下没有那个权限，用户是在应用详情页里关掉"允许通知"的；
 *   只查权限会在那一半设备上永远判成"开着"。
 * - "拦一次"只记在**进程内**（[promptedThisLaunch]）：同一个 App 启动里不重复弹，
 *   而权限还是没开的话**下次冷启动照样拦** —— 用户要的是"给他开"，不是"问过一次就算了"。
 * - 单测钉的是 [shouldPrompt] 这个纯函数（`app/src/test/.../core/NotifyPermissionTest.kt`）。
 */
object NotifyPermission {

    /**
     * 系统层面允不允许这个 App 发通知（App 级总开关）。
     *
     * 走 Compat：内部就是 `NotificationManager.areNotificationsEnabled()`，
     * 不用自己 `getSystemService(...) ?: return false` 那一套（拿不到服务时它给 false）。
     */
    fun enabled(context: Context): Boolean =
        NotificationManagerCompat.from(context.applicationContext).areNotificationsEnabled()

    /**
     * **这一次 App 启动**里是否已经拦过一次（首页那道硬提示不重复弹）。
     *
     * ⛔ 不许落盘：落成"一辈子只拦一次"就等于替用户做了"他不想开"的决定，
     *    而这条权限的后果是漏单 → 账错（见类注释里的用户原话）。
     */
    var promptedThisLaunch: Boolean = false
        private set

    /** 记下"这一轮启动已经拦过"。唯一写入口。 */
    fun markPrompted() {
        promptedThisLaunch = true
    }

    /**
     * 该不该拦：**没开** ＋ **这一轮启动还没拦过**。
     *
     * 纯函数（不碰 Context），因为这是本事项唯一需要单测钉住的判断 ——
     * 它被写成"恒真"会变成每次进首页都弹、写成"恒假"就等于这个功能不存在。
     */
    fun shouldPrompt(enabled: Boolean, promptedThisLaunch: Boolean): Boolean =
        !enabled && !promptedThisLaunch

    /**
     * 把用户送到"这个 App 的通知"开关那一页。
     *
     * ⚠️ 目标页在个别 ROM 上不存在（各家都改过设置页），所以带一个"应用详情页"兜底 ——
     * **必须能点到某个设置页**，否则用户点「去开启」没反应，会以为 App 坏了。
     */
    fun openSettings(context: Context) {
        startFirstResolvable(
            context,
            Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                .putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        ) {
            Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + context.packageName))
        }
    }
}

/**
 * 跳系统设置：首选页在个别 ROM 上不存在（各家都改过），
 * 所以留一个"应用详情页"兜底——**必须能点到某个设置页**，
 * 否则用户点「去开启」没反应，会以为 App 坏了。
 *
 * 这一份原来私有在 `ui/profile/AlertSettingsScreen.kt`（只有它一个调用方）；
 * CHG-0056 起通知（[NotifyPermission.openSettings]）与省电（`openBatterySettings`）两处共用，
 * 所以搬到 core 里 —— ⛔ 别再抄第二份。
 */
internal fun startFirstResolvable(context: Context, preferred: Intent, fallback: () -> Intent) {
    val candidates = listOf(preferred, fallback().addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    for (i in candidates) {
        if (i.resolveActivity(context.packageManager) != null) {
            runCatching { context.startActivity(i) }
            return
        }
    }
}
