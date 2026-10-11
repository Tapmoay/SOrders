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
import com.tapmoay.sorders.ui.nav.Routes
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonElement

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

    /**
     * 一般消息（FEAT-0027，2026-10-11）：severity = warn 的站内信。
     *
     * ⛔ 为什么是**新 id** 而不是改 [MESSAGES_ALERT]：安卓的渠道是一次性的（改 importance
     *    对老机器一点用都没有）⇒ 想按 severity 分档，只能各自一条新渠道。
     *    重要性 DEFAULT：有系统提示音，但不弹横幅（要处理、但不着急）。
     */
    const val MESSAGES_WARN = "messages_warn"

    /**
     * 低优先级消息（FEAT-0027）：severity = info 的站内信（公告、设备登录这类）。
     *
     * 重要性 LOW：只安静地进通知栏。⛔ 不震动是有意的 —— LOW 的语义就是"知道就行"，
     * 给安静那一档加震动，用户就没法用系统设置把它和"要马上看"的消息分开了。
     */
    const val MESSAGES_INFO = "messages_info"

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

    /**
     * 摘要窗口里攒下的那些消息（判定见 [MessageNotify.plan]）。
     *
     * 为什么要有这个窗口：一次每日扫描会**同时**发出 N 条消息，逐条弹就是刷屏；
     * 攒到窗口结束再看"这批有几条"，1 条照发、≥2 条合并成一条"有 N 条新消息"。
     */
    private val pending = mutableListOf<PendingMessage>()

    /** 摘要窗口的计时器（只在**首条**消息到达时起一次，不随后续消息顺延）。 */
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

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
                // ⭐ 2026-10-11（FEAT-0027）：消息按 severity 分三档，这两条是新增的两档。
                // ⛔ 位置必须在 SERVICE **之后**：判据 `_check_alert_ringback.py` 用
                //    between(MESSAGES_ALERT, SERVICE) 取"消息"那一段来断言它不设 setSound ——
                //    插在它前面会把新渠道的文字算进那一段。
                NotificationChannel(
                    NotifyChannels.MESSAGES_WARN,
                    "消息提醒（一般）",
                    NotificationManager.IMPORTANCE_DEFAULT,
                ).apply {
                    description = "库存偏低、应付到期这类要处理但不着急的站内消息"
                    enableVibration(true)
                    vibrationPattern = longArrayOf(0, 400, 200, 400, 200, 400)
                },
                NotificationChannel(
                    NotifyChannels.MESSAGES_INFO,
                    "消息（低）",
                    NotificationManager.IMPORTANCE_LOW,
                ).apply {
                    description = "公告、设备登录这类知道就行的站内消息（不响铃、不震动）"
                    setShowBadge(true)
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
     * 普通消息进系统通知栏（FEAT-0027 起：按 severity 分档、点它直达那一页、多条合并成一条摘要）。
     *
     * ⚠️ `notificationId` = **服务端那条站内信的 id**（2026-09-23 复核 H9 后加）。
     *    在这之前这里写死一个常量：[MESSAGE_ID]（9200），于是**所有**普通消息共用通知栏里的
     *    同一格 —— 后到的那条直接把前一条盖掉，用户永远只能看到最后一条
     *    （"刚才是不是还有一条？"）。订单那条路（[postOrder]）早就按单号一格一条了，
     *    消息这条路漏了同一个道理（见它上面那段注释）。
     *    传 0 / 不传时退回常量那一格：老调用点与单测不受影响，但会退化成"只留最后一条"。
     *
     * 四个"不弹"的理由都在 [MessageNotify.shouldPost] 一处：没有通知权限 / 用户关掉了这个开关 /
     * App 正在前台（界面里本来就会刷出来，不重复打扰）/ 这条 id 已经弹过
     * （同一条站内信会从 socket 实时与重连回补**两条链**各到一次）。
     * ⛔ 不弹**不等于**把消息丢掉：列表、未读数、已读都由原有那条链维护。
     */
    fun postMessage(
        title: String,
        body: String,
        notificationId: Long = 0L,
        severity: String? = null,
        type: String = "",
        payload: Map<String, JsonElement>? = null,
        roleKey: String? = null,
    ) {
        // 读法与开关都在这一处问（权限的读法唯一处 = core/NotifyPermission.kt，见 canPost）
        val allowed = canPost()
        val now = System.currentTimeMillis()
        val seen = MessageNotify.decodeSeen(prefs.seenMessageIds, now)
        if (!MessageNotify.shouldPost(
                id = notificationId,
                allowed = allowed,
                enabled = prefs.messageNotifyEnabled,
                foreground = AppForeground.visible,
                seen = seen,
            )
        ) {
            return
        }
        ensureChannels()
        // 先记"弹过了"再发：两条链几乎同时到达时，第二遍必须被挡住（见 isDuplicate 的注释）
        MessageNotify.markSeen(seen, notificationId, now)
        prefs.seenMessageIds = MessageNotify.encodeSeen(seen)
        val m = PendingMessage(
            id = notificationId,
            risk = MessageNotify.riskOfSeverity(severity),
            title = title,
            body = body,
            route = MessageNotify.routeOf(roleKey, type, payload),
            type = type,
            payload = payload,
        )
        synchronized(pending) {
            val first = pending.isEmpty()
            pending += m
            if (first) {
                scope.launch {
                    delay(MessageNotify.SUMMARY_WINDOW_MS)
                    flushMessages()
                }
            }
        }
    }

    /**
     * 摘要窗口到了：把这一批发出去 —— 1 条单独一格；≥[MessageNotify.SUMMARY_MIN] 条合并成一条摘要。
     *
     * 为什么合并而不是逐条：一次每日扫描同时发 N 条，逐条弹就是**刷屏**（用户要点 N 次才清干净），
     * 而它们本来就是"同一件事的一批"。摘要点进去是消息中心，那里面一条都没少。
     */
    private fun flushMessages() {
        val batch = synchronized(pending) {
            val copy = pending.toList()
            pending.clear()
            copy
        }
        when (val b = MessageNotify.plan(batch)) {
            is MessageBatch.None -> Unit
            is MessageBatch.Single -> notify(messageIdOf(b.message.id), singleMessageNotification(b.message))
            is MessageBatch.Summary -> notify(SUMMARY_NOTIFICATION_ID, summaryNotification(b))
        }
    }

    /** 单条消息：标题＝消息标题、折叠行＝正文首行（超过 [MessageNotify.BODY_PREVIEW_MAX] 截断），展开是全文。 */
    private fun singleMessageNotification(m: PendingMessage): Notification =
        NotificationCompat.Builder(context, MessageNotify.channelOf(m.risk))
            .setSmallIcon(R.drawable.ic_stat_order)
            .setContentTitle(m.title)
            .setContentText(MessageNotify.preview(m.body))
            .setStyle(NotificationCompat.BigTextStyle().bigText(m.body))
            .setAutoCancel(true)
            .setContentIntent(messageIntent(m))
            .build()

    /** 摘要：一条代表这一批（"有 N 条新消息"），点它进消息中心。 */
    private fun summaryNotification(b: MessageBatch.Summary): Notification =
        NotificationCompat.Builder(context, MessageNotify.channelOf(b.risk))
            .setSmallIcon(R.drawable.ic_stat_order)
            .setContentTitle(MessageNotify.SUMMARY_TITLE)
            .setContentText(MessageNotify.summaryBody(b.count))
            .setStyle(NotificationCompat.BigTextStyle().bigText(MessageNotify.summaryBody(b.count)))
            .setAutoCancel(true)
            .setContentIntent(summaryIntent())
            .build()

    /**
     * 点这条消息通知进 App：带 [EXTRA_MESSAGE_ROUTE] 就直达那一页（FEAT-0027）。
     *
     * 路由在**投递时**就算好（[MessageNotify.routeOf]，与消息中心里点这张卡同一份），
     * 不是点的时候再猜一次；extras 里同时带上 id / type / payload 那些键，
     * 是为了在真机上排查"这条通知当初带着什么"（路由已经是唯一跳转依据）。
     * ⚠️ 与 [openApp] 一样必须带 [EXTRA_NOTIFY_TOKEN]：本 Activity 是 exported + LAUNCHER，
     *    深链也是外部可伪造的 extra（凭据校验见 [PushTrust.trustedRoute]）。
     */
    private fun messageIntent(m: PendingMessage): PendingIntent {
        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP
            putExtra(EXTRA_NOTIFY_TOKEN, prefs.notifyToken)
            putExtra(EXTRA_MESSAGE_ID, m.id)
            putExtra(EXTRA_MESSAGE_TYPE, m.type)
            MessageNotify.payloadExtras(m.payload).forEach { (k, v) -> putExtra(k, v) }
            if (m.route != null) putExtra(EXTRA_MESSAGE_ROUTE, m.route)
        }
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        // requestCode 与通知 id **同源**：两条不同消息各自的 PendingIntent 不许互相覆盖
        // （覆盖的表现是"点第二条打开了第一条的页面"，而两条通知看起来都正常）。
        return PendingIntent.getActivity(context, messageIdOf(m.id), intent, flags)
    }

    /** 摘要那一格：点它进消息中心（这一条代表的是"一批消息"，没有单一目标页）。 */
    private fun summaryIntent(): PendingIntent {
        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP
            putExtra(EXTRA_NOTIFY_TOKEN, prefs.notifyToken)
            putExtra(EXTRA_MESSAGE_ROUTE, Routes.MESSAGES)
        }
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        return PendingIntent.getActivity(context, SUMMARY_NOTIFICATION_ID, intent, flags)
    }

    /**
     * 消息那一族的通知 id：加一个远大于任何订单号/占位 id 的基数，保证与 [postOrder]
     * 那一族**永不撞号**（撞号的表现是"消息把订单通知盖掉"，比原来更难查）；越界就退回常量那一格。
     */
    private fun messageIdOf(messageId: Long): Int =
        if (messageId in 1..MESSAGE_ID_MAX) {
            (MESSAGE_ID_BASE + messageId).toInt()
        } else {
            MESSAGE_ID
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

        /** 通知里那条深链（[MessageNotify.routeOf] 算出来的整条路由）：点通知直达那一页 */
        const val EXTRA_MESSAGE_ROUTE = "sorders_message_route"

        /** 这条通知对应哪一条站内信（排查用；去重与"哪一格"都用它） */
        const val EXTRA_MESSAGE_ID = "sorders_message_id"

        /** 这条通知的 type（排查用；路由已经算好，不再拿它二次判定） */
        const val EXTRA_MESSAGE_TYPE = "sorders_message_type"

        /** 摘要那一格的通知 id：同一批消息反复覆盖自己，不刷屏；点它进消息中心 */
        const val SUMMARY_NOTIFICATION_ID = 9300

        private const val ORDER_FALLBACK_ID = 9100
        private const val MESSAGE_ID = 9200
        /** 站内信通知 id 的基数：远大于任何订单号与上面两个占位 id，保证两族不撞号。 */
        private const val MESSAGE_ID_BASE = 10_000_000
        /** 站内信 id 超过这个数就不加基数了（Int 溢出让两族重新撞到一起）。 */
        private const val MESSAGE_ID_MAX = 1_000_000_000L
    }
}
