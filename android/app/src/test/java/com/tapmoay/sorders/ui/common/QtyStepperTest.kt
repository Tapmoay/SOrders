package com.tapmoay.sorders.ui.common

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 数量判据（`QtyStepper.kt::typedQty`）的单测 —— 纯 JVM，不需要模拟器。
 *
 * 为什么值得单测：这条判据原来在**两个弹窗里各写了一遍**（选品页与下单页行编辑），
 * 收敛成一份之后，两个地方的行为差异就再也不会出现了。它是"用户敲进来的东西"
 * 与"会被提交上去的数量"之间**唯一**的一道门 —— 门错了不会报错，只会多一条 0 件的订单行。
 */
class QtyStepperTest {

    @Test
    fun `正常数字原样通过`() {
        assertEquals(1, typedQty("1"))
        assertEquals(12, typedQty("12"))
        assertEquals(9999, typedQty("9999"))
    }

    @Test
    fun `空串与清空退回下限`() {
        assertEquals(QTY_MIN, typedQty(""))
        assertEquals(QTY_MIN, typedQty("   "))
    }

    @Test
    fun `0 退回下限（0 件不该存在订单行上）`() {
        assertEquals(QTY_MIN, typedQty("0"))
        assertEquals(QTY_MIN, typedQty("000"))
    }

    @Test
    fun `字母与符号敲不进来`() {
        assertEquals(12, typedQty("12ab"))
        assertEquals(3, typedQty("a3b"))
        assertEquals(QTY_MIN, typedQty("abc"))
        assertEquals(5, typedQty("5-"))
        assertEquals(15, typedQty("1.5"))
    }

    @Test
    fun `全角数字归一成半角，不是丢掉`() {
        // 中文输入法全角模式下打出来的就是它们：丢掉等于让用户对着"明明打了却没进去"的框发愣
        assertEquals(138, typedQty("１３８"))
    }

    @Test
    fun `超过四位数按前四位截断（敲不出五位数）`() {
        // ⚠️ 这是 `InputRules.intInput(v, 4)` 的**既有语义**（超位截断，不是夹到上限）——
        //    这一轮是纯界面改版，**行为一个字没改**，所以单测钉的是"现在的真实行为"：
        //    敲第 5 位会被吃掉；粘贴 `123456` 只留前 4 位。
        assertEquals(QTY_MAX, typedQty("99999"))
        assertEquals(1234, typedQty("123456"))
    }

    @Test
    fun `负数不可能出现（减号被丢掉，不是变成下限）`() {
        // 减号不是数字 → `intInput` 直接丢字符，`-5` 剩下 `5`。
        // 数量框键盘是 Number，正常路径下根本敲不出减号；这条钉的是"粘进来也不会变负"。
        assertEquals(5, typedQty("-5"))
        assertEquals(QTY_MIN, typedQty("-"))
    }

    @Test
    fun `上下限常量自洽（数字位数与上限是同一个口径）`() {
        assertEquals("9".repeat(QTY_DIGITS), QTY_MAX.toString())
        assertEquals(1, QTY_MIN)
    }
}
