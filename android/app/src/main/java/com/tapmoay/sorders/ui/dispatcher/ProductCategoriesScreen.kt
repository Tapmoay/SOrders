package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.ProductCategoryDto
import com.tapmoay.sorders.ui.common.*

/**
 * 商品分类管理：**新建 / 改名 / 上下移动排序 / 删除**。
 *
 * ## 为什么要有这一页（用户 2026-09-18）
 * 之前的分类顺序是**推出来的**（按商品数倒序）—— 那是"现在哪类货多"，
 * 不是"店家想让人先看哪类"。用户要的是：
 * > 派单端可以创建商品分类，甚至可以更改商品分类的显示顺序。
 *
 * ## 排序为什么用"上移/下移"按钮而不是拖拽
 * 拖拽在这个列表里会**没有位置放删除和改名**（长按拖动与长按菜单冲突），
 * 而且拖到一半松手时"到底插在谁前面"常常看不准。上下移一步一次、结果确定，
 * 排完点「保存顺序」一次提交 —— 后端要求**整份顺序**（见 `ProductCategoryReorder` 的注释）。
 * 分类一般只有几个到十几个，点几下不算负担。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProductCategoriesScreen(
    container: AppContainer,
    onBack: () -> Unit,
) {
    val vm: ProductCategoriesViewModel = appViewModel { ProductCategoriesViewModel(container) }
    val snackbar = remember { SnackbarHostState() }

    OneShotSnackbar(snackbar, vm.notice, onConsumed = { vm.notice = null })
    OneShotSnackbar(snackbar, vm.loadError, onConsumed = { vm.loadError = null })

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background,
                ),
                title = { Text("商品分类", style = MaterialTheme.typography.titleLarge) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    TextButton(onClick = { vm.openCreate() }) {
                        Icon(Icons.Default.Add, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(4.dp))
                        Text("新建分类")
                    }
                },
            )
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            // 顺序改动是**本地草稿**，要点「保存顺序」才提交 —— 这样连点几下上下移
            // 只产生一次请求，也不会出现"移一步发一次、中途失败顺序半新半旧"。
            if (vm.dirty) {
                Surface(
                    color = MaterialTheme.colorScheme.primaryContainer,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Row(
                        Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(Icons.Default.SwapVert, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(8.dp))
                        Text(
                            "顺序改过了，记得保存",
                            style = MaterialTheme.typography.bodyMedium,
                            modifier = Modifier.weight(1f),
                        )
                        TextButton(enabled = !vm.busy, onClick = { vm.saveOrder() }) { Text("保存顺序") }
                        TextButton(enabled = !vm.busy, onClick = { vm.revertOrder() }) { Text("撤销") }
                    }
                }
            }

            when {
                vm.loading -> LoadingBox()
                vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
                vm.categories.isEmpty() -> EmptyBox()
                else -> LazyColumn(
                    Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    item {
                        Text(
                            "这一列的顺序 = 下单页「选择商品」左侧的顺序（从上到下）。" +
                                "没有商品的分类不会出现在下单页里，但会留在这里。",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Spacer(Modifier.height(4.dp))
                    }
                    itemsIndexed(vm.categories, key = { _, c -> c.id }) { idx, c ->
                        CategoryRow(
                            index = idx,
                            total = vm.categories.size,
                            c = c,
                            busy = vm.busy,
                            onUp = { vm.move(idx, -1) },
                            onDown = { vm.move(idx, 1) },
                            onRename = { vm.openRename(c) },
                            onDelete = { vm.askDelete(c) },
                        )
                    }
                }
            }
        }
    }

    // 新建 / 改名
    vm.editing?.let { editing ->
        CategoryNameDialog(
            initial = editing.second,
            isNew = editing.first == null,
            busy = vm.busy,
            onConfirm = { name -> vm.submit(editing.first, name) },
            onDismiss = { vm.editing = null },
        )
    }

    // 删除确认：把"还有几个商品挂在这一类"写在脸上（后端也会拦，这里先说清楚）
    vm.deleting?.let { c ->
        AlertDialog(
            onDismissRequest = { vm.deleting = null },
            title = { Text("删除分类「${c.name}」？") },
            text = {
                Text(
                    if (c.productCount > 0) {
                        "还有 ${c.productCount} 个商品挂在这个分类下，删不掉。" +
                            "先把这些商品改成别的分类（或给它改个名）再来删。"
                    } else {
                        "这个分类下没有商品，删除后不影响任何商品。"
                    }
                )
            },
            confirmButton = {
                TextButton(
                    enabled = !vm.busy && c.productCount == 0,
                    onClick = { vm.confirmDelete(c) },
                ) { Text("删除", color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = { TextButton(onClick = { vm.deleting = null }) { Text("取消") } },
        )
    }
}

@Composable
private fun EmptyBox() {
    Column(
        Modifier.fillMaxSize().padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text(
            "还没有任何分类",
            style = MaterialTheme.typography.titleMedium,
        )
        Spacer(Modifier.height(6.dp))
        Text(
            "分类只影响下单页左侧怎么分组。建好之后在商品编辑页把商品归到对应分类即可。",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun CategoryRow(
    index: Int,
    total: Int,
    c: ProductCategoryDto,
    busy: Boolean,
    onUp: () -> Unit,
    onDown: () -> Unit,
    onRename: () -> Unit,
    onDelete: () -> Unit,
) {
    Surface(
        shape = RoundedCornerShape(12.dp),
        color = MaterialTheme.colorScheme.surface,
        border = androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(Modifier.padding(horizontal = 12.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            // 序号：让人一眼看出"这是第几个"，排序时不至于数错
            Box(
                Modifier.size(26.dp).clip(RoundedCornerShape(8.dp))
                    .background(MaterialTheme.colorScheme.surfaceVariant),
                contentAlignment = Alignment.Center,
            ) {
                Text((index + 1).toString(), style = MaterialTheme.typography.labelMedium)
            }
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(c.name, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(
                    if (c.productCount > 0) "${c.productCount} 个商品" else "暂无商品",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            IconButton(onClick = onUp, enabled = !busy && index > 0) {
                Icon(Icons.Default.KeyboardArrowUp, contentDescription = "上移", tint = if (index > 0) Color(0xFF1E6FFF) else MaterialTheme.colorScheme.outlineVariant)
            }
            IconButton(onClick = onDown, enabled = !busy && index < total - 1) {
                Icon(Icons.Default.KeyboardArrowDown, contentDescription = "下移", tint = if (index < total - 1) Color(0xFF1E6FFF) else MaterialTheme.colorScheme.outlineVariant)
            }
            IconButton(onClick = onRename, enabled = !busy) {
                Icon(Icons.Default.DriveFileRenameOutline, contentDescription = "改名", modifier = Modifier.size(18.dp))
            }
            IconButton(onClick = onDelete, enabled = !busy) {
                Icon(
                    Icons.Default.DeleteOutline,
                    contentDescription = "删除",
                    modifier = Modifier.size(18.dp),
                    tint = MaterialTheme.colorScheme.error,
                )
            }
        }
    }
}

@Composable
private fun CategoryNameDialog(
    initial: String,
    isNew: Boolean,
    busy: Boolean,
    onConfirm: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    var name by remember { mutableStateOf(initial) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (isNew) "新建分类" else "给分类改名") },
        text = {
            Column {
                SoTextField(
                    value = name,
                    onValueChange = { name = it.take(8) },
                    placeholder = "分类名，如 饮料 / 粮油 / 日化",
                )
                if (!isNew) {
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "改名会把挂在这个分类下的商品**一起改过去**（同一事务），不会让它们变成未分类。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        },
        confirmButton = {
            TextButton(enabled = !busy && name.isNotBlank(), onClick = { onConfirm(name) }) {
                Text(if (busy) "提交中…" else "确定")
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}
