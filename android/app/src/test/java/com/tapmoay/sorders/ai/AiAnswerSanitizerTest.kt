package com.tapmoay.sorders.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * [AiAnswerSanitizer] 的单元测试。
 *
 * 这里守的是两条互相拉扯的线：
 * - **该抹的必须抹干净**：`user_id 122` 之类绝不能漏到用户眼前；
 * - **不该动的一个字都不能动**：金额、订单号、手机号、日期长得再像数字也不是编号。
 *   第二条比第一条更容易写错——用「像数字就删」的写法一定会误伤金额。
 */
class AiAnswerSanitizerTest {

    @Test
    fun removesIdInChineseParentheses() {
        assertEquals(
            "测试货主甲公司本月 6 单，共 1584.00 元。",
            AiAnswerSanitizer.clean("测试货主甲公司（user_id 122）本月 6 单，共 1584.00 元。"),
        )
    }

    @Test
    fun removesIdInAsciiParenthesesAndEqualsForm() {
        assertEquals(
            "司机 王建国 跑了 22 单",
            AiAnswerSanitizer.clean("司机 王建国 (driver_id=3) 跑了 22 单"),
        )
    }

    @Test
    fun removesBareIdAndChineseConnector() {
        assertEquals("这个货主本月 6 单。", AiAnswerSanitizer.clean("这个货主（ID 122）本月 6 单。"))
        assertEquals("找到了。", AiAnswerSanitizer.clean("找到了（user_id 为 122）。"))
        assertEquals("编号已去。", AiAnswerSanitizer.clean("编号已去（shipper_id：7）。"))
    }

    @Test
    fun keepsOrderNoAmountPhoneAndDateUntouched() {
        val text = "订单 SOTEST2026091500001 金额 1584.00 元，手机 13700001001，日期 2026-09-15。"
        assertEquals(text, AiAnswerSanitizer.clean(text))
    }

    @Test
    fun keepsEnglishWordsContainingId() {
        // valid / provide 里的 id 前面不是词边界，不该被当成编号
        val text = "This is valid and we provide it."
        assertEquals(text, AiAnswerSanitizer.clean(text))
    }

    @Test
    fun keepsChineseTextWithoutId() {
        val text = "海天酱油库存 2 箱，已到报警线 10 箱。"
        assertEquals(text, AiAnswerSanitizer.clean(text))
    }

    @Test
    fun stripsHashStyleEntityId() {
        assertEquals("货主 本月 6 单", AiAnswerSanitizer.clean("货主#122 本月 6 单"))
        assertEquals("司机 跑了 22 单", AiAnswerSanitizer.clean("司机 #3 跑了 22 单"))
    }

    @Test
    fun isIdempotentAndBlankSafe() {
        val once = AiAnswerSanitizer.clean("甲（user_id 122）乙")
        assertEquals("甲乙", once)
        assertEquals(once, AiAnswerSanitizer.clean(once))
        assertEquals("", AiAnswerSanitizer.clean(""))
        assertEquals("   ", AiAnswerSanitizer.clean("   "))
    }

    @Test
    fun keepsMultilineStructure() {
        val cleaned = AiAnswerSanitizer.clean("结论：\n（user_id 5）\n明细如下")
        assertTrue("换行结构要保留，实际：<$cleaned>", cleaned.contains("\n"))
        assertFalse(cleaned.contains("user_id"))
    }

    @Test
    fun stripsControlCharactersButKeepsLineBreaks() {
        // 由来：模拟器上 AI 聊天页在前台时 `uiautomator dump` 连崩两次，logcat 是
        // `IllegalArgumentException: Illegal character (U+0)`（AccessibilityNodeInfoDumper）
        // ——界面文本里的 NUL 让整棵无障碍树序列化不出来（读屏与自动化全失效）。
        val dirty = "库存\u0000+5，备注\u0007如下\u001b[0m\r\n第二行\u009f结束"
        val cleaned = AiAnswerSanitizer.clean(dirty)
        assertEquals("库存+5，备注如下[0m\r\n第二行结束", cleaned)
        // 一个控制字符都不许剩（含 C1 区）
        assertTrue(
            "还有控制字符没剥掉：${cleaned.map { it.code }}",
            cleaned.none { it.code < 0x20 && it != '\t' && it != '\n' && it != '\r' } &&
                cleaned.none { it.code in 0x7F..0x9F },
        )
        // 制表符与换行是排版手段，不是控制字符，必须原样留着
        assertEquals("甲\t乙\n丙", AiAnswerSanitizer.clean("甲\t乙\n丙"))
        // 幂等性对这条同样成立（净化器整体是幂等的）
        assertEquals(cleaned, AiAnswerSanitizer.clean(cleaned))
    }
}
