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
 * 播报素材：`android/app/src/main/res/raw/` 下两份，**一个角色一句**
 * （`new_order.wav`「来订单了，你有新的订单，请及时查看」= 司机；
 *   `pending_order.wav`「来订单了，有新订单待派单，请及时处理」= 派单员），
 * 由 `_tools/media/_gen_new_order_clip.py --kind {driver,dispatcher}` 离线合成。**不用手机 TTS 是有意的**：
 * 国产 ROM 常常没有中文语音包，最关键的这一句不能赌在它上面（放不出来时才退回 TTS）。
 */
enum class AlertKind {
    /** 新派单：司机在等活，最重要的一件事，默认重复到司机动手为止 */
    NEW_ORDER,

    /**
     * 新订单待派单：**派单员的活**（2026-09-21 用户要求「派单员收到订单、有单要派的时候
     * 也要有语音播报，就跟司机一样」）。
     *
     * 与 [NEW_ORDER] 分开是一件事的两面：两者的**触发事件不同**（`order.created` / `order.assigned`）、
     * **听的句子不同**（「请及时派单」/「请及时查看」）、**打断的时机也不同**
     * （司机接单 / 派单员派完）。合成一个的话，"这句话该不该对这个人说"就没有地方表达了。
     */
    PENDING_ORDER,

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

    /**
     * 派单员那句素材的实测时长（`res/raw/pending_order.wav`）。
     *
     * 句子是「来订单了，有新订单待派单，请及时处理」，比司机那句长一点，所以是**另一个常量**
     * ——两条播报共用一份时长会让重复播报叠在一起（而这个错在真机上听起来只是"有点糊"）。
     * 同样由 `_tools/media/_gen_new_order_clip.py --kind dispatcher` 生成，脚本会打印该填的数字。
     *
     * ⚠️ **音色必须与司机那句一致**（晓晓，女声）：第一版是拿脚本当时的默认音色（云健，男声）
     * 生成的，用户一听就听出来了。两份素材的音色由 `_tools/media/_probe_clip_voice.py` 量基频对账
     * （红线在跑），女声中位 F0 ≈245~260Hz、男声 ≈116Hz。
     */
    const val PENDING_CLIP_MS = 5210L

    /**
     * 这一类播报的素材时长（毫秒）。
     *
     * ⛔ 只留一处映射：播放器 `delay`、「一直响」的止损、设置页那句"约几秒"全都要用它，
     * 各处自己 `when` 一遍的话，加了第三句素材就会有一处漏改（漏的那处不报错，只是叠音）。
     */
    fun clipMs(kind: AlertKind): Long = when (kind) {
        AlertKind.PENDING_ORDER -> PENDING_CLIP_MS
        else -> CLIP_MS
    }

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
        AlertKind.NEW_ORDER, AlertKind.PENDING_ORDER -> plan(setting)
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
     * 这个角色**平时听哪一句**（没有语音的角色 → null）。
     *
     * 一个角色只有一种"日常播报"：司机听「有新派单」，派单员听「有新订单待派单」。
     * 设置页的开关文案与「试听一声」都读它，**不许各自硬编码**
     * ——否则派单员点试听听到的是司机那句「请及时查看」，他会以为配错了。
     *
     * ⚠️ 「任务被撤回」不在其中：那是**事件**不是角色（见 [speaks]）。
     */
    fun voiceKind(role: Role?): AlertKind? = when (role) {
        Role.DRIVER -> AlertKind.NEW_ORDER
        Role.DISPATCHER -> AlertKind.PENDING_ORDER
        else -> null
    }

    /**
     * 这个角色有没有语音播报这件事（设置页/「我的」入口用它决定摆不摆语音那几项）。
     *
     * 2026-09-21 起**派单员也有**（用户要求）；货主仍然没有——「来单了」对他是**错的信息**，
     * 他不是要跑车也不是要派单的那个人。
     */
    fun hasVoice(role: Role?): Boolean = voiceKind(role) != null

    /**
     * 这一刻该不该响（**按角色 × 事件类型判**，不是"这个角色有没有语音"）。
     *
     * ⛔ 为什么必须两维：`announce()` 是站内信与实时事件**共用**的一个入口，
     * 只按角色判的话，派单员会对着司机的「来订单了，你有新的订单」发呆
     * （那不是他的活），司机也会被派单员那句「请及时派单」喊醒。
     */
    fun speaks(role: Role?, kind: AlertKind): Boolean = when (kind) {
        // 撤回/取消是司机那条线上的事（他不用跑了）。派单员不播它：
        // 一单被撤，待派池少一单是安静地变少的，为它喊一嗓子只会让人以为又多了一单。
        AlertKind.REVOKED -> role == Role.DRIVER
        else -> voiceKind(role) == kind
    }

    /** 没设置过「后台常驻」时按角色给缺省：司机与派单员默认开（都在等"响一声"），货主默认关 */
    fun defaultBackground(role: Role?): Boolean = hasVoice(role)

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
        // 新订单进待派池：后端 `publish_new_order_to_dispatchers` 给**每个**派单员发一条
        // 站内信（type=order.created，标题「新订单待派单」）。派单员那条语音就挂在这个事件上。
        // ⛔ 不认「dispatcher.pending_pool」那条实时事件：它**不带单号**（只是一句"角标该刷新了"），
        //    拿它当触发会变成"单号是 null 的一类播报"，去重键退化成 `pending:-1`
        //    → 60 秒内第二张单完全不响。
        "order.created" -> AlertEvent(
            kind = AlertKind.PENDING_ORDER,
            orderId = orderId,
            title = title,
            dedupeKey = "pending:" + (orderId ?: -1L),
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
        // 派单员的三个：`*_dispatcher` 是后端广播给**所有**派单员的同形事件
        // （司机接单/送达/订单被撤销）——对派单员就是"这一单已经有人处理了/没了"，
        // 他手机上那句「有新订单待派单」此时已经过时（他还盯着手机找那一单呢）。
        "order.driver_ack_dispatcher", "order.delivered_dispatcher", "order.cancelled_dispatcher",
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

    /**
     * 收到「这单结束了」的信号时，把该单的**新单去重键**作废（R14-14，2026-09-19 审计）。
     *
     * ⛔ 缺陷形状：派单员把单派给司机 A（响「来单了」）→ **撤回** → 60 秒内再派给同一个司机
     *    → 新事件带的还是**同一个** `assigned:{orderId}` 键、仍在 [DEDUPE_MS] 窗口内
     *    → `isDuplicate` 返回 true → **第二声完全不响**。
     *    司机刚被告知"撤回了"，重派却没有提示音；列表会刷新，但人在车上不会盯屏幕。
     *
     * 归 [shouldStop] 管是有道理的：接单/送达/撤回/取消之后，"这一单的新单提醒"本就该作废
     * ——作废之后如果这单又被重新派给他，那是一次**新的派单**，必须重新响。
     */
    fun forgetOnStop(seen: MutableMap<String, Long>, type: String, orderId: Long?) {
        if (orderId == null || !shouldStop(type)) return
        seen.remove("assigned:" + orderId)
        // 派单员那条同理：这一单已经处理完了，之后它若又回到待派池（撤销后重开、拆单等），
        // 那是一次**新的**待派单，必须重新响。
        seen.remove("pending:" + orderId)
    }

    /** 设置页显示的档位文案（用户看不懂「0 次」是什么意思） */
    fun repeatLabel(setting: Int, role: Role? = null): String = when (setting) {
        // 「一直响到……我干什么」这件事按角色说：司机是接单，派单员是派完单。
        // 派单员在设置页看到「响到我接单」会以为自己点错了页面（他不接单）。
        FOREVER -> if (role == Role.DISPATCHER) "一直响到我派完单" else "一直响到我接单"
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
     * 而它必须**按角色**说不同的话——语音只有司机和派单员有（见 [hasVoice] / [voiceKind]），
     * 给**货主**写「语音 3 次」，他看到的就是一句假话（他会等一个永远不会响的东西）。
     */
    fun summary(
        role: Role?,
        notificationsAllowed: Boolean,
        voiceEnabled: Boolean,
        repeat: Int,
        background: Boolean,
    ): String {
        if (!notificationsAllowed) return "通知权限未开"
        if (!hasVoice(role)) return if (background) "后台接收中" else "仅前台接收"
        if (!voiceEnabled) return "语音已关"
        // ⚠️ 档位文案要带上角色：派单员那一行如果写「一直响到我接单」，他会以为自己点错了页面
        return "语音 " + repeatLabel(repeat, role) + if (background) "·后台接收" else ""
    }
}
