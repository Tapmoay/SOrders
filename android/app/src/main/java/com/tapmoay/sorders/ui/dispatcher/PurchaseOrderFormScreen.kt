package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
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
import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.data.remote.dto.PurchaseItemRequest
import com.tapmoay.sorders.data.remote.dto.PurchaseOrderCreateRequest
import com.tapmoay.sorders.data.remote.dto.PurchaseOrderUpdateRequest
import com.tapmoay.sorders.data.remote.dto.SupplierCreateRequest
import com.tapmoay.sorders.data.remote.dto.SupplierDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.util.formatMoney
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset
import kotlinx.coroutines.launch

/**
 * 「采购单」表单页（FEAT-0013 第三期，2026-10-04）：**新建与改单是同一页**。
 *
 * ## 这一页保存时会发生什么（用户最需要知道的一件事）
 * 后端在**同一个事务**里做三件事：库存加上去、这个商品的**成本价**按这次单价更新、
 * 给供应商记一张**应付单**。所以这一页不是"记一笔账"，它**真的改库存**。
 *
 * ## 改单的语义：整单替换
 * 保存时把当前列表里的行整个发回去（已有行带 `id`）。**在这个列表里被删掉的行 = 撤行** ——
 * 后端会把那条入库流水改成失效（`change=0`、状态 VOID）并把库存退回去。
 * 所以"删掉一行"与"把数量改成 0"不是一回事：前者是撤行，后者会被后端拒绝（数量要大于 0）。
 *
 * ## ⛔ 界面上不做金额运算
 * 行金额与整单合计都由后端算（口径只有一处：`backend/app/services/purchase_service.py`），
 * 这一页只把用户输的数量与单价原样发上去。
 */

/** 一行进货明细（草稿）。`itemId != null` = 服务端已有这一行（改单时要带着 id 回去）。 */
data class PurchaseDraftLine(
    val itemId: Long? = null,
    val productId: Long,
    val name: String,
    val unit: String,
    val quantity: String,
    val unitCost: String,
)

class PurchaseOrderFormViewModel(
    private val container: AppContainer,
    private val orderId: Long?,
) : ViewModel() {

    val isNew: Boolean get() = orderId == null

    var loading by mutableStateOf(false)
        private set
    var loadError by mutableStateOf<String?>(null)
    var saving by mutableStateOf(false)
        private set
    var actionResult by mutableStateOf<String?>(null)
    var saved by mutableStateOf(false)
        private set

    var supplierId by mutableStateOf<Long?>(null)
        private set
    var supplierName by mutableStateOf("")
        private set
    var docDate by mutableStateOf(LocalDate.now().toString())
        private set
    var remark by mutableStateOf("")
        private set
    var lines by mutableStateOf<List<PurchaseDraftLine>>(emptyList())
        private set

    /** 这一单那张应付单的两个数（后端算好的字符串）。只读不参与写回。 */
    var paidText by mutableStateOf("0.00")
        private set
    var unpaidText by mutableStateOf("0.00")
        private set

    var suppliers by mutableStateOf<List<SupplierDto>>(emptyList())
        private set
    var suppliersLoading by mutableStateOf(false)
        private set
    var products by mutableStateOf<List<ProductDto>>(emptyList())
        private set
    var productsLoading by mutableStateOf(false)
        private set

    private var started = false

    fun start() {
        if (started) return
        started = true
        loadSuppliers()
        loadProducts()
        if (orderId != null) loadOrder()
    }

    fun loadSuppliers() {
        viewModelScope.launch {
            suppliersLoading = true
            try {
                suppliers = container.repo.suppliers()
            } catch (e: Exception) {
                actionResult = toApiException(e).message
            } finally {
                suppliersLoading = false
            }
        }
    }

    fun loadProducts() {
        viewModelScope.launch {
            productsLoading = true
            try {
                // 含停用商品：进货常常是"这个不卖了但库里还有"（选品弹层里能看到停用标记）。
                products = container.repo.products(includeInactive = true)
            } catch (e: Exception) {
                actionResult = toApiException(e).message
            } finally {
                productsLoading = false
            }
        }
    }

    private fun loadOrder() {
        val id = orderId ?: return
        viewModelScope.launch {
            loading = true
            loadError = null
            try {
                val o = container.repo.purchaseOrder(id)
                supplierId = o.supplierId
                supplierName = o.supplierName
                if (o.docDate.isNotBlank()) docDate = o.docDate
                remark = o.remark
                paidText = o.payablePaid
                unpaidText = o.payableUnpaid
                // ⚠️ 只把**没撤的行**带进表单：撤掉的行本来就不算数（后端那边 `is_void`），
                //    带进来会让用户以为它还在，而保存时又会被整单替换逻辑当成撤行。
                lines = o.items.filter { !it.isVoid }.map {
                    PurchaseDraftLine(
                        itemId = it.id,
                        productId = it.productId,
                        name = it.productName,
                        unit = it.unit,
                        quantity = it.quantity.toString(),
                        unitCost = it.unitCost,
                    )
                }
            } catch (e: Exception) {
                loadError = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun setDate(d: String) {
        docDate = d
    }

    // 方法名不能叫 setRemark：属性 remark 的私有 setter 在 JVM 上就是 setRemark(String)，会撞签名
    fun updateRemark(t: String) {
        remark = t
    }

    fun pickSupplier(s: SupplierDto) {
        supplierId = s.id
        supplierName = s.name
    }

    /**
     * 就地新建一家供应商（CHG-0068 / 台账 L-40）：在选供应商的弹层里就能建，不用跑「供应商 / 厂商」页。
     *
     * 只送**名称 ＋ 电话**（用户 2026-10-07 拍板的"最小可建"：地址/备注以后到档案页补，
     * 弹窗底部已经写了这句话）。建完把名册重拉一遍、**顺手选中刚建的那一家** ——
     * 不然用户还得在列表里再找一遍自己刚建的东西。
     *
     * 重名由后端 `_check_name_free` 拦（400），这里把它那句人话原样显示，不自己另编一套。
     */
    fun createSupplierInline(name: String, phone: String, onCreated: (SupplierDto) -> Unit) {
        viewModelScope.launch {
            try {
                val s = container.repo.createSupplier(SupplierCreateRequest(name = name, phone = phone))
                loadSuppliers()
                pickSupplier(s)
                actionResult = "已建档案：${s.name}"
                onCreated(s)
            } catch (e: Exception) {
                actionResult = toApiException(e).message
            }
        }
    }

    /** 从选品弹层加行。单价由弹层按"这个商品上一次的进货价"预填（见 [lastCostOrBlank]）。 */
    fun addPicked(picked: List<PickedLine>) {
        if (picked.isEmpty()) return
        lines = lines + picked.map {
            PurchaseDraftLine(
                itemId = null,
                productId = it.productId,
                name = it.name,
                unit = it.unit,
                quantity = if (it.qty > 0) it.qty.toString() else "1",
                unitCost = it.price,
            )
        }
    }

    fun setQty(index: Int, v: String) {
        lines = lines.mapIndexed { i, l -> if (i == index) l.copy(quantity = v) else l }
    }

    fun setCost(index: Int, v: String) {
        lines = lines.mapIndexed { i, l -> if (i == index) l.copy(unitCost = v) else l }
    }

    /** 从表单里去掉一行。已有行去掉 = 保存时**撤行**（后端把那条流水作废、库存退回去）。 */
    fun removeLine(index: Int) {
        lines = lines.filterIndexed { i, _ -> i != index }
    }

    /**
     * 保存。新建走 `POST`，改单走 `PATCH`（`items` 整个给出 = 整单替换）。
     *
     * ⚠️ 下面这些"还没发请求就先说一句"的校验，与后端那几条 400 是**同一套口径**
     * （数量要大于 0、单价要大于 0）—— 最终判据仍然在后端；这里只是省一趟往返。
     */
    fun save() {
        val sid = supplierId
        if (sid == null) {
            // 不是报错，是**入口**：这句话会让提示条上长出「现在就建一家」（见 [NEED_SUPPLIER]）。
            actionResult = NEED_SUPPLIER
            return
        }
        if (lines.isEmpty()) {
            actionResult = "至少加一行进货商品"
            return
        }
        val items = ArrayList<PurchaseItemRequest>(lines.size)
        for ((i, l) in lines.withIndex()) {
            val qty = l.quantity.toIntOrNull()
            if (qty == null || qty < 1) {
                actionResult = "第 ${i + 1} 行「${l.name}」的数量要填一个大于 0 的整数"
                return
            }
            val cost = l.unitCost.trim()
            val costValue = cost.toDoubleOrNull()
            if (cost.isEmpty() || costValue == null || costValue <= 0.0) {
                actionResult = "第 ${i + 1} 行「${l.name}」的单价要填一个大于 0 的数"
                return
            }
            items.add(PurchaseItemRequest(id = l.itemId, productId = l.productId, quantity = qty, unitCost = cost))
        }
        saving = true
        viewModelScope.launch {
            try {
                val id = orderId
                if (id == null) {
                    container.repo.createPurchaseOrder(
                        PurchaseOrderCreateRequest(
                            supplierId = sid,
                            docDate = docDate,
                            remark = remark,
                            items = items,
                        )
                    )
                } else {
                    container.repo.updatePurchaseOrder(
                        id,
                        PurchaseOrderUpdateRequest(
                            supplierId = sid,
                            docDate = docDate,
                            remark = remark,
                            items = items,
                        )
                    )
                }
                saved = true
            } catch (e: Exception) {
                // 后端那句人话原样显示（"进货价要大于 0"、"库存不够…"、"改到小于已付…"）。
                actionResult = toApiException(e).message
            } finally {
                saving = false
            }
        }
    }
}

/**
 * 没选供应商时那句引导（CHG-0068 / 台账 L-40，用户 2026-10-07 拍板：「带一颗『现在就建一家』」）。
 *
 * ⛔ 它是**入口**不是报错：提示条上那颗按钮就是靠这句话认出来的（见 [PurchaseOrderFormScreen]
 *    里 `actionLabel = if (vm.actionResult == NEED_SUPPLIER)`）—— 改这句要连着改那一处。
 */
private const val NEED_SUPPLIER = "还没选供应商 —— 现在就建一家"

/** 金额一律"后端字符串 → 加个 ¥"，⛔ 客户端不做四则运算。 */
private fun yuan(s: String?): String = "¥" + formatMoney(s ?: "0")

/**
 * 选品弹层里给每行预填的单价：**这个商品上一次的进货价**。
 *
 * ⚠️ 成本价是 0（从没带价进过货）时**留空**，不要预填 0 —— 后端拒绝 0 价进货，
 *    预填 0 会让用户以为"这样就行"。
 */
private fun lastCostOrBlank(cost: String): String {
    val c = cost.trim()
    if (c.isEmpty()) return ""
    return if (c.all { it == '0' || it == '.' }) "" else c
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PurchaseOrderFormScreen(
    container: AppContainer,
    orderId: Long?,
    onBack: () -> Unit,
) {
    val vm: PurchaseOrderFormViewModel = appViewModel { PurchaseOrderFormViewModel(container, orderId) }
    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(Unit) { vm.start() }

    var showSupplierPicker by remember { mutableStateOf(false) }
    var showProductPicker by remember { mutableStateOf(false) }
    var showDatePicker by remember { mutableStateOf(false) }
    // 就地新建供应商（CHG-0068）：弹层里那颗「新建供应商」把这张表单打开。
    var creatingSupplier by remember { mutableStateOf(false) }

    // 只有"还没选供应商"那句带按钮：点一下直接开选供应商弹层，人不用退出去补档案。
    OneShotSnackbar(
        snackbar,
        vm.actionResult,
        onConsumed = { vm.actionResult = null },
        actionLabel = if (vm.actionResult == NEED_SUPPLIER) "现在就建一家" else null,
        onAction = { showSupplierPicker = true },
    )
    // 保存成功就回上一页（列表页每次进组合都会重拉，新单立刻出现在那儿）。
    LaunchedEffect(vm.saved) { if (vm.saved) onBack() }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            AppTopBar(
                title = if (vm.isNew) "新增采购单" else "改采购单 #${orderId ?: 0}",
                onBack = onBack,
            )
        },
        bottomBar = {
            Surface(color = MaterialTheme.colorScheme.surface) {
                PrimaryActionButton(
                    text = if (vm.isNew) "保存并入库" else "保存修改",
                    icon = Icons.Default.Check,
                    onClick = { vm.save() },
                    enabled = !vm.saving,
                    modifier = Modifier.fillMaxWidth().padding(16.dp),
                )
            }
        },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            when {
                vm.loading -> LoadingBox()
                vm.loadError != null -> ErrorView(vm.loadError.orEmpty(), onRetry = { vm.start() })
                else -> Column(
                    Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
                ) {
                    FormGroup(
                        icon = Icons.Default.ShoppingCart,
                        title = "这一单是谁供的货",
                        tint = Color(0xFF4CAF50),
                    ) {
                        FormPickRow(
                            label = "供应商",
                            value = vm.supplierName,
                            onClick = { showSupplierPicker = true },
                            required = true,
                            placeholder = "点这里选一家",
                            icon = Icons.Default.Storefront,
                            iconTint = Color(0xFF00B578),
                        )
                        FormPickRow(
                            label = "进货日期",
                            value = vm.docDate,
                            onClick = { showDatePicker = true },
                            required = true,
                            icon = Icons.Default.Event,
                            iconTint = Color(0xFF1E6FFF),
                        )
                        FormTextAreaRow(
                            label = "备注",
                            value = vm.remark,
                            onValueChange = { vm.updateRemark(it) },
                            placeholder = "选填：批号、送货人、结算方式",
                            icon = Icons.Default.Notes,
                        )
                    }

                    Spacer(Modifier.height(14.dp))

                    FormGroup(
                        icon = Icons.Default.Inventory2,
                        title = "进了哪些货（${vm.lines.size} 行）",
                        tint = Color(0xFF4CAF50),
                    ) {
                        if (vm.lines.isEmpty()) {
                            Text(
                                "还没加商品。点下面那行「加一行商品」从商品库里挑。",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.padding(horizontal = 14.dp, vertical = 8.dp),
                            )
                        }
                        vm.lines.forEachIndexed { i, line ->
                            PurchaseLineEditor(
                                index = i,
                                line = line,
                                onQty = { v -> vm.setQty(i, v) },
                                onCost = { v -> vm.setCost(i, v) },
                                onRemove = { vm.removeLine(i) },
                            )
                        }
                        FormActionRow(
                            label = "加一行商品",
                            onClick = { showProductPicker = true },
                            icon = Icons.Default.Add,
                            iconTint = Color(0xFF4CAF50),
                        )
                    }

                    if (!vm.isNew) {
                        Spacer(Modifier.height(14.dp))
                        FormGroup(
                            icon = Icons.Default.ReceiptLong,
                            title = "这一单的应付单",
                            tint = Color(0xFFE53935),
                        ) {
                            FormRow(label = "已付", icon = Icons.Default.Payments) {
                                Text(yuan(vm.paidText), style = MaterialTheme.typography.bodyLarge)
                            }
                            FormRow(label = "还差", icon = Icons.Default.Payments) {
                                Text(
                                    yuan(vm.unpaidText),
                                    style = MaterialTheme.typography.bodyLarge,
                                    fontWeight = FontWeight.SemiBold,
                                    color = MaterialTheme.colorScheme.error,
                                )
                            }
                            Text(
                                "改单后的金额不得小于已付；付过钱的单也不许换供应商 —— 后端会拒绝并说明原因。",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.padding(horizontal = 14.dp, vertical = 6.dp),
                            )
                        }
                    }

                    Spacer(Modifier.height(14.dp))

                    // 说明卡：这一页保存下去动的是三处钱（用户最容易忽略"它真的改库存"）。
                    SectionCard {
                        Text(
                            "保存时后端在同一个事务里做三件事",
                            style = MaterialTheme.typography.titleSmall,
                            fontWeight = FontWeight.SemiBold,
                        )
                        Spacer(Modifier.height(6.dp))
                        Text(
                            "① 库存按每一行的数量加上去；② 这个商品的成本价按这次单价更新；" +
                                "③ 给供应商记一张应付单。三件事要么一起成，要么一件都不做。" +
                                "改单时把某一行从列表里去掉 = 撤行：那条入库流水作废、库存退回去。",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Spacer(Modifier.height(24.dp))
                }
            }
        }
    }

    if (showSupplierPicker) {
        SupplierPickSheet(
            suppliers = vm.suppliers,
            loading = vm.suppliersLoading,
            onPick = { s ->
                vm.pickSupplier(s)
                showSupplierPicker = false;
            },
            onRetry = { vm.loadSuppliers() },
            // 建完**直接选中刚建的那家**、两个弹层一起关：回到采购单上，供应商那一栏已经填好了。
            onCreate = { creatingSupplier = true },
            onDismiss = { showSupplierPicker = false },
        )
    }

    if (creatingSupplier) {
        SupplierEditorDialog(
            initial = null,
            minimal = true,
            onDismiss = { creatingSupplier = false },
            onSave = { name, _, phone, _, _ ->
                vm.createSupplierInline(name, phone) {
                    creatingSupplier = false
                    showSupplierPicker = false
                }
            },
        )
    }

    if (showProductPicker) {
        ProductPickerSheet(
            products = vm.products,
            loading = vm.productsLoading,
            // 预填"上一次的进货价"（成本价是 0 = 从没带价进过货 ⇒ 留空，见 lastCostOrBlank）。
            priceFor = { p -> lastCostOrBlank(p.costPrice) },
            onConfirm = { picked ->
                vm.addPicked(picked)
                showProductPicker = false;
            },
            onDismiss = { showProductPicker = false },
            onRetry = { vm.loadProducts() },
        )
    }

    if (showDatePicker) {
        val dpState = rememberDatePickerState()
        DatePickerDialog(
            onDismissRequest = { showDatePicker = false },
            confirmButton = {
                TextButton(onClick = {
                    dpState.selectedDateMillis?.let { millis ->
                        // 与 `DateRangeDialog` 同一套换算（UTC 取日，避免时区把日期挪一天）。
                        vm.setDate(Instant.ofEpochMilli(millis).atZone(ZoneOffset.UTC).toLocalDate().toString())
                    }
                    showDatePicker = false;
                }) { Text("确定") }
            },
            dismissButton = { TextButton(onClick = { showDatePicker = false }) { Text("取消") } },
        ) {
            DatePicker(state = dpState)
        }
    }
}

/** 一行进货明细的编辑卡：行名 + 数量 + 单价（两个框都走 `InputRules`）。 */
@Composable
private fun PurchaseLineEditor(
    index: Int,
    line: PurchaseDraftLine,
    onQty: (String) -> Unit,
    onCost: (String) -> Unit,
    onRemove: () -> Unit,
) {
    SectionCard(Modifier.fillMaxWidth()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                "${index + 1}. ${line.name}",
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            if (line.itemId != null) {
                Text(
                    "已入库",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            TextButton(onClick = onRemove) { Text(if (line.itemId == null) "删掉" else "撤行") }
        }
        // ⚠️ 数量走 `InputRules.intInput`（只留数字、全角归一），⛔ 不在调用点手写过滤。
        FormInputRow(
            label = "数量",
            value = line.quantity,
            onValueChange = { onQty(InputRules.intInput(it, 7)) },
            keyboardType = KeyboardType.Number,
            placeholder = "0",
            // 用户点进来直接打 15 ⇒ 15（不是 115）。
            selectAllOnFocus = true,
            icon = Icons.Default.SwapVert,
            iconTint = Color(0xFF1E6FFF),
        )
        // ⚠️ 单价走 `InputRules.priceInput`（4 位小数）：它与 `products.cost_price` 是同一档
        //    精度 `Numeric(14,4)`，不是金额那档 2 位 —— 别合并（见 InputRules.PRICE_DECIMALS）。
        FormInputRow(
            label = "单价",
            value = line.unitCost,
            onValueChange = { onCost(InputRules.priceInput(it)) },
            keyboardType = KeyboardType.Decimal,
            placeholder = "0.00",
            icon = Icons.Default.Payments,
            iconTint = Color(0xFFE53935),
        )
        Text(
            "这一行的小计与整单合计都由后端算（界面上不做乘法）。",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 6.dp),
        )
    }
}

/**
 * 选供应商的底部弹层：能搜（供应商可能几十家）。
 *
 * [onCreate] 非空时底部多一颗「新建供应商」——**就地新建**（CHG-0068 / 台账 L-40：
 * 「没有建供应商的话他可以在这里直接选择新建供应商，省得又跑到那边去」）。
 * 空态那句话与这颗按钮指的是同一件事，别再写第二个入口。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SupplierPickSheet(
    suppliers: List<SupplierDto>,
    loading: Boolean,
    onPick: (SupplierDto) -> Unit,
    onRetry: () -> Unit,
    onCreate: (() -> Unit)? = null,
    onDismiss: () -> Unit,
) {
    var q by remember { mutableStateOf("") }
    val filtered = remember(suppliers, q) {
        if (q.isBlank()) suppliers else suppliers.filter { it.name.contains(q.trim(), ignoreCase = true) }
    }
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp)) {
            Text(
                "选供应商",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            Spacer(Modifier.height(10.dp))
            SearchField(value = q, onValueChange = { q = it }, placeholder = "搜供应商名字")
            Spacer(Modifier.height(10.dp))
            when {
                loading -> LoadingBox(Modifier.height(160.dp))
                suppliers.isEmpty() -> {
                    // 空态本身就是入口（下面那颗「新建供应商」）—— 不再支使人跑去别的页面。
                    EmptyView("还没有供应商 —— 现在就建一家")
                    Spacer(Modifier.height(8.dp))
                    TextButton(onClick = onRetry) { Text("重新加载") }
                }
                filtered.isEmpty() -> EmptyView("没有名字里带「${q.trim()}」的供应商")
                else -> LazyColumn(
                    Modifier.fillMaxWidth().heightIn(max = 420.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(filtered, key = { it.id }) { s ->
                        Surface(
                            modifier = Modifier.fillMaxWidth().clickable { onPick(s) },
                            shape = MaterialTheme.shapes.medium,
                            color = MaterialTheme.colorScheme.surfaceContainerLow,
                        ) {
                            Column(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 12.dp)) {
                                Text(
                                    s.name.ifBlank { "供应商 #${s.id}" },
                                    // 定死宽度：名字太长时省略号在**这一行内部**截断，
                                    // 而不是让这一行被挤瘪（Column 里挂不了 vertical weight）。
                                    modifier = Modifier.fillMaxWidth(),
                                    style = MaterialTheme.typography.bodyLarge,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                )
                                if (s.contactName.isNotBlank() || s.phone.isNotBlank()) {
                                    Text(
                                        listOf(s.contactName, s.phone).filter { it.isNotBlank() }.joinToString(" · "),
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                            }
                        }
                    }
                }
            }
            if (onCreate != null) {
                Spacer(Modifier.height(4.dp))
                TextButton(onClick = onCreate) { Text("新建供应商") }
            }
            Spacer(Modifier.height(16.dp))
        }
    }
}