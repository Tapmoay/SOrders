package com.tapmoay.sorders.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 「AI 权限按角色划分」在**提示词**这一侧的测试。
 *
 * ### 为什么提示词也要测
 * 权限在代码里裁得很干净（货主 13 个动作），但真机上它还是会说"我能查司机绩效"——
 * 因为 system prompt 第一行写死的是「给**派单员**用的助手」，后面又按派单员的口径
 * 列了库存/账号/商品/派单/36 张表。**它没有撒谎，是提示词告诉它它是派单员。**
 * （用户原话：「那是因为你那个系统提示词没写好、没有分开」。）
 *
 * 所以这里钉三件事：
 * 1. 货主那份身份段里**不许出现派单员的能力名**；
 * 2. 能力清单必须**从代码算出来**（[AiWrites.forModel] / [AiReads.forRole]），不是手写的；
 * 3. 认不出角色时 fail-closed（什么都不许说能做）。
 */
class AiRolePromptTest {

    private val shipper = AiRolePrompt.brief(AiActor.byRole(AiRole.SHIPPER))
    private val dispatcher = AiRolePrompt.brief(AiActor.byRole(AiRole.DISPATCHER))
    private val unknown = AiRolePrompt.brief(null)

    /**
     * 只取**「你能做什么」那一段**。
     *
     * 为什么不能整份查关键字：身份段和「⛔ 不归你的」那两处会**否定地**提到库存/派单
     * （"这些不归他"），那是好事——它正是用来阻止模型乱认能力的。
     * 第一版测试整份查，结果把这两句正确的否定也算成违规。
     */
    private fun canDoPart(brief: String): String =
        brief.substringAfter("【你实际能干的事").substringBefore("⛔ 不归你的")

    @Test
    fun `货主那份不许出现派单员的能力名（用户口述：库存这些他根本不需要）`() {
        // 这些词一旦出现在"你能做什么"里，模型就会把它们当成"我能做"（真机实测过）
        val forbidden = listOf("库存", "派单", "拆单", "账号与收费规则", "司机绩效", "操作日志", "成本价", "批发商定价")
        val can = canDoPart(shipper)
        for (w in forbidden) {
            assertFalse("货主能做的那段里不该出现「$w」：\n$can", can.contains(w))
        }
        // 但"不归你"那段**必须**把它们点出来（点名了它才不会去试）
        val notMinePart = shipper.substringAfter("⛔ 不归你的")
        for (w in listOf("库存", "账号与收费规则")) {
            assertTrue("「$w」不归货主，必须在提示词里点名：\n$shipper", notMinePart.contains(w))
        }
    }

    @Test
    fun `派单员那份必须还是全量（别把管理员也裁了）`() {
        assertTrue("派单员的身份段要说明他是管理员", dispatcher.contains("管理员"))
        val can = canDoPart(dispatcher)
        for (w in listOf("库存", "账号与收费规则", "商品")) {
            assertTrue("派单员能做的那段该有「$w」：\n$can", can.contains(w))
        }
    }

    @Test
    fun `能力清单是从代码算出来的，不是手写的`() {
        val can = canDoPart(shipper)        // 写能力：货主能改的每个域都要念出来
        val shipperGroups = AiWrites.forModel(AiActor.byRole(AiRole.SHIPPER)).map { it.group }.distinct()
        for (g in shipperGroups) {
            assertTrue("货主能改的域「$g」必须出现在提示词里：\n$can", can.contains(g))
        }
        // 读能力：念出来的模块**正好**等于 AiReads.forRole 的模块集合（不多不少）
        // ⚠️ 2026-09-21：分母换成 `AiReads.allModules()` —— `brief` 的默认参数就是它，
        //    本机能力（`location` 读手机定位）也在里面；还用目录那一份算的话，这条会因为
        //    提示词里多念了一个「location」而红（而那是**对的**，不是 bug）。
        val want = AiReads.forRole(AiActor.byRole(AiRole.SHIPPER), AiReads.allModules().toSet())
            .map { it.action.substringBefore('.') }.distinct().sorted()
        val line = can.lines().first { it.startsWith("· 查数据") }
        val got = line.substringAfter("：").split("、").map { it.trim() }.sorted()
        assertEquals("读能力清单必须和 AiReads.forRole 一致：\n$can", want, got)
        // 全量写域必须都被覆盖（有域没进"不归你"，货主就不知道它不归他）
        val allGroups = AiWrites.ALL.map { it.group }.distinct()
        val notMine = allGroups.filter { it !in shipperGroups }
        assertTrue("全量写域至少 6 个（解析挂了就会漏）", allGroups.size >= 6)
        val notMinePart = shipper.substringAfter("⛔ 不归你的")
        for (g in notMine) {
            assertTrue("「$g」不归货主，必须写进提示词：\n$notMinePart", notMinePart.contains(g))
        }
    }

    @Test
    fun `货主的能力清单里全是白名单里的动作（一件不多）`() {
        // 「能做」那段逐个 title 念的必须是 forModel(SHIPPER) 的子集
        val titles = AiWrites.forModel(AiActor.byRole(AiRole.SHIPPER)).map { it.title }
        val others = AiWrites.forModel(AiActor.byRole(AiRole.DISPATCHER)).map { it.title } - titles.toSet()
        val can = canDoPart(shipper)
        for (t in others) {
            assertFalse("派单员专属的「$t」不该出现在货主的能力清单里：\n$can", can.contains(t))
        }
        for (t in titles) {
            assertTrue("货主能做的「$t」要念给他听（否则他不知道能让我干这个）：\n$can", can.contains(t))
        }
    }

    @Test
    fun `工具本身也按角色裁（货主不该拿到库存预警、司机跑车统计、出表格）`() {
        // v3.28 真机实测：这一层原来**没裁**——四个专门工具 + 出表格谁登录都能看到，
        // 于是货主问"你能做什么"，模型照着工具清单念，把库存预警/司机绩效说成自己能做；
        // 真去调 → 后端 403 → 只能回一句"没权限"。用户的原话是"提示词没分开"，根子在这层。
        val shipperTools = AiTools.toolsFor(AiRole.SHIPPER)
        for (t in listOf("inventory_alerts", "driver_performance", "shipper_performance", "search_shipper", "export_sheet")) {
            assertFalse("货主不该拿到「$t」工具（后端也是派单员权限）", t in shipperTools)
        }
        // 该有的必须有（裁多了 = 能力缺失）
        for (t in listOf("read_data", "preview_write", "remember")) {
            assertTrue("货主该有「$t」工具", t in shipperTools)
        }
        // 派单员 = 全部；认不出角色 = 一个都不给（fail-closed）
        assertEquals(AiTools.ALL.toSet(), AiTools.toolsFor(AiRole.DISPATCHER).toSet())
        assertTrue("认不出角色时不许给任何工具", AiTools.toolsFor(null).isEmpty())
        // 设置页的开关清单也必须同步裁：给货主一个永远不生效的开关 = "看起来有、其实没有"
        assertEquals(shipperTools.toSet(), AiTools.settingsItems(AiActor.byRole(AiRole.SHIPPER)).map { it.name }.toSet())
    }

    @Test
    fun `货主的身份段写的是货主（不是把派单员那句抄过来）`() {
        // ⚠️ 这一条是反向验证逼出来的：把 `SHIPPER_IDENTITY` 前面拼上 `DISPATCHER_IDENTITY`
        //    之后，上面那些"能做那段不许出现派单员能力名"的断言**全绿**——因为我只查了能力清单，
        //    没查**身份句本身**。而身份句正是这个 bug 的源头（原文写死「给派单员用的助手」）。
        //
        // ⚠️ 后来又按用户的反馈改过一次口径：原来这里断言"身份段里不许出现「派单员」"，
        //    但用户要求货主被问派单时**要**说清"派单是派单员做的、你把单下出来他会派"
        //    （原话：「货主没有派单的权限，他只有下单，他的提醒应该说可以通知派单员进行派单」）。
        //    所以判据从"不许提这个词"收紧成"**不许自称是派单员的助手**"——
        //    真正要防的是身份被抄错，不是防它提到另一个角色的名字。
        val head = shipper.substringBefore("【你实际能干的事")
        assertTrue("身份段要写明是给货主用的：\n$head", head.contains("给**货主**用的助手"))
        assertFalse("身份段不许自称是派单员的助手（这才是那个 bug）：\n$head", head.contains("给**派单员"))
        assertFalse("身份段不许出现「管理员」：\n$head", head.contains("管理员"))
        assertFalse("身份段不许说「整个系统都归他管」：\n$head", head.contains("整个系统都归他管"))
        // 派单员那份反过来：必须写明他是管理员
        val dHead = dispatcher.substringBefore("【你实际能干的事")
        assertTrue("派单员的身份段要写明管理员：\n$dHead", dHead.contains("管理员"))
    }

    @Test
    fun `货主被问派单要指向派单员，而不是让他自己去派（用户明确要求）`() {
        // 真机实测的错答：「派单不归我管，去「订单」页面自己派一下」——
        // 货主那边**根本没有派单按钮**，这是把人指到墙上。
        val head = shipper.substringBefore("【你实际能干的事")
        assertTrue("要说明派单是派单员的活：\n$head", head.contains("派单是派单员的活"))
        assertTrue("要告诉他正确的下一步（把单下出来）：\n$head", head.contains("把单下出来"))
        assertTrue("要写明他自己没有派单这个操作：\n$head", head.contains("没有派单这个操作"))
        // ⚠️ 这里**不能**用 `assertFalse(head.contains("去订单页面自己派"))`：
        //    身份段里那句禁止语正是「**绝不能**让他「去订单页面自己派一下」」——
        //    断言会命中禁止语本身，把写对的提示词判成错的（自己把自己绊倒，实测踩到）。
    }

    @Test
    fun `指路只能用他真有的页面（页面清单从界面配置算，不是手写）`() {
        // 同一个 bug 的另一半：回答里指的那些页面，货主可能一个都没有
        // （实测被指去过「商品页面」「库存页面」）。所以提示词里必须带上**真实页面清单**，
        // 并且明确"没有那个页面就不要指页面"。
        val can = shipper.substringAfter("【你实际能干的事")
        for (page in listOf("我的订单", "下单", "地址与联系人", "我的账本", "消息中心")) {
            assertTrue("货主页面清单里该有「$page」：\n$can", can.contains(page))
        }
        // 派单员专属的页面**不该**出现在货主的页面清单里
        val pagesLine = can.lines().firstOrNull { it.contains("他界面上有的页面") }.orEmpty()
        assertTrue("要有一行页面清单：\n$can", pagesLine.isNotEmpty())
        for (page in listOf("库存管理", "商品管理", "报表中心", "司机管理")) {
            assertFalse("货主没有「$page」这个页面，清单里不该出现：\n$pagesLine", pagesLine.contains(page))
        }
        assertTrue("要写明「没有那个页面就不要指页面」：\n$can", can.contains("不要指任何页面"))
    }

    @Test
    fun `认不出角色就什么都不许说能做（fail-closed）`() {
        assertTrue("要说明没认出角色", unknown.contains("没认出"))
        assertFalse("认不出角色时不许列任何能力", unknown.contains("改数据（"))
        assertFalse(unknown.contains("查数据："))
    }

    @Test
    fun `身份段要求它只照清单念，不许凭印象归纳`() {
        // 这条是这次 bug 的直接对策：它原来"自己归纳工具 schema"，而归纳就会说大
        assertTrue(shipper.contains("照**上面这份清单**念"))
        assertTrue(shipper.contains("不许凭印象归纳"))
        assertTrue(dispatcher.contains("照**上面这份清单**念"))
    }
}
