package com.tapmoay.sorders.ui.common

import androidx.compose.material3.LocalTextStyle
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.TextUnit
import com.tapmoay.sorders.core.HintPrefs

/**
 * # 界面「提示/说明」的**唯一入口**
 *
 * 用户 2026-09-21 定的规矩，两条：
 *
 * > 「打开就打开**所有的提示相关的内容**，关闭就关闭**所有的提示**，就按我们正常的按钮进行显示。」
 * > 「以后写其他的功能……要写说明或者提示，都要按照这个规范走**统一的接口**。」
 *
 * 所以界面上每一个**文字**只可能是两种身份之一：
 *
 * | 身份 | 用什么写 | 总开关关掉时 |
 * |---|---|---|
 * | **解释句**（"按下去会怎样""为什么这样""去哪找"） | **[Hint]** | **不显示** |
 * | **数据 / 标签 / 状态 / 警告 / 错误** | 照旧 `Text` | **永远显示** |
 *
 * ⛔ **不许**为了省事把数据写成 [Hint] —— 那等于"关掉提示"把用户的**金额、数量、单号、
 *    错误原因**一起关掉了。这条是这套设计里唯一不可犯的错，判据见
 *    `_tools/qa/_check_hints.py`（它会扫出"该走 [Hint] 却还是裸 Text"的解释句，
 *    以及反向那一条：**数据/警告不许走 [Hint]**）。
 *
 * ## 怎么判断一句话算不算"解释句"
 * 三条自问（细则见 `docs/HINT_STYLE.md`）：
 * 1. 把它删掉，用户**还能不能把这件事做完**？能 → 它是解释，走 [Hint]；
 *    不能（它是个数字/状态/报错/按钮后果）→ 它是数据或警告，留 `Text`。
 * 2. 它是在**教**用户（"会自动并成一个"）还是在**报**事实（"共 3 条"）？
 * 3. 它带 `$` 插值（渲染当前值）吗？带 → 一律算数据，留 `Text`。
 *
 * ## 开关从哪来
 * 根上（`MainActivity`）用 [LocalHints] 把**唯一那一份** [HintPrefs] 提供下来 ——
 * 与 `LocalContext` 同一个套路。合成时同步读，所以拨一下开关**所有已打开的页面立刻跟着变**。
 *
 * ⚠️ 没提供时（单测、Preview、忘了在根上提供）**照画**：这套开关是"让界面变干净"的
 *    附加控制，不是安全闸；"文字莫名其妙不见了"比"开关一时不生效"难查得多。
 *    根上到底有没有提供，由红线钉着。
 */
val LocalHints = staticCompositionLocalOf<HintPrefs?> { null }

/**
 * 解释句：**总开关关掉时整句不显示**（[HintPrefs.visible]）。
 *
 * 参数表与 `androidx.compose.material3.Text`(String) **逐一对齐**（含顺序与默认值），
 * 目的就一个：把一处 `Text("…")` 改成 `Hint("…")` 不该牵动别的任何东西 ——
 * 全库那一百多处迁移是**改名**，不是重写。
 *
 * ⚠️ 只覆盖 `String` 那一支。`AnnotatedString` / `buildAnnotatedString {}` 的调用点
 * 不在迁移范围内（它们本来就不是一句话，多半是富文本状态）。
 */
@Composable
fun Hint(
    text: String,
    modifier: Modifier = Modifier,
    color: Color = Color.Unspecified,
    fontSize: TextUnit = TextUnit.Unspecified,
    fontStyle: FontStyle? = null,
    fontWeight: FontWeight? = null,
    fontFamily: FontFamily? = null,
    letterSpacing: TextUnit = TextUnit.Unspecified,
    textDecoration: TextDecoration? = null,
    textAlign: TextAlign? = null,
    lineHeight: TextUnit = TextUnit.Unspecified,
    overflow: TextOverflow = TextOverflow.Clip,
    softWrap: Boolean = true,
    maxLines: Int = Int.MAX_VALUE,
    minLines: Int = 1,
    onTextLayout: ((TextLayoutResult) -> Unit)? = null,
    style: TextStyle = LocalTextStyle.current,
) {
    val prefs = LocalHints.current
    if (prefs != null && !prefs.visible) return
    Text(
        text = text,
        modifier = modifier,
        color = color,
        fontSize = fontSize,
        fontStyle = fontStyle,
        fontWeight = fontWeight,
        fontFamily = fontFamily,
        letterSpacing = letterSpacing,
        textDecoration = textDecoration,
        textAlign = textAlign,
        lineHeight = lineHeight,
        overflow = overflow,
        softWrap = softWrap,
        maxLines = maxLines,
        minLines = minLines,
        onTextLayout = onTextLayout,
        style = style,
    )
}

/**
 * ⛔ **兼容壳，新代码一律直接用 [Hint]** —— 迁移完就删。
 *
 * 原来这里（`Components.kt`）是"每条最多出现 3 次"那套机制：`prefs.hasLeft(key)` 决定画不画、
 * `prefs.markSeen(key)` 记账。用户 2026-09-21 取消了那套机制，改成**一个总开关**，
 * 于是 [key] 与 [prefs] 都没有意义了。
 *
 * 为什么先留壳：还有 6 个调用点在**另一会话正在改的文件**里（`ui/order/OrderDetailScreen.kt`、
 * `ui/shipper/OrderCreateScreen.kt`、`ui/home/WorkbenchScreen.kt`）。
 * 等那些文件收工，把调用点改成 [Hint] 之后，**把这个函数删掉**
 * （而不是让它长期以"两种写法都行"的状态存在 —— 那就是下一个人写成哪种都行的开始）。
 */
@Deprecated("改用 Hint(text, modifier)（总开关见 docs/HINT_STYLE.md）", ReplaceWith("Hint(text, modifier)"))
@Composable
fun HintOnce(prefs: HintPrefs, key: String, text: String, modifier: Modifier = Modifier) {
    // prefs / key 刻意不用：新机制里没有"每条各算各的"这件事（保留形参只为不动调用点）
    Hint(text = text, modifier = modifier)
}
