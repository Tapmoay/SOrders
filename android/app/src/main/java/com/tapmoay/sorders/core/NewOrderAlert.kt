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

/**
 * `sync` 回补里的一条候选（2026-10-06 CHG-0055）：重连后要判断"这一条该不该补响一声"。
 *
 * 只带判定要用的三样：事件类型、单号、标题（标题只进播报文案，不参与判定）。
 * 与 [AlertEvent] 分开是因为它比后者**更早**一步：候选里混着撤回、送达、改单这些
 * 根本不该响的事件，先得由 [NewOrderAlert.ringbackOf] 挑出那一条，才轮得到 [AlertEvent]。
 */
data class RingItem(val type: String, val orderId: Long?, val title: String)

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

    /**
     * 没设置过「后台常驻」时给什么缺省：**所有角色都开**。
     *
     * 2026-10-04（CHG-0030，用户点名）：原来是 `hasVoice(role)`——只有司机与派单员默认开，
     * 货主 / 批发商默认关，他们「我的 → 消息提醒」那一行就写着**「仅前台接收」**：
     * 关掉 App 之后**一条通知都收不到**，而那些消息对货主是"司机接单了 / 货送到了"，
     * 不是可有可无的响铃。
     *
     * 用户的判词是「所有角色后台都能接收」：语音播报仍然是司机与派单员的活（见 [voiceKind]，
     * 「来单了」对货主是**错的信息**），但**后台接收只是把消息推进通知栏**，
     * 对哪个角色都是净收益 —— 真要说差别，只有"司机更在乎"这一条，
     * 而"缺省"不是用来表达在乎程度的。
     *
     * 参数留着：三个调用点都是在问"我这个角色该怎么算"（[AlertPrefs.backgroundEnabled] /
     * [AlertService.sync] / [BootReceiver]），答案一样也仍然是同一个问题 ——
     * 将来真要分角色，只动这一行（别的写法都会让某个角色的缺省悄悄漂走）。
     */
    @Suppress("UNUSED_PARAMETER")
    fun defaultBackground(role: Role?): Boolean = true

    /**
     * 后台常驻那条通知上该写什么（标题 to 正文）。**按角色说对的话**。
     *
     * 2026-10-04（CHG-0030）：它原来在 [com.tapmoay.sorders.core.NotifyCenter.serviceNotification]
     * 里写死「SOrders 正在后台接收派单 / 有新派单会立刻提醒你」—— 那时只有司机与派单员默认开着，
     * 这句话大致说得通；现在**所有角色**都默认开，货主的通知栏里就会出现"正在接收派单"，
     * 而他既不接单也不派单：那是一句**假话**，而且它常驻在通知栏、一天要看很多次。
     * 分工与 [voiceKind] 同一套：司机收派单、派单员收待派新订单、其余角色收自己那些消息
     * （司机那一句**逐字不动**，它是真机上验过的那句）。
     */
    fun serviceNotice(role: Role?): Pair<String, String> = when (voiceKind(role)) {
        AlertKind.NEW_ORDER -> "SOrders 正在后台接收派单" to "有新派单会立刻提醒你"
        AlertKind.PENDING_ORDER -> "SOrders 正在后台接收新订单" to "有新订单待派单会立刻提醒你"
        // REVOKED 走不到这里（[voiceKind] 只映射两个角色）；写出来是为了让 when 穷尽，
        // 也让"除这两种之外都一样"这件事在代码里看得见。
        AlertKind.REVOKED, null -> "SOrders 正在后台接收消息" to "有新消息会立刻提醒你"
    }

    /**
     * 设置页「关掉 App 也收单」那一档的文案（标题 to 副标题）—— 同样按角色说要收的是什么。
     *
     * 副标题是用户决定**要不要关掉它**时唯一读到的理由：给货主写「关闭后只有打开 App 时
     * 才收得到新派单」，他会得出"派单跟我无关，关了吧"—— 可他关掉的其实是
     * "司机接单了 / 货送到了"这些消息（分工见 [serviceNotice]）。
     */
    fun backgroundRowText(role: Role?): Pair<String, String> = when (voiceKind(role)) {
        AlertKind.NEW_ORDER -> "关掉 App 也收单" to "关闭后只有打开 App 时才收得到新派单"
        AlertKind.PENDING_ORDER -> "关掉 App 也收单" to "关闭后只有打开 App 时才收得到新订单"
        AlertKind.REVOKED, null -> "关掉 App 也收消息" to "关闭后只有打开 App 时才收得到新消息"
    }

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
        // BUG-0027（台账 TA-05）：**被派单员删进回收站**是第三件同一件事 —— 单子从司机手里
        // 消失了，他得听见一句（语音素材沿用「有任务被撤回」，不新增音频）。
        // 去重键沿用 `revoked:`：同一单先撤回后被删（或反过来）不该喊两遍。
        "order.revoked", "order.cancelled", "order.deleted" -> AlertEvent(
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
        // BUG-0027（台账 TA-05）：单子被删进回收站 → 活没了，正在喊的「来订单了」立刻闭嘴
        "order.deleted",
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

    /**
     * 「已响过」记录的保留窗口：**一天**。
     *
     * 比 [DEDUPE_MS]（60 秒，防两条链路推同一件事）长得多，因为它防的是另一件事：
     * 进程被杀 / 冷启动后重连，后端会把断线期间那批站内信**再补一遍** ——
     * 内存里那份 `announced` 已经随进程没了，只有落盘的记录能回答"这一声我之前响过没有"
     * （用户 2026-10-06 的口径：**响过了就没必要，没响的话就要响**）。
     * 一天足够覆盖"司机今天出车"这一段；超窗的记录在读的时候就丢掉了。
     */
    const val RUNG_KEEP_MS = 24 * 60 * 60 * 1000L

    /** 「已响过」最多记多少条：超了从最旧的丢。这不是业务口径，是防"越攒越长"。 */
    const val RUNG_MAX = 64

    /**
     * 读落盘的「已响过」记录（`AlertPrefs.rungKeys`）：`key@时间戳;key@时间戳`。
     *
     * ⛔ 坏行一律丢掉、不抛异常：这个串只由本机进程写，格式坏了最多是升级时的残留，
     *    而"读失败"**不该**让新单不响（少一条记录 = 多响一声，比不响安全得多）。
     */
    fun rungDecode(raw: String?, now: Long): MutableMap<String, Long> {
        val out = mutableMapOf<String, Long>()
        raw?.split(';')?.forEach { part ->
            val cut = part.lastIndexOf('@')
            if (cut <= 0) return@forEach
            val at = part.substring(cut + 1).toLongOrNull() ?: return@forEach
            out[part.substring(0, cut)] = at
        }
        rungTrim(out, now)
        return out
    }

    /** 写回盘上：按时间升序拼（老的在前，人肉看的时候顺序与发生顺序一致）。 */
    fun rungEncode(seen: Map<String, Long>): String =
        seen.entries.sortedBy { it.value }.joinToString(";") { it.key + "@" + it.value }

    /** 裁剪：先丢掉超过 [RUNG_KEEP_MS] 的，条数超过 [RUNG_MAX] 时只留最新的那些。 */
    fun rungTrim(seen: MutableMap<String, Long>, now: Long) {
        seen.entries.removeAll { now - it.value > RUNG_KEEP_MS }
        if (seen.size <= RUNG_MAX) return
        val keep = seen.entries.sortedByDescending { it.value }.take(RUNG_MAX).map { it.key }
        seen.keys.retainAll(keep.toSet())
    }

    /** 记一条"响过了"（顺手裁一次，别让这份记录一直长）。 */
    fun markRung(seen: MutableMap<String, Long>, key: String, now: Long) {
        seen[key] = now
        rungTrim(seen, now)
    }

    /**
     * 回补（重连 / 登录后的 `sync`）里该补响哪一条；没有就返回 null。
     *
     * ⛔ 为什么必须有这个函数（2026-10-06 CHG-0055，台账 L-26）：
     *    `sync` 那条分支只把回补的站内信推进通知栏、**一声不响**（代码注释自己写着
     *    "司机错过新单的三层提醒在重连这条路径上是空的"）。于是车子发动前才登录、
     *    或者路上断网那一段被派的单：通知栏里躺着，人在车上不会翻通知栏 —— 而那正是
     *    他最需要听见的一声。用户原话：「假如司机登录了账号，这时候有个订单派给他了，
     *    他就直接开始响铃……**那个铃声要响的，不是不响**」。
     *
     * 三条"自己不响"的规矩都在这里：
     *   · 只补**还在等他动手**的那一声（[voiceKind] 那一类）：撤回/取消不补
     *     （错过的活已经没了，为它喊一嗓子只会让人以为又来了一单）；
     *   · 同一单在它**之后**还有"该闭嘴了"的信号（接单 / 送达 / 撤回 / 派完）⇒ 这单不用他管了，不补；
     *   · 一次只补**最新的一条**（其余只进通知栏）：回补可能一次带来十几条，全放出来就是十几段语音叠着响。
     *
     * `rung` 是落盘的"已响过"（[rungDecode] 的产物）：命中就说明这一声之前已经响过，不再补。
     * 传进来的 `items` 按**时间升序**（后端取最新那批之后客户端 reverse），所以从后往前找第一条。
     */
    fun ringbackOf(items: List<RingItem>, role: Role?, rung: Map<String, Long>): RingItem? {
        val kind = voiceKind(role) ?: return null
        val stopped = mutableSetOf<Long>()
        for (i in items.indices.reversed()) {
            val item = items[i]
            // "这单结束了"的信号：先把它记下来，再判它**前面**那些候选该不该补
            if (shouldStop(item.type)) {
                item.orderId?.let { stopped += it }
                continue
            }
            val ev = eventOf(item.type, item.orderId, item.title) ?: continue
            if (ev.kind != kind) continue
            if (item.orderId != null && item.orderId in stopped) continue
            if (rung.containsKey(ev.dedupeKey)) continue
            return item
        }
        return null
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
     *
     * 反过来也一样（2026-10-04 CHG-0030）：**「后台接收」这一半每个角色都要写**——
     * 有语音的那两个角色从前只在开着的时候加一句「·后台接收」，关掉就一个字不提，
     * 于是"关掉 App 还收不收得到"这件事在他们那一行上**看不出来**。
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
        // ⚠️ 「后台接收 / 仅前台接收」这一半对**每个**角色都要说（2026-10-04 CHG-0030）：
        //    从前只有货主那一支写「仅前台接收」，司机把「关掉 App 也收单」关掉之后这一行
        //    还是「语音 3 次」—— 他会以为关掉 App 也收得到。同一个状态，全角色同一个说法。
        return "语音 " + repeatLabel(repeat, role) +
            if (background) "·后台接收" else "·仅前台接收"
    }
}
