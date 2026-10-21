package com.tapmoay.sorders.ui.common

import com.tapmoay.sorders.ui.dispatcher.isoDateOfMillis
import java.time.LocalDate
import java.time.temporal.ChronoUnit

/**
 * 「送达日期」这一格的全部规则 —— **唯一实现**（界面里一个字都不许再碰 `java.time`）。
 *
 * ## 用户口径（2026-10-21 原话）
 *
 * > 「货主和批发商以及派单员，他们在下单的时候……**可以选择送到的日期**；……还要加一个警示，
 * >   告诉他们**订单必须提前一天下达**，当天下的单不一定能准时送达。」
 *
 * 于是这一格只有三条规则，都写在这个文件里：
 *
 * 1. **默认明天**（[defaultDeliveryDate]）——「必须提前一天」落到默认值上，用户不动它就是对的那天；
 * 2. **不早于今天**（[deliveryDateAllowed]）—— 昨天已经过去了，选它只会造出一单"注定晚点"；
 *    今天**允许**选（有生意就是这么做的），但界面上要如实说"不一定准时"（文案在下单页那张红条上）；
 * 3. **显示成"明天 · 10-22"**（[deliveryDateLabel]）—— 只印 `2026-10-22` 的话，用户得自己在
 *    脑子里换算"那是周几、还剩几天"，而这一格要回答的正是"还有多久到"。
 *
 * ## 为什么住在 `ui/common`（CHG-0134，2026-10-22 挪进来的）
 *
 * 下单页要"选"，而**订单卡片**（`ui/common/OrderCard.kt`，货主 / 派单员 / 司机三端共用）与
 * **订单详情**（`ui/order/OrderDetailScreen.kt`）要"看" —— 用户 2026-10-22 逐字：
 * 「我们的订单[详情]……也是可以看到它时间信息」「**司机**可以知道他这个订单大概是多少天……
 * **派单员**也能知道，就能提前做好规划」。
 * 三个页面都要用，规则就不能住在某一个角色页（`ui/shipper`）里：那会让 `ui/common` 反过来
 * 依赖 `ui/shipper`。⛔ 也别为了省事在卡片里再写一遍"还有几天"——同一句话两个算法，
 * 迟早一处改了另一处没改。
 *
 * ## ⚠️ 选日期用的毫秒是 **UTC 零点**（复用全 App 那一份换算，不在这里再抄一遍）
 *
 * Material3 的 `DatePicker` 约定：`initialSelectedDateMillis` / `selectedDateMillis` 都是
 * "那一天的 **UTC 00:00**"的毫秒。换算住在 [com.tapmoay.sorders.ui.dispatcher.isoDateOfMillis]
 * （`ui/dispatcher/VehicleInspection.kt`）—— **全 App 只有那一份**，车辆年检页与这里共用
 * （判据 `_check_vehicle_inspection_ui.py:158` 盯着"只有一处"）。
 *
 * ⛔ 别在下面再写一对：按设备时区换算（`atStartOfDay(ZoneId.systemDefault())`）在东八区会
 * **整体差一天** —— 打开时停在昨天、确认时又写回昨天，界面上完全看不出来（用户只会说
 * "我明明选的明天"）。2026-10-21（FEAT-0028）已经把那一份改成了 **`ZoneOffset.UTC`**，
 * 顺带修掉车辆年检页同一个"差一天"。
 */

/** 「必须提前一天」——默认值就落在这上面，改它等于改业务口径。 */
const val DELIVERY_LEAD_DAYS: Long = 1L

/** 解析 `YYYY-MM-DD`；坏串/空 = null（⛔ 不许抛异常：这一格的值可能来自旧请求或手改的草稿）。 */
internal fun parseDeliveryDate(raw: String?): LocalDate? {
    val s = raw?.trim().orEmpty()
    if (s.length != 10) return null
    return runCatching { LocalDate.parse(s) }.getOrNull()
}

/** 默认送达日 = **明天**（设备当地日；[today] 只是给单测传"今天"用的）。 */
fun defaultDeliveryDate(today: LocalDate = LocalDate.now()): String =
    today.plusDays(DELIVERY_LEAD_DAYS).toString()

/** 这一天还能不能选：**不早于今天**（今天可选 —— 只是不保证准时）。空/坏串 = 不可选。 */
fun deliveryDateAllowed(raw: String?, today: LocalDate = LocalDate.now()): Boolean {
    val d = parseDeliveryDate(raw) ?: return false
    return !d.isBefore(today)
}

/** 距离今天还有几天：明天 = 1、今天 = 0、昨天 = -1；空/坏串 = null（界面上说"未选择"）。 */
fun deliveryLeadDays(raw: String?, today: LocalDate = LocalDate.now()): Long? {
    val d = parseDeliveryDate(raw) ?: return null
    return ChronoUnit.DAYS.between(today, d)
}

/** 星期几的中文：周一…周日（只给"超过大后天"的那些日子用，见 [deliveryDateLabel]）。 */
internal fun weekdayCn(d: LocalDate): String =
    when (d.dayOfWeek.value) {
        1 -> "周一"
        2 -> "周二"
        3 -> "周三"
        4 -> "周四"
        5 -> "周五"
        6 -> "周六"
        else -> "周日"
    }

/** 抽屉里那几行的一句话名字：「今天（10-21）」「明天（10-22）」「10-25 周日」。 */
fun deliveryDayWord(raw: String?, today: LocalDate = LocalDate.now()): String {
    val d = parseDeliveryDate(raw) ?: return "未选择"
    val md = "%02d-%02d".format(d.monthValue, d.dayOfMonth)
    return when (ChronoUnit.DAYS.between(today, d)) {
        0L -> "今天（" + md + "）"
        1L -> "明天（" + md + "）"
        2L -> "后天（" + md + "）"
        3L -> "大后天（" + md + "）"
        else -> md + " " + weekdayCn(d)
    }
}

/**
 * 下单页那一行右侧显示什么：**「明天 · 10-22」**（空 = 「未选择」）。
 *
 * ⚠️ 超过大后天就不再说"几天后"（「4 天后」读起来像倒计时，而这一格要的是**日期**本身），
 * 改成「10-26 周一」—— 一眼看得出是哪天、周几。
 */
fun deliveryDateLabel(raw: String?, today: LocalDate = LocalDate.now()): String {
    val d = parseDeliveryDate(raw) ?: return "未选择"
    val md = "%02d-%02d".format(d.monthValue, d.dayOfMonth)
    return when (ChronoUnit.DAYS.between(today, d)) {
        0L -> "今天 · " + md
        1L -> "明天 · " + md
        2L -> "后天 · " + md
        3L -> "大后天 · " + md
        else -> md + " " + weekdayCn(d)
    }
}

/**
 * 抽屉里那四行：**今天 / 明天 / 后天 / 大后天**（`iso to 文案`，界面照它一行一行画）。
 *
 * ⚠️ 只给这四行 + 一个「选其他日期」：这一行的答案 99% 是明天（提前一天），最近四天摊在
 * 一层里 = 一次点选；再远的日子才值得翻日历（那次要多点一下，但那是少数）。
 */
fun deliveryDateChoices(today: LocalDate = LocalDate.now()): List<Pair<String, String>> =
    (0L..3L).map { d ->
        val iso = today.plusDays(d).toString()
        iso to deliveryDayWord(iso, today)
    }

/**
 * 卡片 / 详情上的**倒计时**：「今天送到」「还有 N 天」「已过 N 天」；没选过 = null。
 *
 * 用户 2026-10-22 逐字：「**司机**可以知道他这个订单大概是多少天的时候，大概什么多少天，
 * **派单员**也能知道，就能提前做好规划」——所以这一格回答的是**还剩几天**，不是"几号"。
 */
fun deliveryCountdown(raw: String?, today: LocalDate = LocalDate.now()): String? {
    val d = parseDeliveryDate(raw) ?: return null
    val n = ChronoUnit.DAYS.between(today, d)
    return when {
        n == 0L -> "今天送到"
        n > 0L -> "还有 " + n + " 天"
        else -> "已过 " + (-n) + " 天"
    }
}

/** 终态订单：日子已经是历史，⛔ 不再给"还有几天"（那会读成"还没到"）。 */
private val FINISHED_STATUS = setOf("DELIVERED", "CANCELLED", "RETURNED")

/**
 * 订单卡片 / 订单详情那一行要显示的整句：`10-23 · 还有 1 天`；终态只印 `10-23`。
 *
 * 返回 null = **这一单没选过送达日**（存量单 / 老客户端 / AI 下单）→ 调用方整行不画。
 * ⛔ 别在界面里自己拼"还有几天"：倒计时只有 [deliveryCountdown] 那一个算法。
 */
fun deliveryDateText(raw: String?, status: String, today: LocalDate = LocalDate.now()): String? {
    val d = parseDeliveryDate(raw) ?: return null
    val md = "%02d-%02d".format(d.monthValue, d.dayOfMonth)
    if (status.uppercase() in FINISHED_STATUS) return md
    return md + " · " + (deliveryCountdown(raw, today) ?: md)
}

/**
 * 卡片 / 详情上**一定画得出来**的那一句（[deliveryDateText] 的兜底版）。
 *
 * 用户 2026-10-22 纠正过一次：没选过的单**不许整行消失** ——
 * 「如果他没选择的话，订单的就会有一个信息，就是用户或者说货主他并没有选择送达日期」。
 * 也就是说：**"没选"本身是一条要写出来的事实**，不能让司机/派单员自己猜"这条为什么没有日期"。
 *
 * ⛔ 所以界面只许调这一个（别再用可空的 [deliveryDateText] 自己写 if/else）。
 */
fun deliveryDateDisplay(raw: String?, status: String, today: LocalDate = LocalDate.now()): String =
    deliveryDateText(raw, status, today) ?: "未选择送达日期"

/** `selectableDates` 要的形态：给毫秒判断能不能选（"不早于今天"）。 */
internal fun deliveryDateSelectable(utcTimeMillis: Long): Boolean =
    deliveryDateAllowed(isoDateOfMillis(utcTimeMillis), LocalDate.now())
