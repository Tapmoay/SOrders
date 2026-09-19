package com.tapmoay.sorders.core

import com.tapmoay.sorders.ui.nav.Role

/**
 * 「来单了」这件事的**判定逻辑**（纯函数，不碰任何 Android API，可单测）。
 *
 * 为什么单拎出来：这一段决定「什么时候会响、响几次、什么时候闭嘴」，
 * 而它最贵的 bug 是**静默失效**——司机那头的表现只有「这次没响」，
 * 没人能从界面上看出来是判定写错了、网络没到、还是素材没声音。
 * 判定抽成纯函数，才有廉价的单测能钉住它；Android 侧只剩"把声音放出来"。
 *
 * 播报素材：`android/app/src/main/res/raw/new_order.wav`（约 3 秒：叮咚 + 「来单了，来单了」），
 * 由 `_tools/media/_gen_new_order_clip.ps1` 离线合成。**不用手机 TTS 是有意的**：
 * 国产 ROM 常常没有中文语音包，最关键的这一句不能赌在它上面（放不出来时才退回 TTS）。
 */
enum class AlertKind {
    /** 新派单：司机在等活，最重要的一件事，默认重复到司机动手为止 */
    NEW_ORDER,

    /** 任务被撤回 / 取消：说一遍就够，重复只会让人以为还有别的事 */
    REVOKED,
}

/** 一次播报的计划（由用户设置算出来） */
data class AlertPlan(val repeats: Int, val gapMs: Long) {

    /** true = 一直响到司机接单（用户选了「一直响」） */
    val forever: Boolean get() = repeats <= 0
}

/** 一次播报事件：播什么、是哪一单、去重键是什么 */
data class AlertEvent(
    val kind: AlertKind,
    val orderId: Long?,
    val title: String,
    /**
     * 去重键。**必须有**：同一次派单后端会从两条链路各推一次
     * （`notification` 一条站内信 + `realtime` 一条状态事件，见 message_center.publish_order_assigned），
     * 不去重的话司机听到的是「来单了来单了」连着放两组。
     */
    val dedupeKey: String,
)

object NewOrderAlert {

    /**
     * 播报素材实测时长（毫秒）。
     *
     * ⚠️ 换素材要同步改这里，否则重复播报会叠在一起。
     * 素材结构 = [古典号角 ≈1.0 秒，大小交替] + [语音「来订单了，你有新的订单，请及时查看」≈3.6 秒]。
     * 语音是微软神经语音 **zh-CN-XiaoxiaoNeural（晓晓）**——用户听完云健那一版后指定要晓晓。
     * 生成脚本会直接打印该改的数字；红线还会拿 wav 文件头对账，对不上就红。
     */
    const val CLIP_MS = 4874L

    /** 两次播报之间留的静默：太短会粘成一片，太长会错过"赶紧看一眼"的紧迫感 */
    const val GAP_MS = 350L

    /** 重复次数取值里的 0 = 一直响到接单 */
    const val FOREVER = 0

    /**
     * 设置页给的档位。给固定档位而不是自由输入：司机在车上没法调一个滑杆。
     *
     * 一段 ≈5 秒（号角 + 一整句话），所以档位是 1/2/3/一直响：
     * 5 次就是 25 秒，那已经不是"提醒"而是"吵"。用户的说法是「这句话可能播 2 到 3 遍」。
     */
    val REPEAT_CHOICES = listOf(1, 2, 3, FOREVER)

    const val DEFAULT_REPEAT = 3

    /** 同一条去重键在这个窗口内只响一次 */
    const val DEDUPE_MS = 60_000L

    /** 「一直响」也要有个止损，否则一条没人接的单能响一整夜 */
    const val FOREVER_MAX_MS = 60_000L

    /** 非法/越界设置一律回落到默认档，不要让一个坏值变成"永远不响" */
    fun plan(setting: Int): AlertPlan {
        val n = if (setting in REPEAT_CHOICES) setting else DEFAULT_REPEAT
        return AlertPlan(repeats = n, gapMs = GAP_MS)
    }

    /**
     * 按播报类型取计划：重复次数只对**新单**有意义。
     * 「有任务被撤回」连说三遍，司机只会以为又撤了两单。
     */
    fun planFor(kind: AlertKind, setting: Int): AlertPlan = when (kind) {
        AlertKind.NEW_ORDER -> plan(setting)
        AlertKind.REVOKED -> AlertPlan(repeats = 1, gapMs = GAP_MS)
    }

    /**
     * 响铃时若媒体音量偏低，临时提到这个比例（播完还原）——货拉拉那类 App 都会这么干。
     *
     * 用户听完第一版的反馈是「声音比较小」，明确要求「调到手机的 80% 播放」，
     * 所以这里是 **80%**，不是随手取的 70%。
     * 只抬不降：用户自己把音量开到 100% 时不该被我们按回 80%。
     */
    const val BOOST_RATIO = 0.8f

    /** 音量要不要抬、抬到几；不用动就返回 null（避免"什么都没变还去写一次音量"） */
    fun boostTarget(max: Int, current: Int): Int? {
        if (max <= 0) return null
        val target = Math.round(max * BOOST_RATIO).toInt()
        return if (current < target) target else null
    }

    /**
     * 语音只给司机播。
     *
     * 派单员/货主大部分时间在电脑前，手机上还放语音是打扰；
     * 而且「来单了」这句对他们是**错的信息**（不是他们的活）。
     */
    fun isSpoken(role: Role?): Boolean = role == Role.DRIVER

    /** 没设置过「后台常驻」时按角色给缺省：司机默认开，其余角色默认关 */
    fun defaultBackground(role: Role?): Boolean = role == Role.DRIVER

    /**
     * 把一条事件认成「要不要播、播什么」。
     *
     * 两条链路都走这里：站内信（`notification` 的 `type`）与状态事件（`realtime` 的 `type`），
     * 它们对同一件事用的是**同一套 type 名**（order.assigned / order.revoked / order.cancelled）。
     */
    fun eventOf(type: String, orderId: Long?, title: String = ""): AlertEvent? = when (type) {
        "order.assigned" -> AlertEvent(
            kind = AlertKind.NEW_ORDER,
            orderId = orderId,
            title = title,
            dedupeKey = "assigned:" + (orderId ?: -1L),
        )
        // 撤回与取消对司机是同一件事：这单不用跑了。取消单不会再有 realtime 事件，
        // 只有站内信，所以这里也得认。
        "order.revoked", "order.cancelled" -> AlertEvent(
            kind = AlertKind.REVOKED,
            orderId = orderId,
            title = title,
            // 撤回可能一单发多次（不同原因），按「一单一次」去重即可
            dedupeKey = "revoked:" + (orderId ?: -1L),
        )
        else -> null
    }

    /**
     * 这条事件是不是"该闭嘴了"的信号。
     *
     * 新单播报必须能被**司机自己的动作**打断：接单成功后再继续喊"来单了"
     * 会让司机怀疑到底接上没有。撤回/取消同理（活没了还喊就是耍人）。
     */
    fun shouldStop(type: String): Boolean = when (type) {
        "order.driver_ack", "order.delivered_driver", "order.delivered",
        "order.revoked", "order.cancelled", "order.recalled",
        -> true
        else -> false
    }

    /** 同一条事件在 [DEDUPE_MS] 内重复到达时返回 true（true = 这次不要响） */
    fun isDuplicate(seen: MutableMap<String, Long>, key: String, now: Long): Boolean {
        val last = seen[key]
        // 顺手清掉过期项：这个 map 跟着进程活，长期不清理就是一条慢泄漏
        if (seen.size > 32) seen.entries.removeAll { now - it.value > DEDUPE_MS }
        return last != null && now - last < DEDUPE_MS
    }

    /** 设置页显示的档位文案（用户看不懂「0 次」是什么意思） */
    fun repeatLabel(setting: Int): String = when (setting) {
        FOREVER -> "一直响到我接单"
        1 -> "1 次"
        else -> setting.toString() + " 次"
    }

    /** 播报总时长（毫秒）；一直响返回 null */
    fun totalMs(plan: AlertPlan): Long? =
        if (plan.forever) null else plan.repeats * CLIP_MS + (plan.repeats - 1) * plan.gapMs

    /**
     * 「我的 → 消息提醒」右侧那一行的状态摘要。
     *
     * 为什么放进纯函数：这一行是用户判断「派单来了会不会响」的唯一入口，
     * 而它必须**按角色**说不同的话——语音只有司机有（见 [isSpoken]），
     * 给货主/派单员也写「语音 3 次」，他们看到的就是一句假话。
     */
    fun summary(
        role: Role?,
        notificationsAllowed: Boolean,
        voiceEnabled: Boolean,
        repeat: Int,
        background: Boolean,
    ): String {
        if (!notificationsAllowed) return "通知权限未开"
        if (!isSpoken(role)) return if (background) "后台接收中" else "仅前台接收"
        if (!voiceEnabled) return "语音已关"
        return "语音 " + repeatLabel(repeat) + if (background) "·后台接收" else ""
    }
}
