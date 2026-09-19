package com.tapmoay.sorders.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * `InputRules` 的单测。
 *
 * 为什么这些用例值钱：这些规则**不是**"看着对就行"的字符串处理 ——
 * 它们决定了"用户敲进去的东西能不能进库"。每一条背后都有一个具体的坏结果：
 * - `mobileInput("138abc00000")` 若不过滤 → 库里存 `138abc00000`，这个人**永远登不进来**
 *   （后端 `^1\d{10}$` 会拒），而错误只在他下次登录时才出现；
 * - `moneyInput("1.2.3")` 若照抄旧的 `isDigit() || '.'` → `toDoubleOrNull()` 得 null，
 *   界面小计变 ¥0.00、提交后靠后端 422 兜底；
 * - `phoneInput` 的 7~12 位若写成"必须 11 位以 1 开头" → **座机全被挡在门外**
 *   （`01012345678` 是合法的 11 位座机）。这一条是设计取舍，所以拿用例钉住。
 */
class InputRulesTest {

    // ------------------------------------------------------------------ 手机号

    @Test
    fun `手机号过滤只留数字且截到 11 位`() {
        assertEquals("13800000000", InputRules.mobileInput("13800000000"))
        // 字母、汉字、空格、连字符、加号一律敲不进去
        assertEquals("13800000000", InputRules.mobileInput("138-0000 0000"))
        assertEquals("138", InputRules.mobileInput("1a3b8嘿嘿"))
        // 全角数字（中文输入法全角模式打出来的就是这些）**归一成半角，而不是丢掉**。
        // ⚠️ 这块第一版是**错的**两次：先是写 `it.isDigit()`（Kotlin 的是 Unicode 判断，
        //    `１３８` 原样放过 → 后端 Python 的 `\d` 同样是 Unicode 的 → 全角手机号能进库）；
        //    改成"只认 ASCII、其余丢掉"之后，`moneyInput("１.５")` 只剩一个 ASCII 点儿、
        //    算出 `0.`（想输 1.5 得到 0）。现在是**归一**：`１.５` → `1.5`。
        assertEquals("138", InputRules.mobileInput("１３８"))
        assertEquals("123", InputRules.intInput("１２３", 6))
        assertEquals("1.5", InputRules.moneyInput("１.５"))
        assertEquals("13800000000", InputRules.mobileInput("１３８００００００００"))
        // 超位截断（而不是原样留着让用户提交时才发现）
        assertEquals("13800000001", InputRules.mobileInput("1380000000123"))
    }

    @Test
    fun `粘贴带国家码的号码会剥掉 86 而不是变成另一个号`() {
        // ⚠️ 这条是写完单测才发现真问题的地方：只"留数字"的话
        //    `+8613800000000` 会变成 `86138000000` —— 11 位、看着正常、打不通，
        //    而且在联系电话规则（7~12 位）下**会被放过去**（司机照着拨是空号，全程无提示）。
        assertEquals("13800000000", InputRules.mobileInput("+86 138 0000 0000"))
        assertEquals("13800000000", InputRules.mobileInput("+8613800000000"))
        assertEquals("13800000000", InputRules.phoneInput("+8613800000000"))
        // 186 开头的手机号（11 位）**不受影响**：只有"正好 13 位且以 86 开头"才剥
        assertEquals("18612345678", InputRules.mobileInput("18612345678"))
    }

    @Test
    fun `手机号校验挡住位数不对与不以 1 开头的`() {
        assertNull(InputRules.mobileError("13800000000"))
        assertNotNull(InputRules.mobileError("1380000000"))   // 10 位
        assertNotNull(InputRules.mobileError("138000000012")) // 12 位
        assertNotNull(InputRules.mobileError("23800000000"))  // 不以 1 开头
        assertNotNull(InputRules.mobileError(""))             // 必填
        // 提示里要带实际位数，用户才知道自己少输了
        assertEquals("手机号要填 11 位数字（现在 10 位）", InputRules.mobileError("1380000000"))
    }

    @Test
    fun `手机号可以选填`() {
        assertNull(InputRules.mobileError("", required = false))
    }

    // ---------------------------------------------------------------- 联系电话

    @Test
    fun `联系电话过滤只留数字且截到 12 位`() {
        assertEquals("13800000000", InputRules.phoneInput("13800000000"))
        assertEquals("057188888888", InputRules.phoneInput("0571-88888888"))  // 带连字符的座机
        assertEquals("", InputRules.phoneInput("嘿嘿"))
        assertEquals("123456789012", InputRules.phoneInput("1234567890123456"))
    }

    @Test
    fun `联系电话收手机也收座机`() {
        assertNull(InputRules.phoneError("13800000000"))   // 手机
        assertNull(InputRules.phoneError("01012345678"))   // 北京座机 010 + 8 位 = 11 位，**不以 1 结尾开头也要过**
        assertNull(InputRules.phoneError("057188888888"))  // 杭州座机 0571 + 8 位 = 12 位
        assertNull(InputRules.phoneError("1234567"))       // 7 位下限
    }

    @Test
    fun `联系电话挡住太短的和打不通的`() {
        // 生产库里真有一条 `222`（改之前 shipper_contacts 里查到的）
        assertNotNull(InputRules.phoneError("222"))
        assertNotNull(InputRules.phoneError("12345"))
        assertEquals("电话太短（现在 3 位，至少 7 位；座机请把区号一起填上）", InputRules.phoneError("222"))
    }

    @Test
    fun `联系电话可选填时留空放行`() {
        assertNull(InputRules.phoneError("", required = false))
        assertNotNull(InputRules.phoneError("", required = true))
    }

    // -------------------------------------------------------------------- 金额

    @Test
    fun `金额过滤只留数字与一个小数点`() {
        assertEquals("12.50", InputRules.moneyInput("12.50"))
        assertEquals("", InputRules.moneyInput("abc"))
        assertEquals("12", InputRules.moneyInput("1a2"))
    }

    @Test
    fun `金额多点一个点儿不会丢数字`() {
        // `1.2.3` 是手滑多按了一下点儿，用户想说的多半是 1.23；丢掉数字比丢掉点儿糟得多
        assertEquals("1.23", InputRules.moneyInput("1.2.3"))
        assertEquals("1.23", InputRules.moneyInput("1..23"))
        assertEquals("1.23", InputRules.moneyInput("1.2.3.4"))
    }

    @Test
    fun `金额补前导零但允许停在点儿上`() {
        assertEquals("0.5", InputRules.moneyInput(".5"))
        // 允许停在 `1.`：用户正准备输小数，这时把点儿吃掉会让下一个数字跑到整数位上
        assertEquals("1.", InputRules.moneyInput("1."))
    }

    @Test
    fun `金额小数最多两位整数最多 8 位`() {
        assertEquals("1.23", InputRules.moneyInput("1.234"))
        assertEquals("12345678", InputRules.moneyInput("123456789"))
        assertEquals("95.5", InputRules.moneyInput("95.5", maxDecimals = 2, maxWhole = 3))
    }

    @Test
    fun `单价允许四位小数但金额只允许两位`() {
        // ⚠️ 这条是差点改错的地方：库里**单价**是 `Numeric(14,4)`
        //    （products.default_unit_price / cost_price / special_unit_price、
        //     order_products.unit_price、ledgers.unit_price），
        //    而**金额**是 `Numeric(12,2)`（收款/开销/运费/工资）。
        //    第一版把所有金额框都收成两位小数 —— 那等于把"给商品定 12.3456 元"
        //    这件本来能干的事**悄悄封掉**（用户只会发现第四位小数打不进去）。
        assertEquals("12.3456", InputRules.priceInput("12.3456"))
        assertEquals("12.34", InputRules.moneyInput("12.3456"))
        // 单价同样只允许一个小数点、整数位同样有上限
        assertEquals("12.3456", InputRules.priceInput("12.3.456"))
        assertEquals("12345678.1234", InputRules.priceInput("123456789.1234"))
    }

    @Test
    fun `金额校验挡住空与不可解析`() {
        assertNull(InputRules.moneyError("0"))
        assertNull(InputRules.moneyError("12.50"))
        assertNull(InputRules.moneyError(""))
        assertNotNull(InputRules.moneyError("", required = true))
        assertNotNull(InputRules.moneyError("0", required = true))
        // 经过过滤后正常敲不出这种串，但 state 里可能被程序塞进坏值，所以校验要能兜住
        assertNotNull(InputRules.moneyError("..."))
    }

    // ------------------------------------------------------------------ 正整数

    @Test
    fun `正整数过滤只留数字并截断`() {
        assertEquals("12", InputRules.intInput("12", 4))
        assertEquals("1234", InputRules.intInput("123456", 4))
        // 负号被丢掉、数字留下（数量/库存本来就不接受负数，后端也是 ge=1 / ge=0，所以
        // 敲 `-5` 得到的 `5` 是"能用的那个理解"，而不是把整串清空让用户莫名其妙）
        assertEquals("5", InputRules.intInput("-5", 4))
        assertEquals("", InputRules.intInput("二", 4))
    }

    // -------------------------------------------------------------- 拆单份数

    @Test
    fun `拆单输入只留数字与斜杠`() {
        assertEquals("150/150", InputRules.splitPartsInput("150/150"))
        assertEquals("150/150", InputRules.splitPartsInput("150//150"))
        assertEquals("150150", InputRules.splitPartsInput("150abc150"))
        assertEquals("100/100/100", InputRules.splitPartsInput("100/100/100"))
    }
}
