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
    fun `formatMoney 仍然是两位小数的显示口径（两者不许混用）`() {
        assertEquals("12.35", formatMoney("12.3456"))   // 显示用：四舍五入到两位
        assertEquals("12.3456", trimMoneyZeros("12.3456")) // 编辑用：一位不少
        assertEquals("12.50", formatMoney("12.5"))
        assertEquals("12.5", trimMoneyZeros("12.5000"))
    }

    // ---------------------------------------------------------------- 订单商品行合计（唯一一处）

    private fun line(total: String?) = OrderProductDto(
        id = 1, productNameSnapshot = "荷兰豆", quantity = 1, lineTotal = total,
    )

    private fun order(vararg totals: String?) = OrderDto(
        id = 1, orderNo = "SO1", status = "DELIVERED", orderProducts = totals.map { line(it) },
    )

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
