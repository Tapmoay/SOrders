package com.tapmoay.sorders.util

import org.junit.Assert.assertEquals
import java.time.ZoneId
import org.junit.Test

/**
 * `parseBackendInstant` / `formatDateTime`：**后端 naive UTC → 设备本地时间**。
 *
 * ## 为什么这个文件必须存在
 * 后端的时间列一律是 naive UTC，JSON 里是 `"2026-09-19T10:09:36.713251"`（没有 `Z`、没有偏移）。
 * 老代码用 `OffsetDateTime.parse` 解析它 —— **必然抛异常**，于是每一处调用都掉进兜底分支、
 * 把 UTC 原样印出来：真机上所有时间**早 8 小时**，而界面上看不出来
 * （格式正常、排序也正常，因为大家一起偏移）。
 *
 * ⚠️ 这个缺陷**在模拟器上永远看不见**：模拟器时区恰好是 UTC。
 * 所以这里断言时**必须显式传时区**，不能靠 `ZoneId.systemDefault()` ——
 * 那样换一台机器跑测试就会红/绿翻转，判据等于没有。
 */
class TimeFmtTest {

    private val shanghai = ZoneId.of("Asia/Shanghai")

    @Test
    fun `naive 串按 UTC 解释_不是按本地时间`() {
        // 后端实际发的形状（无时区后缀）
        val t = parseBackendInstant("2026-09-19T10:09:36.713251")
        assertEquals("2026-09-19T10:09:36.713251Z", t.toInstant().toString())
    }

    @Test
    fun `带偏移量的串按它自己说的算`() {
        val t = parseBackendInstant("2026-09-19T10:09:36+00:00")
        assertEquals("2026-09-19T10:09:36Z", t.toInstant().toString())
        // +08:00 的 10:09 与 UTC 的 02:09 是同一时刻
        assertEquals(
            parseBackendInstant("2026-09-19T02:09:36Z").toInstant(),
            parseBackendInstant("2026-09-19T10:09:36+08:00").toInstant(),
        )
    }

    @Test
    fun `东八区设备上 UTC 10点09 显示成 18点09`() {
        // ⛔ 这条就是那个"早 8 小时"缺陷的判据：老实现会显示成 "09-19 10:09"
        assertEquals("09-19 18:09", formatDateTime("2026-09-19T10:09:36.713251", shanghai))
    }

    @Test
    fun `跨日也按本地算`() {
        // UTC 的 19 号 20:30 = 东八区的 20 号 04:30（月/日都要跟着翻）
        assertEquals("09-20 04:30", formatDateTime("2026-09-19T20:30:00", shanghai))
    }

    @Test
    fun `认不出来的形状退化成截断显示而不是崩`() {
        // `date` 型字段只给日期（项目的 formatDateCN 用另一条路，这里只是别崩）
        assertEquals("2026-09-19", formatDateTime("2026-09-19", shanghai))
        assertEquals("", formatDateTime(null, shanghai))
        assertEquals("", formatDateTime("  ", shanghai))
    }
}
