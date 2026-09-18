package com.tapmoay.sorders.ai

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 「只给用户要的」—— 提示词与话术的测试。
 *
 * ### 用户原话（2026-09-16，一次说了四件事）
 * 1. 「货主如果涉及到权限不够的话，不用说那么多，直接返回权限不够。」
 * 2. 「异常订单那个卡片还会显示一些没必要的数据——代码返回什么就照样渲染上去了。」
 * 3. 「AI 回答的时候没必要说的就不要说，不要说返回了什么什么，用户只要知道结果。」
 * 4. 「大量商品或人员尽量用表格展示，全是文字用户根本没法看。」
 *
 * 这一组测试钉的是 **2/3/4 里能静态检查的部分**（1 的措辞在 `AiReadService`/`AiTools` 里，
 * 用红线钉）。第 2 条的"卡片字段筛选"在 UI 里，见 `ReportCenter.ExceptionCard`。
 */
class AiAnswerStyleTest {

    /** 直接读**提示词真正用的那一份**（[AiAnswerStyle.RULES]），不是测试里复制的一份。 */
    private val prompt: String = AiAnswerStyle.RULES

    @Test
    fun `提示词要求只讲结果（不许复述结构、字段、返回条数）`() {
        val p = prompt
        assertTrue("要有一条「只讲结果」的规则：\n$p", p.contains("只讲结果，不讲过程"))
        for (w in listOf("不许出现工具名、参数名、字段名", "「返回了 N 条」")) {
            assertTrue("提示词里要写明「$w」：\n$p", p.contains(w))
        }
    }

    @Test
    fun `提示词要求权限不够只回一句（用户原话：不用说那么多）`() {
        val p = prompt
        assertTrue("提示词要写明权限不够只回一句：\n$p", p.contains("权限不够时**只回一句**"))
        assertTrue("并明确不许给替代数据：\n$p", p.contains("不许列「我还能给你什么替代数据」"))
        assertTrue("被追问也还是同一句：\n$p", p.contains("被追问第二次，还是同一句"))
    }

    @Test
    fun `「不啰嗦」不许被过度执行成「什么都不说」（用户 2026-09-17 补的边界）`() {
        // 用户原话：「并不是说让它不要太啰嗦，而是说有些建议啊、提醒啊，该说的还是得说的。」
        // 判据必须钉在**提示词真的那一份**上：没有这一段，模型会把"少说过程"执行成"少说话"，
        // 把该提醒的风险一起省掉——而用户是拿这个回答去派单/改价/结账的。
        val p = prompt
        assertTrue("要写明「不啰嗦≠什么都不说」：\n$p", p.contains("「不啰嗦」不等于「什么都不说」"))
        assertTrue("要给出唯一判断标准：\n$p", p.contains("这句话会不会改变用户下一步怎么做？会，就必须说"))
        assertTrue("要明确「只省过程话」：\n$p", p.contains("被省掉的**只有过程话**"))
        // 至少要有具体的例子，否则模型不知道该说什么
        assertTrue("要有风险提醒的具体例子：\n$p", p.contains("动了会影响已结的账"))
        // 而且不能和"权限不够只回一句"打架：那条要保留
        assertTrue("权限话术仍然要短：\n$p", p.contains("权限不够时**只回一句**"))
    }

    @Test
    fun `提示词要求条目多时用表格（全是文字用户没法看）`() {
        val p = prompt
        assertTrue("要写明超过 3 项优先用表格：\n$p", p.contains("超过 3 项"))
        assertTrue("要写明原因（用户原话）：\n$p", p.contains("全是文字的话，用户根本没办法看了"))
        assertTrue("保留窄屏列数上限：\n$p", p.contains("表格**最多 4 列**"))
    }

    /**
     * 剥掉行注释再断言。
     *
     * ⚠️ 这一条是本仓库栽过三次的坑：**新写的注释里往往会引用被禁掉的旧文案**
     * （"这里以前是『当前登录账号没有权限查看这项数据。』"），拿原文断言就会把解释当成违规。
     * 红线脚本早就统一 `strip_comments` 了，测试里也得一样。
     */
    private fun stripComments(src: String): String =
        src.lines().filterNot { it.trimStart().startsWith("//") || it.trimStart().startsWith("*") }
            .joinToString("\n")

    @Test
    fun `权限话术本身要短（工具返回和读服务两侧）`() {
        // 这两句是**给模型看的**工具返回，越长它越会照着念
        val readService = stripComments(
            java.io.File("src/main/java/com/tapmoay/sorders/ai/AiReadService.kt").readText(),
        )
        assertTrue("读服务的角色门要短：\n$readService", readService.contains("权限不够。告诉用户这个查不了"))
        assertFalse("不该再出现长篇解释", readService.contains("这个角色不能查（当前角色："))
        val tools = stripComments(
            java.io.File("src/main/java/com/tapmoay/sorders/ai/AiTools.kt").readText(),
        )
        assertTrue("403 映射要短：\n$tools", tools.contains("权限不够。一句话告诉用户这项他看不了"))
        assertFalse("旧的 403 文案要删掉", tools.contains("当前登录账号没有权限查看这项数据。"))
    }

    @Test
    fun `异常卡片不再把后端枚举名直接印在卡上`() {
        val card = stripComments(
            java.io.File("src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenter.kt").readText(),
        )
        // 原来说 `+ " · " + e.status` —— 屏幕上就会出现 PENDING_DISPATCH
        assertFalse("卡上不许直接拼 e.status（会印出 PENDING_DISPATCH）", card.contains("\" · \" + e.status"))
        assertTrue("状态要走中文化：\n$card", card.contains("statusLabel(e.status)"))
        // 「谁的异常」不许用 `?: ""` 拼出空壳
        assertTrue("货主/司机用 listOfNotNull 拼（缺谁就不显示谁）", card.contains("val who = listOfNotNull("))
    }
}
