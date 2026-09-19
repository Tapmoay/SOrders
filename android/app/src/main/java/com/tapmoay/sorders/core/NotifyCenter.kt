package com.tapmoay.sorders.core

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.tapmoay.sorders.MainActivity
import com.tapmoay.sorders.R

/** 通知渠道 id。**改这里必须同时改系统设置里的旧渠道**，所以定了就别动。 */
object NotifyChannels {

    /** 派单/新单/撤回：要横幅、要震动，但**不出系统提示音**（声音由 App 自己放，见 NewOrderPlayer） */
    const val ORDERS = "orders"

    /** 普通站内信：静默进通知栏，不打断 */
    const val MESSAGES = "messages"

    /** 前台服务常驻通知：最低优先级，只为了让用户知道"它在后台收单"并能一键停 */
    const val SERVICE = "service"
}

/** 前台服务通知的固定 id（一个服务只该有一条常驻通知） */
const val SERVICE_NOTIFICATION_ID = 9001

/**
 * 系统通知出口。
 *
 * 为什么要有这一层：在这个类之前，App **从来没有发过一条系统通知**——
 * `POST_NOTIFICATIONS` 权限申请了、用户也点了允许，但代码里没有任何
 * `NotificationChannel` / `notify()`（2026-09-16 真机 `dumpsys notification` 确认：
 * 只有一条 AppSettings，没有任何渠道）。结果是"消息只在打开 App 时存在"，
 * 锁屏、口袋里的手机上什么都没有——这正是"不像别的软件"的原因。
 */
class NotifyCenter(private val context: Context, private val prefs: AlertPrefs) {

    private val manager = NotificationManagerCompat.from(context)

    /** 渠道是幂等的：重复创建不会重置用户在系统里改过的设置（安卓按 id 去重） */
    fun ensureChannels() {
        val nm = context.getSystemService(NotificationManager::class.java) ?: return
        nm.createNotificationChannels(
            listOf(
                // 声音 = null 是有意的：新单要循环播「来单了」并能被接单打断，
                // 系统提示音一旦响了就停不下来，会和语音叠成一片。
                // 震动交给渠道（跟着用户的系统设置走），所以 App 里不再自己振。
                NotificationChannel(
                    NotifyChannels.ORDERS,
                    "派单与新单",
                    NotificationManager.IMPORTANCE_HIGH,
                ).apply {
                    description = "有新派单、任务被撤回时提醒（语音播报由 App 负责）"
                    setSound(null, null)
                    enableVibration(true)
                    vibrationPattern = longArrayOf(0, 400, 200, 400, 200, 400)
                    enableLights(true)
                },
                NotificationChannel(
                    NotifyChannels.MESSAGES,
                    "消息",
                    NotificationManager.IMPORTANCE_DEFAULT,
                ).apply {
                    description = "订单状态、账本、价格等站内消息"
                },
                NotificationChannel(
                    NotifyChannels.SERVICE,
                    "后台接收派单",
                    NotificationManager.IMPORTANCE_MIN,
                ).apply {
                    description = "关闭 App 后仍在接收派单的常驻提示"
                    setShowBadge(false)
                },
            )
        )
    }

    fun canPost(): Boolean = manager.areNotificationsEnabled()

    /** 新单/派单/撤回：高优先级，锁屏也看得见 */
    fun postOrder(orderId: Long?, title: String, body: String) {
        if (!canPost()) return
        ensureChannels()
        val n = NotificationCompat.Builder(context, NotifyChannels.ORDERS)
            .setSmallIcon(R.drawable.ic_stat_order)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_STATUS)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setAutoCancel(true)
            .setContentIntent(openApp(orderId))
            .build()
        // 一条订单一格：司机一次可能收到好几单，堆成一条会看不出有几单。
        // 单号在进到这里之前已经被 PushTrust.orderIdOf 限制在 1..Int.MAX_VALUE（越界/负数
        // 那一步就丢了），所以这个 toInt() 不会回绕——回绕会让两张单落到同一个通知 id 上
        // （后一条把前一条盖掉），而同 id 的 requestCode 还会让点旧通知打开新单。
        notify(orderId?.toInt() ?: ORDER_FALLBACK_ID, n)
    }

    /** 普通消息：静默进通知栏 */
    fun postMessage(title: String, body: String) {
        if (!canPost()) return
        ensureChannels()
        val n = NotificationCompat.Builder(context, NotifyChannels.MESSAGES)
            .setSmallIcon(R.drawable.ic_stat_order)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setAutoCancel(true)
            .setContentIntent(openApp(null))
            .build()
        notify(MESSAGE_ID, n)
    }

    /** 前台服务的常驻通知。文案要能回答"它到底在干什么、怎么关掉" */
    fun serviceNotification(text: String): Notification {
        ensureChannels()
        return NotificationCompat.Builder(context, NotifyChannels.SERVICE)
            .setSmallIcon(R.drawable.ic_stat_order)
            .setContentTitle("SOrders 正在后台接收派单")
            .setContentText(text)
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .setOngoing(true)
            .setShowWhen(false)
            .setContentIntent(openApp(null))
            .build()
    }

    private fun notify(id: Int, n: Notification) {
        try {
            manager.notify(id, n)
        } catch (_: SecurityException) {
            // Android 13+ 用户拒了通知权限：**不能崩**（放不出通知不该影响接单）
        }
    }

    /**
     * 点通知进 App：带单号就直达订单详情，没单号落消息中心。
     *
     * ⚠️ 单号 extra 必须**同时**带上 [EXTRA_NOTIFY_TOKEN] 凭据：本 Activity 是 exported 的
     * LAUNCHER，别的 App 也能拼一个带单号的 intent 进来（见 [AlertPrefs.notifyToken]、
     * [PushTrust.trustedOrderId]）。凭据只有本机建的这一份 PendingIntent 带得上。
     */
    private fun openApp(orderId: Long?): PendingIntent {
        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP
            putExtra(EXTRA_NOTIFY_TOKEN, prefs.notifyToken)
            if (orderId != null) putExtra(EXTRA_ORDER_ID, orderId)
        }
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        return PendingIntent.getActivity(context, orderId?.toInt() ?: 0, intent, flags)
    }

    companion object {
        /** 从通知点进来的订单号（AppRoot 消费后直达详情） */
        const val EXTRA_ORDER_ID = "sorders_order_id"

        /** 本机通知的凭据（[AlertPrefs.notifyToken]）：对不上就忽略 [EXTRA_ORDER_ID] */
        const val EXTRA_NOTIFY_TOKEN = "sorders_notify_token"

        private const val ORDER_FALLBACK_ID = 9100
        private const val MESSAGE_ID = 9200
    }
}
