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
import com.tapmoay.sorders.data.remote.dto.PlaceCategoryDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.ShipperTeal

/**
 * **地点分组管理**（用户 2026-09-19）：「管理分组是一个新的界面吧，像商品管理的分组一样，
 * 同样是可以创建分组然后进行排序」。
 *
 * ## 为什么是"面板"而不是"一页"
 * 第一版做成了一整页（`Routes.PLACE_CATEGORIES`）。真机上用户点左栏那格时看到的是
 * **地址抽屉先收起来、再弹出一整页**，中间闪一下 —— 他的原话：
 * 「切换的时候突然会闪一下…这样太麻烦了。要干脆就不要弹一个界面，干脆就直接弹一个 ——
 *   也算一个抽屉吧，**它 2 个抽屉**」。
 * 所以现在它是**同一个抽屉里的第二层**：点「管理分组」→ 抽屉内容换成这一块 + 一个返回；
 * 没有任何导航、没有 dismiss/push，也就不闪。
 *
 * ## 与「商品分类管理」的关系
 * 同一套做法（名册管顺序、字符串管归属、改名级联、整份顺序提交幂等），差别只有一处：
 * **按人分区** —— 货主和派单员各管自己地址库那一列。
 *
 * ## 排序
 * **两种方式共用一处逻辑**（`moveCategoryTo` 那一份，见 `VM.moveTo/move`）：
 * 这里用的是"填第几位"（与商品分类管理页的输入框同一个语义），
 * 长按拖动的手势代码没有搬过来 —— 分组通常只有几个，数字框已经够用，
 * 而拖动那套（行高量尺 + 拖影 + 手势取消）在抽屉里还要再处理滚动冲突。
 * 提交的始终是**整份顺序**（后端 `/reorder` 要整份，只传一部分会 400）。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PlaceCategoriesPanel(
    vm: PlaceCategoriesViewModel,
    onBack: () -> Unit,
) {
    Column(Modifier.fillMaxWidth()) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 20.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("地点分组", style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
            TextButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(4.dp))
                Text("返回地址")
            }
        }
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 8.dp),
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
            "分组只影响你自己的地址库（左栏那一列），别人看不到也改不到。顺序就是左栏里从上到下的顺序。",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 20.dp),
        )
        Spacer(Modifier.height(8.dp))
        when {
            vm.loading && vm.rows.isEmpty() -> LoadingBox(Modifier.fillMaxWidth().height(160.dp))
            vm.loadError != null -> ErrorView(vm.loadError.orEmpty(), onRetry = { vm.load() })
            vm.rows.isEmpty() -> Text(
                "还没有分组。分组是可选的：不建分组，下单时的地址库照样能用默认那三段（线路 / 我的地点 / 共享地点）。",
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
                    CategoryRow(
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
            confirmButton = { TextButton(onClick = { vm.rename() }, enabled = !vm.acting) { Text("保存") } },
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

/**
 * 一行分组：位次输入框 + 名字 + 挂着几个地点 + 上下移 / 改名 / 删。
 *
 * 位次那个小框与「商品分类管理」是**同一个交互**（填几就排到第几，1 起）——
 * 用户 2026-09-19：「调整排序你直接复用商品管理的那个分类管理的代码就可以了」。
 * 上下箭头保留着：改一位时它比"选中数字再敲"快，两种都是同样的整份提交。
 */
@Composable
private fun CategoryRow(
    c: PlaceCategoryDto,
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
            OutlinedTextField(
                value = posField,
                onValueChange = { v ->
                    val clean = com.tapmoay.sorders.core.InputRules.intInput(v, 3)
                    posField = clean
                    clean.toIntOrNull()?.let(onMoveTo)
                },
                singleLine = true,
                textStyle = MaterialTheme.typography.titleMedium.copy(
                    textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                    color = Color(ShipperTeal),
                ),
                keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(
                    keyboardType = androidx.compose.ui.text.input.KeyboardType.Number,
                ),
                modifier = Modifier.width(58.dp),
            )
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(c.name, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold, maxLines = 1)
                Text(
                    c.locationCount.toString() + " 个地点",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            IconButton(onClick = onUp, enabled = !first) {
                Icon(
                    Icons.Default.KeyboardArrowUp,
                    contentDescription = "上移",
                    tint = if (first) MaterialTheme.colorScheme.outlineVariant else Color(ShipperTeal),
                )
            }
            IconButton(onClick = onDown, enabled = !last) {
                Icon(
                    Icons.Default.KeyboardArrowDown,
                    contentDescription = "下移",
                    tint = if (last) MaterialTheme.colorScheme.outlineVariant else Color(ShipperTeal),
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
