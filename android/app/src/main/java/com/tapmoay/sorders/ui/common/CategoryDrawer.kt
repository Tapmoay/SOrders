package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp

/**
 * 「按分类看」抽屉里的一格（[CategoryDrawerSheet] 的数据形状）。
 *
 * [key] 沿用全库同一套约定（出处见 `ui/shipper/AddressViewModel.kt::contactRailKey`）：
 * `""` = 全部、`"c|<分类名>"` = 某一类。抽屉末尾那行动作的 `"manage"` 由零件自己加，
 * **不要**混进这个列表里（否则会跟真分类抢同一个 key）。
 */
data class CategoryDrawerItem(val key: String, val label: String)

/**
 * 分类入口：一行标题里的那颗小胶囊（「全部」/ 某个分类名 + 一个下拉箭头）。
 *
 * 为什么不做成常驻左栏：用户否掉的正是商品管理那种布局 ——
 * 「商品管理的话，那样子的布局导致了右边的卡片的信息被挤压了不是很好看」。
 * 所以这里只占一行里的一小块，真正的分类列表在点开后的左侧抽屉（[CategoryDrawerSheet]）里。
 *
 * ⚠️ 颜色只染图标、不染字：分类名长短不一，染成一片彩色反而看不出哪一段是数据
 * （见 `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md`「一色一功能」）。
 */
@Composable
fun CategoryTriggerChip(
    current: String,
    accent: Color,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        onClick = onClick,
        color = accent.copy(alpha = 0.12f),
        shape = MaterialTheme.shapes.small,
        // 长分类名不许把这一行右边的「新增 X」挤出去
        modifier = modifier.widthIn(max = 132.dp),
    ) {
        Row(
            Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                Icons.Default.Folder,
                contentDescription = null,
                tint = accent,
                modifier = Modifier.size(15.dp),
            )
            Spacer(Modifier.width(5.dp))
            Text(
                if (current.isBlank()) "全部" else current,
                style = MaterialTheme.typography.labelLarge,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Icon(
                Icons.Default.ArrowDropDown,
                contentDescription = null,
                tint = accent,
                modifier = Modifier.size(18.dp),
            )
        }
    }
}

/**
 * 左侧抽屉里的分类列表：一趟「全部」+ 每个分类 + 末尾一行「管理分类」。
 *
 * 挂在 `ModalNavigationDrawer` 的 `drawerContent = { ModalDrawerSheet { … } }` 里用
 * （挂法照 `ui/dispatcher/FreightSettlementScreen.kt`：选中/进管理时 `scope.launch { drawer.close() }`）。
 *
 * ⛔ 每一格**都不显示条数**：用户 2026-09-19 对左栏的裁定是
 * 「那个分组下面不要显示有多少条啊，这是多余信息」。要看影响面去管理面板（删之前那一步）。
 */
@Composable
fun CategoryDrawerSheet(
    title: String,
    items: List<CategoryDrawerItem>,
    selectedKey: String,
    accent: Color,
    manageLabel: String,
    onPick: (String) -> Unit,
    onManage: () -> Unit,
) {
    Column(
        Modifier
            .fillMaxSize()
            .padding(horizontal = 16.dp),
    ) {
        Spacer(Modifier.height(20.dp))
        Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(6.dp))
        Hint("选一类只看这一类；不选就是全部。")
        Spacer(Modifier.height(6.dp))
        LazyColumn(Modifier.weight(1f)) {
            items(items, key = { it.key }) { item ->
                CategoryDrawerRow(
                    label = item.label,
                    selected = item.key == selectedKey,
                    accent = accent,
                    onClick = { onPick(item.key) },
                )
            }
            item(key = "manage") {
                HorizontalDivider(Modifier.padding(vertical = 4.dp))
                CategoryDrawerRow(
                    label = manageLabel,
                    selected = false,
                    accent = accent,
                    icon = Icons.Default.Settings,
                    onClick = onManage,
                )
            }
        }
        Spacer(Modifier.height(12.dp))
    }
}

@Composable
private fun CategoryDrawerRow(
    label: String,
    selected: Boolean,
    accent: Color,
    onClick: () -> Unit,
    icon: ImageVector? = null,
) {
    Row(
        Modifier
            .fillMaxWidth()
            .height(48.dp)
            .clickable(onClick = onClick),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            label,
            style = MaterialTheme.typography.bodyLarge,
            fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal,
            color = if (selected) accent else MaterialTheme.colorScheme.onSurface,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f),
        )
        if (selected) {
            Icon(
                Icons.Default.Check,
                contentDescription = "已选中",
                tint = accent,
                modifier = Modifier.size(18.dp),
            )
        }
        if (icon != null) {
            Icon(
                icon,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(18.dp),
            )
        }
    }
}
