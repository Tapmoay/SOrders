package com.tapmoay.sorders.ui.common

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
import androidx.compose.material.icons.filled.Apps
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
 * 分类抽屉**半展开**的宽度：240dp（约屏宽的 2/3）。
 *
 * M3 的 `ModalDrawerSheet` 默认几乎顶满整屏（360dp 屏上约 304dp ≈ 84%），而分类抽屉里
 * 通常只有一两格（「全部」+ 一两个分类），于是右边什么都看不见、下面一大片空 ——
 * 用户 2026-10-05 的原话：「全部展开的话，他属于啊内容又比较短太空旷了我们可以搞一个半展开」。
 *
 * 240dp 的两条理由：① 右边留出可见的列表，点分类时**能立刻看到卡片跟着筛**，不用先关抽屉；
 * ② 比既有先例 `ui/ai/AiChatScreen.kt:142 DrawerWidth = 300.dp` 窄一档 —— 那边是聊天记录
 * （一行字多），这边是一列分类名（一格两个字），240 够放最长的那类名。
 *
 * ⛔ **选人抽屉不吃这条**：结算页 / 账本页那种带搜索框 + 副标题的选人抽屉内容多，
 * 保持 `ModalDrawerSheet` 的默认宽度（别顺手统一，那几处另有判据钉着）。
 */
val CategoryDrawerWidth = 240.dp
/**
 * 「按分类看」抽屉里的一格（[CategoryDrawerSheet] 的数据形状）。
 *
 * [key] 沿用全库同一套约定（出处见 `ui/shipper/AddressViewModel.kt::contactRailKey`）：
 * `""` = 全部、`"c|<分类名>"` = 某一类。抽屉末尾那行动作的 `"manage"` 由零件自己加，
 * **不要**混进这个列表里（否则会跟真分类抢同一个 key）。
 */
data class CategoryDrawerItem(
    val key: String,
    val label: String,
    /**
     * 缩进级数：0 = 大类、1 = 子类（2026-10-11 CHG-0112：账户管理页的左栏是两级）。
     * 默认 0 —— 地址与联系人、车辆那几份名册都是平表，一个字都不用改。
     */
    val depth: Int = 0,
)

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
        // 常驻文案压到 8 字：「半展开」的抽屉只有 240.dp 宽，16 字那句会折成两行、把第一格
        // 往下顶。规范 §4.10「常驻文案最多 7 到 8 个字」。
        Hint("选一类只看这一类")
        Spacer(Modifier.height(6.dp))
        LazyColumn(Modifier.weight(1f)) {
            items(items, key = { it.key }) { item ->
                CategoryDrawerRow(
                    label = item.label,
                    selected = item.key == selectedKey,
                    accent = accent,
                    // 「全部」用九宫格、真分类用文件夹：一眼分清"这是复位"还是"这是一类"
                    icon = if (item.key.isEmpty()) Icons.Default.Apps else Icons.Default.Folder,
                    depth = item.depth,
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
    /** 缩进级数（0 = 大类、1 = 子类）；只有账户管理那份名册会传 1。 */
    depth: Int = 0,
) {
    // 选中那格给自己一个浅色底（只有字变色时，一列里"选中的是哪一格"要靠读字才知道；
    // 底色是 `accent.copy(alpha = 0.12f)`，与 `CategoryTriggerChip` 同一口径 —— 一色一功能）
    Surface(
        onClick = onClick,
        shape = MaterialTheme.shapes.small,
        color = if (selected) accent.copy(alpha = 0.12f) else Color.Transparent,
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 2.dp),
    ) {
        Row(
            Modifier
                .fillMaxWidth()
                .height(48.dp)
                .padding(horizontal = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            // 子类缩进一级（2026-10-11 CHG-0112）：**不做展开箭头、不做动画** ——
            // 用户要的是「一眼看出谁在谁下面」，展开/收起反而多一次点击
            // （他的原话是「假如他没有那么多分类吗？一堆的话到时候查起来非常麻烦」，要的是少翻找）。
            if (depth > 0) Spacer(Modifier.width((18 * depth).dp))
            // 图标在**最左**：一列分类的图标要对齐成一条线，人才扫得快
            // （原来画在右端，跟选中的对勾抢同一个位置）
            if (icon != null) {
                Icon(
                    icon,
                    contentDescription = null,
                    tint = if (selected) accent else MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(16.dp),
                )
                Spacer(Modifier.width(10.dp))
            }
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
        }
    }
}
