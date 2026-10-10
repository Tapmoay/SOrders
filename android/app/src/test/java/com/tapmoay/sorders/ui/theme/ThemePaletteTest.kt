package com.tapmoay.sorders.ui.theme

import com.tapmoay.sorders.ui.nav.Modules
import kotlin.math.sqrt
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 整套配色（CHG-0101 起；CHG-0105 只还色相）的判据。
 *
 * 用户口径：
 * - m02474（逐字）：「按照它的配色方案进行一下修改以及我给你的那个照片」
 * - m02545（逐字）：「这是新任务吼也就是改我途中给你发的那些样式」
 * - **m02683（逐字）：「继续继续，但我不希望整体太过于灰啊」** ← 本测试第 ① 条就是它
 *
 * 为什么这几条必须有机器的判据（都是"坏了不报错"的那一类）：
 * 1. **发灰**这件事没有任何东西会报错 —— 渲染完全正常，只是整套界面看着没精神。
 *    用户已经明确否过一次"太灰"，所以把"饱和度地板"钉成一条真的会红的断言。
 * 2. 主操作色被谁顺手改成别的颜色，也没有任何东西会报错 —— 它只是一块颜色。
 *    用户是**画了图**给的色（三张图里的主操作色一直是他画的那支绿），所以要钉住那个值：
 *    CHG-0101 曾被"按图量测"带跑、整套换成红棕，是用户自己回来说
 *    「你怎么把我一些颜色给全部变成了棕色……功能性全丢掉了」才纠回来的。
 * 3. `Modules.kt` 里那几格既有裸字面量、又有 token 引用；改了 token 却忘了改字面量，
 *    或者反过来，界面不会报错、编译也不会报错，只是**两块图标变成了同一个颜色**。
 *
 * ⚠️ 与 `ui/nav/ModulesEntryTest.kt` 的分工：那边守"同屏两两距离"（真的量 RGB 距离），
 *    这边守**取色本身**（是不是用户给的那套、够不够不灰）。两边都要看，别互相替代。
 *
 * ⚠️ CHG-0105（2026-10-10「只还色相」）：保留 CHG-0101 之前的老色相，明度/彩度仍取 H 档，
 *    所以整套现值与 CHG-0091 / CHG-0101 / CHG-0102 哪一版都不相同
 *    （其中工作台的 4 个身份色按用户「工作台就按我们一开始的那个题目那个方案去做」
 *    退回 CHG-0102 的原值 —— 它们的 L\* 与还色相后的现值完全一样）。
 *    断言里钉的是**现值**，不是某一版旧值；判据（数量、阈值、语义）一个字没动。
 */
class ThemePaletteTest {

    /** RGB 欧氏距离，口径与 `ModulesEntryTest.colorGap` 逐字相同（那边是 private，这里重写一份）。 */
    private fun gap(a: Long, b: Long): Double {
        fun ch(c: Long, sh: Int) = ((c shr sh) and 0xFF).toDouble()
        val dr = ch(a, 16) - ch(b, 16)
        val dg = ch(a, 8) - ch(b, 8)
        val db = ch(a, 0) - ch(b, 0)
        return sqrt(dr * dr + dg * dg + db * db)
    }

    /** 这个颜色"有多不灰"：HSL 里的饱和度（0~1）。 */
    private fun saturation(c: Long): Double {
        val r = ((c shr 16) and 0xFF) / 255.0
        val g = ((c shr 8) and 0xFF) / 255.0
        val b = (c and 0xFF) / 255.0
        val mx = maxOf(r, g, b)
        val mn = minOf(r, g, b)
        return if (mx == 0.0) 0.0 else (mx - mn) / mx
    }

    private fun hex(c: Long) = "#" + (c and 0xFFFFFF).toString(16).uppercase().padStart(6, '0')

    /**
     * 用户口径 m02683：「我不希望整体太过于**灰**啊」。
     *
     * 这条线是**量出来的、不是拍的**（`_tmp/probe_sat_table.py` 把三组颜色排了队）：
     * · 用户参考图 21 格：饱和度 **最低 11% / 中位 31% / 最高 52%**，最灰的四个是
     *   账户管理 11%、采购单 13%、代理下单 20%、货主管理 21%；
     * · 旧方案（HEAD）那套：**中位 86%** —— 那正是用户说"太亮、刺眼"的那套；
     * · 所以要守的不是"越高越好"，而是**别掉到用户自己都嫌灰的那一档以下**。
     * 地板取 **15%**：严格高于参考图里最灰的那两格（11% / 13%），
     * 又容得下参考图自己的低饱和家族（它后半段本来就落在 20%~30%）。
     * ⚠️ 别再往上提这条线：用户给的色**本身就是低饱和的**（图三设计要点第 ② 条写着
     *    「图标使用低饱和语义色……保护老年用户视觉舒适度」），把地板提到 22%/30%
     *    会逼着每一格都偏离他画的色 —— 那是**用尺子改设计**，不是执行他的要求。
     *    （实测：地板 22% 时「账户管理」#A2763D 当场判红，而它正是照参考图取的灰棕。）
     */
    private val SAT_FLOOR = 0.15

    @Test
    fun `货主端工作台的 7 格，饱和度都不低于 15%（用户点名过不要太灰）`() {
        val weak = Modules.shipperEntries
            .filter { it.route != "ai/chat" }   // AI 那格是 Google 品牌蓝，不是本套语义色
            .map { it.label to saturation(it.color) }
            .filter { it.second < SAT_FLOOR }
        assertTrue(
            "这几格灰掉了（饱和度 <${(SAT_FLOOR * 100).toInt()}%）：" +
                weak.joinToString { "${it.first}=${(it.second * 100).toInt()}%" },
            weak.isEmpty(),
        )
    }

    @Test
    fun `派单端工作台那 21 格，饱和度也都不低于 15%`() {
        val weak = Modules.dispatcherEntries
            .map { it.label to saturation(it.color) }
            .filter { it.second < SAT_FLOOR }
        assertTrue(
            "这几格灰掉了：${weak.joinToString { "${it.first}=${(it.second * 100).toInt()}%" }}",
            weak.isEmpty(),
        )
    }

    @Test
    fun `主操作色是用户画的那支墨绿 28684B，不许改回蓝或红棕`() {
        // 用户 2026-10-09 三张图里的「主操作色（确认接单）」—— 他画的那支色相一直是绿的。
        // CHG-0101 曾按"参考图量测"把它换成一整套低饱和红棕（#8B4A4A），用户随后反馈
        // 「你怎么把我一些颜色给全部变成了棕色……功能性全丢掉了」；CHG-0105 起 **只还色相**
        // （老色相 ＋ H 档明度彩度），所以现在读到的值是墨绿 #28684B，不再是 #8B4A4A。
        // 它同时是 Primary（主按钮底）、NavBlue（底部导航）、InfoBlue（信息）三处读的那个值。
        assertEquals("主操作色变了（用户画的那支绿，CHG-0105 起是 #28684B 墨绿）", 0xFF006C43L, ThemeGreen)
        assertEquals("NavBlue 必须还是主操作色的别名", ThemeGreen, NavBlue)
        assertEquals("InfoBlue 必须还是主操作色的别名", ThemeGreen, InfoBlue)
    }

    @Test
    fun `商品块那两个 token 还是裸 ARGB 值（CHG-0105 起回到墨绿一族）`() {
        // ⛔ 这两个必须是 `Long`（`0x…L`）而不是 `Color(0x…)`：
        //    本仓库的语义色 token 统一是裸 ARGB，用色处自己写 `Color(token)`；
        //    写成 Color 会让同一条 Row 里两种类型混用、编译不过（Color.kt 里写着这条）。
        // ⚠️ 值本身**不是** CHG-0091 那支绿：CHG-0105 还的是**色相**，明度与彩度仍取 H 档
        //    （用户看到红棕那版的原话是「你怎么把我一些颜色给全部变成了棕色……功能性全丢掉了」），
        //    所以底是极浅的薄荷灰绿 #DBE8E1、字是近黑的墨绿 #1B2E22。
        assertEquals("商品行底变了（CHG-0105 起是极浅薄荷灰绿）", 0xFFDBE8E1L, ProductRowTint)
        assertEquals("商品行上的字变了（CHG-0105 起是近黑墨绿）", 0xFF12301EL, OnProductRowTint)
        // ⛔ 这两条负向断言防的是 **CHG-0091 那支绿的原值**回来：还色相不等于把老值搬回来。
        assertTrue("商品行底变回 CHG-0091 那支绿了", ProductRowTint != 0xFFE0F9ECL)
        assertTrue("商品行上的字变回 CHG-0091 那支墨绿了", OnProductRowTint != 0xFF003519L)
    }

    @Test
    fun `账本管理入口页 7 格的取色都不低于 15% 饱和度`() {
        val weak = Modules.ledgerHomeEntries
            .map { it.label to saturation(it.color) }
            .filter { it.second < SAT_FLOOR }
        assertTrue(
            "这几格灰掉了：${weak.joinToString { "${it.first}=${(it.second * 100).toInt()}%" }}",
            weak.isEmpty(),
        )
    }

    @Test
    fun `账本管理入口页 7 格与货主端 8 格，两两距离都不低于 60（换色后仍成立）`() {
        // 这条与 `ModulesEntryTest` 那两个断言是**同一个口径**，写在这里是为了：
        // 换色的人跑 `ThemePaletteTest` 就能立刻看到"我这一改把哪两格挤到一起了"，
        // 不必等到跑另一个测试类。
        fun worst(entries: List<com.tapmoay.sorders.ui.nav.ModuleEntry>): Triple<String, String, Double>? {
            var w: Triple<String, String, Double>? = null
            for (i in entries.indices) {
                for (j in i + 1 until entries.size) {
                    val d = gap(entries[i].color, entries[j].color)
                    if (w == null || d < w!!.third) w = Triple(entries[i].label, entries[j].label, d)
                }
            }
            return w
        }
        for ((name, entries) in listOf(
            "账本管理入口页" to Modules.ledgerHomeEntries,
            "货主端工作台" to Modules.shipperEntries,
        )) {
            val w = worst(entries)!!
            assertTrue(
                "$name 里「${w.first}」与「${w.second}」只差 ${w.third.toInt()}（${hex(entries.first { it.label == w.first }.color)} × ${hex(entries.first { it.label == w.second }.color)}），阈值 60",
                w.third >= 60.0,
            )
        }
    }

    @Test
    fun `主操作色上的白字读得清（对比度过 AA 的 4_5）`() {
        fun lum(c: Long): Double {
            fun ch(sh: Int): Double {
                val v = ((c shr sh) and 0xFF) / 255.0
                return if (v <= 0.04045) v / 12.92 else Math.pow((v + 0.055) / 1.055, 2.4)
            }
            return 0.2126 * ch(16) + 0.7152 * ch(8) + 0.0722 * ch(0)
        }

        val ratio = (1.0 + 0.05) / (lum(ThemeGreen) + 0.05)
        assertTrue(
            "白字压在主操作色 ${hex(ThemeGreen)} 上只有 %.2f:1，读不清（要 >=4.5）".format(ratio),
            ratio >= 4.5,
        )
    }
}
