package com.tapmoay.sorders.ui.common

/**
 * 订单列表**空着的时候**该说的那一句 —— 派单员「订单管理」与货主「我的订单」共用这一份
 * （2026-10-09，测试台账 TA-01）。
 *
 * ## 由来（真机上复现出来的）
 *
 * 派单员那一页的缺省档是「派单中」，它的列表**带 `status=PENDING_DISPATCH`**、不带日期条件。
 * 于是用户搜一个**已经派过单**的单号「SO202610095032003138」时，App 发出去的是
 * `GET /orders?status=PENDING_DISPATCH&q=SO…` → 200 空 → 屏幕上只有四个字
 * 「没有匹配的订单」；而那页的标题写着"全部订单"、右上角药丸写着「不限时间」——
 * **屏幕上没有任何一处**写着"这一页只看派单中"。用户看到的是"这单不见了 / 搜坏了"，
 * 接口那边的 `q` 一点问题都没有（切到页签「全部」立刻搜得到）。
 *
 * 所以空态的规矩是：**说清是哪个筛子把结果挡住了，并给出出路**。
 *
 * ## 四档（`when` 的顺序就是优先级，⛔ 别调换）
 *
 * 1. 有日期窗口 + 搜过 → 两条出路都给出（换时间 / 点页签「全部」再搜）；
 * 2. 有日期窗口（没搜过）→ **原来那一句照旧**：它已经指明了出路（右上角那颗药丸），
 *    是司机端 2026-09-20 用一次"筛空之后没有出路"的事故换来的，⛔ 不许改短；
 * 3. 有状态筛选（`statusFiltered`）+ 搜过 → **点名是哪一档在挡** + 出路；
 * 4. 有状态筛选（没搜过）→ 这一档现在没单 + 出路（点页签「全部」看别的状态）。
 *
 * 剩下的一律交给调用方给的兜底句（`noMatch`）。
 *
 * ## 为什么写成**纯函数**（不 import Compose、不碰 Android）
 *
 * 两页共用**同一份**判断，而它必须能**直接喂参数单测**（`OrderEmptyHintTest`）：
 * 这是一句"只在列表空着时出现"的话，真机上要复现它得先造出一个空列表；
 * 判据与反验都抓不住"四个字 vs 一句实话"的差别 —— 单测能。
 * ⛔ 别把 `if` 挪回两个页面里各写一份：本仓库在这页上已经吃过一次
 * "抄两份 = 下次只修一页"（见 `OrderWindowViewModel.kt` 文件头那段 2026-09-22 的记录）。
 */
internal fun orderEmptyHint(
    tabLabel: String,
    statusFiltered: Boolean,
    windowWord: String?,
    searching: Boolean,
    noMatch: String,
): String = when {
    windowWord != null && searching ->
        "「" + windowWord + "」的" + tabLabel + "里没搜到 —— 点右上角可以换一段时间，或者点页签「全部」再搜"
    windowWord != null ->
        "「" + windowWord + "」没有" + tabLabel + "的订单 —— 点右上角可以换一段时间"
    statusFiltered && searching ->
        "「" + tabLabel + "」里没搜到 —— 这一页只看「" + tabLabel + "」，点页签「全部」可以搜别的状态"
    statusFiltered ->
        "「" + tabLabel + "」还没有单 —— 点页签「全部」可以看到其他状态的单"
    else -> noMatch
}
