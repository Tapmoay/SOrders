package com.tapmoay.sorders.ui.common

/**
 * 商品单位的**唯一一份词表** + "选择列表怎么排"的**唯一一份算法**。
 *
 * ## 为什么要收成一份（2026-09-21 商品管理改版第 1 期）
 * 在这之前，单位是**硬编码在商品编辑抽屉里的 16 个字符串**
 * （`ProductsScreen.kt` 里那个 `listOf("件","个",…)`），而 `products.unit` 在库里是
 * `String(32)` 的**自由串** —— 两边对不上：库里可能存着"提"，而下拉里根本没有它，
 * 于是"改单位"这件事在界面上是**做不到也不报错**的。
 *
 * 用户 2026-09-21 定的档位（原话）：
 * > 「单位就是做到我们现在有的（那）档…**他的档位不要超**，只是抄他的那个**布局**的样式。」
 *
 * 所以这里**不新增任何单位**、也不建服务端名册（那是另一档，要动核心区的线上迁移文件）：
 * 词表就是原来那 16 个，**再把商品库里已经在用的那些并进来** —— 后者才是真正的兜底，
 * 它保证"库里有什么就一定选得到"。
 *
 * ## 为什么没有"最近用过的"（原本方案里写的那一条，实施时去掉了）
 * 它要新增**一份本地持久状态**（SharedPreferences），而"库里已经在用的"是同一件事的
 * **更好来源**：跨设备一致、不依赖这台手机以前点过什么、也不用多一个"清缓存"的出口。
 * 档位是"不超现有的"，那就不该为了排序多养一份状态。
 */

/**
 * 预设单位。**顺序就是 chips 里的顺序**（常用/通用的排在前面）。
 *
 * ⚠️ 改动这里等于改所有商品的"能选什么"，改之前先确认两件事：
 * ① 后端 `products.unit` 的列宽是 `String(32)`（够）；
 * ② 库存、下单、订单行快照都只把它当**显示串**用（没有按单位做的换算 ——
 *    "进货按箱、销售按件"那种带换算率的双单位是另一件事，会同时动库存与成本两处核心）。
 */
val UNIT_PRESETS: List<String> = listOf(
    "件", "个", "块", "包", "箱", "桶", "袋", "捆",
    "瓶", "盒", "盘", "斤", "公斤", "吨", "米", "车",
)

/** 没填单位时的兜底（与后端 `products.unit` 的缺省值一致）。 */
const val DEFAULT_UNIT = "件"

/** 单位兜底：null / 空串 / 纯空格 → [DEFAULT_UNIT]。 */
fun unitOrDefault(raw: String?): String = raw?.trim().orEmpty().ifBlank { DEFAULT_UNIT }

/**
 * 单位选择页里要摆出来的那些单位，**顺序即展示顺序**。
 *
 * 规则（三条，都有单测）：
 * 1. **库里已经在用的排最前面**（[inUse]，按传入顺序、去重、去空）——
 *    这一档是在用的货真价实的单位，比预设更该先看到；
 * 2. 然后是 [UNIT_PRESETS]；
 * 3. ⛔ **[current] 必须在列表里**：它是这个商品现在用的单位，可能是某个老数据里的冷门词
 *    （"提""筐"），既不在预设、也不在别处用着 —— 少了它，用户点开选择页找不到当前值、
 *    随手点一个别的，**保存就等于把单位静默改掉了**（界面上完全看不出来）。
 *    所以它若不在前两档里，就补在**最前面**。
 */
fun unitChoices(current: String?, inUse: List<String> = emptyList()): List<String> {
    val used = inUse.mapNotNull { it.trim().ifEmpty { null } }.distinct()
    val all = (used + UNIT_PRESETS).distinct()
    val cur = current?.trim().orEmpty()
    return if (cur.isNotEmpty() && cur !in all) listOf(cur) + all else all
}

/**
 * 单位在**搜索框**里怎么匹配：子串、忽略大小写（[keyword] 空白 = 全部）。
 *
 * 纯函数、单独一个入口：搜索框是"再筛一层"，它和 [unitChoices] 是两件事 ——
 * 混在一起写的话，"搜不到"与"没有这个单位"就会变成同一句话。
 */
fun filterUnits(units: List<String>, keyword: String): List<String> {
    val k = keyword.trim()
    if (k.isEmpty()) return units
    return units.filter { it.contains(k, ignoreCase = true) }
}
