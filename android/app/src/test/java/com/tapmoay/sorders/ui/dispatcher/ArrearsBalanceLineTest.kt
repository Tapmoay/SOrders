package com.tapmoay.sorders.ui.dispatcher

import com.tapmoay.sorders.data.remote.dto.CustomerBalanceRowDto
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 挂账单位卡上那一行余额（TB-01，2026-10-09 财务方向测试发现后补的）。
 *
 * ### 为什么这一行值得一个测试文件
 * 它最容易被"顺手写错"的三种写法，都是界面上**看起来正常**、只有数或措辞是错的：
 *
 * - 没有这一行（这个单位没欠过钱）时写成「已挂账 ¥0」—— 把"没有欠款事实"说成"欠了 0 元"；
 * - 没设过额度时写成「额度 ¥0」—— 把"没管过"说成"一分钱都不许赊"；
 * - 超限时自己拿 `credit_used - limit` 算一遍"超了多少" —— 客户端出现第二份钱算法。
 *
 * 所以这里钉的是**每一档的措辞与取数来源**，不是"这个函数能跑"。
 */
class ArrearsBalanceLineTest {

    /** 造一行：只写关心的那几格，其余走 DTO 的默认值（与后端缺省一致）。 */
    private fun row(
        creditUsed: String = "0.00",
        limit: String? = null,
        creditAvailable: String? = null,
        overLimit: Boolean = false,
        prepaid: String = "0.00",
    ) = CustomerBalanceRowDto(
        kind = "unit",
        unitId = 7L,
        name = "兴盛蔬菜",
        prepaid = prepaid,
        limit = limit,
        creditUsed = creditUsed,
        creditAvailable = creditAvailable,
        overLimit = overLimit,
    )

    @Test
    fun `余额表里没有这一行 = 到目前没欠过，不许写成欠了 0 元`() {
        val line = arrearsBalanceLine(null)
        assertEquals("到目前还没有欠款记录", line.text)
        assertFalse("这一句不是「出事了」，不该用警示色", line.warn)
        assertFalse("⛔ 不许把「没有欠款事实」印成金额", line.text.contains("0"))
    }

    @Test
    fun `设了额度又没超：说清欠多少 + 还能赊多少（都取接口的数）`() {
        val line = arrearsBalanceLine(row(creditUsed = "3348.20", limit = "5000.00", creditAvailable = "1651.80"))
        assertEquals("已挂账 ¥3348.2 · 还能赊 ¥1651.8", line.text)
        assertFalse(line.warn)
    }

    @Test
    fun `没设过额度：只说「不限额」，不许冒出一个 ¥0 的额度`() {
        val line = arrearsBalanceLine(row(creditUsed = "520.00"))
        assertEquals("已挂账 ¥520 · 额度：不限额", line.text)
        assertFalse(line.warn)
    }

    @Test
    fun `超了：用接口的 over_limit 说话，界面上不许自己算差额`() {
        val line = arrearsBalanceLine(
            row(creditUsed = "1200.00", limit = "1000.00", creditAvailable = "-200.00", overLimit = true)
        )
        assertEquals("已挂账 ¥1200 · 额度 ¥1000（已超）", line.text)
        assertTrue("超限要用警示色（与客户欠款报表同一处提醒）", line.warn)
        // 只说「（已超）」，不许出现「超了 ¥多少」—— 那个差额是客户端自己减出来的（第二份钱算法）。
        assertFalse("⛔ 不许自己减出差额", line.text.contains("超了"))
    }

    @Test
    fun `后端说「还能赊」算不出来时只说额度，不许当成 0`() {
        val line = arrearsBalanceLine(row(creditUsed = "88.00", limit = "1000.00", creditAvailable = null))
        assertEquals("已挂账 ¥88 · 额度 ¥1000", line.text)
        assertFalse("⛔ 「还能赊 ¥0」是它没说过的意思", line.text.contains("还能赊"))
    }

    @Test
    fun `有往来但现在不欠：说没有欠款（不是「欠 0 元」）`() {
        val line = arrearsBalanceLine(row(creditUsed = "0.00", limit = "1000.00", creditAvailable = "1000.00"))
        assertEquals("没有欠款", line.text)
        assertFalse(line.warn)
    }

    @Test
    fun `有预收：预收与欠款分开说，两个数都来自接口`() {
        val line = arrearsBalanceLine(row(creditUsed = "0.00", prepaid = "300.00", limit = "1000.00", creditAvailable = "1000.00"))
        assertEquals("没有欠款 · 预收 ¥300", line.text)
        assertFalse(line.warn)
    }

    @Test
    fun `金额按全仓同一套去零规则印（多余的两位小数要抹掉）`() {
        val line = arrearsBalanceLine(row(creditUsed = "5000.00", limit = "20000.00", creditAvailable = "15000.00"))
        assertEquals("已挂账 ¥5000 · 还能赊 ¥15000", line.text)
        assertFalse("与报表页的 money(...) 同一个格式", line.text.contains(".00"))
    }
}
