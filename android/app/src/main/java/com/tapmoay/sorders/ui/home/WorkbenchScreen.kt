package com.tapmoay.sorders.ui.home

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.ui.common.RoleBadge
import com.tapmoay.sorders.ui.nav.ModuleEntry
import com.tapmoay.sorders.ui.nav.Modules
import com.tapmoay.sorders.ui.nav.Role

/**
 * 工作台：**卡片 + 图标网格**（像手机桌面，每个图标=一个功能）。
 *
 * ⚠️ **只有一张卡片**。2026-09-20 曾经短暂做过"派单端两张卡片"（第二张装账本那 8 件事），
 * 当天就被用户推翻了：「派单员的那个工作台全部改一下，**改回原来的样式**」——
 * 那 8 件事改成一个「账本管理」入口页（报表中心那种形式），已经收进 `dispatcherEntries` 里的一格。
 * ⛔ 别再往这里加第二张卡片：网格能装下的东西，分成两张只会让用户在两块区域之间来回找。
 */
@Composable
fun WorkbenchScreen(
    container: AppContainer,
    role: Role,
    entries: List<ModuleEntry>,
    onOpen: (String) -> Unit,
) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item { WelcomeBar(role) }
        item { WorkbenchCard(title = null, entries = entries, onOpen = onOpen) }
    }
}

/** 欢迎条（原来固定在网格上面；现在它是列表的第一项，滚动时会跟着走） */
@Composable
private fun WelcomeBar(role: Role) {
    Surface(color = MaterialTheme.colorScheme.primaryContainer, shape = MaterialTheme.shapes.large) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(20.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(
                    "工作台",
                    style = MaterialTheme.typography.titleLarge,
                    color = MaterialTheme.colorScheme.onPrimaryContainer,
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    when (role) {
                        Role.SHIPPER -> "货主端 · 订单与账本"
                        Role.DRIVER -> "司机端 · 任务与送达"
                        Role.DISPATCHER -> "派单端 · 全量管理"
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.75f),
                )
            }
            RoleBadge(role.key)
        }
    }
}

/** 一屏 4 列（与改造前的工作台同一列数：图标大小、字距都不用重新适应） */
private const val GRID_COLUMNS = 4

/**
 * 一张工作台卡片：可选标题 + 4 列图标格。
 *
 * ⛔ 图标格只有 [WorkbenchTile] 一份实现 —— 第二张卡片要是照着抄一遍，
 *    两处迟早长得不一样（同一个 App 里两种图标大小）。
 * ⛔ 末行**补空位**（不满 4 个也要占满 4 列）：不补的话最后一行的图标会被拉宽，
 *    与上面的格子对不齐（看着像排错了）。
 */
@Composable
private fun WorkbenchCard(title: String?, entries: List<ModuleEntry>, onOpen: (String) -> Unit) {
    Surface(
        color = MaterialTheme.colorScheme.surface,
        shape = MaterialTheme.shapes.large,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(horizontal = 12.dp, vertical = 16.dp)) {
            if (title != null) {
                Text(
                    title,
                    style = MaterialTheme.typography.titleMedium,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(14.dp))
            }
            entries.chunked(GRID_COLUMNS).forEachIndexed { rowIndex, row ->
                if (rowIndex > 0) Spacer(Modifier.height(20.dp))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    row.forEach { entry -> WorkbenchTile(entry, onOpen, Modifier.weight(1f)) }
                    repeat(GRID_COLUMNS - row.size) { Spacer(Modifier.weight(1f)) }
                }
            }
        }
    }
}

/** 一个图标格（图标 + 名字）。工作台两张卡片共用这一份。 */
@Composable
private fun WorkbenchTile(entry: ModuleEntry, onOpen: (String) -> Unit, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier.clickable { onOpen(entry.route) },
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        // 有 gradient 的入口（目前只有 AI）用品牌渐变，其余用单色语义色。
        // 渐变必须走 background(brush) —— Surface 的 color 只吃单色，想用画刷就得自己铺一层底。
        if (entry.gradient.isEmpty()) {
            Surface(
                color = androidx.compose.ui.graphics.Color(entry.color),
                shape = MaterialTheme.shapes.large,
            ) {
                Icon(
                    entry.icon,
                    contentDescription = entry.label,
                    tint = androidx.compose.ui.graphics.Color.White,
                    modifier = Modifier.padding(13.dp).size(32.dp),
                )
            }
        } else {
            Box(
                modifier = Modifier
                    .background(
                        brush = Brush.linearGradient(entry.gradient.map { androidx.compose.ui.graphics.Color(it) }),
                        shape = MaterialTheme.shapes.large,
                    )
                    .padding(13.dp),
            ) {
                Icon(
                    entry.icon,
                    contentDescription = entry.label,
                    tint = androidx.compose.ui.graphics.Color.White,
                    modifier = Modifier.size(32.dp),
                )
            }
        }
        Spacer(Modifier.height(8.dp))
        Text(
            entry.label,
            style = MaterialTheme.typography.labelMedium,
            textAlign = TextAlign.Center,
            maxLines = 1,
        )
    }
}

/** 通用二级列表页（分组图标点进来） */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ModuleListScreen(
    title: String,
    entries: List<ModuleEntry>,
    onBack: () -> Unit,
    onOpen: (String) -> Unit,
) {
    Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
        TopAppBar(
            title = { Text(title) },
            navigationIcon = {
                IconButton(onClick = onBack) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                }
            },
        )
        entries.forEach { e ->
            ListItem(
                headlineContent = { Text(e.label) },
                leadingContent = {
                    Icon(e.icon, contentDescription = null, tint = androidx.compose.ui.graphics.Color(e.color))
                },
                trailingContent = { Icon(Icons.Default.ChevronRight, contentDescription = null) },
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { onOpen(e.route) },
            )
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        }
    }
}
