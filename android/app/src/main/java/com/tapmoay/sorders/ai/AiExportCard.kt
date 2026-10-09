package com.tapmoay.sorders.ai

/**
 * 导出文件卡上那**两颗按钮**现在的样子（台账 L-61 / CHG-0095）。
 *
 * ## 为什么单独抽一个纯函数
 * 卡片上同时摆着「下载」与「分享」两颗图标按钮 —— 这是用户 2026-10-09 点名的形态
 * （ref `m00002`：「左边是有个那个框那是个文件图标……最后这一右边的那个小框那就是一个下载的
 * 图标按钮……还有一个按钮叫做就是分享也就是它有 2 个按钮」，并且「这 2 个按钮不要靠的太近」）。
 *
 * 两颗按钮一起摆在屏幕上之后，「**哪一颗现在点得动**」就成了纯逻辑问题：
 * 点不动的那颗必须看起来点不动（否则用户会对着它连点，然后以为 App 坏了），
 * 而"什么时候点得动"这件事**三条链路各自知道一半**：
 * - [busy] 是这一条消息的取件状态（`ExportRowState.busy`）；
 * - [saved] 是文件**已经落到这台手机上了**（`ExportRowState.file != null`）；
 * - [shareable] 是这台手机**给不给得出 `content://`**（Android 10 以下给不出，见 CHG-0078 口径 m01865）。
 *
 * 写错任何一档都不报错、不崩、单测也不会红，只是按钮变得点不动或点得动得莫名其妙 ——
 * 所以逐档钉在 `AiExportCardTest` 里，界面侧只管照着画。
 *
 * ⛔ 这里**不看** [ExportRowState.error]：失败之后两颗按钮的**可用性**与失败前一样
 * （「下载」还是能再点一次，「分享」还是没东西可分享），变的只是「下载」那颗上写的字
 * （`再试一次`，见 [exportDownloadLabel]）。把 error 也塞进可用性判定，就会做出
 * "错一次之后连重试都点不动"的死角。
 *
 * @param busy 正在取件 / 正在等账本任务生成（这一条消息此刻在忙）。
 * @param saved 文件已经落到这台手机上了（成功那一次的产物还在）。
 * @param shareable 这台手机能把文件交给别的 App（`ExportedFile.shareable`：Q+ 才有 `content://`）。
 */
internal data class ExportCardActions(
    /** 「下载」那颗此刻点得动吗。 */
    val downloadEnabled: Boolean,
    /** 「分享」那颗此刻点得动吗。 */
    val shareEnabled: Boolean,
    /** 文件已经在手机上了 —— 界面据此在信息区写一句「已保存」（[exportSavedLabel]）并让「下载」退成灰的。 */
    val downloaded: Boolean,
)

/**
 * 取件中的两档说法（**只动字，不动可用性**）。
 *
 * 为什么不把「正在准备文件…」也当成一个"阶段"：界面侧压根到不了那一档 ——
 * 第一颗按钮在 [ExportCardActions.downloadEnabled] 为 false 时点不动，而能点的时候
 * [ExportRowState.file] 必定还是 null（VM 在成功那一次直接把 file 挂上、busy 同时落回 false）。
 * 但**纯函数自己**必须对这一档有确定的答案：`progress` 空着的时候要有一句话顶上去，
 * 否则卡片上就只剩一个转圈的按钮、没有一行字说在干什么。
 */
internal fun exportProgressNote(busy: Boolean, saved: Boolean, progress: String): String = when {
    !busy -> ""
    progress.isNotBlank() -> progress
    saved -> "正在准备文件…"
    else -> "正在生成…"
}

/** 「下载」那颗上写什么（失败过就写「再试一次」——用户点它就是为了再试）。 */
internal fun exportDownloadLabel(hasError: Boolean): String = if (hasError) "再试一次" else "下载"

/**
 * 文件已经落到手机上时，卡片上写什么（台账 **L-62** / CHG-0097）。
 *
 * 用户 2026-10-09 的原话（ref `m01176`，语音转写，逐字）：
 * 「包括什么已保存到那个什么什么什么？也喜也也省略掉啊，不要那么长的信息啊，只表示一保存做个简单的」
 *
 * ⇒ 从前写的是 `"已保存到：" + saved.path`，那句话会把
 * `/storage/emulated/0/Download/SOrders报表/营业纵览-2026-09-01_2026-09-30.xlsx`
 * 整条摊在卡片上、占两三行，把卡片撑成一大块（用户截图圈的就是这一块）。
 * 现在只写两个字，**存到哪儿由右边那颗 [分享] 负责**（要发给谁就直接发），
 * 真要自己去找文件的，系统「下载」App 里那个 `SOrders报表` 目录一直都在。
 *
 * ⛔ 这里**只给这一档**留了函数：失败那一档必须把后端的原话**原样**说出来（`"⚠ " + error`，
 * 换掉就等于把错误吞了），正在忙那一档是 [exportProgressNote]，都不许从这里过一道手。
 */
internal fun exportSavedLabel(): String = "已保存"

/**
 * 卡片信息区最后那一行写什么（**整行收敛到这一处**，台账 **L-62** / CHG-0097）。
 *
 * 三档的先后顺序本身就是判据：**错误 > 已存好 > 正在忙**。
 * 「说一句实话」永远压过"看起来一切正常" —— 失败之后卡片上不许只写「已保存」。
 *
 * ⚠️ 为什么这一行也要抽出来（而不是留在界面里 `when`）：它是**唯一**一处决定
 * 「卡片对用户说的那句话是什么」的地方，而用户点名要改的就是这句话的长短。
 * 留在 Composable 里就只能靠正则去钉字符串；抽成纯函数之后，`AiExportCardTest`
 * 可以直接断言「存好之后卡片上**没有** `/storage/` 这三个字」这种话。
 *
 * @param error 后端/网络的失败原话（空＝这一条没失败过）。
 * @param saved 文件已经在手机上了。
 * @param busy 此刻正在取件。
 * @param progress 取件过程中后端报的那句话（账本才会报，如「已等 8 秒」）。
 */
internal fun exportStatusLine(
    error: String,
    saved: Boolean,
    busy: Boolean,
    progress: String,
): String = when {
    error.isNotBlank() -> "⚠ " + error
    saved -> exportSavedLabel()
    else -> exportProgressNote(busy = busy, saved = false, progress = progress)
}

/**
 * 卡片信息区第二行（文件名下面那一行）：这张表叫什么 ＋ 统计的是哪一段。
 *
 * 两类来源共用一个模型（[StoredExportRecipe]），但**这一行只有两种形状**：
 * - 报表：`营业纵览 · 2026-09-01 ~ 2026-09-30`（表名走 [AiTools.exportTitle]，与报表页签、
 *   后端 sheet 标题**三处逐字相同** —— 用户对着文件名就找得到是哪一个页签）；
 * - 账本：`货主账本`（谁的那本账、哪一段，文件名里已经写全了，⛔ 不再重复一遍）。
 *
 * 认不出的来源（将来新增一类）回落到**什么都不写**那一档：宁可少一行，
 * 也不要在用户眼皮底下编一个不存在的表名。
 */
internal fun exportCardSubtitle(recipe: StoredExportRecipe): String = when (recipe.source) {
    StoredExportRecipe.SOURCE_REPORT -> {
        val title = AiTools.exportTitle(recipe.kind)
        listOf(title, exportSpanLabel(recipe.dateFrom, recipe.dateTo))
            .filter { it.isNotBlank() }
            .joinToString(" · ")
    }
    StoredExportRecipe.SOURCE_LEDGER -> "货主账本"
    else -> ""
}

/** `2026-09-01_2026-09-30` → `2026-09-01 ~ 2026-09-30`；只有一头就只写那一头；两头都没有就不写。 */
private fun exportSpanLabel(from: String, to: String): String {
    val a = from.trim()
    val b = to.trim()
    return when {
        a.isNotEmpty() && b.isNotEmpty() && a != b -> "$a ~ $b"
        a.isNotEmpty() -> a
        else -> b
    }
}

/**
 * 两颗按钮此刻的状态。判据两条（顺序即优先级）：
 * 1. [busy] 压过一切 ⇒ **两颗都点不动**。下载这一头是 CHG-0078 的原始口径（连点就是连开任务）；
 *    分享那一头是同一件事的另一面：重下的时候 [StoredExportRecipe] 的旧 `file` 还挂着
 *    （`AiChatViewModel.downloadExport` 只翻 `busy`，不清 `file`），这时把「分享」留着亮的，
 *    用户分享到的可能是**上一个版本**的那份表 —— 一句"文件已发出去"之后谁也说不清发的是哪一版。
 * 2. 不忙的时候：「下载」在文件**已经在手机上**时退成灰的（再点一次也只是把它存到同一个地方，
 *    而那颗按钮此刻写着「下载」，用户会以为还有第二份文件没拿）；
 *    「分享」只在**文件真在手机上、且这台手机给得出 `content://`** 时才亮 ——
 *    Android 10 以下永远是灰的，界面在下面用一句话把原因和文件位置说清楚（CHG-0078 口径 m01865）。
 */
internal fun exportCardActions(
    busy: Boolean,
    saved: Boolean,
    shareable: Boolean,
): ExportCardActions = ExportCardActions(
    downloadEnabled = !busy && !saved,
    shareEnabled = !busy && saved && shareable,
    downloaded = saved,
)
