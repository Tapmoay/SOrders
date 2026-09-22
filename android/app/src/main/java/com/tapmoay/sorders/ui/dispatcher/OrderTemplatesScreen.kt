package com.tapmoay.sorders.ui.dispatcher

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
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.OrderTemplateDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.util.formatMoney
import kotlinx.coroutines.launch

/**
 * 「预订单」页 —— **专门管理预设好的订单**（2026-09-22 用户要求）。
 *
 * ## 用户原话
 * > 「其实我们**还可以再增加一个叫做「预定单」界面**，**专门去管理**预设的订单 ——
 * > 就是**预设好的订单**，这个**参数没有变**，**直接下单就可以了**。」
 *
 * ## 这一页管什么、不管什么（三条边界，别越界）
 * 1. **它不生成订单**：「用这张下单」只是把这几个参数**带进下单页**（商品与数量预填好、参数仍可改），
 *    最后按的还是下单页那个按钮 —— 下单永远走 `POST /orders` 一条路。
 *    ⛔ 别在这一页直接建单：那会把下单的状态核对/库存/账本口径抄第二遍。
 * 2. **商品与数量预填，价格不预填**：预设单里**没有单价**（价格会变，存旧价＝几个月后按旧价下单）。
 *    价格在下单页按「商品价 / 这个货主的专属价」现算 —— 那一份口径只有一处（下单页的 `priceFor`）。
 * 3. **预设运费是参考值，不是下单参数**：下单接口（`OrderCreate`）**根本不收运费** ——
 *    运费是派单那一步按价目表算的。所以卡片上写的是「参考运费」，⛔ 不许写成"下单就按这个收"。
 *
 * ## 新增与编辑
 * 这一版**页面上只能看 / 删 / 恢复 / 去下单**；建与改走 AI（「建一张预设单」「改预设单」）。
 * 理由：预设单的核心是"一组商品 + 数量"，而在页面上编这一组要么套选品页、要么再写一个表单页 ——
 * 那是**另一件事**（用户已经能在下单页把商品挑好，下一步是"把这一单存成预设单"，排在下一轮）。
 */
class OrderTemplatesViewModel(private val container: AppContainer) : ViewModel() {

    var rows by mutableStateOf<List<OrderTemplateDto>>(emptyList())
        private set
    var loading by mutableStateOf(true)
        private set
    var loadError by mutableStateOf<String?>(null)
    var actionResult by mutableStateOf<String?>(null)

    /** 正在确认删除的那一张（null = 没在确认）。危险操作一律二次确认。 */
    var pendingDelete by mutableStateOf<OrderTemplateDto?>(null)
        private set

    /**
     * 刚删掉的那一张 —— 界面据此显示「撤回」。
     *
     * 用户定的硬规矩：**删除一律软删 + 手边要有一个撤销入口**。
     * 所以删完不是一句"已删除"就完了，而是把"撤回"摆在同一个位置上。
     */
    var lastDeleted by mutableStateOf<OrderTemplateDto?>(null)
        private set

    fun load() {
        loading = rows.isEmpty()
        loadError = null
        viewModelScope.launch {
            try {
                rows = container.repo.orderTemplates()
            } catch (e: Exception) {
                loadError = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun askDelete(t: OrderTemplateDto) {
        pendingDelete = t
    }

    fun cancelDelete() {
        pendingDelete = null
    }

    fun confirmDelete() {
        val t = pendingDelete ?: return
        pendingDelete = null
        viewModelScope.launch {
            try {
                container.repo.deleteOrderTemplate(t.id)
                lastDeleted = t
                // ⚠️ 这里**不写 `actionResult`**：删除的回执由界面那条带「撤回」的
                //    snackbar 负责说（两处都说一句就是两条重复提示，用户不知道该点哪个）。
                load()
            } catch (e: Exception) {
                actionResult = toApiException(e).message
            }
        }
    }

    fun restoreLastDeleted() {
        val t = lastDeleted ?: return
        lastDeleted = null
        viewModelScope.launch {
            try {
                container.repo.restoreOrderTemplate(t.id)
                actionResult = "已恢复「${t.name}」"
                load()
            } catch (e: Exception) {
                actionResult = toApiException(e).message
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OrderTemplatesScreen(
    container: AppContainer,
    onBack: () -> Unit,
    onPlaceOrder: (OrderTemplateDto) -> Unit = {},
) {
    val vm: OrderTemplatesViewModel = appViewModel { OrderTemplatesViewModel(container) }
    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(Unit) { vm.load() }
    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })
    // 删完**立刻**给一个「撤回」（用户定的硬规矩：删除一律软删 + 手边要有一个撤销入口）。
    // ⚠️ 用 `showSnackbar(actionLabel = …)` 的返回值接这一下，⛔ 不要自己再画一个 `Snackbar`：
    //    两个宿主同时存在时，先画出来的那个会被后一个盖住（而后一个没有撤回按钮）。
    LaunchedEffect(vm.lastDeleted) {
        val t = vm.lastDeleted ?: return@LaunchedEffect
        val res = snackbar.showSnackbar(
            message = "已删除「${t.name}」",
            actionLabel = "撤回",
            withDismissAction = false,
        )
        if (res == SnackbarResult.ActionPerformed) vm.restoreLastDeleted()
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = { AppTopBar(title = "预订单", onBack = onBack) },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            when {
                vm.loading -> LoadingBox()
                vm.loadError != null -> ErrorView(vm.loadError.orEmpty(), onRetry = { vm.load() })
                else -> LazyColumn(
                    Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    item { ExplainerCard() }
                    if (vm.rows.isEmpty()) {
                        item {
                            EmptyView(
                                "还没有预订单" +
                                    "\n预设单＝把「以后还要照这样再下一遍」的那一单存下来" +
                                    "\n可以让 AI 帮你建一张（例如「建一张预设单：永盛食品每周单，红富士苹果 6 件」）",
                            )
                        }
                    }
                    items(vm.rows, key = { it.id }) { t ->
                        TemplateCard(
                            t = t,
                            onPlace = { onPlaceOrder(t) },
                            onDelete = { vm.askDelete(t) },
                        )
                    }
                }
            }
        }
    }

    vm.pendingDelete?.let { t ->
        AlertDialog(
            onDismissRequest = { vm.cancelDelete() },
            title = { Text("删除预设单") },
            text = { Text("「${t.name}」会从列表里消失（后台是伪装删除，删完还能撤回）。") },
            confirmButton = {
                TextButton(onClick = { vm.confirmDelete() }) {
                    Text("删除")
                }
            },
            dismissButton = {
                TextButton(onClick = { vm.cancelDelete() }) { Text("取消") }
            },
        )
    }
}

/** 顶上那张说明卡：这一页是什么、预设单里有什么、没有什么。 */
@Composable
private fun ExplainerCard() {
    SectionCard {
        Text("预设单是什么", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        Text(
            "把常用的那一单（货主 / 地址 / 收货人 / 商品与数量）存下来，下次点「用这张下单」" +
                "就把这些带进下单页 —— 参数还能改，最后按的还是下单页那个按钮。",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(4.dp))
        Text(
            "· 预设单不含单价：金额在下单那一刻按商品价算（价格会变，存旧价会按旧价下单）\n" +
                "· 预设运费只是参考值：运费在下单之后由派单那一步定（下单接口不收运费）",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/**
 * 一张预设单。
 *
 * 版式（与全项目一致）：**名字是主角**、次要信息是小灰字、动作横排——
 * 「删」在**最左**（相反操作）、「用这张下单」在**右**（主操作，右手够得着）。
 */
@Composable
private fun TemplateCard(t: OrderTemplateDto, onPlace: () -> Unit, onDelete: () -> Unit) {
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                Icons.Default.BookmarkAdded, contentDescription = null,
                modifier = Modifier.size(20.dp), tint = Color(TemplateBlue),
            )
            Spacer(Modifier.width(8.dp))
            Column(Modifier.weight(1f)) {
                Text(t.name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Text(
                    t.shipperName?.takeIf { it.isNotBlank() } ?: "货主：下单时再选",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(
                if (t.freightFee == null) "运费不预设" else "参考运费 ¥" + formatMoney(t.freightFee),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        if (t.address.isNotBlank()) {
            Spacer(Modifier.height(4.dp))
            InfoRow("送到", t.address)
        }
        if (t.receiverName.isNotBlank() || t.receiverPhone.isNotBlank()) {
            InfoRow("收货人", (t.receiverName + " " + t.receiverPhone).trim())
        }
        Spacer(Modifier.height(4.dp))
        Text(
            goodsText(t),
            style = MaterialTheme.typography.bodyMedium,
        )
        if (t.remark.isNotBlank()) {
            InfoRow("备注", t.remark)
        }
        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = onDelete, modifier = Modifier.height(40.dp)) {
                Icon(Icons.Default.DeleteOutline, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(4.dp))
                Text("删")
            }
            Spacer(Modifier.weight(1f))
            Button(onClick = onPlace, modifier = Modifier.height(40.dp)) {
                Icon(Icons.Default.AddShoppingCart, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(4.dp))
                Text("用这张下单")
            }
        }
    }
}

/**
 * 商品那一行怎么写。
 *
 * 最多列 3 样 + 「等 N 样」：预设单可能有 30 行，全列出来会把卡片撑到两屏
 * （而用户在这一页要认的是"哪一张"，不是逐行核对 —— 逐行核对在下单页做）。
 */
private fun goodsText(t: OrderTemplateDto): String {
    if (t.lines.isEmpty()) return "（这张预设单还没选商品）"
    val head = t.lines.take(GOODS_SHOWN).joinToString("、") { "${it.name}×${it.qty}" }
    val more = t.lines.size - GOODS_SHOWN
    return if (more > 0) "$head 等 ${t.lines.size} 样货" else head
}

/** 卡片上最多列几样货（见 [goodsText]）。 */
private const val GOODS_SHOWN = 3

/**
 * 「预订单」的语义色：**靛蓝**。
 *
 * 与工作台网格里已有的十几个语义色两两 RGB 距离 ≥60（判据在
 * `ui/nav/ModulesEntryTest.kt` 与 `_tools/qa/_check_adaptive_layout.py` 那一线）。
 * ⛔ 别改成接近 `ProductPurple`（紫）或 `ProgressYellow`（订单管理的黄）——
 * 前者是商品、后者是订单流转，两个都会让人认错格子。
 */
private const val TemplateBlue = 0xFF3949ABL
