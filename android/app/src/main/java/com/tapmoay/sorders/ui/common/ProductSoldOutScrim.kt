package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

/**
 * 「沽清 = 整卡变灰」的两个数值 —— **全库唯一一份定义**。
 *
 * ## 这条口径是谁定的
 * 用户 2026-10-07 在下单页选品弹层上定的（台账 L-35 / `BUG-0017`，ref `m01347`，逐字）：
 * > 「灰掉了之后**就不能点**的哈……就是**整卡变灰**嘛……就是**拦住不让下**，
 * >  不可能是提示后他仍然可以下呀。」
 *
 * 2026-10-10 他在**商品管理页**又提了一次（台账 L-66 / `CHG-0103`，ref `m05399`，逐字）：
 * > 「顺便参考他这个样式啊，我们现在的商品管理。如果估清了。他那个卡片只会有一个沽清的状态，
 * >  但是并没有整体变灰的样式啊参考。他的样式啊，他当时就有一个整体变灰的变动啊啊，改一下吧。」
 *
 * ## 为什么这两个数字要单独有一个文件
 * 它们坏起来**不报错、不崩溃、界面照样能点**：`0.45f` 被写成 `0.95f` 是"几乎看不见灰"、
 * 被写成 `0.05f` 是"整张卡糊成一团"，而两种都编译得过、单测也照样绿。数值放在谁都能引的
 * 一个地方，`_tools/qa/_check_sold_out_card_grey.py` 才能一条一条钉住它们，
 * 而不是去猜某个页面里的字面量。
 *
 * ## 现在是"两个文件各一份值"，不是"两个页面各一套样式"
 * 已经上线的那一份在 `ui/common/ProductPicker.kt`（选品弹层），它是 `BUG-0017` 落地时
 * 直接写在 `ProductRow` 里的。本次（`CHG-0103`）**没有把它改过来** —— 那个文件当时正被
 * 另一笔配色变更（`CHG-0102`）改着，同时动它会撞车。
 *
 * 所以现状是：**取值同一套，代码两个文件**。判据 `_tools/qa/_check_sold_out_card_grey.py`
 * 拿本文件的数字去对 `ProductPicker.kt` 里那一份（两处对不上就红）。
 * 等 `CHG-0102` 落地、`ProductPicker.kt` 不再被并行改时，把那个字面量换成这里的常量即可
 * —— **后续可以合并到哪：就是本文件，`ProductPicker.kt::ProductRow`**。
 *
 * 本文件**只依赖 Compose**（不 import `android.*`），所以它同时能被单测直接引用。
 */

/**
 * 整卡变灰时垫在卡片底下那一层的底色 —— 压到 45% 的 `surfaceVariant`。
 *
 * 不能用某个写死的灰代替：`surfaceVariant` 在浅色主题与深色主题下是**两个不同的值**，
 * 写死一个灰会在深色主题里变成"卡片比别人亮"。半透明的同一份色叠在两种主题各自的
 * `surface` 上，两边都是"比自己周围暗一档"。
 */
@Composable
fun productSoldOutCardColor(): Color =
    MaterialTheme.colorScheme.surfaceVariant.copy(alpha = PRODUCT_SOLD_OUT_SURFACE_ALPHA)

/** [productSoldOutCardColor] 里那个透明度：压得太轻看不出、压得太重整卡糊成一团。 */
const val PRODUCT_SOLD_OUT_SURFACE_ALPHA: Float = 0.45f

/**
 * 整卡变灰时，卡上**内容**（图 / 名称 / 数字 / 三个按钮 / 角标）一起降到的不透明度。
 *
 * 为什么内容也要跟着暗、而不只换底色：用户说的是「**整体**变灰」—— 只换底色的话，
 * 白底按钮和红字在新底色上反而更刺眼，"哪几个动作还点得动"这件事看不出区别（参考图里
 * 「取消沽清」那颗就是暗的）。0.6 与选品弹层那一份**同值**，见文件头那段"两个文件各一份值"。
 */
const val PRODUCT_SOLD_OUT_CONTENT_ALPHA: Float = 0.6f

/**
 * 已经沽清的那张商品卡的**卡壳**：灰底 + 圆角 + 细描边，内容在 `content` 里照常按白卡画。
 *
 * 用法就是"把原来直接写 `SectionCard { … }` 的地方整个包进来"：
 *
 * ```kotlin
 * ProductSoldOutCard(soldOut = !p.isActive) {
 *     SectionCard { …原样… }
 * }
 * ```
 *
 * ⚠️ 为什么是包在**外面**、而不是给 `SectionCard` 塞一个 `containerColor` 参数：
 * `SectionCard`（`ui/common/Components.kt`）是另外十几张卡共用的件，为了这一种状态
 * 给它开一个参数，等于让每个调用点都要想一次"这里该传什么色"。包一层则**新旧调用点
 * 一个字都不用改**，而且能被本文件的判据独立钉住。
 *
 * ⚠️ 圆角取 12dp 是为了与 `SectionCard` 的 `shapes.medium` 对齐 —— 包层比内层更圆或更方，
 * 四角都会露出一圈"第二张卡"的边。
 *
 * @param soldOut `false` = 在售：**一个像素都不变**（这是本函数最要紧的性质 ——
 *   在售的卡不许被这一层顺手改掉，所以那一支里连 alpha 都不挂）。
 */
@Composable
fun ProductSoldOutCard(
    soldOut: Boolean,
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    if (!soldOut) {
        Column(modifier = modifier, content = content)
        return
    }
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        color = productSoldOutCardColor(),
        tonalElevation = 0.dp,
        shadowElevation = 1.dp,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
    ) {
        // ⚠️ 这一层是 Box 而**不是** Column：`SectionCard` 自己就是一张填满宽度的卡，
        //    外面再套一个 Column 会多出一次纵向测量，真机上表现为卡片高度抖一下。
        //    alpha 挂在 Box 上 = 整棵子树一起暗（图 / 名 / 数字 / 三个按钮 / 角标同一档）。
        Box(Modifier.alpha(PRODUCT_SOLD_OUT_CONTENT_ALPHA)) {
            Column(content = content)
        }
    }
}
