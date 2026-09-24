package com.tapmoay.sorders.util

import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.data.remote.dto.OrderProductDto
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * `trimMoneyZeros`：**可编辑的价框**里显示用的那个"去尾零"。
 *
 * 为什么它必须与 [formatMoney] 分开测：两者都是"把后端那个数变好看"，但一个能丢精度、一个不能 ——
 * 混用一次就会出现"用户没改价、价却变了"（`12.3456` 显示成 `12.35`，保存即生效）。
 *
 * 末尾四条测 [goodsTotal] / [goodsTotalText]：那是**算钱**（收款页拿它当判据），
 * 与上面两个"显示"函数是两回事 —— 2026-09-21 之前它在 Android 里写了三遍。
 */
class MoneyTest {

    @Test
    fun `去尾零但不丢精度`() {
        // 后端单价列是 Numeric(14,4)，序列化出来一律 4 位小数
        assertEquals("12.5", trimMoneyZeros("12.5000"))
        assertEquals("10", trimMoneyZeros("10.0000"))
        assertEquals("0", trimMoneyZeros("0.0000"))
        // ⚠️ 四位真的有用时，一位都不能少（这条就是"不能拿 formatMoney 来显示"的原因）
        assertEquals("12.3456", trimMoneyZeros("12.3456"))
        assertEquals("12.3", trimMoneyZeros("12.3000"))
    }

    @Test
    fun `不是数字或为空时原样返回`() {
        assertEquals("", trimMoneyZeros(null))
        assertEquals("", trimMoneyZeros(""))
        assertEquals("", trimMoneyZeros("   "))
        // 界面层不在这里做校验（校验是 core/InputRules.kt 的事），坏值不该被这里吃掉
        assertEquals("abc", trimMoneyZeros("abc"))
    }

    @Test
    fun `没有小数点的整数不受影响`() {
        assertEquals("64", trimMoneyZeros("64"))
        assertEquals("0", trimMoneyZeros("0"))
    }

    @Test
    fun `formatMoney 显示：末尾多余的 0 去掉，但有效位一位不许少`() {
        // 用户 2026-09-22 给的三个例子（原话：「有零的全省」「56.77 是必须要有的，不能把七约掉」）
        assertEquals("56.7", formatMoney("56.70"))
        assertEquals("87", formatMoney("87.00"))
        assertEquals("56.77", formatMoney("56.77"))
        // 后端单价列是 Numeric(14,4)：显示只留两位（到分为止），再去尾零
        assertEquals("12.35", formatMoney("12.3456"))
        assertEquals("12.5", formatMoney("12.5000"))
        assertEquals("10", formatMoney("10.0000"))
        assertEquals("0", formatMoney("0.00"))
        assertEquals("0.5", formatMoney("0.50"))
        // 负零不是钱（`-0.001` 只去零会印成 `-0` → 界面上一行「¥-0」）
        assertEquals("0", formatMoney("-0.001"))
        assertEquals("-5.5", formatMoney("-5.50"))
        // 坏值/缺失 → "0"（不是 "0.00"：界面上只印一个 0）
        assertEquals("0", formatMoney(null))
        assertEquals("0", formatMoney(""))
        assertEquals("0", formatMoney("abc"))
    }

    @Test
    fun `显示与编辑两个口径不许混用`() {
        // 显示：到分为止（12.35）；编辑：四位一位不少（12.3456）——这 4 条一起看才是"不许混"的意思
        assertEquals("12.35", formatMoney("12.3456"))
        assertEquals("12.3456", trimMoneyZeros("12.3456"))
        assertEquals("12.5", formatMoney("12.5"))
        assertEquals("12.5", trimMoneyZeros("12.5000"))
        // ⛔ 反过来也不许：显示不能改用 trimMoneyZeros（那会把 12.3456 原样印到卡片上）
        assertEquals("12.34", formatMoney("12.3400"))
        assertEquals("12.34", trimMoneyZeros("12.3400"))
    }

    // ---------------------------------------------------------------- 订单商品行合计（唯一一处）

    private fun line(total: String?) = OrderProductDto(
        id = 1, productNameSnapshot = "荷兰豆", quantity = 1, lineTotal = total,
    )

    private fun order(vararg totals: String?) = OrderDto(
        id = 1, orderNo = "SO1", status = "DELIVERED", orderProducts = totals.map { line(it) },
    )

    /** 带欠款的一张单（`arrearsAmount` 就是"整单核销要收多少"）。 */
    private fun orderWithArrears(lineTotal: String?, arrears: String) = OrderDto(
        id = 1,
        orderNo = "SO1",
        status = "DELIVERED",
        orderProducts = listOf(line(lineTotal)),
        arrearsAmount = arrears,
    )

    @Test
    fun `整单核销取的是欠款，不是商品行合计`() {
        // ⛔ 2026-09-24 第 28 轮（第 24 轮 10 区 F1）：退过货的单上这两个数差一大截 ——
        //    退货只红冲账本、不改行金额。界面原来拿"行合计"当判据 → 后端按欠款算 → 必 400，
        //    而用户想填欠款又过不了界面那道 compareTo → **这张单从此再也收不了款**。
        //    本机实测样本：order 13（行 42.80 / 欠 21.40）、394（192.60 / 138.90）、419（156.80 / 142.00）。
        val o = orderWithArrears("42.80", "21.40")
        assertEquals("行合计仍是「当时卖了多少」（不随退货变）", "42.80", o.goodsTotalText())
        assertEquals("整单核销要收的是欠款", "21.40", o.settleArrears().toPlainString())
    }

    @Test
    fun `多张单的整单核销合计是欠款逐单相加`() {
        val a = orderWithArrears("100.00", "100.00")
        val b = OrderDto(
            id = 2, orderNo = "SO2", status = "DELIVERED",
            orderProducts = listOf(line("50.00")), arrearsAmount = "30.00",
        )
        assertEquals("130.00", listOf(a, b).settleTotal().toPlainString())
    }

    @Test
    fun `欠款字段缺失或为空时按 0（老数据或裁剪后不许崩）`() {
        val o = OrderDto(
            id = 1, orderNo = "SO1", status = "DELIVERED",
            orderProducts = listOf(line("10.00")), arrearsAmount = "",
        )
        assertEquals("0", o.settleArrears().toPlainString())
    }

    @Test
    fun `商品行合计是定点相加，不是 Double 相加`() {
        // 0.1 + 0.2：Double 是 0.30000000000000004，定点就是 0.3
        assertEquals("0.30", order("0.1", "0.2").goodsTotalText())
        assertEquals("0.30", order("0.10", "0.20").goodsTotal().toPlainString())
    }

    @Test
    fun `行金额为空当作 0（老数据可能没有行金额）`() {
        assertEquals("12.30", order("12.30", null).goodsTotalText())
        assertEquals("0.00", order().goodsTotalText())
    }

    @Test
    fun `两位小数按 HALF_UP 进位 —— 与后端 order_money 同口径`() {
        // `1.005` 这种"差半分"的值最容易看出进位规则：定点 HALF_UP 是 1.01。
        assertEquals("1.01", order("1.005").goodsTotalText())
        // ⚠️ 别拿 `formatMoney`（Double + `%.2f`）来算钱：它是**显示**口径，
        //    而且 `%.2f` 的进位跟着 JDK 的最短十进制表示走 —— 这里不钉它的行为，
        //    只钉"算钱走定点"。
    }

    @Test
    fun `多行累加不许退化成 Double（P0-4 那把收款卡死的原型）`() {
        // 三行 1063.56：定点相加正好 3190.68；而 Double 顺序累加是 3190.6799999999994 ——
        // 2026-09-19 报告 P0-4 就是这么来的：界面把它显示成 ¥3190.68、判据却拿那个长串比，
        // 于是用户照抄填进去必然 400，**多行/多单时永久收不了款**。
        assertEquals("3190.68", order("1063.56", "1063.56", "1063.56").goodsTotalText())
        // 定点相加也是精确的（不是"看起来对"）
        assertEquals("3190.68", order("1063.56", "1063.56", "1063.56").goodsTotal().toPlainString())
    }

    @Test
    fun `只相加、不重算（行金额是后端算好下发的）`() {
        // 行金额里已经含了后端那一层的四舍五入；客户端拿 qty × 单价重算就会与账本差一分
        assertEquals("24.69", order("12.3456", "12.3456").goodsTotalText())
    }
}
