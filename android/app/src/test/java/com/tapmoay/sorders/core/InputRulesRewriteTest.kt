package com.tapmoay.sorders.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 过滤的**说明**（BUG-0028 / 测试台账 TA-09、TA-10）。
 *
 * 这一份测的不是"怎么过滤"（那是 `InputRulesTest`），而是"这次过滤该不该吭声"：
 * `note == null` 才允许保存，`note != null` 的输入界面必须让用户看见（改价弹窗据此禁用确定键、
 * 联系人抽屉据此拒绝保存）—— 不许把用户打的字改成别的值再悄悄落库。
 *
 * ⚠️ 改前（HEAD `1b91cdf`）`priceRewriteNote` / `phoneInputNote` 不存在，这个文件根本编译不过 ——
 * 这是它"改前是红的"的第一层；第二层与界面接线一起看 `_tools/qa/_check_basicdata_input_guard.py`。
 */
class InputRulesRewriteTest {

    // ------------------------------------------------------------------ TA-09 售价

    /** `-3`：过滤照旧把它变成 `3`（符号丢掉），但**必须**给出说明，否则库里存 3、用户以为存 -3。 */
    @Test
    fun negativePriceIsReportedNotSilentlyTurnedPositive() {
        assertEquals("3", InputRules.priceInput("-3"))
        assertEquals("1", InputRules.priceInput("-1"))
        val note = InputRules.priceRewriteNote("-3")
        assertNotNull("打进 -3 必须有说明（不然就是静默改数）", note)
        assertTrue("文案要点名「负数」：实际是 " + note, note!!.contains("负数"))
    }

    /** 字母 / 汉字不许被悄悄丢掉。 */
    @Test
    fun letterPriceIsReported() {
        val note = InputRules.priceRewriteNote("abc")
        assertNotNull(note)
        assertTrue(note!!.contains("只能填数字"))
    }

    /** 第二个小数点（`1.2.3` → `1.23`）改的是值，也要说。 */
    @Test
    fun secondDotIsReported() {
        assertEquals("1.23", InputRules.priceInput("1.2.3"))
        assertNotNull(InputRules.priceRewriteNote("1.2.3"))
    }

    /** 位数超限（第 5 位小数 / 第 9 位整数）会被 take() 截掉，要说。 */
    @Test
    fun overlongPriceIsReported() {
        val frac = InputRules.priceRewriteNote("12.34567")
        assertNotNull(frac)
        assertTrue(frac!!.contains("4 位小数"))
        val whole = InputRules.priceRewriteNote("123456789")
        assertNotNull(whole)
        assertTrue(whole!!.contains("整数位"))
    }

    /** 合法的归一**不算改写**：全角数字、`.5`、停在 `1.`、千分位 —— 不该拿红字烦用户。 */
    @Test
    fun `合法归一不弹说明`() {
        assertNull(InputRules.priceRewriteNote("12.5"))
        assertNull(InputRules.priceRewriteNote("0.005"))
        assertNull(InputRules.priceRewriteNote(""))
        assertNull(InputRules.priceRewriteNote(".5"))
        assertNull(InputRules.priceRewriteNote("1."))
        assertNull(InputRules.priceRewriteNote("１２３"))
        assertNull(InputRules.priceRewriteNote("1 000"))
        assertNull(InputRules.priceRewriteNote("1,000"))
    }

    // ------------------------------------------------------------------ TA-10 电话

    /** `abc`：过滤照旧得到空串（= 存 NULL），但**必须**说出来。 */
    @Test
    fun letterPhoneIsReportedNotSilentlyNulled() {
        assertEquals("", InputRules.phoneInput("abc"))
        val note = InputRules.phoneInputNote("abc")
        assertNotNull("打进 abc 必须有说明（不然用户以为填过电话，库里是 NULL）", note)
        assertTrue(note!!.contains("只能填数字"))
        assertNotNull(InputRules.phoneInputNote("嘿嘿"))
    }

    /** 抄电话时的分隔符与 `+86` 是既有归一（值等价），不算丢字。 */
    @Test
    fun phoneSeparatorsAreNotLosses() {
        assertEquals("13800000000", InputRules.phoneInput("138-0000-0000"))
        assertNull(InputRules.phoneInputNote("138-0000-0000"))
        assertEquals("13800000000", InputRules.phoneInput("+8613800000000"))
        assertNull(InputRules.phoneInputNote("+8613800000000"))
        assertNull(InputRules.phoneInputNote("010-12345678"))
        assertNull(InputRules.phoneInputNote(""))
    }

    /** 超长号码会被截到 12 位 —— 与丢字母同一类，要说。 */
    @Test
    fun overlongPhoneIsReported() {
        val note = InputRules.phoneInputNote("138000000012345")
        assertNotNull(note)
        assertTrue(note!!.contains("12 位"))
    }

    /** "位数不够"是**格式**的事（phoneError 管），不是"丢字" —— 这里不许抢它的活。 */
    @Test
    fun shortPhoneIsNotARewriteNote() {
        assertNull(InputRules.phoneInputNote("222"))
    }
}
