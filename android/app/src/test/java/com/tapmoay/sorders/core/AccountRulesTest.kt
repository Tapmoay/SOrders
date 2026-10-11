package com.tapmoay.sorders.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 「所有账号初始密码默认 123321」这条**规定**的纯逻辑钉子（CHG-0118，用户 2026-10-11）。
 *
 * 规定原文：「我们的所有账号初始密码默认是 123321，这是**规定死的**。AI 也要知道 ——
 * 我叫它创建一个账号，它**直接帮我创建好、不要问我密码是什么**。」
 *
 * 这里只钉**常量与那句给人看的话**；"AI 卡片怎么写、执行时发的是不是它"钉在
 * [com.tapmoay.sorders.ai.AiWriteTest]（那里有真实的 preview → 确认卡 → execute 链路）。
 * 分开的理由：这一份谁都能跑、一秒钟出结论 —— 而规定本身（是不是 123321、编辑时能不能预填）
 * 正是最不该靠"跑一整条链路才知道"的东西。
 */
class AccountRulesTest {

    @Test
    fun `默认初始密码就是规定的那一个`() {
        // 改这个字符串就是改规定：后端 `security.py::DEFAULT_INITIAL_PASSWORD` 必须同时改，
        // 判据 `_tools/qa/_check_default_password.py` 会核对两侧一致（不然会出现
        // "卡片上写着 123321、账号实际是别的密码"这种没人报错的分叉）。
        assertEquals("123321", AccountRules.DEFAULT_INITIAL_PASSWORD)
    }

    @Test
    fun `新建账号的密码框预填默认值_编辑时必须是空串`() {
        assertEquals(
            "新建要预填默认值（手工建号也该有一个默认）",
            AccountRules.DEFAULT_INITIAL_PASSWORD,
            AccountRules.passwordDraft(isEdit = false),
        )
        // ⛔ 编辑必须是空串：空串的语义是"不改密码"，预填会把所有人的密码静默重置。
        assertEquals(
            "编辑时预填默认值 = 改个手机号就把密码重置了",
            "",
            AccountRules.passwordDraft(isEdit = true),
        )
    }

    @Test
    fun `写明默认密码的那句话两样东西都不能少`() {
        val note = AccountRules.DEFAULT_PASSWORD_NOTE
        assertTrue("必须写出密码是什么，否则用户不知道该拿什么登录：$note", note.contains(AccountRules.DEFAULT_INITIAL_PASSWORD))
        assertTrue("必须写明可以改（用户口径里就带着这句）：$note", note.contains("你可以改"))
        // 它是**给用户看的一句话**：不许出现内部命名（同"回答里不许出现内部编号"那条规矩）。
        assertFalse("给用户看的话里不许出现内部字段名：$note", note.contains("password", ignoreCase = true))
        assertFalse("给用户看的话里不许出现内部字段名：$note", note.contains("AccountRules"))
    }
}
