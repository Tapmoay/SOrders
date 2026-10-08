package com.tapmoay.sorders.ui.ai

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tapmoay.sorders.ai.AiAnswerShape
import com.tapmoay.sorders.ai.AiAnswerTone
import com.tapmoay.sorders.ai.AiMarkdown
import com.tapmoay.sorders.ai.AnswerTone
import com.tapmoay.sorders.ui.theme.AiToneDanger
import com.tapmoay.sorders.ui.theme.AiToneMoney
import com.tapmoay.sorders.ui.theme.AiToneOk
import com.tapmoay.sorders.ui.theme.AiToneWarn

/**
 * 把模型答复渲染成「能看清」的样子：**表格画成 Excel 那样的真表格，`**粗体**` 真加粗**。
 *
 * ### 为什么表格要单独做，不能靠正文字号缩一缩
 * 实测模型爱输出四五列的 Markdown 表格。当纯文本贴出来时，用户看到的是
 * 「`| 王建国 | 22 | 31.8% | 430.8 分钟 |`」这种被竖线切碎的句子——**列对不上，数字看串行**。
 * 表格的价值全在"上下对齐"，纯文本把唯一的价值弄丢了。
 *
 * ### 为什么按 Excel 的规矩画（用户原话："像做一个 excel 那样子的渲染"）
 * 手机上要"一眼看懂一张表"，靠的不是好看，而是**读者早就学会的那套视觉约定**——
 * 而所有人对表格的约定都是从 Excel 来的：
 * | 约定 | 为什么它降低摩擦 |
 * | --- | --- |
 * | **每一格都有网格线** | 没有竖线的表在手机上会串列（4 列以上的时候尤其明显） |
 * | **表头有底纹 + 加粗** | 表头和数据长得一样时，用户要先读一遍才知道哪行是表头 |
 * | **数字右对齐**（文本左对齐） | 右对齐的小数点天然成一条线，金额/数量能竖着比大小 |
 * | **等宽数字（tnum）** | 不换字体就能让每一列的数字宽度一致，右对齐才真的对齐 |
 * | **隔行浅底** | 一行很长时，眼睛不会滑到隔壁行 |
 * | **合计行加粗** | "合计/总计/小计"那行是结论，不该和明细长一样 |
 *
 * ### 重要信息由界面自动上色（台账 L-24）
 * 用户要的是「重要的信息用特殊的样式」「信息越重要越要用特殊的颜色」，同时又钉了一条红线：
 * **「样式不能随便乱搞」——联系人就统一是联系人那一套，数字、账本信息也各有各的统一写法**。
 * 让模型自己挑颜色做不到"统一"（同一句话今天红、明天橙），还要为这套标记语法常年付提示词的 token。
 * 所以分工是：**加粗归模型**（它在回答里圈出最多 3 处重点）、**颜色归界面**——
 * 界面按 `AiAnswerTone` 的封闭词表确定性地判定类别并上色，模型既不知道也写不出来。
 *
 * 用户气泡也走这个渲染器，而它是蓝底白字——所以上色由调用点决定（用户气泡传 `toned = false`）。
 *
 * ### 表格的配色刻意**不跟随气泡**
 * 用户气泡是蓝底白字、助手气泡是浅灰底深字。表格如果跟着气泡走，两张底色下的
 * 表头/斑马纹都要各调一遍，还容易调出对比度不足的组合。所以表格统一画在**中性白卡**上、
 * 用固定的 `onSurface` 文字色——**对比度只取决于一个组合，不用每个场景都验一遍**。
 */
@Composable
fun AiRichText(
    text: String,
    fontSize: TextUnit,
    lineHeight: TextUnit,
    color: Color,
    toned: Boolean = true,
    modifier: Modifier = Modifier,
) {
    val blocks = remember(text, toned) {
        val parsed = AiMarkdown.parse(text)
        // 顺序有讲究：**先补形状、再上色**（2026-10-09 CHG-0092）。
        // [AiAnswerTone] 的既定裁定是「表格不参与上色」，若反过来，刚染上色的散行会带着
        // 染色名额被 [AiAnswerShape] 收进表格、颜色随后丢掉 —— 名额白花，后面的行反而没颜色。
        val shaped = if (toned) AiAnswerShape.apply(parsed) else parsed
        if (toned) AiAnswerTone.apply(shaped) else shaped
    }
    Column(modifier, verticalArrangement = Arrangement.spacedBy(6.dp)) {
        blocks.forEach { b ->
            when (b) {
                is AiMarkdown.Block.Table -> MdTable(b, fontSize = TableFontSize)
                is AiMarkdown.Block.Line -> MdLineBlock(b, fontSize, lineHeight, color, toned)
            }
        }
    }
}

/** 表格字号固定 14sp：比正文小一号才能把 4~5 列塞进手机宽度，又不至于看不清。 */
private val TableFontSize = 14.sp

@Composable
private fun MdLineBlock(
    line: AiMarkdown.Block.Line,
    fontSize: TextUnit,
    lineHeight: TextUnit,
    color: Color,
    toned: Boolean,
) {
    val annotated = line.annotated(toned)
    when (line.kind) {
        AiMarkdown.Block.Kind.HEADING -> Text(
            annotated,
            fontSize = fontSize,
            lineHeight = lineHeight,
            color = color,
            fontWeight = FontWeight.Bold,
            modifier = Modifier.padding(top = 2.dp),
        )

        AiMarkdown.Block.Kind.BULLET, AiMarkdown.Block.Kind.NUMBERED -> Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.Top,
        ) {
            // 记号占固定宽度，让多行文字左边缘对齐（否则第二行会顶到记号下面）
            Text(
                line.marker.orEmpty(),
                fontSize = fontSize,
                lineHeight = lineHeight,
                color = color,
                modifier = Modifier.width(if (line.kind == AiMarkdown.Block.Kind.NUMBERED) 26.dp else 16.dp),
            )
            Text(annotated, fontSize = fontSize, lineHeight = lineHeight, color = color)
        }

        AiMarkdown.Block.Kind.TEXT -> Text(annotated, fontSize = fontSize, lineHeight = lineHeight, color = color)
    }
}

/** 把行内片段拼成 AnnotatedString（粗体 → SemiBold，比 Bold 在中文小字下更清楚一点）。 */
private fun AiMarkdown.Block.Line.annotated(toned: Boolean): AnnotatedString = buildAnnotatedString {
    spans.forEach { s ->
        val tone = if (toned) s.tone else null
        if (!s.bold && tone == null) {
            append(s.text)
        } else {
            withStyle(
                SpanStyle(
                    color = toneColor(tone),
                    fontWeight = if (s.bold) FontWeight.SemiBold else null,
                )
            ) { append(s.text) }
        }
    }
}

/**
 * 类别 → 语义色。颜色只在 `ui/theme/Color.kt` 里定义（⛔ 这里不写裸十六进制），
 * 四个 token 是既有语义色的别名，**没有新造色**：危险 → 红、钱 → 橙、提醒 → 琥珀、正常 → 绿。
 *
 * null（或没开启上色）返回 [Color.Unspecified]，行内片段的颜色就沿用文本自己的 color。
 */
private fun toneColor(tone: AnswerTone?): Color = when (tone) {
    AnswerTone.DANGER -> Color(AiToneDanger)
    AnswerTone.MONEY -> Color(AiToneMoney)
    AnswerTone.WARN -> Color(AiToneWarn)
    AnswerTone.OK -> Color(AiToneOk)
    null -> Color.Unspecified
}

// ==================================================================== 表格

/** 数字列最窄/最宽（列宽按内容实测，夹在这个区间里）。 */
private val MinColWidth = 52.dp
private val MaxColWidth = 168.dp

/** 单元格左右内边距与上下内边距。 */
private val CellPadH = 8.dp
private val CellPadV = 7.dp

/**
 * 真表格（Excel 观感）。见 [AiRichText] 的类注释里那张"约定表"。
 *
 * ### 列宽怎么来：**实测**，不是按字符数猜
 * 以前按"最长内容的字符数 × 7.5dp"估，中文（15dp/字）和数字（7.5dp/字）差别很大，
 * 于是中文列被估窄、断行成竖排字，数字列被估宽、留一片空白。
 * 现在用 `TextMeasurer` 把每列最长的那一格**真量一遍**，再夹到 [MinColWidth]/[MaxColWidth]。
 *
 * ### 装不下就横向滚（并**告诉用户能滚**）
 * 按比例压窄会让 `100.0%` 断成三行——比纯文本还难读。所以宁可让它横向滚；
 * 而"能横向滚"这件事**必须写出来**（一个不动的表格看起来就是被截断了）。
 * 表头与各行**共用同一个 [androidx.compose.foundation.ScrollState]**，
 * 所以滑动任意一行，整张表（含表头）一起走，列不会错位。
 */
@Composable
private fun MdTable(table: AiMarkdown.Block.Table, fontSize: TextUnit) {
    // 无表头的表也要画：[AiAnswerShape] 把「标签：值」散行兜成的两列小表就是这种（header 为空）。
    // 以前这里是 if (table.header.isEmpty()) return —— 那种表会**整块消失**，等于兜底补出来的表看不见。
    val hasHeader = table.header.any { it.isNotBlank() }
    if (!hasHeader && table.body.isEmpty()) return

    val density = LocalDensity.current
    val measurer = rememberTextMeasurer()
    val cellStyle = remember(fontSize) {
        // tnum = 等宽数字：不换字体也能让每一列的数字宽度一致（右对齐才真的对齐）
        TextStyle(fontSize = fontSize, fontFeatureSettings = "tnum")
    }
    val headerStyle = remember(cellStyle) { cellStyle.copy(fontWeight = FontWeight.SemiBold) }

    val cols = if (hasHeader) table.header.size else table.body.maxOf { it.size }
    val natural: List<Dp> = remember(table, cellStyle, density) {
        (0 until cols).map { ci ->
            val cells = buildList {
                if (hasHeader) add(table.header.getOrNull(ci).orEmpty())
                table.body.forEach { add(it.getOrNull(ci).orEmpty()) }
            }
            val maxPx = cells.maxOfOrNull { measurer.measure(AnnotatedString(it), cellStyle).size.width } ?: 0
            with(density) { (maxPx.toDp() + CellPadH * 2).coerceIn(MinColWidth, MaxColWidth) }
        }
    }
    // 无表头时喂一份等宽的合成表头：AiMarkdown.numericColumns 只看列数（header.size），
    // 空表头会让它一列都判不出来 —— 金额 / 数量那种列本该右对齐，会全变成左对齐。
    val numeric = remember(table, cols, hasHeader) {
        AiMarkdown.numericColumns(if (hasHeader) table else table.copy(header = List(cols) { "" }))
    }

    val line = MaterialTheme.colorScheme.outlineVariant
    val headBg = MaterialTheme.colorScheme.surfaceContainerHigh
    val zebra = MaterialTheme.colorScheme.surfaceContainerLow
    val surface = MaterialTheme.colorScheme.surface
    val totalBg = MaterialTheme.colorScheme.secondaryContainer
    val scroll = rememberScrollState()

    BoxWithConstraints(Modifier.fillMaxWidth()) {
        val total = natural.fold(0.dp) { a, b -> a + b }
        val scrollable = total > maxWidth
        // 装得下 → 按比例拉伸填满（不留空白）；装不下 → 保持自然宽度 + 整表横向滚
        val widths = if (scrollable) natural else natural.map { it * (maxWidth / total) }

        Column {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(10.dp))
                    .background(surface)
                    .border(1.dp, line, RoundedCornerShape(10.dp)),
            ) {
                // ---- 表头 ----（无表头的小表整块不画表头，第一列当标签列）
                if (hasHeader) {
                    MdRow(
                        cells = table.header,
                        widths = widths,
                        style = headerStyle,
                        numeric = numeric,
                        background = headBg,
                        line = line,
                        scrollModifier = Modifier.horizontalScroll(scroll),
                    )
                }
                // ---- 数据行 ----
                table.body.forEachIndexed { i, row ->
                    val isTotal = AiMarkdown.isTotalRow(row)
                    Box(Modifier.fillMaxWidth().height(1.dp).background(line))
                    MdRow(
                        cells = row,
                        widths = widths,
                        // 无表头的小表：第一列是标签（「收货人」「电话」），压暗一档让值显出来
                        labelColumn = !hasHeader,
                        style = if (isTotal) headerStyle else cellStyle,
                        numeric = numeric,
                        background = when {
                            isTotal -> totalBg
                            i % 2 == 1 -> zebra
                            else -> surface
                        },
                        line = line,
                        scrollModifier = Modifier.horizontalScroll(scroll),
                    )
                }
            }
            if (scrollable) {
                Spacer(Modifier.height(3.dp))
                Text(
                    "← 这张表有 $cols 列，左右滑动可以看全 →",
                    fontSize = 11.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

/** 一行。格子之间画竖线（没有竖线的表在手机上会串列）。 */
@Composable
private fun MdRow(
    cells: List<String>,
    widths: List<Dp>,
    labelColumn: Boolean = false,
    style: TextStyle,
    numeric: List<Boolean>,
    background: Color,
    line: Color,
    scrollModifier: Modifier,
) {
    Row(
        modifier = Modifier
            .background(background)
            // IntrinsicSize.Min：让格子的竖线能撑满这一行的高度（行高由内容决定）
            .height(IntrinsicSize.Min)
            .then(scrollModifier),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        cells.forEachIndexed { i, cell ->
            Text(
                text = cell,
                style = style,
                // 无表头小表的第一列＝标签列：压暗一档（值才是要读的东西）
                color = if (labelColumn && i == 0) MaterialTheme.colorScheme.onSurfaceVariant
                else MaterialTheme.colorScheme.onSurface,
                textAlign = if (numeric.getOrElse(i) { false }) TextAlign.End else TextAlign.Start,
                modifier = Modifier
                    .width(widths.getOrElse(i) { MinColWidth })
                    .padding(horizontal = CellPadH, vertical = CellPadV),
            )
            if (i < cells.size - 1) {
                Box(Modifier.width(1.dp).fillMaxHeight().background(line))
            }
        }
    }
}

/** 数值格：可选货币符号、千分位、可选小数、可选百分号/单位。判据在 [AiMarkdown.numericColumns]。 */
