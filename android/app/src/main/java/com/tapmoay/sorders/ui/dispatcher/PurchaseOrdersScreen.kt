package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.PurchaseOrderDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.CashOut
import com.tapmoay.sorders.util.formatMoney
import kotlinx.coroutines.launch

/**
 * 「采购单」列表页（FEAT-0013 第三期，2026-10-04）。
 *
 * ## 这一页回答什么
 * 「我进过哪些货、一张单多少钱、还欠这家供应商多少」。点一行进去改单，右下角新建一张。
 *
 * ## ⛔ 三个数一律取服务端
 * `total` / `payablePaid` / `payableUnpaid` 都是后端算好的（口径只有一处：
 * `backend/app/services/purchase_service.py`）。**界面上一个减法都不做** ——
 * 界面上再减一遍就是第二个口径，哪天两边不一样，谁都不知道该信哪个。
 *
 * ## ⚠️ 「撤单」撤的是整张单，不是一条记录
 * 撤单会让这一单的入库流水一起失效（**库存退回去**、成本价按剩下的进货重算），
 * 所以确认框必须把这件事说明白，不能只说"确定删除吗"。
 */
class PurchaseOrdersViewModel(private val container: AppContainer) : ViewModel() {

    var rows by mutableStateOf<List<PurchaseOrderDto>>(emptyList())
        private set
    var loading by mutableStateOf(true)
        private set
    var loadError by mutableStateOf<String?>(null)
    var actionResult by mutableStateOf<String?>(null)
    var showDeleted by mutableStateOf(false)
        private set

    /** 刚撤掉的那一张（给界面那条带「撤回」的 snackbar 用）。 */
    var lastDeleted by mutableStateOf<PurchaseOrderDto?>(null)
        private set

    fun start() {
        // ⚠️ 每次进这一页都重新拉一次（⛔ 不加"只拉一次"的开关）：从表单页保存完回来时，
        //    新单必须已经在这一页上；而 Navigation Compose 返回时会重新进组合，正好触发这里。
        load()
    }

    fun load() {
        viewModelScope.launch {
            // 已经有数据时不摆 loading（否则从表单页回来会闪一下白屏、列表位置也丢了）。
            if (rows.isEmpty()) loading = true
            loadError = null
            try {
                rows = container.repo.purchaseOrders(includeDeleted = showDeleted)
            } catch (e: Exception) {
                loadError = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun toggleDeleted() {
        showDeleted = !showDeleted
        rows = emptyList()
        load()
    }

    /**
     * 撤单（软删）。
     *
     * ⚠️ 名下有**没撤销的付款**时后端会拒绝并给出人话（"这张单已经付过钱了"）——
     * 那句话**原样显示**给用户，不翻成"操作失败"（翻掉以后用户不知道该先去做什么）。
     */
    fun delete(o: PurchaseOrderDto) {
        viewModelScope.launch {
            try {
                container.repo.deletePurchaseOrder(o.id)
                lastDeleted = o
                // ⚠️ 这里**不写 `actionResult`**：撤单的回执由那条带「撤回」的 snackbar 说
                //    （两处都说一句就是两条重复提示，用户不知道该点哪个）。
                load()
            } catch (e: Exception) {
                actionResult = toApiException(e).message
            }
        }
    }

    fun restoreLastDeleted() {
        val o = lastDeleted ?: return
        lastDeleted = null
        viewModelScope.launch {
            try {
                container.repo.restorePurchaseOrder(o.id)
                actionResult = "已恢复 #${o.id}"
                load()
            } catch (e: Exception) {
                actionResult = toApiException(e).message
            }
        }
    }

    /** 从回收站里把某一张放回来（不是"刚撤的那一张"那条路）。 */
    fun restore(o: PurchaseOrderDto) {
        viewModelScope.launch {
            try {
                container.repo.restorePurchaseOrder(o.id)
                actionResult = "已恢复 #${o.id}"
                load()
            } catch (e: Exception) {
                actionResult = toApiException(e).message
            }
        }
    }
}

/** 金额一律"后端字符串 → 加个 ¥"，⛔ 客户端不做四则运算。 */
private fun yuan(s: String?): String = "¥" + formatMoney(s ?: "0")

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PurchaseOrdersScreen(
    container: AppContainer,
    onBack: () -> Unit,
    onOpenForm: (Long?) -> Unit,
) {
    val vm: PurchaseOrdersViewModel = appViewModel { PurchaseOrdersViewModel(container) }
    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(Unit) { vm.start() }
    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })
    // 撤完**立刻**给一个「撤回」（硬规矩：删除一律软删 + 手边要有一个撤销入口）。
    LaunchedEffect(vm.lastDeleted) {
        val o = vm.lastDeleted ?: return@LaunchedEffect
        val res = snackbar.showSnackbar(
            message = "已撤销采购单 #${o.id}",
            actionLabel = "撤回",
            withDismissAction = false,
        )
        if (res == SnackbarResult.ActionPerformed) vm.restoreLastDeleted()
    }
    // 撤单前把"会连带发生什么"说清楚（库存退回去、成本价重算）。
    var confirmDelete by remember { mutableStateOf<PurchaseOrderDto?>(null) }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            AppTopBar(
                title = "采购单",
                onBack = onBack,
                actions = {
                    TextButton(onClick = { vm.toggleDeleted() }) {
                        Text(if (vm.showDeleted) "看在用的" else "回收站")
                    }
                },
            )
        },
        floatingActionButton = {
            if (!vm.showDeleted) {
                ExtendedFloatingActionButton(
                    onClick = { onOpenForm(null) },
                    containerColor = Color(CashOut),
                    contentColor = Color.White,
                    icon = { Icon(Icons.Default.Add, contentDescription = null) },
                    text = { Text("新增采购单") },
                )
            }
        },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            when {
                vm.loading -> LoadingBox()
                vm.loadError != null -> ErrorView(vm.loadError.orEmpty(), onRetry = { vm.load() })
                else -> LazyColumn(
                    Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp, 16.dp, 16.dp, 88.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    item { PurchaseExplainerCard(deleted = vm.showDeleted) }
                    if (vm.rows.isEmpty()) {
                        item {
                            EmptyView(
                                if (vm.showDeleted) {
                                    "回收站里没有采购单"
                                } else {
                                    "还没有采购单。点右下角「新增采购单」记一次进货。"
                                },
                            )
                        }
                    }
                    items(vm.rows, key = { it.id }) { o ->
                        PurchaseOrderRowCard(
                            order = o,
                            onOpen = { onOpenForm(o.id) },
                            onDelete = { confirmDelete = o },
                            onRestore = { vm.restore(o) },
                        )
                    }
                }
            }
        }
    }

    confirmDelete?.let { o ->
        CardAlertDialog(
            tone = DialogTone.DANGER,
            onDismissRequest = { confirmDelete = null },
            title = { Text("撤销采购单 #${o.id}？") },
            text = {
                Text(
                    "这张单的 ${o.itemCount} 行货会一起退回：" +
                        "库存减回去、这些商品的成本价按剩下的进货重算，" +
                        "供应商那张应付单（还欠 ${yuan(o.payableUnpaid)}）也会撤销。" +
                        "\n\n单子会进回收站，随时可以恢复。"
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    confirmDelete = null
                    vm.delete(o)
                }) { Text("撤销这张单") }
            },
            dismissButton = { TextButton(onClick = { confirmDelete = null }) { Text("再想想") } },
        )
    }
}

/** 采购单一行（卡片）。⛔ 卡里的数全是服务端给的字符串，这里只排版。 */
@Composable
private fun PurchaseOrderRowCard(
    order: PurchaseOrderDto,
    onOpen: () -> Unit,
    onDelete: () -> Unit,
    onRestore: () -> Unit,
) {
    SectionCard(Modifier.fillMaxWidth().clickable(onClick = onOpen)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                Icons.Default.ShoppingCart,
                contentDescription = null,
                tint = Color(0xFF4CAF50),
                modifier = Modifier.size(18.dp),
            )
            Spacer(Modifier.width(8.dp))
            Text(
                order.supplierName.ifBlank { "供应商 #${order.supplierId}" },
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            if (order.isDeleted) {
                Text(
                    "已撤销",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.error,
                )
            }
        }
        Spacer(Modifier.height(6.dp))
        Text(
            "单号 #${order.id} · ${order.docDate} · ${order.itemCount} 行",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(8.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                "合计 ${yuan(order.total)}",
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
            )
            Spacer(Modifier.weight(1f))
            // 「已付/还差」两个数都来自后端那张应付单；没挂应付（理论上不会）就不显示。
            if (order.payableId != null) {
                Text(
                    if (order.payableUnpaid == "0.00") {
                        "已付清 ${yuan(order.payablePaid)}"
                    } else {
                        "还差 ${yuan(order.payableUnpaid)}"
                    },
                    style = MaterialTheme.typography.bodyMedium,
                    color = if (order.payableUnpaid == "0.00") {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    } else {
                        MaterialTheme.colorScheme.error
                    },
                )
            }
        }
        if (order.remark.isNotBlank()) {
            Spacer(Modifier.height(6.dp))
            Text(
                order.remark,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Spacer(Modifier.height(4.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
            if (order.isDeleted) {
                TextButton(onClick = onRestore) { Text("恢复") }
            } else {
                TextButton(onClick = onOpen) { Text("改单") }
                TextButton(onClick = onDelete) { Text("撤单") }
            }
        }
    }
}

/** 顶上那张说明卡：这一页和"进货"的关系，以及撤单会连带发生什么。 */
@Composable
private fun PurchaseExplainerCard(deleted: Boolean) {
    SectionCard {
        Text(
            if (deleted) "回收站：这里是被撤销的采购单" else "采购单 = 一次进货入库",
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.SemiBold,
        )
        Spacer(Modifier.height(6.dp))
        Text(
            if (deleted) {
                "恢复一张单要重新占库存、重新记回成本价和欠款 —— 库存不够时后端会拒绝并说明原因。"
            } else {
                "保存时后端在同一个事务里做三件事：库存加上去、这个商品的成本价按这次单价更新、" +
                    "给供应商记一张应付单。撤销整张单会把这三件事一起退回去。"
            },
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}