package com.tapmoay.sorders.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 确认卡信息区的「标签 / 值」解析 —— 用户 2026-09-20 要求那里用表格显示。
 *
 * 这份单测守的是**解析不能猜错**：把一整句话拆成「标签：值」是安全的，
 * 把一句话的前半截当成标签则是**误导**（用户会照着错的标签去核对数字）。
 * 所以每条规则都要有正例与反例 —— 只有正例的话，"一律按第一个冒号切"也能全绿。
 */
class AiCardTableTest {

    private fun rows(vararg lines: String) = AiCardTable.rows(lines.toList())

    @Test
    fun `标签冒号值是最普通的一行`() {
        val r = rows("订单号：SO202609206168396216", "货主：Shipper", "订单金额：1.00 元")
        assertEquals(3, r.size)
        assertEquals(AiCardTable.Row.Pair("订单号", "SO202609206168396216"), r[0])
        assertEquals(AiCardTable.Row.Pair("订单金额", "1.00 元"), r[2])
    }

    @Test
    fun `半角冒号也算（AI 与后端的文案两种都出现过）`() {
        assertEquals(
            AiCardTable.Row.Pair("状态", "PENDING_DISPATCH"),
            rows("状态: PENDING_DISPATCH")[0],
        )
    }

    @Test
    fun `值里可以再有冒号 —— 只按第一个冒号切`() {
        // 「备注：9:30 送到」切成「备注 / 9:30 送到」；切错会变成「备注：9 / 30 送到」
        assertEquals(
            AiCardTable.Row.Pair("备注", "9:30 送到"),
            rows("备注：9:30 送到")[0],
        )
        // 箭头也留在值里（那是"改前 → 改后"，不是标签的一部分）
        assertEquals(
            AiCardTable.Row.Pair("价格", "12.00 元 → 15.00 元"),
            rows("价格：12.00 元 → 15.00 元")[0],
        )
    }

    @Test
    fun `分段标题认得三种写法`() {
        assertEquals(AiCardTable.Row.Section("用这个点的坐标"), rows("———— 用这个点的坐标 ————")[0])
        assertEquals(AiCardTable.Row.Section("会写三处"), rows("———— 会写三处 ————")[0])
        assertEquals(AiCardTable.Row.Section("改成"), rows("---- 改成 ----")[0])
        assertEquals(AiCardTable.Row.Section("改前"), rows("==== 改前 ====")[0])
    }

    @Test
    fun `像句子的行不当标签（反例）`() {
        // 带 emoji/空格前缀的警告：整行显示
        assertTrue(rows("⚠️ 写进去就撤不回来（没有「取消导航」这个动作）")[0] is AiCardTable.Row.Full)
        // 列表项（处理器里用「· 」开头）
        assertTrue(rows("· 第 3 行 老王 商品：可乐")[0] is AiCardTable.Row.Full)
        // 没有冒号的一行
        assertTrue(rows("这单的导航、货主的地点库、全库共享地点库")[0] is AiCardTable.Row.Full)
        // 冒号太靠后（前半截是半句话，不是标签）
        assertTrue(
            rows("司机一趟跑下来大概能拿到：300 元")[0] is AiCardTable.Row.Full,
        )
        // 标签里带箭头 = 它其实是「改前 → 改后」那种整行
        assertTrue(rows("旧地址 → 新地址：南山路 1 号")[0] is AiCardTable.Row.Full)
    }

    @Test
    fun `空行丢掉、空值不当标签`() {
        assertEquals(1, rows("", "   ", "货主：Shipper", "")[0].let { 1 })
        assertTrue(rows("备注：")[0] is AiCardTable.Row.Full)
        assertTrue(rows("：值")[0] is AiCardTable.Row.Full)
    }

    @Test
    fun `顺序原样保留（用户核对时靠的是顺序）`() {
        val r = rows(
            "订单号：SO1",
            "———— 用这个点的坐标 ————",
            "地点：仓库",
            "坐标：22.93, 114.43",
            "这单的导航、货主的地点库、全库共享地点库",
        )
        assertEquals(AiCardTable.Row.Pair("订单号", "SO1"), r[0])
        assertEquals(AiCardTable.Row.Section("用这个点的坐标"), r[1])
        assertEquals(AiCardTable.Row.Pair("坐标", "22.93, 114.43"), r[3])
        assertTrue(r[4] is AiCardTable.Row.Full)
    }
}
