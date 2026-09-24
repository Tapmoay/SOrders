package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
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
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.api.UnitConversionDto
import com.tapmoay.sorders.ui.theme.UnitConvRose

/**
 * 「单位换算」管理页（一车 = 8 方）—— 用户 2026-09-24 要求。
 *
 * 用户原话：
 * > 「我们再加一个功能叫做**自动换算单位**……这换算单位啊，我们就把它加在那个添加单位的那个页面当中，
 * >  添加单位那里再加个按钮可以说**添加单位换算**……然后我们再计算的时候或者是算账的时候
 * >  会自动启动换算的功能，比如说我下的十车，会有 **2 个数据**：第一个是 10 车，第 2 个则是 80 方。」
 *
 * ## 两个入口，同一份实现
 * 1. 工作台上的这一格（**派单员与货主都有** —— 用户点名了「我们的货主和派单员，他可以自动的设置单位」）；
 * 2. 「请选择单位」页里的「添加单位换算」按钮（用户点名要放那儿）。
 * 两处弹出的都是同一个 [UnitConversionDialog]，判据也都在后端的同一处。
 *
 * ## 删除与恢复
 * 删除是**伪装删除**（用户 2026-09-20 的硬规矩），所以这一页下半段永远摆着那个「已删除」区 ——
 * 恢复入口要**手边就有**，不能只藏在删除那一下的提示条里（那个会飘走）。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun UnitConversionsScreen(
    container: AppContainer,
    onBack: () -> Unit,
) {
    val vm: UnitConversionsViewModel = appViewModel { UnitConversionsViewModel(container) }
    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(Unit) { vm.load() }
    OneShotSnackbar(snackbar, vm.notice, onConsumed = { vm.notice = null })

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = { Text("单位换算") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
        floatingActionButton = {
            FloatingActionButton(onClick = { vm.openCreate() }) {
                Icon(Icons.Default.Add, contentDescription = "新增换算")
            }
        },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            when {
                vm.loading && vm.rows.isEmpty() -> LoadingBox()
                vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
                else -> LazyColumn(
                    Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    if (vm.rows.isEmpty()) {
                        item { EmptyView("还没有设过单位换算，点右下角新增") }
                    } else {
                        // ⚠️ 这一句是**解释句**（`Hint` 管），而且必须写在 `else` 分支里：
                        //    `_hint_inventory.looks_empty_state(...)` 会看这句话前面 600 字里
                        //    最后一次 `isEmpty()`，后面**没有 `} else`** 时它就把这句判成
                        //    空态句（EMPTY）—— 而空态句不该走 `Hint`，`_check_hints.py` 当场报
                        //    「一次 Hint 调用里一段解释句都没有」。放在 else 里既让它保持解释句
                        //    的身份，语义也更贴：**有换算可看时才解释**（一条都没有时，
                        //    上面那句空态文案已经把该说的说完了）。
                        item {
                            Hint(
                                "设一条「1 车 = 8 方」这样的换算之后，下单、订单、账本里的数量会同时显示两个单位" +
                                    "（10 车 ≈ 80 方）。金额不受影响，仍按原来的单位算。",
                            )
                        }
                        items(vm.rows, key = { it.id }) { row ->
                            ConversionCard(
                                row = row,
                                onEdit = { vm.openEdit(row) },
                                onDelete = { vm.delete(row) },
                            )
                        }
                    }
                    if (vm.deleted.isNotEmpty()) {
                        item {
                            Spacer(Modifier.height(6.dp))
                            Text("已删除", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        items(vm.deleted, key = { "del-${it.id}" }) { row ->
                            DeletedCard(row = row, onRestore = { vm.restore(row) })
                        }
                    }
                    item { Spacer(Modifier.height(72.dp)) }
                }
            }
        }
    }

    if (vm.showDialog) {
        UnitConversionDialog(
            initial = vm.editing,
            inUse = unitsInUse(vm.rows.flatMap { listOf(it.fromUnit, it.toUnit) }),
            saving = vm.saving,
            error = vm.formError,
            onSave = { vm.save(it) },
            onDismiss = { vm.showDialog = false },
        )
    }
}

/** 一条换算：**主角是那一行等式**（用户要的就是"1 车 = 8 方"这个事实）。 */
@Composable
private fun ConversionCard(
    row: UnitConversionDto,
    onEdit: () -> Unit,
    onDelete: () -> Unit,
) {
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            TintedIcon(Icons.Default.SwapHoriz, Color(UnitConvRose), size = 18.dp, container = 34.dp)
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    "1 ${row.fromUnit} = ${trimFactor(row.factor)} ${row.toUnit}",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                )
                // 举例：把这条换算用到 10 个上是什么样 —— 用户举的例子正是"我下的十车"
                Text(
                    "例如 10 ${row.fromUnit} ≈ ${tenOf(row)} ${row.toUnit}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (row.remark.isNotBlank()) {
                    Text(row.remark, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline)
                }
            }
            IconButton(onClick = onEdit) { Icon(Icons.Default.Edit, contentDescription = "编辑", modifier = Modifier.size(18.dp)) }
            IconButton(onClick = onDelete) {
                Icon(
                    Icons.Default.Delete,
                    contentDescription = "删除",
                    modifier = Modifier.size(18.dp),
                    tint = MaterialTheme.colorScheme.error,
                )
            }
        }
    }
}

@Composable
private fun DeletedCard(row: UnitConversionDto, onRestore: () -> Unit) {
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                "1 ${row.fromUnit} = ${trimFactor(row.factor)} ${row.toUnit}",
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.weight(1f),
            )
            TextButton(onClick = onRestore) { Text("恢复") }
        }
    }
}

/** `8.0000` → `8`（与后端 `format_factor` 同一个口径）。 */
private fun trimFactor(raw: String): String {
    val s = raw.trim()
    if (!s.contains('.')) return s
    return s.trimEnd('0').trimEnd('.')
}

/** 「10 个源单位 ≈ 多少个」—— 卡片上那句举例（算不成就算了，不编数）。 */
private fun tenOf(row: UnitConversionDto): String {
    val f = trimFactor(row.factor).toBigDecimalOrNull() ?: return "—"
    return f.multiply(java.math.BigDecimal(10)).stripTrailingZeros().toPlainString()
}
