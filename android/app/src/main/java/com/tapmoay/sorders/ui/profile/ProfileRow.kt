package com.tapmoay.sorders.ui.profile

import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.ui.common.TintedIcon

/**
 * 「我的」页与「基础设置」页共用的一行：**语义色圆角图标 + 标题(+副标题) + 右侧状态 + `>`**。
 *
 * ## 这是照参考图学来的**卡片样式**（用户 2026-09-21）
 * 三个和旧写法不同的地方，都是有意的：
 * 1. **没有分隔线**。旧版每一行之间画 `HorizontalDivider()`，视觉上是一张"表格"；
 *    参考图那种卡片靠**留白**分行（一行 ≈ 一条 62dp 的实心带）。行与行之间画线会让
 *    "这一页有很多东西"的感觉变强 —— 而这正是用户说「我们按钮太多了」的来源之一。
 * 2. **右侧一律是"当前值/当前状态"**，不是一个空的箭头位。能用一句话说清现在是什么状态的
 *    （消息提醒 → `通知栏提醒 / 后台接收新单`、关于与更新 → `v0.2.3`）就直接写出来，
 *    用户不必点进去才知道；写不出来的才只留箭头。
 * 3. **图标固定 38dp 圆底 / 20dp 图标**。参考图的裸线图标我们不用 —— 本 App 是
 *    「一色一功能」（`ui/theme/Color.kt` 开头那段），换成灰线图标等于把三端的语义色体系
 *    在「我的」这一页开个口子。用户也说了「不要完全的照抄」。
 *
 * ⛔ **行里的副标题该用 `Hint` 还是 `Text`**：说明性句子（"这一格管什么"）走 `Hint`；
 *    数据、状态、警告、空态一律 `Text`（永不隐藏），判据见 `docs/HINT_STYLE.md` §2。
 *
 * @param subtitle 副标题（可空）。传 `null` 就整行只有标题，行高也随之变矮。
 * @param trailing 右侧挂件（文字/开关/进度条…）。**不要**把箭头也塞进来，用 `showChevron`。
 * @param onClick 传 `null` 表示这一行**不可点**（右侧只展示状态）——不要传一个空 lambda，
 *   那会让行有按压反馈却什么都不做。
 */
@Composable
fun ProfileRow(
    icon: ImageVector,
    tint: Color,
    title: String,
    modifier: Modifier = Modifier,
    subtitle: (@Composable () -> Unit)? = null,
    trailing: (@Composable () -> Unit)? = null,
    onClick: (() -> Unit)? = null,
    titleColor: Color? = null,
    showChevron: Boolean = true,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            // ⛔ **点一下不要那个水波纹**（2026-09-22 用户：「他现在**点击圈那个**，
            //    那个会有一种**刷新的感觉**，那个不要有啊，**点进去就是那样子**」）——
            //    所以给一个 `indication = null` 的 clickable：点击照样响应，
            //    但不画扩散的圆。整页的动效只跟**滚动**走（见 `RowMotion`）。
            .then(
                if (onClick != null) {
                    Modifier.clickable(
                        interactionSource = remember { MutableInteractionSource() },
                        indication = null,
                        onClick = onClick,
                    )
                } else {
                    Modifier
                },
            )
            .heightIn(min = 62.dp)
            .padding(start = 18.dp, end = 12.dp, top = 10.dp, bottom = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.Start,
    ) {
        TintedIcon(icon, tint, size = 20.dp, container = 38.dp)
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            // ⚠️ 右侧挂件放在**标题那一行**（不是整行的右侧），副标题因此能独占整行宽度。
            //    2026-09-21 真机抓到：挂在整行右侧时，「消息提醒」那一行的副标题
            //    「语音播报 / 后台接收新单」被右侧状态文字挤成两行、断在「新/单」之间。
            Row(verticalAlignment = Alignment.CenterVertically) {
                // 标题吃剩余宽度（`weight`），右侧挂件用它**自己量出来的宽度** ——
                // 这是 Compose 里"左标题 + 右状态"的标准写法：非加权子项先量，加权的那一个吃剩下的。
                // ⛔ 别写成 `Text(weight(1f, fill = false)) + Spacer(weight(1f))`：
                //    两个加权项平分空间、右边那个不会贴到最右（2026-09-21 试过）。
                Text(
                    text = title,
                    style = MaterialTheme.typography.bodyLarge,
                    color = titleColor ?: MaterialTheme.colorScheme.onSurface,
                    maxLines = 2,
                    modifier = Modifier.weight(1f),
                )
                if (trailing != null) {
                    Spacer(Modifier.width(10.dp))
                    trailing()
                }
            }
            if (subtitle != null) {
                Spacer(Modifier.size(2.dp))
                subtitle()
            }
        }
        if (showChevron) {
            Spacer(Modifier.width(4.dp))
            Icon(
                Icons.AutoMirrored.Filled.KeyboardArrowRight,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.outline.copy(alpha = 0.65f),
                modifier = Modifier.size(22.dp),
            )
        }
    }
}
