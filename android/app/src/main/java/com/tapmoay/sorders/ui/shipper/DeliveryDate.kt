package com.tapmoay.sorders.ui.shipper

import com.tapmoay.sorders.ui.dispatcher.isoDateOfMillis
import com.tapmoay.sorders.ui.dispatcher.isoDateToMillis
import java.time.LocalDate
import java.time.temporal.ChronoUnit

/**
 * 下单页「送达日期」这一格的全部规则 —— **唯一实现**（界面里一个字都不许再碰 `java.time`）。
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
 * ## ⚠️ 选日期用的毫秒是 **UTC 零点**（复用全 App 那一份换算，不在这里再抄一遍）
 *
 * Material3 的 `DatePicker` 约定：`initialSelectedDateMillis` / `selectedDateMillis` 都是
 * "那一天的 **UTC 00:00**"的毫秒。换算住在 [com.tapmoay.sorders.ui.dispatcher.isoDateOfMillis] /
 * [com.tapmoay.sorders.ui.dispatcher.isoDateToMillis]（`ui/dispatcher/VehicleInspection.kt`）——
 * **全 App 只有那一份**，车辆年检页与这里共用（判据 `_check_vehicle_inspection_ui.py:158` 盯着"只有一处"）。
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

/** `selectableDates` 要的形态：给毫秒判断能不能选（"不早于今天"）。 */
internal fun deliveryDateSelectable(utcTimeMillis: Long): Boolean =
    deliveryDateAllowed(isoDateOfMillis(utcTimeMillis), LocalDate.now())
