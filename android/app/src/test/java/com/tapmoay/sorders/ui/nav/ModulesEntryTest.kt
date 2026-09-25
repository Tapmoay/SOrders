package com.tapmoay.sorders.ui.nav

import com.tapmoay.sorders.ui.theme.AiBlue
import com.tapmoay.sorders.ui.theme.AiPink
import com.tapmoay.sorders.ui.theme.AiPurple
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * AI 入口的落位与外观（v3.14）。
 *
 * 背景：AI 入口原来只有一种形态——底部导航正中间那个凸起的圆钮。但货主端底部只有
 * 3 个 Tab，插一个占位后圆钮落在 **1/4 处**（偏左的第二个槽位），不对称、看着像排错了
 * （用户 2026-09-15 反馈）。于是货主端改成工作台网格里的图标。
 *
 * 同一轮用户又定了两件事：**图标放最后一格**、**配色照 Google AI 智能体那套**
 * （三段品牌渐变 蓝#4285F4 → 紫#9B72CB → 粉#D96570，见 theme/AiBrand.kt）。
 *
 * 这一组断言守的是"改完还是恰好一个入口、位置对、司机一个都没有、颜色分得开"。
 * 静态版在 `_tools/ai/_check_ai_guardrails.py` §8（那边查源码文本，这里查真实对象）。
 */
class ModulesEntryTest {

    private val GRIDS = listOf(
        Role.DISPATCHER to Modules.dispatcherEntries,
        Role.SHIPPER to Modules.shipperEntries,
        Role.DRIVER to Modules.driverEntries,
    )

    /** 两个颜色"看起来是不是同一个色"：RGB 欧氏距离。 */
    private fun colorGap(a: Long, b: Long): Double {
        fun ch(c: Long, sh: Int) = ((c shr sh) and 0xFF).toDouble()
        val dr = ch(a, 16) - ch(b, 16)
        val dg = ch(a, 8) - ch(b, 8)
        val db = ch(a, 0) - ch(b, 0)
        return kotlin.math.sqrt(dr * dr + dg * dg + db * db)
    }

    private fun hex(c: Long) = "#" + (c and 0xFFFFFF).toString(16).uppercase().padStart(6, '0')

    /** 低于这个距离就算"看着是同一个色"。经验值：两块只差 15 的蓝并排，肉眼分不出来。 */
    private val MIN_COLOR_GAP = 60.0

    @Test
    fun `货主工作台的 AI 助手排在最后一格`() {
        val last = Modules.shipperEntries.last()
        assertEquals("用户要求：AI 图标不要第一格，放最后一格", Routes.AI_CHAT, last.route)
        assertEquals("货主日常那几件事要排在前面（顺序本身在教怎么用）", "消息中心", Modules.shipperEntries[4].label)
    }

    @Test
    fun `货主端的 AI 图标用的是 Google AI 品牌渐变`() {
        val ai = Modules.shipperEntries.first { it.route == Routes.AI_CHAT }
        // 渐变三段必须是 Google 的品牌色，顺序也不能换（换了就不是那个观感了）
        assertEquals(listOf(AiBlue, AiPurple, AiPink), ai.gradient)
        // 单色底色取渐变起点：这样"渐变没法用的地方"（列表页小图标等）也还是同一个蓝
        assertEquals(AiBlue, ai.color)
    }

    @Test
    fun `只有 AI 用渐变，业务模块仍然是单色语义色`() {
        // 渐变是 AI 的"身份标记"：满屏渐变 = 又变成分不出哪个是哪个。
        val withGradient = GRIDS.flatMap { it.second }.filter { it.gradient.isNotEmpty() }
        assertEquals(
            "用渐变的入口只该有 AI 一个：${withGradient.map { it.label }}",
            listOf("AI 助手"),
            withGradient.map { it.label },
        )
    }

    @Test
    fun `每个角色的 AI 入口恰好一个（或零个）`() {
        for ((role, entries) in GRIDS) {
            val n = entries.count { it.route == Routes.AI_CHAT }
            val want = if (role == Role.SHIPPER) 1 else 0
            // 派单端的入口是底部圆钮（见 RoleHomeScreen），所以网格里应当是 0；
            // 货主端没有圆钮，网格里必须是 1；司机端一条路都没有。
            assertEquals("$role 的网格入口数不对", want, n)
        }
    }

    @Test
    fun `货主底部导航仍然是 3 个 Tab（圆钮放不进正中才改的网格）`() {
        // 这条是**决策前提**本身：如果哪天货主端加到 4 个 Tab，圆钮就落得回正中，
        // 那时这个测试会红，提醒你重新想一遍"网格图标还是圆钮"，而不是默默留着过时结论。
        assertEquals(3, Modules.bottomTabs(Role.SHIPPER).size)
    }

    @Test
    fun `同一个工作台里不许出现两块一模一样颜色的图标`() {
        // 「一色一功能」是这套界面的定位规则（老人靠颜色找功能）。撞色的后果不是难看而已：
        // 两块一样的方块并排，用户会以为其中一块是复制错了。
        for ((role, entries) in GRIDS) {
            val dup = entries.groupBy { it.color }.filterValues { it.size > 1 }
            assertTrue(
                "$role 的工作台里有完全同色的图标：${dup.values.map { es -> es.map { it.label } }}",
                dup.isEmpty(),
            )
        }
    }

    @Test
    fun `AI 的底色必须和货主同屏其它入口分得开`() {
        // ⚠️ 「颜色不相等」是不够的：曾经 AI 用 #2979FF、"我的订单"用 NavBlue #1E6FFF，
        // **数值不同、肉眼几乎一样**（RGB 距离只有 15），并排看就是两块一样的蓝色方块。
        // 这条断言**真的抓到过**那个 bug（写完先跑，看到的就是它红），不是事后补一句"看着还行"。
        //
        // 只对**货主端**用距离判据（不对派单端用）：派单端有 3 个青色系语义色
        // （地址湖蓝 #00A2C7 / 货主管理深青 #00A8A8 / 库存蓝青 #00BCD4，两两距离 29~48），
        // 那是用户早就认可的既有配色，拿一个更严的新尺子去回溯判它，只会逼着改一堆无关的界面。
        // 尺子只量**新引入的颜色**——这是它该管的事。
        val ai = Modules.shipperEntries.first { it.route == Routes.AI_CHAT }
        for (e in Modules.shipperEntries) {
            if (e === ai) continue
            val d = colorGap(ai.color, e.color)
            assertTrue(
                "AI 助手(${hex(ai.color)}) 与「${e.label}」(${hex(e.color)}) 看着几乎同色，距离只有 ${d.toInt()}",
                d >= MIN_COLOR_GAP,
            )
        }
    }

    @Test
    fun `工作台所有入口的路由都不为空且互不重复`() {
        for (entries in listOf(Modules.dispatcherEntries, Modules.shipperEntries, Modules.driverEntries)) {
            val keys = entries.map { it.label + it.route }
            assertEquals("同一个工作台里出现重复入口", keys.size, keys.toSet().size)
            assertTrue(entries.none { it.route.isBlank() })
        }
    }

    // ============================================================ 「账本管理」入口页
    //
    // 用户 2026-09-20 改了**三轮**，最后一句把前两轮都推翻了（先是账本页左栏版、再是
    // 工作台第二张卡片版），定稿是：
    // 「首先，我们将**司机的账和司机结算**这 2 个东西**合并成一个**；然后订单账本，再加上
    //  货主账本以及批发商账，还有客户收款以及开销管理，**合并成一个形式，就叫做账本管理**，
    //  这个账本管理**类似于报表中心的形式**；然后车辆台账属于车辆管理，车辆管理直接放在桌面上」。
    //
    // ⚠️ 2026-09-22 用户又改了一处：**「开销管理」并进新的「收支」**，不再与它并列占一格 ——
    //    「我记得好像有个开销管理吧，干脆把我们两个**整合在一起**」。
    //    所以第 6 格现在是「收支」（收入按来源、支出按去路），开销管理从**支出那张卡底部**进。
    // ⚠️ 2026-09-22 同一天又加了一格：**「供应商/应付」**（第 7 格）——
    //    用户原话「支出主要是**给某个供应商或者说是厂商支付尾款**……**购买一个装备或者说是设备**……
    //    比如说类似**邮费**啊」，拍板口径是"跟客户一个量级的档案"。
    //    它不是把「收支」顶掉：那一格是日记账（一笔一笔的流水），这一格是往来账（欠谁多少）。

    @Test
    fun `账本管理入口页正好 7 格，司机结算并进司机账、车辆台账去了工作台`() {
        val e = Modules.ledgerHomeEntries
        assertEquals("用户点名的就是这 7 件", 7, e.size)
        assertEquals(
            listOf("订单账", "司机账", "货主账", "批发商账", "客户收款", "收支", "供应商/应付"),
            e.map { it.label },
        )
        // 4 类账是**同一页的 4 个档位**（一条带参数的路由），不是四个页面
        assertEquals(
            "4 类账必须都走 dispatcher/ledger?tab=",
            (0..3).map { Routes.dispatcherLedger(it) },
            e.take(4).map { it.route },
        )
        // 三个工具各自有页面（点了就离开账本页）
        assertEquals(
            listOf(Routes.DISPATCH_RECEIPTS, Routes.DISPATCH_CASH, Routes.DISPATCH_SUPPLIERS),
            e.drop(4).map { it.route },
        )
        assertEquals("入口不能重复", e.size, (e.map { it.label + it.route }).toSet().size)
        // 用户点名"合并成一个"的那两处：结算不单独占一格、车辆台账改名去工作台
        assertTrue("「司机结算」不该单独占一格", e.none { it.label == "司机结算" })
        assertTrue("「车辆台账」的旧名不该还在（就是车辆管理）", e.none { it.label == "车辆台账" })
        // 2026-09-22：开销管理**整合进「收支」**（不再并列占一格）
        assertTrue("「开销管理」不该再并列占一格（并进「收支」了）", e.none { it.label == "开销管理" })
        assertTrue("「收支」必须有自己那一页", e.any { it.label == "收支" && it.route == Routes.DISPATCH_CASH })
        // 2026-09-22：供应商/应付是**独立一格**（不是"收支"里的一条），因为它自己有档案与付款两页
        assertTrue(
            "「供应商/应付」必须有自己那一页",
            e.any { it.label == "供应商/应付" && it.route == Routes.DISPATCH_SUPPLIERS },
        )
    }

    @Test
    fun `工作台网格里有账本管理与车辆管理两格，且与入口页不重复`() {
        val grid = Modules.dispatcherEntries
        assertTrue("「账本管理」要在工作台网格里", grid.any { it.label == "账本管理" && it.route == Routes.LEDGER_HOME })
        assertTrue(
            "「车辆管理」要在工作台网格里（用户：直接放在桌面上）",
            grid.any { it.label == "车辆管理" && it.route == Routes.DISPATCH_VEHICLES },
        )
        // ⛔ 入口页那 7 件不许在网格里再来一份（两个入口 = 用户以为丢了东西）
        val dup = Modules.ledgerHomeEntries.map { it.label }.filter { l -> grid.any { it.label == l } }
        assertTrue("同一批东西在网格和入口页各一份：$dup", dup.isEmpty())
    }

    @Test
    fun `工作台那一格与入口页的图标不许和网格里别处撞色（完全同色）`() {
        // 只判**完全相同**：网格里自己就有三只很接近的青（29~48），
        // 拿更严的尺子回溯判它等于逼着改一堆用户早就认可的配色（同一条理由见下面那条 AI 的断言）。
        val added = listOf("账本管理", "车辆管理")
        val dup = Modules.dispatcherEntries
            .filter { it.label in added }
            .flatMap { n -> Modules.dispatcherEntries.filter { it.color == n.color && it.label != n.label }.map { n.label to it.label } }
        assertTrue("新加的格子与邻居完全同色：$dup", dup.isEmpty())
    }

    @Test
    fun `账本管理入口页 6 格两两颜色分得开（同屏不许撞色）`() {
        val e = Modules.ledgerHomeEntries
        for (i in e.indices) {
            for (j in i + 1 until e.size) {
                val d = colorGap(e[i].color, e[j].color)
                assertTrue(
                    "「${e[i].label}」(${hex(e[i].color)}) 与「${e[j].label}」(${hex(e[j].color)}) 几乎同色，距离只有 ${d.toInt()}",
                    d >= MIN_COLOR_GAP,
                )
            }
        }
    }

    // ============================================================ R3-02：入口按能力筛

    @Test
    fun `工作台入口是按能力筛出来的，今天三个角色一个都没被筛掉`() {
        // R3-02 之前没有这条断言：`entriesFor(role)` 直接返回写死的那张表，谁也证明不了
        // 「货主看得见的那 7 格，确实都是他有权做的事」。现在它过一遍能力表（后端生成、带 source hash），
        // 这条断言就是那次改动的**行为等价证明**：今天三个角色可见的入口与改动前逐条相同。
        // ⚠️ 它同时是**回归闸门**：以后谁把某个能力从某个角色身上拿走，这里会红 ——
        //    逼人做一次有意识的决定（「这一格也要跟着对货主关掉吗」），而不是界面默默少一格。
        for ((role, entries) in GRIDS) {
            assertEquals(
                "$role 的工作台入口被能力表筛掉了 —— 要么能力表少了它该有的，要么这一格挂错了能力",
                entries.map { it.route },
                Modules.entriesFor(role).map { it.route },
            )
        }
    }

    @Test
    fun `每个入口都有着落：要么挂着能力，要么在例外表里写了理由`() {
        val all = Modules.dispatcherEntries + Modules.ledgerHomeEntries +
            Modules.shipperEntries + Modules.driverEntries
        val missing = all.map { it.route }.filter {
            it !in Modules.ENTRY_CAPABILITY && it !in Modules.ENTRY_NO_CAPABILITY
        }
        assertTrue("这些入口既没有能力、也没有例外理由：$missing", missing.isEmpty())
        assertTrue("例外表里的理由不许空着", Modules.ENTRY_NO_CAPABILITY.values.all { it.isNotBlank() })
    }

    @Test
    fun `账本管理入口页 6 个图标互不相同`() {
        val icons = Modules.ledgerHomeEntries.map { it.icon.name }
        assertEquals("同一页里两格同图标 = 没标", icons.size, icons.toSet().size)
    }
}
