package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.InventoryMovementDto
import com.tapmoay.sorders.data.remote.dto.InventorySummaryItemDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.util.formatDateTime
import com.tapmoay.sorders.ui.common.Hint

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun InventoryScreen(
    container: AppContainer,
    onBack: () -> Unit,
) {
    val vm: InventoryViewModel = appViewModel { InventoryViewModel(container) }
    val snackbar = remember { SnackbarHostState() }
    var showMovements by remember { mutableStateOf(false) }

    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = { Text("库存管理") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    IconButton(onClick = { vm.refresh() }) {
                        Icon(Icons.Default.Refresh, contentDescription = "刷新")
                    }
                    TextButton(onClick = { showMovements = true }) { Text("流水") }
                },
            )
        },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            when {
                vm.loading -> LoadingBox()
                vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
                vm.summary.isEmpty() -> EmptyView("暂无商品，请先在商品管理中创建", Modifier.align(Alignment.Center))
                else -> InventoryBody(vm)
            }
        }
    }

    // 出入库弹窗
    if (vm.showMovementDialog) {
        AlertDialog(
            onDismissRequest = { vm.showMovementDialog = false },
            title = { Text(if (vm.movementInbound) "入库" else "出库") },
            text = {
                Column {
                    Text(
                        "商品：" + (vm.movementProduct?.productName ?: "") +
                            "（当前库存 " + (vm.movementProduct?.stock ?: 0) + "）",
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    Spacer(Modifier.height(10.dp))
                    SoTextField(
                        vm.movementQty,
                        { vm.movementQty = InputRules.intInput(it, 6) },
                        placeholder = "数量",
                        keyboardType = KeyboardType.Number,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(Modifier.height(8.dp))
                    SoTextField(
                        vm.movementNote,
                        { vm.movementNote = it },
                        placeholder = "备注（如供应商/用途）",
                        modifier = Modifier.fillMaxWidth(),
                    )
                    // 进货价：**只在入库时给**（用户 2026-09-19：「包括进货的时候也要输入成本价，
                    // 因为可能这个时间的进货和那个时间进货的成本价是不一样的」）。
                    // ⚠️ 它现在做**两件**事，说明文字必须两件都写：这一批的价记进流水
                    //    （毛利按入库流水的平均进货价算），同时把商品成本价更新成它。
                    //    只说后半句的话，用户会以为它只影响"下一个报价"，想不到它会改毛利。
                    if (vm.movementInbound) {
                        Spacer(Modifier.height(8.dp))
                        SoTextField(
                            vm.movementCost,
                            // 单价规则唯一实现在 core/InputRules.kt（4 位小数：成本价列是 Numeric(14,4)）
                            { vm.movementCost = InputRules.priceInput(it) },
                            placeholder = "进货价（选填，￥/单位）",
                            keyboardType = KeyboardType.Decimal,
                            modifier = Modifier.fillMaxWidth(),
                        )
                        Spacer(Modifier.height(4.dp))
                        Hint(
                            "填了就把这一批的进货价记下来（毛利率按入库的平均进货价算），" +
                                "并把商品成本价更新成它；不填只改库存。",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    if (!vm.movementInbound) {
                        Spacer(Modifier.height(6.dp))
                        Text(
                            "出库数量不能超过当前库存 " + (vm.movementProduct?.stock ?: 0),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { vm.confirmMovement() }, enabled = !vm.acting) {
                    Text(if (vm.acting) "处理中…" else "确认" + (if (vm.movementInbound) "入库" else "出库"))
                }
            },
            dismissButton = { TextButton(onClick = { vm.showMovementDialog = false }) { Text("取消") } },
        )
    }

    // 流水弹层
    if (showMovements) {
        ModalBottomSheet(onDismissRequest = { showMovements = false }) {
            Column(Modifier.padding(horizontal = 20.dp).padding(bottom = 32.dp)) {
                Text("出入库流水", style = MaterialTheme.typography.titleLarge)
                Spacer(Modifier.height(10.dp))
                DateRangeFilter(onChange = vm::applyMovFilter)
                Spacer(Modifier.height(8.dp))
                if (vm.movements.isEmpty()) {
                    Text(
                        "暂无流水记录",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(vertical = 24.dp),
                    )
                } else {
                    // 截断必须**说出来**：判据是响应头 `X-Truncated`（2026-09-19 后端补的头），
                    // 不再用"这一页满了"去猜（见 InventoryViewModel）。
                    // 出路就是上面那个日期筛选——所以这句话里直接点名它，用户不用自己找。
                    if (vm.movementsTruncated) {
                        TruncationNote(
                            limit = vm.movementsLimit,
                            howToSeeMore = "更早的请用上方日期筛选",
                            modifier = Modifier.padding(bottom = 6.dp),
                        )
                    }
                    LazyColumn(Modifier.heightIn(max = 420.dp)) {
                        items(vm.movements, key = { it.id }) { m ->
                            MovementRow(m)
                        }
                    }
                }
            }
        }
    }
}

/**
 * 库存页主体：**左边分类、右边商品**（用户 2026-09-19：
 * 「库存管理也是跟商品管理一样的，左边是分类右边是商品，并且可以通过搜索名称来搜索商品，
 *   来盘查实时库存是怎样的」）。
 *
 * ## 版式为什么要跟商品管理一致
 * 两页看的是**同一批商品**、做的是同一件事的两个阶段（一个是维护、一个是看库存）。
 * 版式一致之后，"左边那一列"在两个页面里是同一个东西、同一个顺序 ——
 * 用户不用重新学一遍怎么找商品。分类导航条与判据都复用
 * `ui/common/ProductPicker.kt` 的 `CategoryRail` / `categoryTabsOf` / `categoryNameOf`
 * （**不许各写一份**：各写一份就会出现"同一件商品在商品管理页属于日化、在库存页属于未分类"）。
 *
 * ## 搜索为什么放在分类上面（全宽）
 * 它和左边那列是**两个维度**：分类是"这一块有哪些商品"，搜索是"那个商品在哪"。
 * 放进右边那一栏会让它被压成半宽、而且分类为空时它跟着消失 —— 而"找不到某件商品"
 * 恰恰是最需要搜索的时候。所以它横跨整页，任何时候都在。
 */
@Composable
private fun InventoryBody(vm: InventoryViewModel) {
    // 左侧分类：顺序由名册定（与商品管理/选品页同一处实现）
    val cats = remember(vm.summary, vm.categories) {
        categoryTabsOf(vm.summary.map { it.category }, vm.categories.map { it.name })
    }
    var category by remember { mutableStateOf(ALL_CATEGORY) }
    // 选中的分类可能因为改名/商品改分类而消失 → 退回「全部」，
    // 否则用户会停在一个导航条上已不存在的分类上、右边一片空白且无法解释
    LaunchedEffect(cats) {
        if (category !in cats) category = ALL_CATEGORY
    }
    val keyword = vm.query.trim()
    val visible = remember(vm.summary, category, keyword) {
        vm.summary.filter { s ->
            (category == ALL_CATEGORY || categoryNameOf(s.category) == category) &&
                (keyword.isEmpty() || s.productName.contains(keyword, ignoreCase = true))
        }
    }

    Column(Modifier.fillMaxSize()) {
        OutlinedTextField(
            value = vm.query,
            onValueChange = { vm.query = it },
            placeholder = { Text("搜索商品名称，查实时库存", style = MaterialTheme.typography.bodySmall) },
            leadingIcon = { Icon(Icons.Default.Search, contentDescription = null, modifier = Modifier.size(20.dp)) },
            trailingIcon = {
                if (vm.query.isNotEmpty()) {
                    IconButton(onClick = { vm.query = "" }) {
                        Icon(Icons.Default.Close, contentDescription = "清空搜索", modifier = Modifier.size(18.dp))
                    }
                }
            },
            singleLine = true,
            textStyle = MaterialTheme.typography.bodyMedium,
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
        )
        Row(Modifier.weight(1f)) {
            CategoryRail(
                tabs = cats,
                selected = category,
                onSelect = { category = it },
                modifier = Modifier.width(92.dp).fillMaxHeight(),
            )
            Box(Modifier.weight(1f).fillMaxHeight()) {
                if (visible.isEmpty()) {
                    // 「搜不到」和「这一类是空的」是两句不同的话：说不清用户会以为商品丢了
                    EmptyView(
                        if (keyword.isNotEmpty()) "没有名称含「$keyword」的商品" else "「$category」下暂无商品",
                        Modifier.align(Alignment.Center),
                    )
                } else {
                    LazyColumn(
                        Modifier.fillMaxSize(),
                        contentPadding = PaddingValues(start = 10.dp, end = 10.dp, top = 10.dp, bottom = 12.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        item {
                            Text(
                                "共 " + visible.size + " 个商品" +
                                    if (keyword.isNotEmpty()) "（搜索结果）" else "（低库存在前）",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        items(visible, key = { it.productId }) { s ->
                            StockCard(
                                s = s,
                                onInbound = { vm.openMovement(s, inbound = true) },
                                onOutbound = { vm.openMovement(s, inbound = false) },
                            )
                        }
                    }
                }
            }
        }
    }
}

/**
 * 库存页的卡：**左边语义色图标块、右边名称 + 库存事实 + 状态角标，下面一整行两个按钮**。
 *
 * ## ⛔ 这一页的"商品外观"也归 `ui/common/ProductCardKit.kt` 管
 * 用户 2026-09-21（第二轮）：「其他地方你也得改，最好是采用（通）用的继承，
 * 上次你改一个地方，它就其他跟着改了」。所以这一轮把**判据**全部搬进零件：
 * 库存的配色（[productStockColor]）、库存那一行怎么拼（[productStockFact]）、
 * 占用那一行（[productReservedFact]）、状态角标几时出现（[ProductStockBadge]）。
 *
 * ⚠️ 搬之前这里自己判了一套**不一样**的颜色：低库存写红 `#FF4D4F`、
 * 缺货写灰 `#8A8A8E`、正常数字写深青 `#007A8A` —— 而商品卡那边是
 * 到报警线黄 `#FFB300`、断货红 `#E53935`、正常 `#00BCD4`。
 * 同一件商品在两页**颜色不一样**（缺货在卡上是红的、在这里是灰的），
 * 这正是"改一个地方、另一个不跟着"的典型后果。
 *
 * ⚠️ **不能整页换成 [ProductLine]**：这一页手里的 DTO（`InventorySummaryItemDto`）
 * 只有商品名/库存/单位/报警线/占用 —— **没有图、没有名称色、没有售价**，
 * 所以这里画不出"和商品卡一模一样"的一张卡。要那样就得让后端在库存汇总里
 * 多发 `image_url` / `name_color` / `default_unit_price` 三个字段（这一轮没做，
 * 因为本轮是零后端改动；需要的话单独起一轮）。
 */
@Composable
private fun StockCard(
    s: InventorySummaryItemDto,
    onInbound: () -> Unit,
    onOutbound: () -> Unit,
) {
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            // 图标块：颜色跟着**共用判据**走（正常=库存管理蓝青、到报警线=黄、断货=红）
            Surface(
                shape = RoundedCornerShape(12.dp),
                color = productStockColor(s.stock, s.lowStockAlert),
            ) {
                Icon(
                    Icons.Default.Inventory2,
                    contentDescription = null,
                    tint = Color.White,
                    modifier = Modifier.padding(9.dp).size(22.dp),
                )
            }
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    s.productName,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Spacer(Modifier.height(3.dp))
                // 库存与占用都是"事实"，走同一个零件（一个一行、图标 + 标签 + 值）
                ProductFacts(
                    listOfNotNull(
                        productStockFact(s.stock, s.lowStockAlert, s.unit),
                        if (s.reserved > 0) productReservedFact(s.reserved, s.unit) else null,
                    )
                )
            }
            // 状态角标放**名称那一行**（不是按钮那一行）：它说的是"这个商品现在怎么样"，
            // 和库存数字是一件事；和按钮挤在一起会被当成按钮的一部分。
            ProductStockBadge(s.stock, s.lowStockAlert)
        }
        Spacer(Modifier.height(10.dp))
        // ⚠️ 出入库两个按钮**另起一行**（原来是塞在同一行的最右边）：
        //    右边那一栏现在只有 92dp 让给了分类，卡片可用宽度少了近三分之一，
        //    再横着排会把商品名和库存数字挤成一堆省略号 —— 而那两个才是这一页要看的东西。
        //
        // 用户 2026-09-19 的第二次调整：「那 2 个按钮换一下位置，且不要**贴**得太紧了，
        // 那个出库也就是左边的…那个左边那个名字也**放**在下面，也就库存的下面，这样子做个区分」：
        //   · **出库在左、入库在右**（原来入库在左）；
        //   · 两个按钮**各占一半宽度**、中间留 14dp —— 原来只有 8dp、
        //     而且都是"内容宽度"，两个 2 字按钮几乎粘在一起，在窄栏里很容易点错
        //     （而出库点错成入库是**直接改库存**的错，不是视觉问题）；
        //   · 整组仍**在库存那一行下面**（库存的数字在上一行，按钮在这一行 = 两件事分开）。
        Row(
            Modifier.fillMaxWidth().padding(top = 2.dp),
            horizontalArrangement = Arrangement.spacedBy(14.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            OutlinedButton(
                onClick = onOutbound,
                enabled = s.stock > 0,
                modifier = Modifier.weight(1f),
            ) { Text("出库") }
            FilledTonalButton(onClick = onInbound, modifier = Modifier.weight(1f)) {
                Text("入库")
            }
        }
    }
}

@Composable
private fun MovementRow(m: InventoryMovementDto) {
    val inbound = m.change > 0
    Row(
        Modifier.fillMaxWidth().padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Surface(
            color = if (inbound) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.errorContainer,
            shape = MaterialTheme.shapes.small,
        ) {
            Text(
                (if (inbound) "+" else "") + m.change,
                style = MaterialTheme.typography.titleSmall,
                color = if (inbound) MaterialTheme.colorScheme.onPrimaryContainer else MaterialTheme.colorScheme.onErrorContainer,
                modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
            )
        }
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    if (m.note.isBlank()) (if (inbound) "入库" else "出库") else m.note,
                    style = MaterialTheme.typography.bodyMedium,
                    maxLines = 1,
                    modifier = Modifier.weight(1f, fill = false),
                )
                if (m.source == "ORDER") {
                    Spacer(Modifier.width(6.dp))
                    val text = when (m.status) {
                        "RESERVED" -> "自动出库·占用"
                        "COMMITTED" -> "自动出库·已送达"
                        "RELEASED" -> if (m.change > 0) "自动回库" else "已回冲"
                        else -> "自动"
                    }
                    Surface(
                        color = Color(0xFFE8F1FF),
                        shape = MaterialTheme.shapes.small,
                    ) {
                        Text(
                            text,
                            style = MaterialTheme.typography.labelSmall,
                            color = Color(0xFF1E6FFF),
                            modifier = Modifier.padding(horizontal = 5.dp, vertical = 2.dp),
                        )
                    }
                }
            }
            Text(
                if (m.orderNo != null) m.orderNo + " · " + formatDateTime(m.createdAt) else formatDateTime(m.createdAt),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.outline,
            )
        }
    }
}
