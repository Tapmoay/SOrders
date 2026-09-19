package com.tapmoay.sorders.util

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * `trimMoneyZeros`：**可编辑的价框**里显示用的那个"去尾零"。
 *
 * 为什么它必须与 [formatMoney] 分开测：两者都是"把后端那个数变好看"，但一个能丢精度、一个不能 ——
 * 混用一次就会出现"用户没改价、价却变了"（`12.3456` 显示成 `12.35`，保存即生效）。
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
}
