package com.tapmoay.sorders.ui.home

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.ui.common.RoleBadge
import com.tapmoay.sorders.ui.nav.ModuleEntry
import com.tapmoay.sorders.ui.nav.Role

/** 工作台：图标网格（像手机桌面，每个图标=一个功能） */
@Composable
fun WorkbenchScreen(
    container: AppContainer,
    role: Role,
    entries: List<ModuleEntry>,
    onOpen: (String) -> Unit,
) {
    Column(Modifier.fillMaxSize()) {
        // 欢迎条
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
        LazyVerticalGrid(
            columns = GridCells.Fixed(4),
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(16.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(20.dp),
        ) {
            items(entries, key = { it.label + it.route }) { entry ->
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { onOpen(entry.route) },
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    // 有 gradient 的入口（目前只有 AI）用品牌渐变，其余用单色语义色。
                    // 渐变必须走 background(brush) —— Surface 的 color 只吃单色，
                    // 想用画刷就得自己铺一层底。
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
                        textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                        maxLines = 1,
                    )
                }
            }
        }
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
