package com.tapmoay.sorders.ui.ai

/**
 * 「执行过程」那一行标题该写什么（台账 L-60 / CHG-0094）。
 *
 * ## 为什么单独抽一个纯函数
 * 这一行是**用户判断"要不要点开"的唯一线索**：不写清"几步"，折叠就等于把过程藏起来了
 * （用户不知道里面有没有他要找的那一句）；写了"进行中"，用户才知道现在屏幕上动的是哪一块。
 * 三句话都写错得起，所以由单测钉住（`AiTraceHeaderTest`），界面侧只管调用。
 *
 * 优先级：**展开 > 进行中 > 条数**。
 * - 展开时那句是**收起**（点一下要发生什么，写在按钮上）；
 * - 进行中时**不带条数**：一轮多步问答每查一次就会 +1，标题跟着跳字是噪声 ——
 *   用户这会儿要的是"它在干活"，不是账目；
 * - 跑完了才报数（「查看执行过程 · 6 条」）：这是折叠块唯一还留在屏幕上的信息。
 *
 * @param lineCount 这一轮攒下的步骤条数（已去重后的行数，与界面画的行数同源）。
 * @param running 这条消息**此刻还在生成**（不是"这条消息里有过工具调用"）。
 * @param expanded 当前是否展开。
 */
internal fun traceHeaderLabel(lineCount: Int, running: Boolean, expanded: Boolean): String = when {
    expanded -> "收起执行过程"
    running -> "执行过程 · 进行中"
    lineCount > 0 -> "查看执行过程 · " + lineCount + " 条"
    else -> "查看执行过程"
}
