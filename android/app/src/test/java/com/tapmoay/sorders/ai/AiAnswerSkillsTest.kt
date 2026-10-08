package com.tapmoay.sorders.ai

import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 呈现技能（[AiAnswerSkills]）—— 回答里「这段信息怎么排」由模型按**内容形状**自己选。
 *
 * ### 用户原话（2026-10-09，ref m35395 / m35399）
 * - 「AI 的回答最好都要用表格的样式…上面有文字下面有信息混在一起就很难分辨出来。」
 * - 「不要就是他啊就是搞一个我们来搞一个搞一个我们来搞一个，这样子太麻烦了」
 *   —— 要的是**自主判断**，所以这里是「形状 → 排版」表，而不是一条业务场景一条规则。
 * - 「其实基本上只要涉及到信息的基本上他都要想啊想办法…把信息给表达出来。」
 *
 * 和 [AiAnswerStyleTest] 同一规矩：直接读提示词真正用的那一份，不复制。
 */
class AiAnswerSkillsTest {

    private val prompt: String = AiAnswerSkills.RULES

    @Test
    fun `编号接在 AiAnswerStyle 的 11 之后，而且是「按形状自己决定」`() {
        assertTrue("这一段要接在 8.1~11 之后，编号 12：\n$prompt", prompt.startsWith("12. "))
        assertTrue("要写明是模型自己按内容形状决定：\n$prompt", prompt.contains("按「内容形状」自己决定怎么排"))
    }

    @Test
    fun `要明确不是按业务场景套模板（用户原话：不要一个一个地加规则）`() {
        assertTrue("要写明认形状、不是按场景套模板：\n$prompt", prompt.contains("认形状，⛔ 不是按业务场景套模板"))
        assertTrue("要写明「只要涉及信息就让它一眼看清」：\n$prompt", prompt.contains("只要涉及信息，就让它一眼看清"))
    }

    @Test
    fun `五类形状都要写到（一组字段、多条记录、结论先行、步骤、问题）`() {
        for (w in listOf(
            "一个对象的一组字段",
            "多条同类记录",
            "一条结论 + 几条依据",
            "让用户照做的步骤",
            "要用户回答的问题",
        )) {
            assertTrue("要写到形状「$w」：\n$prompt", prompt.contains(w))
        }
    }

    @Test
    fun `一组字段要两列表，不许写成散行（截图那条的病根）`() {
        assertTrue("要指明两列表：\n$prompt", prompt.contains("**两列表**"))
        assertTrue("要引用用户那句「上面有文字下面有信息混在一起」：\n$prompt", prompt.contains("上面有文字下面有信息混在一起"))
        assertTrue("要明确禁止散行写法：\n$prompt", prompt.contains("⛔ 不要写成「• 标签：值」的散行"))
    }

    @Test
    fun `要用户回答的问题：单独一行、放在最后`() {
        assertTrue("问题必须和信息分开（用户那张截图里问题就混在信息后面）：\n$prompt", prompt.contains("**单独一行、放在最后**"))
        assertTrue("并且不许塞进字段行里：\n$prompt", prompt.contains("⛔ 不要塞进字段行里"))
    }

    @Test
    fun `超过 3 项是下限不是门槛（与第 9 条不打架）`() {
        assertTrue("要说明和第 9 条的关系：\n$prompt", prompt.contains("第 9 条那个「超过 3 项」是**下限不是门槛**"))
        assertTrue("并且给下限：\n$prompt", prompt.contains("只要有 ≥2 行同类信息"))
    }

    @Test
    fun `一句话能说完的不许硬凑表格、也不许编内容`() {
        assertTrue("要禁止硬凑：\n$prompt", prompt.contains("⛔ 不要为了排版硬凑一张表"))
        assertTrue("没查到就直说，不许为了凑表编：\n$prompt", prompt.contains("⛔ 不要为了凑表格编内容"))
    }

    @Test
    fun `表格写法：Markdown 表、单元格只放短语、不许手搓 ASCII 边框`() {
        assertTrue("要用 Markdown 表（界面才画得成真表格）：\n$prompt", prompt.contains("用 Markdown 表格"))
        assertTrue("单元格只放短语：\n$prompt", prompt.contains("单元格里只放短语"))
        assertTrue("不许手搓边框：\n$prompt", prompt.contains("⛔ 不要用竖线手搓 ASCII 边框"))
        assertTrue("空值要写「—」而不是省掉那一行：\n$prompt", prompt.contains("某个值没有就写「—」，那一行不要省"))
    }
}
