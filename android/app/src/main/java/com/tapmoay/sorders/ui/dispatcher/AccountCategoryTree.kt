package com.tapmoay.sorders.ui.dispatcher

/**
 * 账号分类左栏的**两级**（2026-10-11 CHG-0112）＋ 那一格的本地过滤。
 *
 * 用户 2026-10-11：「假如我的货主和批发商做了分类的话，然后我这个账户管理就会显示
 * 2 级分类，也就会显示他们里面的子分类。这就方便我们去查角色嘛……假如他没有多少分类吗？
 * 一堆的话到时候查起来非常麻烦」。
 *
 * 名册仍然是**平铺的一列**（后端按 `sort_order, id` 返回，账户/司机/货主/批发商四个名册页共用），
 * 「谁在谁下面」由 [RosterRow.parentId] 表达 —— **树是在这里画出来的**：大类一行，
 * 紧跟它后面的是它的子类（缩进一级）。点大类筛出它**下面所有子类**的账号，点子类只筛那一类。
 *
 * ⛔ 纯函数、零 Compose import（照 `ui/common/OrderEmptyHint.kt`、`ui/dispatcher/ArrearsBalanceLine.kt`
 *    的先例）：这几条判断是这一单最容易被改坏的地方，JVM 单测直接钉
 *    （`android/app/src/test/java/com/tapmoay/sorders/ui/dispatcher/AccountCategoryTreeTest.kt`）。
 *
 * ⛔ 两条不许破的边界：
 * 1. **名册里没有的分类名不是错误** —— 这一层只管左栏怎么画，一个账号都不会被它筛掉
 *    （账号卡片照画那个名字）；
 * 2. **脏数据不许把行藏起来**：`parentId` 指向一个已经不在名册里的行、或指向一个子类
 *    （第三层，后端不会让它产生，但库里可能有）时，这一行**降级成大类**照样画出来 ——
 *    它消失等于那一类的账号在左栏里点不到，而那正是用户要解决的问题的反面。
 */

/** 左栏的一格。[depth] 0 = 大类、1 = 子类（缩进一级）。 */
data class RailRow(
    val key: String,
    val label: String,
    val depth: Int,
    /** 点这一格要筛出**哪些分类名**的账号：大类 = 自己 ＋ 它的子类；子类 = 只有自己。 */
    val covers: Set<String>,
)

/** `c|分类名` → 分类名；「全部」→ 空串（全库同一套 key 约定，见 `ui/common/CategoryDrawer.kt`）。 */
fun railCategoryName(key: String): String = if (key.startsWith("c|")) key.removePrefix("c|") else ""

/** 这一格的**父行**；`null` = 它自己就是大类（见文件头第 2 条：父不在了也当大类）。 */
private fun parentRowOf(row: RosterRow, all: List<RosterRow>): RosterRow? {
    val pid = row.parentId ?: return null
    val parent = all.firstOrNull { it.id == pid } ?: return null
    return if (parent.parentId == null) parent else null
}

/** 名册（平铺）→ 左栏（两级）。大类按名册顺序，每个大类后面紧跟它的子类（同样按名册顺序）。 */
fun categoryRailRows(rows: List<RosterRow>): List<RailRow> {
    val tops = rows.filter { parentRowOf(it, rows) == null }
    val out = ArrayList<RailRow>(rows.size)
    tops.forEach { top ->
        val kids = rows.filter { parentRowOf(it, rows)?.id == top.id }
        out += RailRow(
            key = "c|" + top.name,
            label = top.name,
            depth = 0,
            covers = (kids.map { it.name } + top.name).toSet(),
        )
        kids.forEach { kid ->
            out += RailRow(key = "c|" + kid.name, label = kid.name, depth = 1, covers = setOf(kid.name))
        }
    }
    return out
}

/** 左栏那一格覆盖的分类名（[inRail] 的第 4 个参数）。空串（「全部」）→ 空集 = 不筛。 */
fun railNamesUnder(rows: List<RosterRow>, key: String): Set<String> {
    val name = railCategoryName(key)
    if (name.isBlank()) return emptySet()
    val self = rows.firstOrNull { it.name == name } ?: return setOf(name)
    val kids = rows.filter { parentRowOf(it, rows)?.id == self.id }
    return (kids.map { it.name } + name).toSet()
}

/**
 * 按左栏那一格过滤（空串 = 全部）。名册与列表都在手上 —— 本地过一遍，不往返后端。
 *
 * [covers] = 这一格覆盖的**全部**分类名（两级之后点大类要把它下面所有子类一起端出来，
 * 由 [railNamesUnder] 算）；空集 = 只有它自己那一个名字（平表那几页照旧）。
 */
fun <T> inRail(rows: List<T>, key: String, nameOf: (T) -> String, covers: Set<String> = emptySet()): List<T> {
    val name = railCategoryName(key)
    if (name.isBlank()) return rows
    val want = if (covers.isEmpty()) setOf(name) else covers
    return rows.filter { nameOf(it) in want }
}
