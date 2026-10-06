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

    /**
     * 旧的派单渠道：**只留定义、不再往这里发**（2026-10-06 CHG-0055）。
     *
     * ⛔ 安卓的渠道是**一次性**的：`createNotificationChannels` 对已存在的 id 只更新名字与描述，
     *    importance / 声音 / 震动都归用户在系统设置里管 —— 想给"派单与新单"把震动补回来、
     *    或让"消息"带上系统提示音，**只能换一个新的 id**（[ORDERS_ALERT] / [MESSAGES_ALERT]）:
     *    只改这一份定义，在老用户机器上**什么都不变**。
     *    定义留着不删：删了只是让新装机器没这条渠道，而老机器上用户改过的设置与旧记录还在，
     *    渠道名也要跟着改成"（旧）"—— 两个同名的渠道摆在一起，用户没法判断该关哪个。
     */
    const val ORDERS = "orders"

    /**
     * 派单/新单/撤回（2026-10-06 起实际发的是这一条）：要横幅、要震动，
     * 但**不出系统提示音**（声音由 App 自己放，才停得下来，见 [NewOrderPlayer]）。
     */
    const val ORDERS_ALERT = "orders_alert"

    /** 旧的普通站内信渠道：同上，只留定义（这一条从前是**静默**进通知栏的） */
    const val MESSAGES = "messages"

    /** 普通站内信（2026-10-06 起实际发的是这一条）：带系统提示音、要震动。 */
    const val MESSAGES_ALERT = "messages_alert"

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
                    "派单与新单（旧）",
                    NotificationManager.IMPORTANCE_HIGH,
                ).apply {
                    description = "旧渠道：App 已改用「派单与新单」，这一条不再发送"
                    setSound(null, null)
                    enableVibration(true)
                    vibrationPattern = longArrayOf(0, 400, 200, 400, 200, 400)
                    enableLights(true)
                },
                // ⭐ 2026-10-06（CHG-0055，台账 L-26）：实际发送的派单渠道。
                // 用户原话「通知来的时候手机要震动一下，这个是要有的」——老渠道上这个开关
                // 是用户在系统设置里可以关掉的，而换 id 之后它是一次**新的**默认（震动开）。
                NotificationChannel(
                    NotifyChannels.ORDERS_ALERT,
                    "派单与新单",
                    NotificationManager.IMPORTANCE_HIGH,
                ).apply {
                    description = "有新派单、任务被撤回时提醒（语音播报由 App 负责，会震动）"
                    setSound(null, null)
                    enableVibration(true)
                    vibrationPattern = longArrayOf(0, 400, 200, 400, 200, 400)
                    enableLights(true)
                },
                NotificationChannel(
                    NotifyChannels.MESSAGES,
                    "消息（旧）",
                    NotificationManager.IMPORTANCE_DEFAULT,
                ).apply {
                    description = "旧渠道：App 已改用「消息」，这一条不再发送"
                },
                // ⭐ 2026-10-06（CHG-0055，台账 L-26）：实际发送的消息渠道。
                // 用户原话「系统通知的声音太小了」——老渠道是 IMPORTANCE_DEFAULT 且**不振**；
                // 这里抬到 HIGH（有横幅、有系统提示音）并**明确打开震动**：
                // 「所有通知都要震动」。
                NotificationChannel(
                    NotifyChannels.MESSAGES_ALERT,
                    "消息",
                    NotificationManager.IMPORTANCE_HIGH,
                ).apply {
                    description = "订单状态、账本、价格等站内消息（有提示音，会震动）"
                    enableVibration(true)
                    vibrationPattern = longArrayOf(0, 400, 200, 400, 200, 400)
                },
                // 渠道名要与时俱进（2026-10-04 CHG-0030）：它是**整机共享**的一条，
                // 不能只写"派单"——货主/批发商同样会看到它（见 NewOrderAlert.serviceNotice）。
                NotificationChannel(
                    NotifyChannels.SERVICE,
                    "后台接收消息",
                    NotificationManager.IMPORTANCE_MIN,
                ).apply {
                    description = "关闭 App 后仍在接收消息的常驻提示"
                    setShowBadge(false)
                },
            )
        )
    }

    // ⚠️ 读法全 App 只有一处：`core/NotifyPermission.kt`（CHG-0056 起首页那道硬提示也走它）。
    //    这里只转发 —— 抄第二份的话，两个入口迟早在"到底开没开"上互相矛盾。
    fun canPost(): Boolean = NotifyPermission.enabled(context)

    /** 新单/派单/撤回：高优先级，锁屏也看得见 */
    fun postOrder(orderId: Long?, title: String, body: String) {
        if (!canPost()) return
        ensureChannels()
        val n = NotificationCompat.Builder(context, NotifyChannels.ORDERS_ALERT)
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

    /**
     * 普通消息：静默进通知栏。
     *
     * ⚠️ `notificationId` = **服务端那条站内信的 id**（2026-09-23 复核 H9 后加）。
     *    在这之前这里写死一个常量：[MESSAGE_ID]（9200），于是**所有**普通消息共用通知栏里的
     *    同一格 —— 后到的那条直接把前一条盖掉，用户永远只能看到最后一条
     *    （"刚才是不是还有一条？"）。订单那条路（[postOrder]）早就按单号一格一条了，
     *    消息这条路漏了同一个道理（见它上面那段注释）。
     *    传 0 / 不传时退回常量那一格：老调用点与单测不受影响，但会退化成"只留最后一条"。
     */
    fun postMessage(title: String, body: String, notificationId: Long = 0L) {
        if (!canPost()) return
        ensureChannels()
        val n = NotificationCompat.Builder(context, NotifyChannels.MESSAGES_ALERT)
            .setSmallIcon(R.drawable.ic_stat_order)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setAutoCancel(true)
            .setContentIntent(openApp(null))
            .build()
        // 加一个远大于任何订单号/占位 id 的基数，保证与 [postOrder] 那一族**永不撞号**
        // （撞号的表现是"消息把订单通知盖掉"，比原来更难查）；越界就退回常量那一格。
        val id = if (notificationId in 1..MESSAGE_ID_MAX) {
            (MESSAGE_ID_BASE + notificationId).toInt()
        } else {
            MESSAGE_ID
        }
        notify(id, n)
    }

    /**
     * 前台服务的常驻通知。文案要能回答"它到底在干什么、怎么关掉"。
     *
     * 标题由调用方给（[com.tapmoay.sorders.core.NewOrderAlert.serviceNotice]）：
     * 从前这里写死「正在后台接收派单」，而 2026-10-04（CHG-0030）起所有角色都默认开——
     * 货主的通知栏里会出现一句跟他无关的"接收派单"。
     */
    fun serviceNotification(title: String, text: String): Notification {
        ensureChannels()
        return NotificationCompat.Builder(context, NotifyChannels.SERVICE)
            .setSmallIcon(R.drawable.ic_stat_order)
            .setContentTitle(title)
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
        /** 站内信通知 id 的基数：远大于任何订单号与上面两个占位 id，保证两族不撞号。 */
        private const val MESSAGE_ID_BASE = 10_000_000
        /** 站内信 id 超过这个数就不加基数了（Int 溢出让两族重新撞到一起）。 */
        private const val MESSAGE_ID_MAX = 1_000_000_000L
    }
}
