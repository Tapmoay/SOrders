package com.tapmoay.sorders.ui.common

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 「选人」左栏那一列的分组（CHG-0128，用户 2026-10-15：「像**选地点库那样**（左分类、右对应项）」）。
 *
 * 为什么值得单独测：左边这一列**不是**新算法 —— 它是商品 / 库存 / 预设单 / 选商品弹层
 * 已经在用的 `ProductPicker.kt::categoryTabsOf`。所以这里真正要钉住的是**转发没走样**：
 * 「未分类」排最后、「名册外的老分类」照样出一格、全都没分类时只剩「全部」这三条兜底
 * 一旦在选人这里走样，坏法是**不报错**的 —— 屏幕上只是"少了几个人"，
 * 用户会以为"这个人没存上"，然后再建一个（同一个人两本账）。
 */
class PersonGroupsTest {

    /** 与 [com.tapmoay.sorders.data.remote.dto.ContactDto] / `UserDto` 同形的那一格：`""` = 未分类。 */
    private data class P(val name: String, val category: String?)

    private fun p(name: String, category: String? = "") = P(name, category)

    /** 一行断言，省得每条判据都写一遍 prefix。 */
    private fun assertTab(rows: List<P>, expected: List<String>) =
        assertEquals(expected, groupTabsOf(rows) { it.category })

    @Test
    fun `一屋子人都没有分类_左栏只剩「全部」`() {
        // 用户口径：**没分类的人归「未分类」，不许藏起来**（这里全员没分类）。
        // 但左栏只有「全部」一格 —— 不逼用户先去"管理分类"补一遍才能挑到人
        // （补分类是整理名册的动作，不是挑人的前置条件）。
        assertTab(listOf(p("老王"), p("小李"), p("张姐")), listOf(ALL_CATEGORY))
        // 空名册同样只剩「全部」：⛔ 不许返回空列表 —— 空列表会让左栏整列消失，
        // 用户看到的是干瘪的右半页，还会以为"弹层没加载出来"。
        assertTab(emptyList<P>(), listOf(ALL_CATEGORY))
    }

    @Test
    fun `「未分类」永远排在最后_哪怕它人数最多`() {
        // 人数多也**不许**把它顶到前面：它不是一个"分类"，是"还没归类"的兜底格子
        // （用户 2026-09-19：「那个分组下面不要显示有多少条啊，这是多余信息」——
        //  这一列只回答"分在哪一类"，不回答"哪一类人更多"）。
        assertTab(
            listOf(p("A"), p("B"), p("C"), p("D"), p("E"), p("老王", "食堂")),
            listOf(ALL_CATEGORY, "食堂", NO_CATEGORY),
        )
    }

    @Test
    fun `没分类的人归「未分类」_一条都不许少`() {
        // 这是整个改动最容易坏、又最不容易被看出来的地方：把没分类的人从右栏筛掉，
        // 屏幕上什么都不报错，用户只会以为"这个人没存上"→ 再建一个 → 同一个人两本账。
        val rows = listOf(p("老王", "食堂"), p("小李"), p("张姐", "  "), p("赵师傅", "教室"))
        assertTab(rows, listOf(ALL_CATEGORY, "食堂", "教室", NO_CATEGORY))
        // 点「未分类」那一格，右栏必须把 category 为空 / 只有空格的人都给出来
        assertEquals(listOf("小李", "张姐"), inGroup(rows, NO_CATEGORY) { it.category }.map { it.name })
        // 而且这些人在「全部」里也照样在（兜底格子不是"另一个名册"）
        assertEquals(4, inGroup(rows, ALL_CATEGORY) { it.category }.size)
    }

    @Test
    fun `名册里没有的老分类名_照样出一格`() {
        // 后端 category 是**自由文本**（`shipper_contacts.category` / `users.category`）：
        // 「管理分类」里改过名、或者干脆没建过名册，老数据里都可能有名册外的名字。
        // 按名册过滤 = 这些人整批从选人弹层里消失，而他们**一条都没被删**。
        val rows = listOf(p("老王", "食堂"), p("小李", "十年前的老分类"), p("张姐", "食堂"))
        assertTab(rows, listOf(ALL_CATEGORY, "食堂", "十年前的老分类"))
        assertEquals(listOf("小李"), inGroup(rows, "十年前的老分类") { it.category }.map { it.name })
    }

    @Test
    fun `分类名前后带空格_与不带的算同一类`() {
        // 名册建的时候手滑打了空格是常事；不归一的话左栏会出现两格看起来一模一样的
        // 「食堂」—— 点哪一格都对，用户会以为坏了。
        val rows = listOf(p("老王", "食堂"), p("小李", " 食堂 "), p("张姐", "\t教室\n"))
        assertTab(rows, listOf(ALL_CATEGORY, "食堂", "教室"))
        assertEquals(listOf("老王", "小李"), inGroup(rows, "食堂") { it.category }.map { it.name })
        assertEquals(listOf("张姐"), inGroup(rows, "教室") { it.category }.map { it.name })
    }

    @Test
    fun `选「全部」就是一条都不筛`() {
        // 「全部」那一格必须与"还没选"完全等价：多筛一次（例如又按 category 比一遍）
        // 会让"没分类的人"在这一格里消失 —— 而它本来是"全都在这儿"的那一格。
        val rows = listOf(p("老王", "食堂"), p("小李"), p("张姐", "教室"))
        assertEquals(rows, inGroup(rows, ALL_CATEGORY) { it.category })
        // 顺序也要原样：右栏的顺序是名册/N 的顺序，不是按分类重排过的
        assertEquals(listOf("老王", "小李", "张姐"), inGroup(rows, ALL_CATEGORY) { it.category }.map { it.name })
    }

    @Test
    fun `选中了一个已经不在左栏里的分类_右栏是空的（不许静默回退成「全部」）`() {
        // 分类被改名/删掉之后（名册一变），调用方靠 `LaunchedEffect(groups)` 自愈回「全部」。
        // 自愈**没跑**的那一瞬间如果这里悄悄返回全部，就变成了"点着一格、看到的却是所有人"。
        val rows = listOf(p("老王", "食堂"), p("小李"))
        assertTrue(inGroup(rows, "早就不存在的分类") { it.category }.isEmpty())
    }

    @Test
    fun `与商品那边的分组是同一份实现_不许各写一遍`() {
        // ⛔ 这条测的就是"没有第二份算法"：把同一批名字直接喂给 categoryTabsOf，
        // 结果必须**逐字相同**（顺序也在内）。留在这里当护栏 ——
        // 哪天有人为了"选人这边特殊一点"在 PersonGroups.kt 里手写一遍分组，这条先红。
        val rows = listOf(p("老王", "食堂"), p("小李"), p("张姐", "教室"), p("赵师傅", "食堂"))
        assertEquals(
            categoryTabsOf(rows.map { it.category }),
            groupTabsOf(rows) { it.category },
        )
        // 首格永远是「全部」（右栏"不筛"的入口 + 左栏的选中态基准）
        assertEquals(ALL_CATEGORY, groupTabsOf(rows) { it.category }.first())
    }
}
