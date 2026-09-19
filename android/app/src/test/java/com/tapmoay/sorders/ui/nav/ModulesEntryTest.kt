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
}
