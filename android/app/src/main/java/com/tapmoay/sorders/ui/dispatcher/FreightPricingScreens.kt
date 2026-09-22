package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.PriceChange
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.FreightCategoryDto
import com.tapmoay.sorders.data.remote.dto.FreightQuoteCandidateDto
import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.data.remote.dto.OrderFreightPriceRequest
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.util.formatMoney
import kotlinx.coroutines.launch
import com.tapmoay.sorders.ui.common.Hint

/**
 * **运费待定价**（2026-09-21 用户：「没有匹配到就没有计费、没有定价……这个订单就得我们那个
 * 派单员**手动去给他定价**。这个定价完之后，同理，他会**新增对应的地点/路线线路和对应的运费模板**，
 * 并且放到那个分类当中去」）。
 *
 * ⛔ 它**不是异常单**：`is_exception` 是派单员人工标的业务异常（货损/客户不要了…），
 *    而"还没定价"是一个**待办**。两件事混在一列，异常页就再也看不清了（用户选的也是这个口径）。
 *
 * 这一页只做一件事：把「已派单但没有运费」的单列出来，点一行 → 填一个数 → 存。
 * 存的时候可以顺手把这条**线路 + 价目**沉淀下来（勾选框），下次同样的单就自动带价了。
 */
class UnpricedOrdersViewModel(private val container: AppContainer) : ViewModel() {

    var orders by mutableStateOf<List<OrderDto>>(emptyList())
        private set
    var categories by mutableStateOf<List<FreightCategoryDto>>(emptyList())
        private set
    var loading by mutableStateOf(true)
        private set
    var error by mutableStateOf<String?>(null)
    var notice by mutableStateOf<String?>(null)

    /** 正在定价的那一单（null = 弹层没开）。 */
    var target by mutableStateOf<OrderDto?>(null)
    var draftFee by mutableStateOf("")
    var draftCategoryId by mutableStateOf<Long?>(null)
    var draftSaveTemplate by mutableStateOf(true)
    var draftPriceName by mutableStateOf("")
    var acting by mutableStateOf(false)
        private set

    /** 打开弹层时自动带出来的那句话：这个价是哪来的（司机规则 / 运费模板 / 没找到）。 */
    var quoteHint by mutableStateOf("")
        private set

    /** 同样优先的价目多于一条：后端**不猜**，列出来让派单员点一条带出。 */
    var quoteChoices by mutableStateOf<List<FreightQuoteCandidateDto>>(emptyList())
        private set

    init {
        load()
        viewModelScope.launch { runCatching { categories = container.repo.freightCategories() } }
    }

    fun load() {
        loading = true
        error = null
        viewModelScope.launch {
            try {
                orders = container.repo.unpricedOrders().rows
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun open(o: OrderDto) {
        target = o
        // 单上已经有分类就默认它（比如上一次定价定的），否则空着让派单员选
        draftCategoryId = o.freightCategoryId
        draftFee = o.freightFee ?: ""
        draftPriceName = ""
        draftSaveTemplate = true
        quoteHint = ""
        quoteChoices = emptyList()
        // 用户 2026-09-21（第二轮）：「他在带定价的时候**要么直接沿用司机已有规则**进行定价，
        // 要么假如以前没有规则的话，那就走**普通的定价规则**，就是这个模板的规则，它规一个分类」。
        // → 所以先按"这位司机的规则勾了哪些价目"问一次；那边没有，再退回"只看路线 + 分类"的模板层。
        // 两次都用同一个已存在的端点（`driver_id` 传 / 不传），**不新增后端逻辑**。
        viewModelScope.launch {
            val byRule = runCatching {
                container.repo.quoteFreight(o.id, driverId = o.driverId, categoryId = o.freightCategoryId)
            }.getOrNull()
            var q = byRule
            var fromRule = byRule?.matched != null
            if (byRule?.matched == null && o.driverId != null) {
                val plain = runCatching {
                    container.repo.quoteFreight(o.id, driverId = null, categoryId = o.freightCategoryId)
                }.getOrNull()
                if (plain?.matched != null) {
                    q = plain
                    fromRule = false
                }
            }
            val m = q?.matched
            val choices = q?.ambiguous.orEmpty()
            when {
                m != null -> {
                    // 单上本来就有数就不覆盖（人填过的优先），只把"哪来的"说清楚
                    if (draftFee.isBlank()) draftFee = m.fee
                    quoteHint = if (fromRule) {
                        "沿用这位司机的计费规则里勾的价目：" + quoteBrief(m) + "（已带出，可改）"
                    } else {
                        "他的规则里没勾到这条路线 —— 用运费模板里的价目：" + quoteBrief(m) + "（已带出，可改）"
                    }
                }
                choices.isNotEmpty() -> {
                    quoteChoices = choices
                    quoteHint = "有 " + choices.size + " 条价目同样优先（系统不猜），点一条带出："
                }
                else -> {
                    quoteHint = q?.reason?.takeIf { it.isNotBlank() }
                        ?: "没找到可用的价目 —— 填一个数，勾上「存成价目」下次自动带"
                }
            }
        }
    }

    /** 歧义时点一条候选 → 带出它的价格。 */
    fun pickQuote(c: FreightQuoteCandidateDto) {
        draftFee = c.fee
        quoteHint = "已选：" + quoteBrief(c) + "（可改）"
        quoteChoices = emptyList()
    }

    private fun quoteBrief(c: FreightQuoteCandidateDto) =
        (c.route.ifBlank { c.name }) + " ¥" + formatMoney(c.fee) +
            if (c.priceName.isBlank()) "" else "（" + c.priceName + "）"

    fun submit() {
        val o = target ?: return
        val fee = draftFee.trim().toDoubleOrNull()
        if (fee == null || fee < 0) {
            error = "请填写运费金额"
            return
        }
        acting = true
        error = null
        viewModelScope.launch {
            try {
                container.repo.priceFreight(
                    o.id,
                    OrderFreightPriceRequest(
                        freightFee = draftFee.trim(),
                        categoryId = draftCategoryId,
                        saveTemplate = draftSaveTemplate,
                        templateName = "",
                        priceName = draftPriceName.trim(),
                    ),
                )
                notice = if (draftSaveTemplate) {
                    "已定价 ¥" + formatMoney(draftFee) + "，并存成价目（下次同样的单自动带价）"
                } else {
                    "已定价 ¥" + formatMoney(draftFee)
                }
                target = null
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun UnpricedOrdersScreen(container: AppContainer, onBack: () -> Unit, onOpenOrder: (Long) -> Unit = {}) {
    val vm: UnpricedOrdersViewModel = appViewModel { UnpricedOrdersViewModel(container) }
    val snackbar = remember { SnackbarHostState() }
    OneShotSnackbar(snackbar, vm.notice, onConsumed = { vm.notice = null })
    OneShotSnackbar(snackbar, vm.error, onConsumed = { vm.error = null })

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background,
                ),
                title = { Text("运费待定价", style = MaterialTheme.typography.titleLarge) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
    ) { padding ->
        when {
            vm.loading -> LoadingBox(Modifier.padding(padding))
            vm.error != null && vm.orders.isEmpty() -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
            vm.orders.isEmpty() -> Column(
                Modifier.fillMaxSize().padding(padding),
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text("没有待定价的单", style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(6.dp))
                Text(
                    "已经派出去的单都有运费了。这里出现单子时，说明「线路 + 分类」还没配到价目。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = 32.dp),
                )
            }
            else -> LazyColumn(
                Modifier.fillMaxSize().padding(padding),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                item {
                    Text(
                        "这些单已经派出去了、但还没有运费（这就是它们的待办）。填一个数就结清；勾上「存成价目」的话，" +
                            "系统会把这条线路 + 这个分类的价目记下来（下次同样的单自动带价）。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                items(vm.orders, key = { it.id }) { o ->
                    SectionCard {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(
                                    (o.shipperName?.ifBlank { null } ?: o.tempShipperName?.ifBlank { null } ?: "未命名")
                                        + "  " + (o.driverName?.let { "· 司机 $it" } ?: ""),
                                    style = MaterialTheme.typography.titleSmall,
                                    fontWeight = FontWeight.Bold,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                )
                                Text(
                                    listOfNotNull(
                                        o.addressDetail.ifBlank { null },
                                        o.orderNo.ifBlank { null },
                                    ).joinToString(" · "),
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    maxLines = 2,
                                    overflow = TextOverflow.Ellipsis,
                                )
                            }
                            Spacer(Modifier.width(8.dp))
                            Text(
                                "待定价",
                                style = MaterialTheme.typography.labelLarge,
                                color = Color(0xFFFF6B2C),
                            )
                        }
                        Spacer(Modifier.height(6.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Button(onClick = { vm.open(o) }) {
                                Icon(Icons.Default.PriceChange, null, Modifier.size(18.dp))
                                Spacer(Modifier.width(4.dp))
                                Text("定价")
                            }
                            TextButton(onClick = { onOpenOrder(o.id) }) { Text("看订单") }
                        }
                    }
                }
            }
        }
    }

    vm.target?.let { o ->
        AlertDialog(
            onDismissRequest = { if (!vm.acting) vm.target = null },
            title = { Text("给这一单定价") },
            text = {
                Column(Modifier.verticalScroll(rememberScrollState())) {
                    Text(
                        (o.shipperName?.ifBlank { null } ?: "未命名") + " · " + o.addressDetail,
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    Spacer(Modifier.height(10.dp))
                    SoTextField(
                        vm.draftFee,
                        { vm.draftFee = InputRules.moneyInput(it) },
                        placeholder = "运费 ¥",
                        keyboardType = KeyboardType.Decimal,
                    )
                    // 这个价是哪来的（沿用司机规则 / 退回运费模板 / 没找到），一句话说清楚
                    if (vm.quoteHint.isNotBlank()) {
                        Spacer(Modifier.height(6.dp))
                        Text(
                            vm.quoteHint,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    // 同样优先多于一条时**不猜**：列出来，点一条就带出它的价
                    if (vm.quoteChoices.isNotEmpty()) {
                        Spacer(Modifier.height(4.dp))
                        vm.quoteChoices.forEach { c ->
                            Text(
                                "· " + (c.route.ifBlank { c.name }) + " ¥" + formatMoney(c.fee) +
                                    if (c.priceName.isBlank()) "" else "（" + c.priceName + "）",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.primary,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clickable { vm.pickQuote(c) },
                            )
                        }
                    }
                    Spacer(Modifier.height(10.dp))
                    Text("这一类货（计费规则按分类给钱时要用）", style = MaterialTheme.typography.labelMedium)
                    Spacer(Modifier.height(4.dp))
                    if (vm.categories.isEmpty()) {
                        Text(
                            "还没有运费分类（可在运费模板页的「分类管理」里建）",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    } else {
                        DropField(
                            label = "运费分类",
                            text = vm.categories.firstOrNull { it.id == vm.draftCategoryId }?.name ?: "不指定",
                            options = listOf("" to "不指定") + vm.categories.map { it.id.toString() to it.name },
                            onSelect = { vm.draftCategoryId = it.toLongOrNull() },
                        )
                    }
                    Spacer(Modifier.height(10.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(checked = vm.draftSaveTemplate, onCheckedChange = { vm.draftSaveTemplate = it })
                        Column(Modifier.weight(1f).clickable { vm.draftSaveTemplate = !vm.draftSaveTemplate }) {
                            Text("存成价目（下次自动带价）", style = MaterialTheme.typography.bodyMedium)
                            Text(
                                "会按这一单的送货地址建/找一条线路，把这条价目挂到上面",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                    if (vm.draftSaveTemplate) {
                        Hint(
                            "存好之后会自动勾进这位司机的计费规则（价目归规则，不绑司机）—— " +
                                "他还没挂规则的话，会提示你去给他挂一份再勾上。",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Spacer(Modifier.height(6.dp))
                        SoTextField(
                            vm.draftPriceName,
                            { vm.draftPriceName = it },
                            placeholder = "价目名（选填，如 小车价）",
                        )
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { vm.submit() }, enabled = !vm.acting) { Text("保存") }
            },
            dismissButton = { TextButton(onClick = { vm.target = null }, enabled = !vm.acting) { Text("取消") } },
        )
    }
}
