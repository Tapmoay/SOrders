package com.tapmoay.sorders.ui.common

import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * **「一行放不下」时全 App 唯一的一份处理规则**（2026-09-22 用户定调 + 官方文档校正）。
 *
 * ## 为什么不能"按屏宽等比缩放字号"（用户最初的直觉，已被这条规则取代）
 *
 * 用户原话：「所有卡片样式要根据手机的不同的大小来做一个适配……比如说就是正常的一种缩放吧，svg 啊的一种形式」，
 * 紧接着自己把它改掉了：「我们的小屏**整体的样式是不能有改变的**……甚至那个小屏啊，我发现，我们这些
 * **字体都已经看不清了**……**他不可能每度做一遍**吧」。
 *
 * 三条一起定下来，每条都有官方出处 —— **别照直觉改**：
 *
 * 1. ⛔ **不做"设计稿宽度缩放"**（把 dp/sp 乘上 `屏宽/设计稿宽` 那种，社区叫 AutoSize）。
 *    [窗口大小类别](https://developer.android.com/develop/ui/compose/layouts/adaptive/use-window-size-classes)
 *    把 **宽度 < 600dp 的手机竖屏全部算作同一档（紧凑）**，断点只有 600 / 840 / 1200 / 1600。
 *    也就是说：**手机之间本来就不该做出两套版式**，"每个机型适配一遍"从规范上就是错的。
 * 2. ⛔ **不缩小字号**。[网格和单位](https://developer.android.com/design/ui/mobile/guides/layout-and-content/grids-and-units)
 *    写明 dp 的职责是"跨屏幕物理尺寸一致"、**sp 的职责就是跟随用户的字体设置**；
 *    [Android 14 起](https://developer.android.com/about/versions/14/features)系统支持字体放大到 **200%**，
 *    引入非线性曲线的唯一原因就是"别让大号文本被截断"。把老人特意调大的字压回去，与这条正好相反。
 * 3. ⛔ **不截断** —— 尤其是档位/状态这种"少一个字就变成另一个意思"的词
 *    （真机实测踩到：「已接单」被截成「**已接**」、「已送达」被截成「**已送**」，用户分不出这两档）。
 *
 * → 于是"放不下"只剩两条路：**换到下一行**，或**整条横向滑动**。
 *   两种做法都要求先知道"到底放不放得下"——[rememberTextWidth] 就是那把尺。
 *
 * ## 为什么用实测而不是按字数估算
 *
 * 中文字宽约等于一个字身，数字/字母只有 0.5~0.6 个字身，再叠加字重、字体与**系统字号**的差异 ——
 * 估出来的宽度迟早会在某一档上算错，而算错的后果是"该换行的时候没换行"（正是要修的那类 bug）。
 */

/** 一行里两个元素之间的标准间隔。判定"放不放得下"与真正排版必须用**同一个数**。 */
val ROW_ITEM_GAP: Dp = 8.dp

/**
 * 量出 [text] 在 [style] 下的**单行自然宽度**。
 *
 * ⚠️ 调用点必须把它传给**同一个** style 实例或等价的 style：`Text(x, style = s)` 与
 * `rememberTextWidth(x, s)` 用的必须是同一份（含 `fontWeight`）—— 所以下面几个调用点都是
 * 先把 style `copy(...)` 成一个局部变量，再同时喂给两边，避免两处各自漂移。
 *
 * ⚠️ 只能在**组合期**、且**不在条件分支里**调用（`remember` 的槽位要求）：
 * `forEach` / `fold` / `sumOf` 是 inline 函数，可以在里面调；`map` 不是，**别用 `map`**。
 */
@Composable
fun rememberTextWidth(text: String, style: TextStyle): Dp {
    val measurer = rememberTextMeasurer()
    val density = LocalDensity.current
    // density 里带着 fontScale：用户改系统字号后 key 随之变化 → 自动重新测量（这正是要的）
    return remember(text, style, density) {
        with(density) { measurer.measure(text, style).size.width.toDp() }
    }
}
