package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material3.Icon
import androidx.compose.material3.LocalTextStyle
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp

/**
 * # 表单行的**唯一一套**（2026-09-21 商品管理改版第 1 期，P7）
 *
 * ## 它长什么样、为什么这么长
 * 用户 2026-09-21 对着一份 POS「新增商品」的截图说：
 * > 「这是他的新建商品的界面，我们也改一下我们的新建商品的界面——**不是很好看，也太乱了**。
 * >   …他有的没必要的东西嘛，不要加，我们按照我们的来就行了，**只是照抄他的样式**。」
 *
 * 那一页的每一行都是同一个形态：**标签在左、值在右、能进二级的带一个 `>`**，
 * 而且**整页一个输入框边框都没有** —— 框只在点进去那一刻才出现。
 *
 * 我们原来那一屏"乱"的根因就是**三层框叠在一起**：
 * ① 三个 `OutlinedTextField` 各自带边框 + 浮动 `label`（一屏三个矩形框）；
 * ② 外面又套着 `SectionCard` 的卡片描边（框里还有框）；
 * ③ 每个字段下面再跟一到两句灰字说明。
 * 换成这一套行之后 ①③ 同时消失：**"值即占位符"的形态本身就不需要那么多解释句**。
 *
 * ## 一行是什么
 * | 组件 | 用在 |
 * |---|---|
 * | [FormGroup] | **分组白卡**：卡外一行小字组标题 + [SectionCard] 白卡（卡里只放下面这几种行） |
 * | [FormInputRow] | 就地输入（值靠右对齐；空的时候把提示画成右对齐的灰字） |
 * | [FormTextAreaRow] | **长文本**（地址 / 备注）：标签在第一行、值在它下面占满整宽 |
 * | [FormPickRow] | 点进去二级选择（值 + `>`） |
 * | [FormActionRow] | 点进去**做一件事**（标签 + `>`，右边没有值） |
 * | [FormSwitchRow] | 开关 |
 *
 * ## ⚠️ 三条纪律
 * 1. **分组仍用 `SectionCard`**（白卡分段），行本身**不画分隔线** —— 靠留白分行。
 *    这是用户同一批参考图里"大圆角卡片列表"的形态（另一位会话在「我的」页也按它改了）。
 *    ⛔ 2026-09-22 用户把它升级成**全局规范**：「只是用线框框起来的话太不美观了，
 *    而且也不够醒目对比，所以把他们改进这种**白色的卡片样式**…**这就是个设计规范，
 *    包括以后也是这样子啊，所有都要这样子去改**」—— 判据 `_tools/qa/_check_form_panel_style.py`
 *    （已改过的页面里 `OutlinedTextField` 必须为 0，且全库总数**只许减不许增**）。
 * 2. **必填用 `required = true` 画那个红 `*`**，不要写进标签文字里（"商品名称（必填）"那种）：
 *    参考图就是一颗红星，而括号里的"（必填）"会被读成说明句、被提示总开关关掉。
 * 3. 这不是"选择类弹层"的替代品：**能进二级的仍然进二级**（单位、分类），
 *    不要为了少一跳把一列选项摊在表单里（设计规范 §5）。
 */

/**
 * **分组白卡**：卡外一行小字组标题（可带一个语义色小图标）+ [SectionCard] 白卡。
 *
 * 用户 2026-09-22 把它定成全局规范（设计系统 §5.0）：**分组一律白卡，不许用描边框当分组**。
 *
 * ⚠️ 组标题**在卡外**（iOS 分组列表的形态）：放进卡里就又多一条"框里的标题行"，
 * 而这一轮要消灭的正是"框套框"。
 * ⚠️ 卡里**只放**这个文件里的那几种行 —— 一个描边输入框都不许有
 * （判据 `_tools/qa/_check_form_panel_style.py`）。
 * ⚠️ 全库**只此一处**：各页自己写一份 `FormGroup` 就等于"白卡的间距/标题样式每页一个样"。
 */
@Composable
fun FormGroup(
    icon: ImageVector,
    title: String,
    tint: Color,
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(modifier) {
        Row(
            Modifier.padding(start = 6.dp, bottom = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(icon, contentDescription = null, tint = tint, modifier = Modifier.size(15.dp))
            Spacer(Modifier.width(6.dp))
            Text(title, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        SectionCard(content = content)
    }
}

/**
 * 一行"标签 + 右侧任意内容"。
 *
 * ## ⚠️ 每一行**自己就是一张卡**（2026-09-22 用户第二轮要求）
 * 原话：「你卡片是加出来的，但是里面的**线框**还是搞一下吧。也不说搞线框吧，而是说，
 * 在**内嵌卡片**——就是**卡片内嵌卡片**，就是每个选择就相当于一个、**每个输入相当于卡片**」。
 * 所以：分组仍是白卡（[FormGroup]），**卡里每一行再套一张"浅色内嵌卡"**
 * （`surfaceContainerLow` + 圆角 12，**不画边框**）—— 一眼能看出"这里有 N 个可以填/可以点的东西"。
 *
 * ## ⚠️ 图标与语义色**不许省**（同一条消息的前半句）
 * 原话：「现在的新卡片样式对应的**图标和（语）义色不能去掉**啊。**该有的还是得有的**」。
 * 所以这一行有 [icon] / [iconTint]：原来那些 `OutlinedTextField(leadingIcon = …)` 里的
 * 图标与色（人=湖蓝、地点=橙、电话=绿…）必须**跟着搬过来**，不能因为"换成共用行了"就丢。
 *
 * @param required 画那颗红星。**只是画** —— 校验必须由调用方（与后端）真的做，
 *   否则就是"标注了必填却让你存下去"。
 * @param onClick 整行可点（不给就是纯展示行）
 */
@Composable
fun FormRow(
    label: String,
    modifier: Modifier = Modifier,
    required: Boolean = false,
    icon: ImageVector? = null,
    iconTint: Color = Color.Unspecified,
    onClick: (() -> Unit)? = null,
    content: @Composable RowScope.() -> Unit,
) {
    Surface(
        modifier = modifier.fillMaxWidth().padding(vertical = 4.dp),
        shape = MaterialTheme.shapes.medium,
        color = MaterialTheme.colorScheme.surfaceContainerLow,
    ) {
        Row(
            Modifier
                .fillMaxWidth()
                .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
                .padding(horizontal = 14.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (icon != null) {
                Icon(
                    icon,
                    contentDescription = null,
                    tint = if (iconTint == Color.Unspecified) MaterialTheme.colorScheme.onSurfaceVariant else iconTint,
                    modifier = Modifier.size(18.dp),
                )
                Spacer(Modifier.width(8.dp))
            }
            if (required) {
                Text(
                    "*",
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.padding(end = 4.dp),
                )
            }
            Text(label, style = MaterialTheme.typography.bodyLarge)
            Spacer(Modifier.width(12.dp))
            Box(Modifier.weight(1f), contentAlignment = Alignment.CenterEnd) {
                Row(verticalAlignment = Alignment.CenterVertically, content = content)
            }
        }
    }
}

/**
 * 就地输入那一行：[value] 靠右；[value] 为空时把 [placeholder] 画成右对齐的灰字
 * （参考图里"请输入商品名(50字以内)"就是这么放的）。
 *
 * ⚠️ **整行都能点**（点标签也聚焦到输入框）—— 真机上试出来的：第一版只在右边那一块放了
 * `BasicTextField`，于是点「售价」这个**标签**没有任何反应（标签是个不可点的 `Text`，
 * Compose 不会把点击透传给旁边的兄弟节点），用户会以为这一行不能填。
 * 参考图那一页也是整行可点，所以这里给整行挂 `clickable` + `FocusRequester`。
 */
@Composable
fun FormInputRow(
    label: String,
    value: String,
    onValueChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    placeholder: String = "请输入",
    required: Boolean = false,
    enabled: Boolean = true,
    keyboardType: KeyboardType = KeyboardType.Text,
    icon: ImageVector? = null,
    iconTint: Color = Color.Unspecified,
) {
    val focus = remember { FocusRequester() }
    FormRow(
        label = label,
        modifier = modifier,
        required = required,
        icon = icon,
        iconTint = iconTint,
        onClick = if (enabled) ({ focus.requestFocus() }) else null,
    ) {
        Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterEnd) {
            if (value.isEmpty() && enabled) {
                Text(
                    placeholder,
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            BasicTextField(
                value = value,
                onValueChange = onValueChange,
                enabled = enabled,
                singleLine = true,
                textStyle = LocalTextStyle.current.merge(
                    MaterialTheme.typography.bodyLarge.copy(
                        color = if (enabled) MaterialTheme.colorScheme.onSurface
                        else MaterialTheme.colorScheme.onSurfaceVariant,
                        textAlign = TextAlign.End,
                    ),
                ),
                keyboardOptions = KeyboardOptions(keyboardType = keyboardType),
                cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
                modifier = Modifier.fillMaxWidth().focusRequester(focus),
            )
        }
    }
}

/**
 * 点进去二级选择那一行：右边是**当前值**（空则显示 [placeholder]），再加一个 `>`。
 *
 * ⚠️ `>` 只在这条**真的能点进去**时才画（[onClick] 非空）—— 画了箭头却没有下一页，
 * 是让人反复去点的一个假入口。
 */
@Composable
fun FormPickRow(
    label: String,
    value: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    placeholder: String = "请选择",
    required: Boolean = false,
    icon: ImageVector? = null,
    iconTint: Color = Color.Unspecified,
) {
    FormRow(
        label = label,
        modifier = modifier,
        required = required,
        icon = icon,
        iconTint = iconTint,
        onClick = onClick,
    ) {
        Text(
            value.ifBlank { placeholder },
            style = MaterialTheme.typography.bodyLarge,
            color = if (value.isBlank()) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.onSurface,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Spacer(Modifier.width(6.dp))
        Icon(
            Icons.AutoMirrored.Filled.KeyboardArrowRight,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.outline,
            modifier = Modifier.size(18.dp),
        )
    }
}

/** 开关那一行。 */
@Composable
fun FormSwitchRow(
    label: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    icon: ImageVector? = null,
    iconTint: Color = Color.Unspecified,
) {
    FormRow(label = label, modifier = modifier, icon = icon, iconTint = iconTint) {
        Switch(checked = checked, onCheckedChange = onCheckedChange, enabled = enabled)
    }
}

/**
 * 点进去**做一件事**的那一行（不是选值）：标签在左、右边只有一个 `>`。
 *
 * 与 [FormPickRow] 的区别是"右边有没有值"：选值那行的意思是"**现在是这个**，点进去换"，
 * 而这一行的意思是"**点它会发生一件事**"（从地点库挑一个、去地图上选点）。
 * 做成两行而不是给 [FormPickRow] 加个开关：值那一栏空着还画一个 `>`，读起来像"值是空的"。
 */
@Composable
fun FormActionRow(
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    icon: ImageVector? = null,
    iconTint: Color = Color.Unspecified,
) {
    FormRow(
        label = label,
        modifier = modifier,
        icon = icon,
        iconTint = iconTint,
        onClick = if (enabled) onClick else null,
    ) {
        Icon(
            Icons.AutoMirrored.Filled.KeyboardArrowRight,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.outline,
            modifier = Modifier.size(18.dp),
        )
    }
}

/**
 * **长文本**那一行（地址 / 备注 / 说明）：标签在第一行，值在它**下面**、占满整宽、左对齐。
 *
 * ⚠️ 为什么不是"标签在左、值在右"：地址是**一段话**（"博罗区园洲镇振兴大道136号之一"），
 * 塞进右边半栏会折成三四行、每行两三个字，比原来的多行输入框还难读。
 * 所以这一行是 [FormRow] 家族里**唯一**上下排的形态 —— 它不是"另一种风格"，
 * 是"标签 + 段落"这件事只能这么排。
 *
 * ⚠️ 整行都能点（与 [FormInputRow] 同一条理由：点标签也要能聚焦，否则用户以为这行不能填）。
 */
@Composable
fun FormTextAreaRow(
    label: String,
    value: String,
    onValueChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    placeholder: String = "请输入",
    required: Boolean = false,
    minLines: Int = 2,
    enabled: Boolean = true,
    icon: ImageVector? = null,
    iconTint: Color = Color.Unspecified,
) {
    val focus = remember { FocusRequester() }
    // 与 [FormRow] 一样：**这一行自己也是一张（内嵌）卡**
    Surface(
        modifier = modifier.fillMaxWidth().padding(vertical = 4.dp),
        shape = MaterialTheme.shapes.medium,
        color = MaterialTheme.colorScheme.surfaceContainerLow,
    ) {
    Column(
        Modifier
            .fillMaxWidth()
            .then(if (enabled) Modifier.clickable { focus.requestFocus() } else Modifier)
            .padding(horizontal = 14.dp, vertical = 12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (icon != null) {
                Icon(
                    icon,
                    contentDescription = null,
                    tint = if (iconTint == Color.Unspecified) MaterialTheme.colorScheme.onSurfaceVariant else iconTint,
                    modifier = Modifier.size(18.dp),
                )
                Spacer(Modifier.width(8.dp))
            }
            if (required) {
                Text(
                    "*",
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.padding(end = 4.dp),
                )
            }
            Text(label, style = MaterialTheme.typography.bodyLarge)
        }
        Spacer(Modifier.height(6.dp))
        Box(Modifier.fillMaxWidth()) {
            if (value.isEmpty() && enabled) {
                Text(
                    placeholder,
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = minLines,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            BasicTextField(
                value = value,
                onValueChange = onValueChange,
                enabled = enabled,
                minLines = minLines,
                textStyle = LocalTextStyle.current.merge(
                    MaterialTheme.typography.bodyLarge.copy(
                        color = if (enabled) MaterialTheme.colorScheme.onSurface
                        else MaterialTheme.colorScheme.onSurfaceVariant,
                    ),
                ),
                cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
                modifier = Modifier.fillMaxWidth().focusRequester(focus),
            )
        }
    }
    }
}
