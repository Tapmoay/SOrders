package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.snapshots.SnapshotStateList
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.OrderTemplateCategoryDto
import com.tapmoay.sorders.data.remote.dto.OrderTemplateCreateRequest
import com.tapmoay.sorders.data.remote.dto.OrderTemplateLineDto
import com.tapmoay.sorders.data.remote.dto.OrderTemplateUpdateRequest
import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.data.remote.dto.UserDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.shipper.LineDraft
import com.tapmoay.sorders.ui.shipper.MAX_ORDER_LINES
import com.tapmoay.sorders.ui.shipper.mergePickedIntoLines
import kotlinx.coroutines.launch

/**
 * 「新建 / 编辑预订单」——**单独一页**（用户 2026-09-22：「**还可以新建一个订单**」）。
 *
 * ## 为什么是单独一页，不是弹窗/抽屉
 * 这一页要做的事与**下单页**是同一类：选货主、选地址、挑一组商品与数量。
 * 那种表单在弹窗里塞不下（选品页自己就是一个全屏弹层）。先例照「新增开销＝单独一页」。
 *
 * ## 三条边界（与预订单页、后端同一套，别越界）
 * 1. **不存单价**：这一页挑了商品与数量，**一个价都不发**（`OrderTemplateLineDto` 里根本没有价）。
 *    金额在下单那一刻按「商品价 / 这个货主的专属价」现算 —— 所以选品页在这一页**不报价**
 *    （`ProductPickerSheet(showPrice = false)`）：画一个不会入库的价，只会让人以为它被存下来了。
 * 2. **参考运费只是参考值**：下单接口根本不收运费（运费是派单那一步按价目算的）。
 *    所以那一行的说明是「下单时由派单那一步定」，⛔ 不许写成"下单就按这个收"。
 * 3. **空 ≠ 0**：运费留空 = 不预设；填 0 = 免运费（两件事，后端也是两件事）。
 */
class OrderTemplateFormViewModel(private val container: AppContainer) : ViewModel() {

    /** 正在编辑哪一张（null = 新建）。 */
    var editingId by mutableStateOf<Long?>(null)
        private set

    var name by mutableStateOf("")
    /** 分类名（空串 = 未分类）。名册里没有的名字由后端补进名册。 */
    var category by mutableStateOf("")
    var shipperId by mutableStateOf<Long?>(null)
    var originAddress by mutableStateOf("")
    var address by mutableStateOf("")
    var receiverName by mutableStateOf("")
    var receiverPhone by mutableStateOf("")
    var remark by mutableStateOf("")
    /** 参考运费（空串 = 不预设）。 */
    var freightFee by mutableStateOf("")

    /** 商品明细：**复用下单页那一份 `LineDraft` 与合并规则**（同一件累加、超限整批拒绝）。 */
    val lines: SnapshotStateList<LineDraft> = mutableStateListOf()

    var categories by mutableStateOf<List<OrderTemplateCategoryDto>>(emptyList())
        private set
    var shippers by mutableStateOf<List<UserDto>>(emptyList())
        private set
    var products by mutableStateOf<List<ProductDto>>(emptyList())
        private set
    var productCategoryOrder by mutableStateOf<List<String>>(emptyList())
        private set

    var loading by mutableStateOf(true)
        private set
    var saving by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
    var showPicker by mutableStateOf(false)
    var showCategoryPicker by mutableStateOf(false)
    var showShipperPicker by mutableStateOf(false)

    /** 保存成功（界面据此回上一页）。 */
    var done by mutableStateOf(false)
        private set

    init {
        viewModelScope.launch {
            try {
                categories = container.repo.orderTemplateCategories()
                shippers = container.repo.shippers()
                products = container.repo.products()
                productCategoryOrder = container.repo.productCategories().map { it.name }
            } catch (_: Exception) {
                // 名册/商品拉不到不该把整页打死：用户还能填名称与地址，
                // 保存时后端会照常校验（错误会落在 `error` 那一行上）。
            } finally {
                loading = false
            }
        }
    }

    /** 按 id 载入一张预设单（编辑）；null = 新建（把上一次的状态清干净）。 */
    fun start(templateId: Long?) {
        if (editingId == templateId && templateId != null) return
        editingId = templateId
        if (templateId == null) return
        viewModelScope.launch {
            try {
                val t = container.repo.orderTemplates().firstOrNull { it.id == templateId }
                if (t == null) {
                    error = "这张预设单已经不在了（可能刚被删掉）"
                    return@launch
                }
                name = t.name
                category = t.category
                shipperId = t.shipperId
                originAddress = t.originAddress
                address = t.address
                receiverName = t.receiverName
                receiverPhone = t.receiverPhone
                remark = t.remark
                freightFee = t.freightFee?.trim().orEmpty()
                lines.clear()
                t.lines.forEach { ln ->
                    lines.add(
                        LineDraft(
                            productId = ln.productId,
                            name = ln.name,
                            quantity = ln.qty,
                            // ⚠️ 价一律空串：预设单里没有价，也不显示价（见文件头第 1 条）
                            price = "",
                            unit = ln.unit.ifBlank { "件" },
                        ),
                    )
                }
            } catch (e: Exception) {
                error = toApiException(e).message
            }
        }
    }

    /** 这一页用的分类下拉项：**未分类** + 名册（名册里没有当前分类时也补上，见下）。 */
    fun categoryOptions(): List<String> {
        val opts = mutableListOf("")
        categories.map { it.name }.forEach { if (it !in opts) opts += it }
        // ⚠️ 当前分类不在名册里（老数据 / 别的路径写进去的）也要能显示出来：
        //    不补的话下拉里没有任何一项是选中的，用户一保存就把分类**悄悄改了**。
        val cur = category.trim()
        if (cur.isNotEmpty() && cur !in opts) opts += cur
        return opts
    }

    fun shipperLabel(): String =
        shippers.firstOrNull { it.id == shipperId }?.let { it.fullName.ifBlank { it.phone } } ?: "下单时再选"

    fun addPicked(picked: List<PickedLine>): Boolean {
        if (picked.isEmpty()) return false
        val merged = mergePickedIntoLines(lines, picked)
        if (merged == null) {
            error = "一张预订单最多 $MAX_ORDER_LINES 组商品，请少选几件"
            return false
        }
        lines.clear()
        lines.addAll(merged)
        error = null
        return true
    }

    fun removeLine(index: Int) {
        if (index in lines.indices) lines.removeAt(index)
    }

    fun setQty(index: Int, qty: Int) {
        if (index in lines.indices) {
            lines[index] = lines[index].copy(quantity = qty.coerceIn(1, 99_999))
        }
    }

    fun save() {
        val cleanName = name.trim()
        val phoneError = InputRules.phoneError(receiverPhone.trim())
        when {
            cleanName.isEmpty() -> {
                error = "请填写这张预订单的名字（例如「永盛食品每周单」）"
                return
            }
            phoneError != null -> {
                error = phoneError
                return
            }
            lines.isEmpty() -> {
                error = "至少选一样商品 —— 预设单就是「以后照这样再下一遍」的那一单"
                return
            }
        }
        val feeText = freightFee.trim()
        val linesDto = lines.map {
            OrderTemplateLineDto(
                productId = it.productId,
                name = it.name,
                unit = it.unit,
                qty = it.quantity,
            )
        }
        saving = true
        error = null
        viewModelScope.launch {
            try {
                val id = editingId
                if (id == null) {
                    container.repo.createOrderTemplate(
                        OrderTemplateCreateRequest(
                            name = cleanName,
                            shipperId = shipperId,
                            category = category.trim(),
                            originAddress = originAddress.trim(),
                            address = address.trim(),
                            receiverName = receiverName.trim(),
                            receiverPhone = receiverPhone.trim(),
                            // ⚠️ 空串 = 不预设（后端 `_money("")` → None）；它**必须发出去**，
                            //    否则"把参考运费改回不预设"这个操作永远做不到。
                            freightFee = feeText,
                            remark = remark.trim(),
                            lines = linesDto,
                        ),
                    )
                } else {
                    container.repo.updateOrderTemplate(
                        id,
                        OrderTemplateUpdateRequest(
                            name = cleanName,
                            shipperId = shipperId,
                            // ⚠️ 空串 = 移到未分类，是一个**真实操作**，照发（后端按"键出现就写"判）
                            category = category.trim(),
                            originAddress = originAddress.trim(),
                            address = address.trim(),
                            receiverName = receiverName.trim(),
                            receiverPhone = receiverPhone.trim(),
                            freightFee = feeText,
                            remark = remark.trim(),
                            lines = linesDto,
                            // 显式清空货主（Android 的 explicitNulls=false 会把 null 丢掉）
                            clearShipper = shipperId == null,
                        ),
                    )
                }
                done = true
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                saving = false
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OrderTemplateFormScreen(
    container: AppContainer,
    templateId: Long?,
    onBack: () -> Unit,
    onSaved: () -> Unit,
) {
    val vm: OrderTemplateFormViewModel = appViewModel { OrderTemplateFormViewModel(container) }
    LaunchedEffect(templateId) { vm.start(templateId) }
    LaunchedEffect(vm.done) { if (vm.done) onSaved() }

    val editing = templateId != null
    Scaffold(
        topBar = { AppTopBar(title = if (editing) "编辑预订单" else "新建预订单", onBack = onBack) },
        bottomBar = {
            Surface(shadowElevation = 8.dp) {
                Row(
                    Modifier.fillMaxWidth().navigationBarsPadding().padding(16.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    PrimaryActionButton(
                        text = if (vm.saving) "保存中…" else "保存",
                        onClick = { vm.save() },
                        enabled = !vm.saving,
                        containerColor = Color(TemplateBlue),
                        icon = Icons.Default.Check,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }
        },
    ) { padding ->
        if (vm.loading) {
            Box(Modifier.fillMaxSize().padding(padding)) { LoadingBox() }
            return@Scaffold
        }
        Column(Modifier.fillMaxSize().padding(padding)) {
            LazyColumn(
                Modifier.weight(1f),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                item {
                    FormGroup(Icons.Default.BookmarkAdded, "这张预订单是什么", Color(TemplateBlue)) {
                        FormInputRow(
                            label = "名字",
                            value = vm.name,
                            onValueChange = { vm.name = it },
                            placeholder = "例如：永盛食品每周单",
                            required = true,
                            icon = Icons.Default.Label,
                        )
                        FormPickRow(
                            label = "分类",
                            value = vm.category.ifBlank { "未分类" },
                            onClick = { vm.showCategoryPicker = true },
                            placeholder = "未分类",
                            icon = Icons.Default.Folder,
                        )
                        // 「预设单是什么」这句解释按提示的形式给（总开关关掉就不显示）——
                        // 用户 2026-09-22：「这个解释没必要…绑到那个提示当中」。
                        Hint(
                            "分类只影响这一页左边那一列怎么分组；不选就是「未分类」",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
                item {
                    FormGroup(Icons.Default.LocalShipping, "这一单送给谁、送到哪", Color(0xFF00A2C7)) {
                        FormPickRow(
                            label = "货主",
                            value = vm.shipperLabel(),
                            onClick = { vm.showShipperPicker = true },
                            placeholder = "下单时再选",
                            icon = Icons.Default.Person,
                        )
                        FormInputRow(
                            label = "送到",
                            value = vm.address,
                            onValueChange = { vm.address = it },
                            placeholder = "送货地址",
                            icon = Icons.Default.Place,
                            iconTint = Color(0xFF1E6FFF),
                        )
                        FormInputRow(
                            label = "起点",
                            value = vm.originAddress,
                            onValueChange = { vm.originAddress = it },
                            placeholder = "可选，从哪出发",
                            icon = Icons.Default.TripOrigin,
                        )
                        FormInputRow(
                            label = "收货人",
                            value = vm.receiverName,
                            onValueChange = { vm.receiverName = it },
                            placeholder = "收货人姓名",
                            icon = Icons.Default.Badge,
                        )
                        FormInputRow(
                            label = "收货人电话",
                            value = vm.receiverPhone,
                            onValueChange = { vm.receiverPhone = InputRules.phoneInput(it) },
                            // ⚠️ 提示语与下单页同一句（`请输入手机号`），⛔ 不要写成"收货人电话"：
                            //    提示语里同时出现"人"和"电话"会被 `_check_user_search.py` 认成
                            //    **按人搜索框**（那一类必须走共用的 `SearchField`）—— 这是个输入框。
                            placeholder = "请输入手机号",
                            keyboardType = androidx.compose.ui.text.input.KeyboardType.Phone,
                            icon = Icons.Default.Phone,
                            iconTint = Color(0xFF00B578),
                        )
                        FormInputRow(
                            label = "参考运费",
                            value = vm.freightFee,
                            onValueChange = { vm.freightFee = InputRules.moneyInput(it) },
                            placeholder = "留空 = 不预设",
                            keyboardType = androidx.compose.ui.text.input.KeyboardType.Decimal,
                            icon = Icons.Default.Payments,
                            iconTint = Color(0xFFFF9500),
                        )
                        // ⛔ 这两句是**业务事实**，不能丢（预订单页那份说明搬到这里来）：
                        //    它们解释的是"为什么这一页没有价、为什么运费只是个参考"。
                        Hint(
                            "预设单不含单价：金额在下单那一刻按商品价算（价格会变，存旧价会按旧价下单）",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Hint(
                            "预设运费只是参考值：运费在下单之后由派单那一步定（下单接口不收运费）",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
                item {
                    FormGroup(Icons.Default.Inventory2, "商品与数量", Color(0xFF8455E6)) {
                        FormActionRow(
                            label = if (vm.lines.isEmpty()) "选商品" else "继续添加商品",
                            onClick = { vm.showPicker = true },
                            icon = Icons.Default.AddShoppingCart,
                            iconTint = Color(0xFF8455E6),
                        )
                        if (vm.lines.isEmpty()) {
                            // ⚠️ 这句是**空态文案**（"这里现在是空的、去哪加"），按 `docs/HINT_STYLE.md` §2
                            //    属"永远显示"那一类 —— 藏掉之后这一块就一片空白，
                            //    "还没选"与"选了但没显示出来"就分不出来了。所以是 `Text` 不是 `Hint`。
                            Text(
                                "点上面那一行挑商品 —— 只记哪几样、各多少，不记价",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        vm.lines.forEachIndexed { i, ln ->
                            LineQtyRow(
                                name = ln.name,
                                unit = ln.unit,
                                qty = ln.quantity,
                                onQty = { vm.setQty(i, it) },
                                onRemove = { vm.removeLine(i) },
                            )
                        }
                    }
                }
                item {
                    FormGroup(Icons.Default.EditNote, "备注", Color(0xFF8A8A8E)) {
                        FormTextAreaRow(
                            label = "备注",
                            value = vm.remark,
                            onValueChange = { vm.remark = it },
                            placeholder = "可选，例如「每周三早上送」",
                        )
                    }
                }
                item { FormErrorLine(vm.error) }
            }
        }
    }

    if (vm.showPicker) {
        ProductPickerSheet(
            products = vm.products,
            loading = false,
            // ⚠️ 不报价（见文件头第 1 条）。`priceFor` 在这种情况下不会被读去显示，
            //    但接口要求给一个 —— 给商品库默认售价即可，⛔ 不要在这里算专属价：
            //    那是**下单页**的口径（唯一一处 `priceFor`），在这儿再算一份就是第二个口径。
            priceFor = { it.defaultUnitPrice },
            onConfirm = { picked ->
                vm.showPicker = false
                vm.addPicked(picked)
            },
            onDismiss = { vm.showPicker = false },
            categoryOrder = vm.productCategoryOrder,
            showPrice = false,
        )
    }

    if (vm.showCategoryPicker) {
        PickerSheet(
            title = "选分类",
            options = vm.categoryOptions(),
            labelOf = { if (it.isBlank()) "未分类" else it },
            selectedOf = { it == vm.category.trim() },
            onPick = { vm.category = it; vm.showCategoryPicker = false },
            onDismiss = { vm.showCategoryPicker = false },
        )
    }

    if (vm.showShipperPicker) {
        PickerSheet(
            title = "选货主",
            options = listOf("") + vm.shippers.map { it.id.toString() },
            labelOf = { key ->
                if (key.isBlank()) "下单时再选"
                else vm.shippers.firstOrNull { it.id.toString() == key }
                    ?.let { it.fullName.ifBlank { it.phone } + "（" + it.phone + "）" } ?: key
            },
            selectedOf = { key -> if (key.isBlank()) vm.shipperId == null else key == vm.shipperId.toString() },
            onPick = { key ->
                vm.shipperId = key.toLongOrNull()
                vm.showShipperPicker = false
            },
            onDismiss = { vm.showShipperPicker = false },
        )
    }
}

/**
 * 商品明细里的一行：**名称 + 单位 + 数量步进 + 删**。
 *
 * ⚠️ 这里**没有单价**（也不许有）：预订单不存价，见文件头第 1 条。
 * 数量的加减是就地改草稿，保存时才整份提交。
 */
@Composable
private fun LineQtyRow(
    name: String,
    unit: String,
    qty: Int,
    onQty: (Int) -> Unit,
    onRemove: () -> Unit,
) {
    FormRow(label = "") {
        Text(
            name.ifBlank { "未命名商品" },
            style = MaterialTheme.typography.bodyLarge,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier.weight(1f),
        )
        IconButton(onClick = { onQty(qty - 1) }) {
            Icon(Icons.Default.Remove, contentDescription = "减", modifier = Modifier.size(18.dp))
        }
        Text(
            "$qty " + unit.ifBlank { "件" },
            style = MaterialTheme.typography.bodyLarge,
            fontWeight = FontWeight.Bold,
            color = Color(0xFF1E6FFF),
        )
        IconButton(onClick = { onQty(qty + 1) }) {
            Icon(Icons.Default.Add, contentDescription = "加", modifier = Modifier.size(18.dp))
        }
        IconButton(onClick = onRemove) {
            Icon(
                Icons.Default.DeleteOutline, contentDescription = "删掉这一行",
                tint = MaterialTheme.colorScheme.error, modifier = Modifier.size(18.dp),
            )
        }
    }
}

/**
 * 一个通用的"选一项"底部弹层（分类 / 货主共用）。
 *
 * 做成一个共用的壳而不是两段各写一遍：两处的差别只有"选项从哪来、怎么显示"
 * （`options` / `labelOf` / `selectedOf`），摆两次就会各自跑偏。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun PickerSheet(
    title: String,
    options: List<String>,
    labelOf: (String) -> String,
    selectedOf: (String) -> Boolean,
    onPick: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
    ) {
        Column(Modifier.fillMaxWidth().padding(bottom = 24.dp)) {
            Text(
                title,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                modifier = Modifier.padding(start = 20.dp, bottom = 8.dp),
            )
            LazyColumn {
                itemsIndexed(options) { _, key ->
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .clickable { onPick(key) }
                            .padding(horizontal = 20.dp, vertical = 14.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(labelOf(key), style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
                        if (selectedOf(key)) {
                            Icon(
                                Icons.Default.Check, contentDescription = "已选中",
                                tint = Color(TemplateBlue), modifier = Modifier.size(20.dp),
                            )
                        }
                    }
                }
            }
        }
    }
}
