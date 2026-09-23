package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.Remove
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.VerticalDivider
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tapmoay.sorders.core.InputRules

/**
 * 「数量步进器」与「单位标签」—— **两个数量弹窗唯一共用的一份**
 * （2026-09-23，用户对着数量小窗说的那两句）。
 *
 * ⚠️ 口径说准：全 App 还有**一处**数量加减不在这里 —— `Components.kt::OrderReturnLines`
 * （退货那页的逐行数量编辑：`− 数字 +` 三个**裸**控件、在列表行里、下限是 **0**、
 * 上限是"这一行还能退几件"）。它是**列表行内联编辑器**，不是弹窗里那个描边成组的控件
 * （整组 56dp 高、描边、数字居中），形态与语义都不一样，所以这一轮**没有**合并；
 * 要合并得先确认那一页的行高与"0 起、有可退上限"能不能落在同一个签名上。
 *
 * ## 为什么要有这个文件
 * 用户原话（对着选品页「＋」弹出的那个小窗）：
 * > 「…那个**中间的数字**把它改成**居中**…还有那个 **+- 的样式和图标样式也全部改一下**，
 * > **整体的样貌全都发生改变一下**…非常的不顺眼啊，非常的难受」。
 *
 * 改之前，「`−` + 数量框 + `+`」这一组东西在**两个地方各写了一遍**，而且长得不一样：
 *
 * | | 选品页 `QtyDialog` | 下单页行编辑 `LineEditDialog` |
 * |---|---|---|
 * | `−` / `+` | `FilledTonalIconButton`（淡蓝实心圆，36dp 起） | `FilledTonalIconButton`（**默认色 = 灰紫**实心圆） |
 * | 数量框 | `OutlinedTextField` 92dp，**数字贴左**、右边一大块空地 | `OutlinedTextField` 96dp，**数字贴左** |
 * | 数量判据 | `InputRules.intInput(v, 4)…coerceIn(1, 9999) ?: 1` | **同一串再抄一遍** |
 *
 * `OrderCreateScreen.kt` 里那句注释当时写着「全 App 同一个形态，见 `ProductPicker::QtyDialog`」——
 * 但两边其实是**两份实现**，所以"同一个形态"只是句愿望。这一版把它变成事实：
 * 判据（[typedQty]）、零件（[QtyStepper]）与单位标签（[UnitTag]）都只在这里定义一次。
 *
 * ## 这一版的形态（以及为什么）
 * 1. **一组，不是一个框加两个圆**：外面一个圆角描边（`outline`，**与 `OutlinedTextField`
 *    未聚焦时的描边同色**，所以视觉上是"一个输入控件"），里面竖着两条 `outlineVariant`
 *    分隔线把 `−` / 数量 / `+` 分成三格。三个格子**等高**（[STEP_HEIGHT]）、左右两格等高宽
 *    （[STEP_CELL]），于是不会再有"圆的和方的混在一起"那种不齐。
 * 2. **数字居中**：`textAlign = TextAlign.Center` —— 用户点名的那一条。数字框本身**会随
 *    整组拉伸**（`Modifier.weight(1f)`），所以数量再长（最多 4 位）也不会把 `+` 挤出去。
 * 3. **图标用 `Icons.Rounded.*`**：圆头圆角的 `−` / `+`，与 App 里"苹果式圆角"的形态一致；
 *    原来的 `Icons.Default.*` 是方头粗笔画，放在圆角描边里显硬。禁用时整格转 `outline` 灰
 *    （数量到下限／上限时看得见，而不是点了没反应）。
 * 4. **数量判据只有一份**：见 [typedQty]。
 *
 * ## 单位标签（用户圈出来的那个位置）
 * 用户原话：「…**放在最右边**…那个**显示单位**也就这个商品的单位」。放在**标题行最右边**，
 * 与商品名同一行。⚠️ 它是**只读**的：`QtyDialog` 只收一个 `unit` 字符串用来显示，
 * **不回传、没有输入框**（[UnitTag] 体内没有 `OutlinedTextField`，红线钉着）。
 * 这条与 2026-09-19 用户定的「下单的人不能改单位」**不冲突**——那条禁的是**能改**的入口，
 * 而"看得见单位"恰恰是他这次要的。
 */

/** 数量下限（1 件起：0 件应该走「移除」而不是数量 0）。 */
const val QTY_MIN: Int = 1

/** 数量上限。与 [QTY_DIGITS] 一致：4 位数最多 9999，超了直接不让敲。 */
const val QTY_MAX: Int = 9999

/** 数量最多几位数（[QTY_MAX] 就是 4 位数拉满）。 */
const val QTY_DIGITS: Int = 4

/**
 * 数量框里敲进去的一串字符 → 合法数量。**唯一一份判据**（原来两份是各写一遍的）。
 *
 * 行为（都有单测 `QtyStepperTest`）：
 * - 非数字字符**根本进不来**（走 `InputRules.intInput`，全角数字归一成半角 —— 规则只有那一份实现）；
 *   减号/点儿这类符号是**被丢掉**，不是变成下限（`-5` → `5`）；
 * - 超过 [QTY_DIGITS] 位**按前几位截断**（敲得出 `9999`，敲不出 `99999`）——
 *   这是 `intInput` 的既有语义，不是这一轮定的（这一轮只动了形态，行为一个字没改）；
 * - 空串 / 清空 / `0` → [QTY_MIN]：数量框**永远显示一个合法的数**，不会出现空框；
 *   把空框当成 0 提交的话，订单行会多一条"0 件"的（金额 0、库存不动，谁也不报错）。
 */
fun typedQty(raw: String): Int =
    InputRules.intInput(raw, QTY_DIGITS).toIntOrNull()?.coerceIn(QTY_MIN, QTY_MAX) ?: QTY_MIN

/** 步进器的整组高度（与 `OutlinedTextFieldDefaults.MinHeight` 一致：中间那个框就是 56dp）。 */
private val STEP_HEIGHT = 56.dp

/** `−` / `+` 两格的宽度（高 56 × 宽 52，够 48dp 的最小点击区）。 */
private val STEP_CELL = 52.dp

/** 三个格子的圆角。 */
private val STEP_SHAPE = RoundedCornerShape(14.dp)

/** 数量与加减号一律用这一个蓝（与选品页那个圆「＋」、订单行的数量同色）。 */
private val StepBlue = Color(0xFF1E6FFF)

/**
 * 数量步进器：`−` | 数量 | `+`，一组三格。
 *
 * [onQtyChange] 收到的是**已经夹好的**数量（不会给出 0 或超过 [QTY_MAX] 的值）——
 * 调用方直接存就行，不必再判一遍（再判一遍就是判据的第二份副本）。
 *
 * 宽度：调用方一般给 `Modifier.weight(1f)`（它在 `Row` 里，与左边的「数量」标签并排），
 * 这样整组会随对话框宽度拉伸，数字框永远在**正中间**。
 */
@Composable
fun QtyStepper(
    qty: Int,
    onQtyChange: (Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .height(STEP_HEIGHT)
            .clip(STEP_SHAPE)
            .border(1.dp, MaterialTheme.colorScheme.outline, STEP_SHAPE),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        StepCell(
            icon = Icons.Rounded.Remove,
            label = "减一件",
            enabled = qty > QTY_MIN,
            onClick = { onQtyChange((qty - 1).coerceAtLeast(QTY_MIN)) },
        )
        StepDivider()
        OutlinedTextField(
            value = qty.toString(),
            onValueChange = { onQtyChange(typedQty(it)) },
            singleLine = true,
            textStyle = MaterialTheme.typography.titleMedium.copy(
                fontWeight = FontWeight.Bold,
                color = StepBlue,
                // ⚠️ 用户 2026-09-23 点名的那一条：原来的数字贴在框的左边（右边一大块空地）。
                textAlign = TextAlign.Center,
            ),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            // 描边由外面那一组负责（整组一个圆角框）；这里把自带描边与光标外的颜色都让开，
            // 否则中间会多出一个"框里的框" —— 那正是用户说的"不顺眼"。
            colors = OutlinedTextFieldDefaults.colors(
                focusedBorderColor = Color.Transparent,
                unfocusedBorderColor = Color.Transparent,
                disabledBorderColor = Color.Transparent,
                cursorColor = StepBlue,
            ),
            modifier = Modifier
                .weight(1f)
                .fillMaxHeight(),
        )
        StepDivider()
        StepCell(
            icon = Icons.Rounded.Add,
            label = "加一件",
            enabled = qty < QTY_MAX,
            onClick = { onQtyChange((qty + 1).coerceAtMost(QTY_MAX)) },
        )
    }
}

/** 组内的一条竖分隔线（跟着整组高度拉满）。 */
@Composable
private fun StepDivider() {
    VerticalDivider(
        modifier = Modifier.fillMaxHeight(),
        thickness = 1.dp,
        color = MaterialTheme.colorScheme.outlineVariant,
    )
}

/** `−` / `+` 其中一格。禁用时图标转灰（看得见"到下限了"，不是点了没反应）。 */
@Composable
private fun StepCell(
    icon: ImageVector,
    label: String,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    Box(
        modifier = Modifier
            .fillMaxHeight()
            .width(STEP_CELL)
            .clickable(enabled = enabled, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            imageVector = icon,
            contentDescription = label,
            // 禁用的那一格**仍然画得出来**（只是发灰）：整组是描边形态，
            // 少画一个图标会变成"这一格坏了"。
            tint = if (enabled) StepBlue else MaterialTheme.colorScheme.outline,
            modifier = Modifier.size(22.dp),
        )
    }
}

/**
 * 单位标签（数量小窗标题行最右边那个）。
 *
 * ⛔ **只读**：它长成一个描边小标签，**不是**输入框、也不接任何点击
 * （红线 `_check_qty_dialog_style.py` 钉着"体内不许出现 `OutlinedTextField`"）。
 * 单位能改的地方只有一个 —— 派单员在「商品管理 → 编辑商品」里选（`UnitPickerSheet`）。
 */
@Composable
fun UnitTag(unit: String, modifier: Modifier = Modifier) {
    val text = unit.trim()
    // 空单位**不画**（也不兜底成「件」）：兜底是商品那一侧 `unitOrDefault` 的事，
    // 调用方已经兜过一次，这里再兜一次就是同一件事两份判据（见 `Units.kt` 顶上那段）。
    if (text.isEmpty()) return
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(8.dp),
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
    ) {
        Text(
            text = text,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 3.dp),
            style = MaterialTheme.typography.labelLarge.copy(fontSize = 13.sp),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = 1,
        )
    }
}
