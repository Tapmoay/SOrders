package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.PlaceCategoryDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.ShipperTeal
import kotlinx.coroutines.launch

/**
 * **地点分组管理**（用户 2026-09-19）：「管理分组是一个**新的界面**吧。然后我们那个界面
 * 就可以像那个商品管理的分组一样，同样是可以**创建分组然后进行排序**都可以」。
 *
 * ## 与「商品分类管理」的关系
 * 同一套做法（名册管顺序、字符串管归属、改名级联、整份顺序一次提交幂等），
 * 差别只有一处：**这是每个人自己那一份** —— 货主和派单员各有自己的地点库，
 * 所以这一页（和后端 `place-categories`）都按登录人分区，看不到也改不到别人的分组。
 *
 * ## 排序为什么用上下箭头，而不是商品分类那一套"填数字 + 长按拖动"
 * 商品分类那边两种都有（数字输入框是主入口、拖是快捷）；这里地点分组通常只有几个，
 * **上下箭头**是最不会出错的一种：一步一格、结果立刻从服务端回来，不用记"第几位"。
 * 提交的仍然是**整份顺序**（后端 `/reorder` 要的就是整份，只传一部分会 400）——
 * 箭头只是把"整份"这件事藏在一次点击里。
 *
 * ⛔ 排序**必须**提交整份：只上移一格也得把完整列表发上去，否则后端无从知道
 * "没提到的那几个该排哪儿"。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PlaceCategoriesScreen(container: AppContainer, onBack: () -> Unit) {
    val vm: PlaceCategoriesViewModel = appViewModel { PlaceCategoriesViewModel(container) }
    val snackbar = remember { SnackbarHostState() }
    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })
    OneShotSnackbar(snackbar, vm.error, onConsumed = { vm.error = null })

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = { Text("地点分组") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
    ) { pad ->
        Column(Modifier.fillMaxSize().padding(pad)) {
            // 新建（就地创建，不用另开弹窗 —— 这一页本来就只有一个动作）
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                SoTextField(
                    value = vm.draftName,
                    onValueChange = { vm.draftName = it },
                    placeholder = "新分组名（如：常送小区 / 工地）",
                    modifier = Modifier.weight(1f),
                )
                Spacer(Modifier.width(8.dp))
                PrimaryActionButton(
                    text = if (vm.acting) "…" else "新建",
                    onClick = { vm.create() },
                    enabled = !vm.acting && vm.draftName.isNotBlank(),
                )
            }
            Text(
                "分组只影响你自己的地址库（左栏那一列），别人看不到也改不到。" +
                    "顺序就是左栏里从上到下的顺序。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 16.dp),
            )
            Spacer(Modifier.height(8.dp))
            when {
                vm.loading && vm.rows.isEmpty() -> LoadingBox(Modifier.fillMaxWidth().weight(1f))
                vm.loadError != null -> ErrorView(vm.loadError.orEmpty(), onRetry = { vm.load() })
                vm.rows.isEmpty() -> EmptyView(
                    "还没有分组。分组是可选的：不建分组，下单时的地址库照样能用默认那三段（线路 / 我的地点 / 共享地点）。",
                    Modifier.fillMaxWidth().weight(1f),
                )
                else -> LazyColumn(
                    Modifier.fillMaxWidth().weight(1f),
                    contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    itemsIndexed(vm.rows, key = { _, c -> c.id }) { idx, c ->
                        CategoryRow(
                            c = c,
                            // ⚠️ 显示的是**列表里的位次**（1 起），不是 `sort_order`：
                            //    后端新建时给的是 `max+1`（第一个是 1 不是 0），拿它 +1 会显示成 2。
                            position = idx + 1,
                            first = idx == 0,
                            last = idx == vm.rows.lastIndex,
                            onUp = { vm.move(idx, -1) },
                            onDown = { vm.move(idx, +1) },
                            onRename = { vm.openRename(c) },
                            onDelete = { vm.deleting = c },
                        )
                    }
                }
            }
        }
    }

    vm.renaming?.let { target ->
        AlertDialog(
            onDismissRequest = { vm.renaming = null },
            title = { Text("重命名分组") },
            text = {
                Column {
                    SoTextField(vm.renameText, { vm.renameText = it }, placeholder = "分组名")
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "改名会把挂在这个分组下的地点一起改过去（不会掉回未分类）。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    if (target.locationCount > 0) {
                        Spacer(Modifier.height(4.dp))
                        Text(
                            "现在有 " + target.locationCount + " 个地点挂在这一组下。",
                            style = MaterialTheme.typography.bodySmall,
                            color = Color(ShipperTeal),
                        )
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { vm.rename() }, enabled = !vm.acting) { Text("保存") }
            },
            dismissButton = { TextButton(onClick = { vm.renaming = null }) { Text("取消") } },
        )
    }

    vm.deleting?.let { target ->
        DangerConfirmDialog(
            title = "删除分组？",
            message = "「" + target.name + "」会从地址库左栏消失。挂在这一组下的地点不会被删。" +
                "（后端不允许删还有地点挂着的分组，真要删请先把它们改到别的组）",
            confirmText = "删除",
            onConfirm = { vm.confirmDelete() },
            onDismiss = { vm.deleting = null },
        )
    }
}

/** 一行分组：位次 + 名字 + 挂着几个地点 + 上移/下移/改名/删。 */
@Composable
private fun CategoryRow(
    c: PlaceCategoryDto,
    position: Int,
    first: Boolean,
    last: Boolean,
    onUp: () -> Unit,
    onDown: () -> Unit,
    onRename: () -> Unit,
    onDelete: () -> Unit,
) {
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Surface(shape = MaterialTheme.shapes.small, color = Color(ShipperTeal).copy(alpha = 0.14f)) {
                Text(
                    position.toString(),
                    style = MaterialTheme.typography.labelLarge,
                    fontWeight = FontWeight.Bold,
                    color = Color(ShipperTeal),
                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
                )
            }
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(c.name, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                Text(
                    c.locationCount.toString() + " 个地点",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            // 上/下移：一步一格，点完立刻回服务端的顺序
            IconButton(onClick = onUp, enabled = !first) {
                Icon(Icons.Default.KeyboardArrowUp, contentDescription = "上移", tint = if (first) MaterialTheme.colorScheme.outlineVariant else Color(ShipperTeal))
            }
            IconButton(onClick = onDown, enabled = !last) {
                Icon(Icons.Default.KeyboardArrowDown, contentDescription = "下移", tint = if (last) MaterialTheme.colorScheme.outlineVariant else Color(ShipperTeal))
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
