package com.tapmoay.sorders.ai

/**
 * AI 设置页那张**能力声明卡**折叠起来之后该写什么（台账 L-63 / CHG-0098）。
 *
 * ## 用户口径（2026-10-09，ref `m01649`）
 * 用户发来「AI 设置」页截图（红框已经不需要 —— 那一屏**大半张**都是这段话），
 * 语音转写逐字：「顺便把这个做一个折叠和隐藏啊，他那些详情的解释啊，不然太长了很占位子。」
 *
 * ⇒ 两条主张：① **默认折叠**（"占位子"指的就是它）；② 不是删掉 —— 点一下还得能看全（"折叠和隐藏"）。
 *
 * ## ⛔ 折的是**界面**，不是那段话本身
 * `AiRolePrompt.settingsSummary` 有两份读者：
 * 1. **设置页上的用户** —— 它占了大半屏，所以本单把它折起来；
 * 2. **system prompt 里的模型** —— `brief()` 把同一段话喂给模型当能力声明。
 *
 * ⛔ 所以**一个字都不许从 `settingsSummary` 里删**：那段话是模型的"我能做什么"，
 * 删窄了它会跟着一起否认自己的能力（`AiRolePromptTest` 与 §19.6 都记着这次事故）。
 * 本单只决定**折叠起来那一行写什么**，正文原样交给展开态。
 *
 * ## 为什么单独抽一个纯函数
 * 折叠块的标题行是用户判断"这里面有没有我要找的东西"的**唯一线索**：
 * 只写「展开」等于把能力清单藏起来，用户还得点一次才知道有没有。
 * 所以标题行必须报数（能查几项 / 能改几项），且报的数字必须**从那段话本身数出来**，
 * 不是手写的第二份清单 —— 手写的清单会跟真实能力走散，这个项目已经因此踩过一次
 * （设置页那句「改价做不了」在批量调价上线后还挂着，见 `AiSettingsScreen.kt:130-136`）。
 *
 * @param canRead 能查几项（`能查：` 后面「、」分隔的条数）。
 * @param canWrite 能改几项（同上）。
 * @param canWriteKnown 「能改」那一行到底有没有说清 —— 认不出来时**不报数**，
 *   宁可少说一句，也不许报一个假的 0（那会让用户以为 AI 什么都改不了）。
 */
internal data class AiCapabilitySummary(
    val canRead: Int,
    val canWrite: Int,
    val canWriteKnown: Boolean,
)

/**
 * 从 `AiRolePrompt.settingsSummary` 的输出里**数出**两份清单各有几项。
 *
 * 数的是「、」分隔的条数（+1）：那句话的写法就是 `能查：A、B、C`，
 * 域里不会出现顿号（`AiWrites` / `AiReads.moduleCn` 给的都是「账号与收费规则」这种词）。
 *
 * 认不出来时返回**零值**（`canWriteKnown = false`），由 [capabilitySummaryLabel] 决定怎么说 ——
 * ⛔ 不在这里抛异常，也不在这里编一个数：设置页宁可少说一句，也不能因为一句话改了就白屏。
 */
internal fun capabilitySummaryCounts(summary: String): AiCapabilitySummary {
    val line = summary.lineSequence().firstOrNull { it.startsWith("能改") }
    val writeKnown = line != null && !line.contains("没有") && !line.contains("没认出")
    return AiCapabilitySummary(
        canRead = countItemsAfter(summary, "能查："),
        canWrite = if (writeKnown) countItemsAfter(line!!, "能改：") else 0,
        canWriteKnown = writeKnown,
    )
}

/**
 * 折叠起来那一行标题该写什么。
 *
 * **顺序即判据：展开 > 认不出 > 全 0 > 报数**（写在前面那档先赢，四档互斥）：
 * 1. 展开时那句是**收起** —— 点一下要发生什么，写在按钮上（照「执行过程」那一块的口径）；
 * 2. 认不出角色时**不下结论**，直接说"点开看"（这时清单里是那句失败兜底的话）；
 * 3. 一项能改的都没有就**不许报「能改 0 项」**（"看起来有、其实没有"在本项目里是红线）；
 * 4. 认得出就报数：`能查 39 项 · 能改 23 项（点开看清单）`。
 *
 * ⛔ 不许只写「展开」两个字：那等于把"这里面有多少东西"也一起藏了 ——
 * 用户点开之前唯一的线索就是这一行，它得先回答"值不值得点"。
 *
 * ⚠️ 「能查 N 项」里的 N 会随着下面那几个只读开关**当场变小**（关掉一个少一项）：
 * 数字是从那段话里数出来的，不是手写的第二份清单。
 */
internal fun capabilitySummaryLabel(counts: AiCapabilitySummary, expanded: Boolean): String = when {
    expanded -> "收起清单"
    !counts.canWriteKnown -> "能做什么（点开看清单）"
    counts.canRead <= 0 && counts.canWrite <= 0 -> "能做什么（点开看清单）"
    counts.canWrite <= 0 -> "能查 ${counts.canRead} 项（点开看清单）"
    else -> "能查 ${counts.canRead} 项 · 能改 ${counts.canWrite} 项（点开看清单）"
}

/**
 * 「、」分隔的条数（认不出那一段时返回 0）。
 *
 * @param text 整段话（或单行）。
 * @param prefix 段首标记，如 `能查：`。
 */
private fun countItemsAfter(text: String, prefix: String): Int {
    val at = text.indexOf(prefix)
    if (at < 0) return 0
    val body = text.substring(at + prefix.length).substringBefore('\n').trim()
    if (body.isEmpty()) return 0
    // 兜底话（「暂时没有…」「没有。」）不是清单，别把它数成 1 项
    if (body.startsWith("暂时没有") || body.startsWith("没有")) return 0
    return body.split('、').count { it.isNotBlank() }
}
