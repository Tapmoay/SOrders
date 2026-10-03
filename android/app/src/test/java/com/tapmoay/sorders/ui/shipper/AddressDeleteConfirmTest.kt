package com.tapmoay.sorders.ui.shipper

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 删除的二次确认说给用户听的那两句话（`deleteConfirmTitle` / `deleteConfirmMessage`）。
 *
 * ## 由来（用户 2026-10-04，语音）
 * > 「有两栋校改第一个就是把地点线路联系人，他那里的**删除键卡片删除键移到编辑界面当中**，
 * > 并且做二次确认的，**不要点一下就直接删掉了，防止误触**」
 *
 * ⇒ 这一组断言守的是"弹层有没有把话说全"，不是布局：
 *   ① **标题要点出删的是哪一条**（三张卡长得像的时候，用户就是靠名字确认）；
 *   ② 名字空着时退成「这条 X」，**不留一对空引号**（空引号比没有更吓人）；
 *   ③ **正文必须说清还能捞回来**（软删 + 恢复入口就在这一页顶上），
 *      少了这一句，用户按下「删除」时是在赌；
 *   ④ 三档的标题 / 正文各说各的档名，⛔ 不许出现 `null`（拼串漏了变量就是它）。
 *
 * ⚠️ 这三个纯函数的调用方只有一处：`AddressViewModel.askDelete`（举手时不落库），
 *    真正执行删除的是 `confirmDelete`。
 */
class AddressDeleteConfirmTest {

    @Test
    fun `标题点出删的是哪一条（名字原样带进去）`() {
        assertEquals("删除联系人「洪惠珍（永盛食品仓库）」？", deleteConfirmTitle("联系人", "洪惠珍（永盛食品仓库）"))
        assertEquals("删除常用线路「仓库 → 门店」？", deleteConfirmTitle("常用线路", "仓库 → 门店"))
        assertEquals("删除地点「永盛食品仓库」？", deleteConfirmTitle("地点", "永盛食品仓库"))
    }

    @Test
    fun `名字空着或全是空格时退成「这条 X」——不留一对空引号`() {
        listOf("", "   ", "\t").forEach { blank ->
            assertEquals("删除这条联系人？", deleteConfirmTitle("联系人", blank))
            assertEquals("删除这条地点？", deleteConfirmTitle("地点", blank))
            assertEquals("删除这条常用线路？", deleteConfirmTitle("常用线路", blank))
        }
    }

    @Test
    fun `正文必须说清还能捞回来（软删 + 顶上那行撤销）`() {
        listOf("联系人", "地点", "常用线路").forEach { what ->
            val text = deleteConfirmMessage(what)
            assertTrue("$what：正文没说「列表顶上」有恢复入口 —— 恢复入口等于不存在", text.contains("列表顶上"))
            assertTrue("$what：正文没点名「撤销」这颗按钮", text.contains("撤销"))
            assertTrue("$what：正文没说清删完是什么样（应该是列表顶上留一行「已删除 X」）", text.contains("已删除$what"))
            assertTrue("$what：正文没交代「什么时候就真找不回来了」", text.contains("找不回来"))
        }
    }

    @Test
    fun `三档各说各的档名，标题互不相同、正文也互不相同`() {
        val titles = listOf("联系人", "地点", "常用线路").map { deleteConfirmTitle(it, "张三") }
        assertEquals("三档标题撞了 —— 弹层上看不出删的是哪一类", 3, titles.toSet().size)
        val messages = listOf("联系人", "地点", "常用线路").map { deleteConfirmMessage(it) }
        assertEquals("三档正文撞了", 3, messages.toSet().size)
    }

    @Test
    fun `两句话里都不许出现 null 或空引号（拼串漏变量的典型症状）`() {
        listOf("联系人", "地点", "常用线路").forEach { what ->
            listOf(deleteConfirmTitle(what, "张三"), deleteConfirmTitle(what, ""), deleteConfirmMessage(what)).forEach { text ->
                assertFalse("$what：$text 里出现了 null —— 有变量没拼进去", text.contains("null"))
                assertFalse("$what：$text 里出现了空引号 —— 名字没取到就别写引号", text.contains("「」"))
                assertTrue("$what：$text 是空的", text.isNotBlank())
            }
        }
    }
}
