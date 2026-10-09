package com.tapmoay.sorders.ui.theme

import com.tapmoay.sorders.ui.nav.Modules
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 整套配色「看着像一套」的判据（CHG-0102）。
 *
 * 用户 2026-10-10 的原话（ref `m04527`，逐字）：
 * 「呃我觉得饱和度还是太低了一点不也不说饱和度吧，应该说太灰了一点。整天都饱和度
 *   或者说是明度吧，应该叫做明度。他们并不是完全都是一致的只是在一个区间内。
 *   就像是色彩理论一样啊……它所有的呃比如说我们一般评价一个画它比较偏低，
 *   饱和但是整体的色调又统一且看的舒适是这样子的这样，它又是怎么做到的呢？」
 *
 * ⚠️ 他这一句把病灶说反了一半，也把钥匙给了出来：
 * · 病根**不是"整体太灰"** —— CHG-0101 那套同屏里「账户管理」C\*=8.1、
 *   「消息中心」C\*=58.4，**差 7 倍**。看着不舒服的是这个落差，不是低饱和本身。
 * · 钥匙是"**在一个区间内**"：统一的从来不是饱和度，是**明度**。
 *   CHG-0091 那套 L\* 极差 51.8（太亮太刺眼），CHG-0101 是 25.6（灰的特别灰），
 *   CHG-0102 压到 **10.0**。
 *
 * 为什么这四条得有机器的判据（都是"坏了不报错"的那一类）：
 * 1. 明度又散开 —— 渲染完全正常，只是整套界面重新变得"不是一套"。
 * 2. 某一格彩度掉下去 —— 也没有任何东西会报错，只是那一格读起来像"禁用"。
 * 3. 同屏两格被调成几乎同色 —— 编译过、界面不报错，用户只是"找不到了"。
 *
 * ⚠️ 与 `ThemePaletteTest` 的分工：那边守**取色本身**（是不是那套、够不够不灰、
 *    白字读不读得清）；这边守**它们之间的关系**（齐不齐、有没有掉队的）。
 *
 * ⚠️ CHG-0105（2026-10-10「只还色相」）：工作台这些身份色按用户 ref `m06138`
 *    「工作台就按我们一开始的那个题目那个方案去做」回到 CHG-0102 的原方案
 *    （`ProgressYellow` / `MessageRed` / `AccountBrown` / `InventoryTeal` 四个 token
 *    退回原值，它们的 L\* 与 CHG-0105 的现值完全相同）。**本文件四条硬指标与
 *    全部阈值一个字没动** —— 上面那些数字是重锚过的现值，不是放宽后的值。
 */
class PaletteUniformityTest {

    private fun tiles(entries: List<com.tapmoay.sorders.ui.nav.ModuleEntry>) =
        entries.map { it.label to it.color }

    private fun spread(entries: List<com.tapmoay.sorders.ui.nav.ModuleEntry>) =
        lightnessSpread(entries.map { it.color })

    private fun report(entries: List<com.tapmoay.sorders.ui.nav.ModuleEntry>): String =
        entries.joinToString("、") { "%s L*=%.1f C*=%.1f".format(it.label, labLightness(it.color), labChroma(it.color)) }

    // ---- ① 明度挤在一条窄带里：这才是"色调统一"的来源 ----

    @Test
    fun `派单端那 19 格的明度极差不超过 12（用户说的「在一个区间内」）`() {
        val s = spread(Modules.dispatcherEntries)
        assertTrue(
            "明度又散开了：极差 %.1f（要 <=12；CHG-0091 那套是 51.8、CHG-0101 是 25.6）\n%s"
                .format(s, report(Modules.dispatcherEntries)),
            s <= 12.0,
        )
    }

    @Test
    fun `货主端 8 格的明度极差不超过 16`() {
        val s = spread(Modules.shipperEntries)
        assertTrue(
            "明度散开了：极差 %.1f（要 <=16）\n%s".format(s, report(Modules.shipperEntries)),
            s <= 16.0,
        )
    }

    @Test
    fun `账本管理入口页 7 格的明度极差不超过 15`() {
        val s = spread(Modules.ledgerHomeEntries)
        assertTrue(
            "明度散开了：极差 %.1f（要 <=15）\n%s".format(s, report(Modules.ledgerHomeEntries)),
            s <= 15.0,
        )
    }

    // ---- ② 彩度地板：低于 C*≈20 就没人数它是颜色了 ----

    @Test
    fun `派单端那 19 格，最没颜色的那一格彩度也不低于 27`() {
        val w = weakestChroma(Modules.dispatcherEntries.map { it.color })
        assertTrue(
            "这几格里有一格掉成灰了：最弱 C*=%.1f（要 >=27）—— %s"
                .format(w, weakestChromaLabel(tiles(Modules.dispatcherEntries))),
            w >= 27.0,
        )
    }

    @Test
    fun `货主端与账本页的彩度地板同样成立`() {
        for ((name, entries) in listOf(
            "货主端" to Modules.shipperEntries,
            "账本管理入口页" to Modules.ledgerHomeEntries,
        )) {
            val w = weakestChroma(entries.map { it.color })
            assertTrue(
                "$name 里有一格掉成灰了：最弱 C*=%.1f（要 >=27）—— %s"
                    .format(w, weakestChromaLabel(tiles(entries))),
                w >= 27.0,
            )
        }
    }

    /**
     * 这一条是用户那句抱怨的**直接编码**：同屏里最艳与最不艳的那两格，彩度差不超过 2 倍。
     * CHG-0101 那套是 **7.2 倍**（消息中心 58.4 / 账户管理 8.1）—— 那才是"太灰"的真身。
     */
    @Test
    fun `同屏里最艳与最不艳的两格，彩度差不超过 2 倍`() {
        for ((name, entries) in listOf(
            "派单端" to Modules.dispatcherEntries,
            // ⚠️ AI 那格是 Google 品牌蓝（C*=63.8），**不是**本套语义色，要排掉 ——
            //    口径与 `ThemePaletteTest` 里那条饱和度地板逐字相同。
            "货主端" to Modules.shipperEntries.filter { it.route != "ai/chat" },
            "账本管理入口页" to Modules.ledgerHomeEntries,
        )) {
            val cs = entries.map { labChroma(it.color) }
            val ratio = cs.max() / cs.min()
            assertTrue(
                "$name 里彩度落差 %.1f 倍（要 <=2.0）—— 最高 %.1f / 最低 %.1f，看着就是「有的灰有的艳」"
                    .format(ratio, cs.max(), cs.min()),
                ratio <= 2.0,
            )
        }
    }

    // ---- ③ 不许挤到一起 ----

    @Test
    fun `派单端 19 格两两距离都不低于 20（够不上 60 的约束，但也不许几乎同色）`() {
        val w = closestPair(tiles(Modules.dispatcherEntries))!!
        assertTrue(
            "「%s」与「%s」只差 %.1f（要 >=20）—— 同屏几乎同色，用户会找不到"
                .format(w.first, w.second, w.third),
            w.third >= 20.0,
        )
    }
}
