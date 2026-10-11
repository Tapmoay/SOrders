package com.tapmoay.sorders.core

import com.tapmoay.sorders.ui.messages.MessageRisk
import com.tapmoay.sorders.ui.messages.noticeRoute
import com.tapmoay.sorders.ui.messages.riskOf
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

/**
 * 一条**该进系统通知栏**的站内信。
 *
 * 为什么做成纯数据：这一段的所有规矩（该不该弹、弹哪一档、合并成几条、点它去哪一页）都是
 * "同一条消息在客户端还应该发生什么"，与 Android 的通知 API 一点关系都没有 ——
 * 抽出来才能被单测钉住（真机上这些行为全是静默的：少弹一次、弹两次、点错页，都不报错）。
 */
data class PendingMessage(
    val id: Long,
    val risk: MessageRisk,
    val title: String,
    val body: String,
    /** 点它去哪一页（[MessageNotify.routeOf] 算出来的整条路由）；null = 认不出来，点了只打开 App。 */
    val route: String?,
    val type: String,
    val payload: Map<String, JsonElement>?,
)

/** 这一批消息该发成什么（判定见 [MessageNotify.plan]）。 */
sealed interface MessageBatch {

    /** 空批：什么都不发。 */
    object None : MessageBatch

    /** 只有一条：照单发，它自己占通知栏一格。 */
    data class Single(val message: PendingMessage) : MessageBatch

    /**
     * 多条：**合并成一条摘要**。
     *
     * @param count 这批有几条（文案是"有 N 条新消息"）
     * @param risk 这批里**最高**的那一档 —— 用来选渠道：一堆 info 里夹着一条 danger 时，
     *   按 info 发就等于把"库存不足"埋进公告堆里（用户要的是"该响的响"）。
     */
    data class Summary(val count: Int, val risk: MessageRisk) : MessageBatch
}

/**
 * 「消息中心的消息在**软件外**也要收得到」的全部判定（FEAT-0027）。
 *
 * 用户口径（2026-10-11 逐字）：「我们这个消息中心……**它不止只有在这个软件才会有** ——
 * 我们的**手机系统消息它也会弹一个消息窗**，就像普通的手机那个软件一样。你光在自己软件里
 * 谈消息没什么用的，有时候你要**在软件外**谈消息。」
 *
 * 这一层刻意**不碰 Android API**（渠道 id 只是 [NotifyChannels] 里的字符串常量）：
 * 判定能被 `MessageNotifyTest` 逐条钉住，而真机上的失败全是静默的。
 */
object MessageNotify {

    /**
     * 摘要窗口（毫秒）：窗口内到达的多条消息合并成一条"有 N 条新消息"。
     *
     * 为什么是 1.5 秒：这批消息是**一次扫描同时发出的**（后端连着 emit N 条），到达间隔是
     * 毫秒级；窗口再长会把"隔一会儿来的第二条"也吞进摘要，而那种消息用户是希望单独看见的
     * （比如刚收到的收款通知）。窗口从**第一条**起算（不做"每来一条就顺延"的防抖）：
     * 否则一次很长的扫描会把摘要无限往后推，用户在那段时间里一条都看不到。
     */
    const val SUMMARY_WINDOW_MS = 1500L

    /** 窗口内到几条才合并：1 条仍单发（阈值写在这里，报告里说明）。 */
    const val SUMMARY_MIN = 2

    /** 摘要的标题（正文见 [summaryBody]）。 */
    const val SUMMARY_TITLE = "SOrders 有新消息"

    /** 摘要正文：用户一眼要知道"有几条"，而不是"有一条很长的公告"。 */
    fun summaryBody(count: Int): String = "有 " + count + " 条新消息，点开看是哪几条"

    /**
     * 单条通知**折叠行**的正文上限（展开后 BigTextStyle 仍是全文）。
     *
     * 与仓库既有的截断规矩一致（Compose 侧是 maxLines + Ellipsis）：通知栏那一行放不下长
     * 公告，截断只影响折叠时的观感，⛔ 不改消息本身的内容。
     */
    const val BODY_PREVIEW_MAX = 60

    /** 「已经弹过系统通知」的保留窗口：一天。 */
    const val SEEN_KEEP_MS = 24 * 60 * 60 * 1000L

    /** 「已经弹过系统通知」的条数上限（与 [NewOrderAlert.RUNG_MAX] 同一个道理：盘上不许无限长）。 */
    const val SEEN_MAX = 128

    /** intent extras 里 payload 键的前缀（`sorders_payload_order_id` …）。 */
    const val PAYLOAD_EXTRA_PREFIX = "sorders_payload_"

    /** 后端 `NotificationOut.severity` → 风险档。**解析只有一处**（[riskOf]，FEAT-0019 立的）。 */
    fun riskOfSeverity(severity: String?): MessageRisk = riskOf(severity)

    /**
     * 风险档 → 通知渠道 id。**severity → 重要性**这条映射的唯一一处。
     *
     * 为什么必须分成三条渠道（而不是一个渠道 + `setPriority`）：API 26 起重要性归**渠道**，
     * `setPriority` 只在渠道之下做微调；而渠道是**一次性**的（改 importance 对老机器无效，
     * 见 [NotifyChannels] 的注释）⇒ 想按 severity 分档，只能各自一个新 id。
     * ⛔ 别往 [NotifyChannels.ORDERS_ALERT] 发：那条是司机的新单（要语音、要横幅）。
     */
    fun channelOf(risk: MessageRisk): String = when (risk) {
        MessageRisk.DANGER -> NotifyChannels.MESSAGES_ALERT
        MessageRisk.WARN -> NotifyChannels.MESSAGES_WARN
        MessageRisk.INFO -> NotifyChannels.MESSAGES_INFO
    }

    /**
     * 这条消息**这一刻该不该落一条系统通知**。四个"不弹"的理由都在这一处：
     * 没有通知权限 / 用户关掉了这个开关 / App 正在前台 / 这条 id 已经弹过。
     *
     * ⛔ 这里返回 false **绝不等于把消息丢掉**：消息本身是服务端的数据，
     * 列表、未读数、已读都由原有那条链维护（本函数只决定"要不要多弹一次系统通知"）。
     */
    fun shouldPost(
        id: Long,
        allowed: Boolean,
        enabled: Boolean,
        foreground: Boolean,
        seen: Map<Long, Long>,
    ): Boolean {
        if (!allowed) return false
        if (!enabled) return false
        if (foreground) return false
        if (isDuplicate(seen, id)) return false
        return true
    }

    /**
     * 这条通知 id 是不是**已经弹过**。
     *
     * ⚠️ 为什么按 id 判而不是按内容：同一条站内信会从**两条链**各到一次
     * （socket 的 notification 实时事件、与重连时的 sync 回补），不去重的话同一条消息会弹两格 ——
     * 与司机新单那条链按 order_id 去重是同一个道理。记录**跨进程落盘**
     * （[AlertPrefs.seenMessageIds]）：进程被杀之后重连，sync 会把断线期间那一批**再补一遍**，
     * 只存在内存里的记录等于没有。
     */
    fun isDuplicate(seen: Map<Long, Long>, id: Long): Boolean = id > 0L && seen.containsKey(id)

    /**
     * 读盘：`"12@1730000000000;13@…"` → id → 时间戳（时间升序，人能看出发生顺序）。
     *
     * 坏行一律**丢掉不抛**（少一条记录 = 多弹一次，比因为一个坏字符整份记录失效好得多），
     * 读的时候就按窗口与条数裁一次。
     */
    fun decodeSeen(raw: String?, now: Long): MutableMap<Long, Long> {
        val out = mutableMapOf<Long, Long>()
        raw.orEmpty().split(';').forEach { line ->
            val s = line.trim()
            if (s.isEmpty()) return@forEach
            val at = s.lastIndexOf('@')
            if (at <= 0 || at >= s.length - 1) return@forEach
            val id = s.substring(0, at).trim().toLongOrNull() ?: return@forEach
            val ts = s.substring(at + 1).trim().toLongOrNull() ?: return@forEach
            if (id > 0L) out[id] = ts
        }
        trimSeen(out, now)
        return out
    }

    /** 写盘（按时间升序，人肉看顺序与发生顺序一致）。 */
    fun encodeSeen(seen: Map<Long, Long>): String =
        seen.entries.sortedBy { it.value }
            .joinToString(";") { it.key.toString() + "@" + it.value.toString() }

    /** 超窗的丢掉；超量的只留最新那 [SEEN_MAX] 条。 */
    fun trimSeen(seen: MutableMap<Long, Long>, now: Long) {
        seen.entries.removeAll { now - it.value > SEEN_KEEP_MS }
        if (seen.size > SEEN_MAX) {
            val keep = seen.entries.sortedByDescending { it.value }.take(SEEN_MAX).map { it.key }.toSet()
            seen.keys.retainAll(keep)
        }
    }

    /** 记一条"弹过了"，顺手裁一次。 */
    fun markSeen(seen: MutableMap<Long, Long>, id: Long, now: Long) {
        if (id <= 0L) return
        seen[id] = now
        trimSeen(seen, now)
    }

    /** 这一批该发成几条：空 → 不发；1 条 → 单发；≥[SUMMARY_MIN] 条 → 一条摘要。 */
    fun plan(pending: List<PendingMessage>): MessageBatch = when {
        pending.isEmpty() -> MessageBatch.None
        pending.size == 1 -> MessageBatch.Single(pending.first())
        else -> MessageBatch.Summary(count = pending.size, risk = highest(pending.map { it.risk }))
    }

    /** 一批里最高的那一档（摘要按它选渠道）。 */
    fun highest(risks: List<MessageRisk>): MessageRisk = when {
        risks.contains(MessageRisk.DANGER) -> MessageRisk.DANGER
        risks.contains(MessageRisk.WARN) -> MessageRisk.WARN
        else -> MessageRisk.INFO
    }

    /**
     * 折叠行的那句正文：只取**第一行**、超过 [max] 字截断加省略号。
     *
     * ⛔ 不改消息本身：展开后的 BigTextStyle 仍是全文（截断只发生在"通知栏那一行放不下"时）。
     */
    fun preview(body: String, max: Int = BODY_PREVIEW_MAX): String {
        val trimmed = body.trim()
        if (trimmed.isEmpty()) return ""
        val first = trimmed.lineSequence().firstOrNull()?.trim().orEmpty()
        val text = first.ifEmpty { trimmed }
        return if (text.length <= max) text else text.take(max) + "…"
    }

    /**
     * 点这条通知该去哪一页 —— **与消息中心里点这张卡是同一份路由**。
     *
     * ⛔ 这个函数体只许有一句：转发给 [noticeRoute]（`ui/messages/MessageGrading.kt`）。
     *    在这里再写一遍 `when (type)` 映射，就是第二套路由：App 内点卡片去 A 页、
     *    点通知去 B 页，而两边都不报错（判据 `_check_message_system_notify.py` 钉着这一句）。
     */
    fun routeOf(roleKey: String?, type: String, payload: Map<String, JsonElement>?): String? = noticeRoute(roleKey, type, payload)

    /**
     * socket 负载里的 payload（是 org.json 转出来的普通 Map）→ 路由要的那份 `Map<String, JsonElement>`。
     *
     * ⚠️ 必须有这一步：消息中心页读的是 **REST** 的 `NotificationDto.payload`（kotlinx 直接给
     * `JsonElement`），而通知这条链读的是 **socket** 的那一份。不归一的话，"库存预警"在 App 内
     * 点得进库存页、点通知却算不出路由（payload 里的 `product_id` 读不到）—— 表现只是
     * "点了没反应"，谁都看不出是两份形状不一致。
     */
    fun payloadOf(raw: Map<*, *>?): Map<String, JsonElement>? {
        if (raw == null) return null
        val out = mutableMapOf<String, JsonElement>()
        raw.forEach { (k, v) ->
            val key = (k as? String)?.trim().orEmpty()
            if (key.isNotEmpty()) out[key] = jsonOf(v)
        }
        return out.ifEmpty { null }
    }

    /**
     * payload 里的**标量**键 → intent extras（键名前缀 [PAYLOAD_EXTRA_PREFIX]）。
     *
     * 深链所需的键（`order_id` / `product_id` / `request_id` …）随通知一起带出去，
     * 排查"点了通知去哪了"时一眼能看到这条通知当初带着什么。
     */
    fun payloadExtras(payload: Map<String, JsonElement>?): Map<String, String> {
        val out = mutableMapOf<String, String>()
        payload.orEmpty().forEach { (k, v) ->
            val key = k.trim()
            if (key.isEmpty()) return@forEach
            val text = (v as? JsonPrimitive)?.contentOrNull ?: return@forEach
            if (text.isNotBlank()) out[PAYLOAD_EXTRA_PREFIX + key] = text
        }
        return out
    }

    private fun jsonOf(v: Any?): JsonElement = when (v) {
        null -> JsonNull
        is JsonElement -> v
        is Boolean -> JsonPrimitive(v)
        is Number -> JsonPrimitive(v)
        is String -> JsonPrimitive(v)
        is Map<*, *> -> JsonObject(
            v.entries.mapNotNull { (k, item) -> (k as? String)?.let { it to jsonOf(item) } }.toMap()
        )
        is List<*> -> JsonArray(v.map { jsonOf(it) })
        else -> JsonPrimitive(v.toString())
    }
}
