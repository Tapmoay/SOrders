package com.tapmoay.sorders.ui.dispatcher

import com.tapmoay.sorders.ui.messages.MessageRisk
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeParseException
import java.time.temporal.ChronoUnit

/**
 * 车辆年检（FEAT-0022）—— 车辆档案里的两个日期 + 「下次年检还有多久」。
 *
 * ## 两个日期（都是**可空**的：老车没有很正常）
 * - `registration_date` 上牌日期：给车子建档案时用户会填的那一格。
 * - `last_inspection_date` 上一次年检日期。
 * 后端入参/出参都带（ISO `YYYY-MM-DD` 字符串，可空）。
 *
 * ## ⛔ 下次年检**只有一处算**（后端）
 * `next_due = (last_inspection_date ?: registration_date) + 1 年`；两个都空 ⇒ 不给提醒。
 * 本文件的 [nextInspectionDue] 是**后端出参还没带 `next_inspection_date` 时的兜底**：
 * 后端一旦在出参里给了，[inspectionBadgeOf] 优先用后端的（同一条规则，不发明第二套）。
 *
 * ## ⛔ 本文件是「车辆年检」的唯一一处实现
 * 界面（`VehicleManageScreen.kt`）只准调这里的函数：不许自己 `LocalDate.parse` /
 * `plusYears` / 算天数 / 写 `0xFFE07B00` 这种风险色字面量（风险色唯一出处见
 * `ui/messages/MessageGrading.kt`）。判据 `_tools/qa/_check_vehicle_inspection_ui.py` 钉着。
 */

/** 距到期多少天开始提醒（warn 档）。后端 `vehicle.inspection_due` 用的也是这 30 天。 */
internal const val INSPECTION_WARN_DAYS = 30L

/**
 * 严格 ISO `YYYY-MM-DD` → [LocalDate]；空串 / 别的形状 / 解析不了 = null。
 *
 * ⛔ 不抛异常、也不拿别的格式去猜（数据库里这两个日期要么是 ISO、要么是空）。
 */
internal fun parseIsoDate(raw: String?): LocalDate? {
    val text = raw?.trim().orEmpty()
    if (text.isEmpty()) return null
    return try {
        LocalDate.parse(text)
    } catch (e: DateTimeParseException) {
        null
    }
}

/**
 * 下次年检日期 = `(上次年检 ?: 上牌) + 1 年`；两个都空 = null（= 后端不给提醒）。
 *
 * 为什么是 `plusYears(1)` 而不是 365 天：年检是按**自然年**办的，闰年那天差 1 天会算错。
 */
internal fun nextInspectionDue(registrationDate: String?, lastInspectionDate: String?): LocalDate? {
    val base = parseIsoDate(lastInspectionDate) ?: parseIsoDate(registrationDate) ?: return null
    return base.plusYears(1)
}

/** 距下次年检还有几天：今天到期 = 0、已经过了 = 负数。 */
internal fun inspectionDaysLeft(due: LocalDate, today: LocalDate): Long =
    ChronoUnit.DAYS.between(today, due)

/**
 * 剩余天数 → 风险档：`> 30` 常规（INFO）/ `≤ 30` 警告（WARN）/ 已过期（`< 0`）危险（DANGER）。
 *
 * ⛔ 档→颜色不在这里：界面拿 [com.tapmoay.sorders.ui.messages.emphasisColor] 上色
 * （DANGER 红 / WARN 橙 / INFO = 不上风险色），那张表是「风险 → 颜色」的唯一一处。
 */
internal fun inspectionRisk(daysLeft: Long): MessageRisk = when {
    daysLeft < 0 -> MessageRisk.DANGER
    daysLeft <= INSPECTION_WARN_DAYS -> MessageRisk.WARN
    else -> MessageRisk.INFO
}

/** 「还有 N 天」那一段话；已经过期就说「已过期 N 天」（⛔ 不写「还有 -3 天」）。 */
internal fun inspectionText(daysLeft: Long): String = when {
    daysLeft < 0 -> "已过期 ${-daysLeft} 天"
    daysLeft == 0L -> "今天到期"
    else -> "还有 $daysLeft 天"
}

/** 卡片上那一行要的全部东西（日期 / 剩余天数 / 风险档 / 文案）。 */
data class InspectionBadge(
    val due: LocalDate,
    val daysLeft: Long,
    val risk: MessageRisk,
    val text: String,
)

/**
 * 算不出来时返回 null（两个日期都空 ⇒ **整行不出现**，跟「这车能装多少」那一行同一个规矩：
 * 宁可不说，也不写一行「下次年检：--」让人以为是坏了）。
 */
internal fun inspectionBadge(due: LocalDate?, today: LocalDate): InspectionBadge? {
    val day = due ?: return null
    val days = inspectionDaysLeft(day, today)
    return InspectionBadge(due = day, daysLeft = days, risk = inspectionRisk(days), text = inspectionText(days))
}

/** 卡片/弹层上的一整行：`下次年检：2027-03-01 · 还有 140 天`；算不出来 = null。 */
internal fun inspectionLine(badge: InspectionBadge?): String? =
    badge?.let { "下次年检：${it.due} · ${it.text}" }

/**
 * 优先用**后端出参**里的 `next_inspection_date`，后端还没给（老版本后端 / 空字段）才本地兜底。
 *
 * [today] 只是给单测传"今天"用的（默认取本机当天）。
 */
internal fun inspectionBadgeOf(
    backendNextDue: String?,
    registrationDate: String?,
    lastInspectionDate: String?,
    today: LocalDate = LocalDate.now(),
): InspectionBadge? = inspectionBadge(
    parseIsoDate(backendNextDue) ?: nextInspectionDue(registrationDate, lastInspectionDate),
    today,
)

// ---------------------------------------------------------------------------
// 日期选择器 ↔ ISO 串（界面里一个字都不许碰 java.time）
// ---------------------------------------------------------------------------

/** 日期选择器给的 UTC 零点毫秒 → 本机那一天的 ISO 串（与 `InvoiceFormScreen` 同一套换算）。 */
internal fun isoDateOfMillis(millis: Long): String =
    Instant.ofEpochMilli(millis).atZone(ZoneId.systemDefault()).toLocalDate().toString()

/** ISO 串 → 日期选择器要的毫秒（用来"打开时先停在已填的那天"）；空/解析不了 = null。 */
internal fun isoDateToMillis(raw: String?): Long? =
    parseIsoDate(raw)?.atStartOfDay(ZoneId.systemDefault())?.toInstant()?.toEpochMilli()

// ---------------------------------------------------------------------------
// 未来日期不可选（后端不做日期范围校验）
// ---------------------------------------------------------------------------

/**
 * 这一天能不能选：**不许选未来**。
 *
 * ⛔ 为什么这道门在界面这一侧：后端**不做**日期范围校验 —— 上牌/上次年检填一个未来的日期，
 * 后端只是"算不出该提醒的那天"（安静地不提醒），不报错、界面上也看不出来（FEAT-0022
 * 后端会话 2026-10-11 补充口径）。等用户发现这台车从没被提醒过，一年已经过去了。
 *
 * 坏串/空 = 不可选（选不出来的一天不该被写进档案）。
 */
internal fun inspectionDateAllowed(iso: String?, today: LocalDate): Boolean {
    val day = parseIsoDate(iso) ?: return false
    return !day.isAfter(today)
}

/** 选择器那条回调要的形态：给毫秒判断能不能选（"今天"取本机当天，界面不碰 java.time）。 */
internal fun inspectionDateSelectable(utcTimeMillis: Long): Boolean =
    inspectionDateAllowed(isoDateOfMillis(utcTimeMillis), LocalDate.now())

// ---------------------------------------------------------------------------
// PATCH 语义：这一格**要不要发**
// ---------------------------------------------------------------------------

/**
 * 新建时：填了才发，没填 = null（键不出现在请求体里；⛔ 不发空串）。
 */
internal fun newDateOrNull(draft: String): String? = draft.trim().ifEmpty { null }

/**
 * 编辑时：**只有用户真的改过才发**，没动过 = null（= 这个键不进请求体，后端一个字段都不动）。
 *
 * ⛔ 为什么不"永远原样发"：这两个日期都可空，老车档案里本来就是空的 ⇒ 界面上是空串；
 * 原样发出去就是一句「把这格清空」——**老车没填过它，不该因为点了一次保存就被写一遍**。
 * 反过来「原来有值、用户点了清除」= 真的改动，发空串（后端 `""` = 清空这一格）。
 */
internal fun changedDateOrNull(original: String?, draft: String): String? {
    val now = draft.trim()
    val before = original?.trim().orEmpty()
    return if (now == before) null else now
}
