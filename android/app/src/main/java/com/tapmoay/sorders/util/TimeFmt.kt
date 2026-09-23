package com.tapmoay.sorders.util

import java.time.LocalDate
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

/**
 * 后端时刻 → **设备本地**墙上时间。
 *
 * ## ⚠️ 这里修过一个"所有时间都早 8 小时"的静默缺陷（2026-09-19）
 *
 * 后端的时间列**一律是 naive UTC**（`business_time.utc_now_naive`），JSON 里长这样：
 *
 * ```
 * "created_at": "2026-09-19T10:09:36.713251"      ← 没有 Z、没有 +08:00
 * ```
 *
 * 而原来这里写的是 `OffsetDateTime.parse(iso)` —— 它**要求带偏移量**，
 * 遇到上面那种串**必然抛异常**，于是每一处调用都掉进兜底分支
 * （`iso.take(16).replace('T',' ')`），把 **UTC 时刻原样印出来**。
 *
 * 后果：真机（东八区）上**所有**时间都比墙上时间早 8 小时——
 * 订单时间、库存流水时间、结算时间全错，而界面上完全看不出来
 * （数字格式正常、排序也正常，因为大家一起偏移）。
 * ⚠️ 本机模拟器里的时区恰好是 UTC，所以这个缺陷**在模拟器上永远看不见** ——
 * 它只会在真机上暴露，而且用户大概率会以为是"服务器的时钟不准"。
 *
 * 现在：naive 串按 **UTC** 解释，再换算到设备时区。带偏移量的串（如果有）照旧按它自己算。
 *
 * @param zone 目标时区，默认设备时区。**测试必须显式传**，
 *   否则断言会跟着跑测试那台机器的时区变（换台机器就红）。
 */
fun formatDateTime(iso: String?, zone: ZoneId = ZoneId.systemDefault()): String {
    if (iso.isNullOrBlank()) return ""
    return runCatching {
        DateTimeFormatter.ofPattern("MM-dd HH:mm").format(parseBackendInstant(iso).atZoneSameInstant(zone))
    }.getOrElse {
        // 认不出来的形状（例如 `date` 型字段只给了 `2026-09-19`）→ 截断显示，至少不崩
        iso.take(16).replace('T', ' ')
    }
}

/**
 * 后端时刻字符串 → 带时区的时刻。
 *
 * 两种形状都认：
 * - 带偏移量的（`2026-09-19T10:09:36+00:00`）→ 按它自己说的算；
 * - **naive 的**（`2026-09-19T10:09:36.713251`，也就是本项目后端实际发的形状）→ 按 **UTC** 解释。
 *
 * 单独抽出来是为了**能被单测直接钉住**：这个函数错了，全 App 的时间都会错，
 * 而错的样子（统一早 8 小时）在界面上看不出来。
 */
fun parseBackendInstant(iso: String): OffsetDateTime =
    runCatching { OffsetDateTime.parse(iso) }.getOrElse {
        LocalDateTime.parse(iso).atOffset(ZoneOffset.UTC)
    }

fun formatDateCN(iso: String?): String = iso?.take(10) ?: ""

/**
 * 后端**时刻**（带时分秒的 naive UTC）→ 当地 `MM-dd`。
 *
 * ⛔ 与 [formatDateCN] 的分工（2026-09-23 第 18 轮并行渗透 A2-4）：
 * · [formatDateCN] 只用于**日期列**（`entry_date` / `exp_date` / `order_date`）——
 *   那些值本身就是当地日、没有时区可换算，`take(10)` 就是对的；
 * · 这个函数只用于**时间戳列**（`delivered_at` / `paid_at` / `created_at`）——
 *   直接 `take(10)` / `take(16)` 印出来的是 **UTC**：真机上比墙上时间早 8 小时，
 *   当地 00:00~08:00 的那些行还会**跨到前一天**（而模拟器时区恰好是 UTC，永远看不见）。
 */
fun formatInstantDay(iso: String?, zone: ZoneId = ZoneId.systemDefault()): String {
    if (iso.isNullOrBlank()) return ""
    return runCatching {
        DateTimeFormatter.ofPattern("MM-dd").format(parseBackendInstant(iso).atZoneSameInstant(zone))
    }.getOrElse {
        iso.take(10)
    }
}

fun today(): String = LocalDate.now().toString()
