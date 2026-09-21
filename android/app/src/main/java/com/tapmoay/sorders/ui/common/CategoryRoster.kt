package com.tapmoay.sorders.ui.common

/**
 * 四个「分类名册」（**开销 / 运费 / 商品 / 地点**）拖动排序时共用的**三条规则**。
 *
 * ### 为什么必须收成一处（2026-09-21 精简轮）
 * 这三条原来在各自的 ViewModel 里**各写了一遍**（开销 / 运费 / 商品三份几乎逐字相同；
 * 地点那份是"拖动即提交"、少了草稿态），而它们守的其实是同一件事：
 * **交给后端的必须是"完整名册的顺序"**。抄几份的代价已经出现过（见第 2 条）。
 *
 * 1. **只提交名册里的行**（[submittableIds]）：开销名册的列表里混着"名册外的分类（老数据）"这种
 *    **界面造的合成行**（`id == 0`），后端不认识它 —— 带上就是整批拒绝
 *    （「顺序里有不存在的分类编号：[0]」）。用户点「保存顺序」看到一句大红字，而顺序明明是对的。
 * 2. **撤销不能丢"保存之后新建的"**（[revertedOrder]）：`savedOrder` 是"上次保存的顺序"，
 *    新建的分类不在里面；只按 `savedOrder` 重建列表，那一行会**从列表里消失**
 *    （后端还在，用户以为被删了，切走再回来才又出现）。
 *    ⚠️ 这正是抄多份走散的地方：**运费那一页的「撤销排序」当时是丢行的那一版**，
 *    开销/商品两份保留 —— 同一个按钮、三页两种行为，谁都没报错。
 * 3. **"顺序改过没有"只有一种判法**（[orderChanged]）：与"上次保存的顺序"逐位比编号。
 */

/** 只提交**名册里的**行（`id > 0`）—— 见文件头第 1 条。 */
fun <T> submittableIds(rows: List<T>, idOf: (T) -> Long): List<Long> = rows.map(idOf).filter { it > 0 }

/**
 * 顺序有没有改过：与 [savedOrder]（上次保存的顺序）逐位比编号。
 *
 * ⚠️ 比的是**名册里的那几行**（[submittableIds]）：名册外的合成行（`id == 0`）一直都在列表最后、
 * 后端也从来不返回它，拿它一起比的话，**保存成功之后"未保存"标记仍然亮着**（用户以为没保存上，
 * 再点一次——而这一次提交的 id 列表与上次完全相同）。三页原来都带着这个毛病。
 */
fun <T> orderChanged(rows: List<T>, savedOrder: List<Long>, idOf: (T) -> Long): Boolean =
    submittableIds(rows, idOf) != savedOrder

/**
 * 「撤销未保存的顺序改动」：回到 [savedOrder] 的顺序，**但保存之后新建的行仍留在后面**
 * （它们在 [savedOrder] 里没有编号，只按它重建就会整行消失）。
 */
fun <T> revertedOrder(rows: List<T>, savedOrder: List<Long>, idOf: (T) -> Long): List<T> {
    val byId = rows.associateBy(idOf)
    val restored = savedOrder.mapNotNull { byId[it] }
    val extra = rows.filter { idOf(it) !in savedOrder }
    return restored + extra
}
