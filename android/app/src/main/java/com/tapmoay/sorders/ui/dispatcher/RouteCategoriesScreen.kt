package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.data.remote.dto.RouteCategoryDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.OriginTeal
import com.tapmoay.sorders.ui.common.Hint

/**
 * **线路分类管理**（2026-10-04）。
 *
 * 用户 2026-10-04 原话：「**干脆给线路联系人以及地点，这3个的界面玩个框了框的位置加一个分类显示**…
 * 它就会弹出一个在左侧来…**可以去参考账本管理的那些代码**」。
 *
 * ## 为什么是"面板"而不是"一页"
 * 与 [PlaceCategoriesPanel] / [ContactCategoriesPanel] 同一条理由（用户 2026-09-19 在真机上抓到的）：
 * 「切换的时候突然会闪一下…要干脆就不要弹一个界面…**它 2 个抽屉**」。
 * 所以它是**同一个左侧抽屉里的第二层**：点抽屉最后一行「管理分类」→ 抽屉内容换成这一块 + 一个返回。
 * ⛔ 不要再给它新建一条路由，也不要为它再开一层抽屉。
 *
 * ## 与 [PlaceCategoriesPanel] 的关系
 * 同一套做法（名册管顺序、字符串管归属、改名级联、整份顺序提交幂等），差别只有级联目标：
 * 那边挂的是地点，这边挂的是线路 —— 所以条数文案是「N 条线路」。
 *
 * ## 排序
 * 「填第几位」（与商品分类管理页同一个语义，用户 2026-09-19：「调整排序你直接复用商品管理的
 * 那个分类管理的代码就可以了」）+ 上下箭头。提交的始终是**整份顺序**（后端 /reorder 要整份）。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RouteCategoriesPanel(
    vm: RouteCategoriesViewModel,
    onBack: () -> Unit,
) {
    Column(Modifier.fillMaxWidth()) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 20.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("线路分类", style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
            TextButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(4.dp))
                Text("返回线路")
            }
        }
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            SoTextField(
                value = vm.draftName,
                onValueChange = { vm.draftName = it },
                placeholder = "新分类名（如：常送工地 / 城东片区）",
                modifier = Modifier.weight(1f),
            )
            Spacer(Modifier.width(8.dp))
            PrimaryActionButton(
                text = if (vm.acting) "…" else "新建",
                onClick = { vm.create() },
                enabled = !vm.acting && vm.draftName.isNotBlank(),
            )
        }
        Hint(
            "只影响你自己看到的分类，别人看不到；顺序就是左栏的顺序。",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 20.dp),
        )
        Spacer(Modifier.height(8.dp))
        when {
            vm.loading && vm.rows.isEmpty() -> LoadingBox(Modifier.fillMaxWidth().height(160.dp))
            vm.loadError != null -> ErrorView(vm.loadError.orEmpty(), onRetry = { vm.load() })
            vm.rows.isEmpty() -> Text(
                "还没有分类。分类是可选的：不建分类，线路就是一份名单，照样能挑、能搜。",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 18.dp),
            )
            else -> LazyColumn(
                Modifier.fillMaxWidth().weight(1f, fill = false).heightIn(max = 460.dp),
                contentPadding = PaddingValues(horizontal = 20.dp, vertical = 4.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                itemsIndexed(vm.rows, key = { _, c -> c.id }) { idx, c ->
                    RouteCategoryRow(
                        c = c,
                        // ⚠️ 显示的是**列表里的位次**（1 起），不是 `sort_order`：
                        //    后端新建时给的是 `max+1`（第一个是 1 不是 0），拿它 +1 会显示成 2。
                        position = idx + 1,
                        first = idx == 0,
                        last = idx == vm.rows.lastIndex,
                        onMoveTo = { pos -> vm.moveTo(c.id, pos) },
                        onUp = { vm.move(idx, -1) },
                        onDown = { vm.move(idx, +1) },
                        onRename = { vm.openRename(c) },
                        onDelete = { vm.deleting = c },
                    )
                }
            }
        }
        vm.error?.let {
            Text(
                it,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 6.dp),
            )
        }
    }

    vm.renaming?.let { target ->
        AlertDialog(
            onDismissRequest = { vm.renaming = null },
            title = { Text("重命名分类") },
            text = {
                Column {
                    SoTextField(vm.renameText, { vm.renameText = it }, placeholder = "分类名")
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "改名会把挂在这个分类下的线路一起改过去（不会掉回未分类）。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    if (target.addressCount > 0) {
                        Spacer(Modifier.height(4.dp))
                        Text(
                            "现在有 " + target.addressCount + " 条线路挂在这一类下。",
                            style = MaterialTheme.typography.bodySmall,
                            color = Color(OriginTeal),
                        )
                    }
                }
            },
            confirmButton = { TextButton(onClick = { vm.rename() }, enabled = !vm.acting) { Text("保存") } },
            dismissButton = { TextButton(onClick = { vm.renaming = null }) { Text("取消") } },
        )
    }

    vm.deleting?.let { target ->
        DangerConfirmDialog(
            title = "删除分类？",
            message = "「" + target.name + "」会从线路左栏消失。挂在这一类下的线路不会被删。" +
                "（后端不允许删还有线路挂着的分类，真要删请先把它们改到别的类）",
            confirmText = "删除",
            onConfirm = { vm.confirmDelete() },
            onDismiss = { vm.deleting = null },
        )
    }
}

/**
 * 一行分类：位次输入框 + 名字 + 挂着几条线路 + 上下移 / 改名 / 删。
 *
 * 与 [CategoryRow]（地点分组）是同一个交互，颜色跟着**模块语义色**走
 * ——「地址与联系人 → 路线」那一档 = `OriginTeal`（设计规范 §2 一色一功能）。
 */
@Composable
private fun RouteCategoryRow(
    c: RouteCategoryDto,
    position: Int,
    first: Boolean,
    last: Boolean,
    onMoveTo: (Int) -> Unit,
    onUp: () -> Unit,
    onDown: () -> Unit,
    onRename: () -> Unit,
    onDelete: () -> Unit,
) {
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            var posField by remember(c.id, position) { mutableStateOf(position.toString()) }
            // 「填第几位」用 SoTextField（浅灰底 + 圆角）而不是 OutlinedTextField：
            // 全库描边输入框的总数是**只减不许增**的基线（判据 _check_form_panel_style.py：
            // 「新页面又写描边框了？用 FormRows.kt 那五行」）。
            Box(Modifier.width(58.dp)) {
                SoTextField(
                    value = posField,
                    onValueChange = { v ->
                        val clean = com.tapmoay.sorders.core.InputRules.intInput(v, 3)
                        posField = clean
                        clean.toIntOrNull()?.let(onMoveTo)
                    },
                    keyboardType = androidx.compose.ui.text.input.KeyboardType.Number,
                )
            }
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    c.name,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold,
                    maxLines = 1,
                    // 显式占满这一列：maxLines=1 + 省略号却不给宽度的文本会去吃兄弟的宽度
                    // （判据 _check_adaptive_layout.py 的存量基线只许减不许增）
                    modifier = Modifier.fillMaxWidth(),
                )
                Text(
                    c.addressCount.toString() + " 条线路",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            IconButton(onClick = onUp, enabled = !first) {
                Icon(
                    Icons.Default.KeyboardArrowUp,
                    contentDescription = "上移",
                    tint = if (first) MaterialTheme.colorScheme.outlineVariant else Color(OriginTeal),
                )
            }
            IconButton(onClick = onDown, enabled = !last) {
                Icon(
                    Icons.Default.KeyboardArrowDown,
                    contentDescription = "下移",
                    tint = if (last) MaterialTheme.colorScheme.outlineVariant else Color(OriginTeal),
                )
            }
            IconButton(onClick = onRename) {
                Icon(Icons.Default.Edit, contentDescription = "重命名", tint = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            IconButton(onClick = onDelete) {
                Icon(Icons.Default.DeleteOutline, contentDescription = "删除", tint = Color(0xFFFF4D4F))
            }
        }
    }
}
