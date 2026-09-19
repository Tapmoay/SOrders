package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Inventory2
import androidx.compose.material.icons.filled.Remove
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.util.formatMoney
import com.tapmoay.sorders.util.resolveStaticUrl

/**
 * 外卖式的**全屏选品页**（货主下单 / 派单员代理下单共用同一个）。
 *
 * ## 为什么不是原来那个列表弹窗
 * 原来的是"一列商品 + 每行一个添加按钮"，点一次弹一次数量框、关一次、再点开——
 * 商品一多就要来回滚，而且**选不了第二件**（弹窗已经关了）。
 * 现在按外卖 App 的组织方式：
 * - 左侧分类竖排（**一屏能看完全部分类**，不用横向滑）、右侧商品列表，各自独立滚动；
 * - 点「＋」弹**数量 + 单位**小窗（用户明确要求"数量后面是要有对应的单位的"）；
 * - 可以一次挑好几件，底部汇总「已选 N 种 · 合计 ¥X」再一起加入清单。
 *
 * ## 分类从哪来
 * `products.category`（商品管理里维护）。三种情况都要能优雅显示：
 * 1. 有分类 → 左侧「全部 + 各分类」，分类按**商品数倒序**（多的排前面）；
 * 2. 全都没分类 → 左侧**只显示「全部」**（不逼用户先去补分类才能下单）；
 * 3. 部分有 → 没填的归到「未分类」，排在最后。
 *
 * @param products 商品目录（调用方已经按专属价算好了 `priceFor`）
 * @param priceFor 实际单价（批发商专属价优先）
 * @param initialPicked 打开时已经选过的商品（同一件再加会**合并数量**而不是多一行）
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProductPickerSheet(
    products: List<ProductDto>,
    loading: Boolean,
    priceFor: (ProductDto) -> String,
    onConfirm: (List<PickedLine>) -> Unit,
    onDismiss: () -> Unit,
    categoryOrder: List<String> = emptyList(),
    /** 商品目录**加载失败**的原因（null = 没失败）。见 `OrderCreateViewModel.productsError`。 */
    error: String? = null,
    /** 失败时的重试入口。 */
    onRetry: () -> Unit = {},
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    // 全屏高度：用户要的就是"底部窗口直接拉到最顶处"
    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState,
        dragHandle = { BottomSheetDefaults.DragHandle() },
    ) {
        ProductPickerBody(
            products = products,
            loading = loading,
            priceFor = priceFor,
            onConfirm = onConfirm,
            modifier = Modifier.fillMaxHeight(0.94f),
            categoryOrder = categoryOrder,
        )
    }
}

/** 选品页本体（与弹窗外壳分开，方便单测/预览直接渲染）。 */
@Composable
fun ProductPickerBody(
    products: List<ProductDto>,
    loading: Boolean,
    priceFor: (ProductDto) -> String,
    onConfirm: (List<PickedLine>) -> Unit,
    modifier: Modifier = Modifier,
    /** 分类名册的顺序（派单员排的）。空 = 还没加载出来，退回"按商品数倒序"。 */
    categoryOrder: List<String> = emptyList(),
    /** 商品目录**加载失败**的原因（null = 没失败）。 */
    error: String? = null,
    onRetry: () -> Unit = {},
) {
    var keyword by remember { mutableStateOf("") }
    var category by remember { mutableStateOf(ALL_CATEGORY) }
    // 已选：productId -> 这一件选了多少/什么单位。用 map 而不是 list，是为了"同一件再加 = 累加"
    val picked = remember { mutableStateMapOf<Long, PickedLine>() }
    var editing by remember { mutableStateOf<ProductDto?>(null) }
    val listState = rememberLazyListState()

    // 分类清单：由商品 + **名册顺序**算出来（不是手写枚举），
    // 保证"派单员在分类管理里排一下、选品页就跟着变"
    val cats = remember(products, categoryOrder) { categoryTabs(products, categoryOrder) }
    val visible = remember(products, category, keyword) {
        products.filter { p ->
            (category == ALL_CATEGORY || categoryOf(p) == category) &&
                (keyword.isBlank() || p.name.contains(keyword.trim(), ignoreCase = true))
        }
    }

    Column(modifier.fillMaxWidth()) {
        // ---- 标题行：左边标题，右边"已选 N 种"（一眼看到自己挑了多少）----
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 20.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("选择商品", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Spacer(Modifier.weight(1f))
            if (picked.isNotEmpty()) {
                TextButton(onClick = { picked.clear() }) {
                    Text("清空", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
        Spacer(Modifier.height(10.dp))

        // ---- 搜索框 ----
        Box(Modifier.fillMaxWidth().padding(horizontal = 20.dp)) {
            SoTextField(
                value = keyword,
                onValueChange = { keyword = it },
                placeholder = "搜索商品名",
            )
            Icon(
                Icons.Default.Search,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.align(Alignment.CenterEnd).padding(end = 14.dp).size(20.dp),
            )
        }
        Spacer(Modifier.height(10.dp))

        when {
            loading -> Box(Modifier.fillMaxWidth().height(240.dp)) { LoadingBox() }
            // ⚠️ 加载失败与"真的没有商品"必须分开说（2026-09-19 审计）：原来两者都落到下面那句
            //    「暂无可用商品…请联系派单员添加」——它是**断言式假话**（服务重启/弱网时打开下单页
            //    就会看到），货主会去质问派单员，而派单员那边一切正常。失败要给原因 + 重试。
            error != null -> Box(Modifier.fillMaxWidth().height(240.dp)) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    EmptyView("商品目录加载失败：$error")
                    Text(
                        "这不是「没有商品」——是没拉到。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(8.dp))
                    OutlinedButton(onClick = onRetry) { Text("重试") }
                }
            }
            products.isEmpty() -> Box(Modifier.fillMaxWidth().height(240.dp)) {
                EmptyView("暂无可用商品\n请联系派单员先在「商品管理」中添加商品后再下单")
            }
            else -> Row(Modifier.weight(1f, fill = true)) {
                // ---- 左：分类（独立滚动，不会把右侧的商品列表一起带走）----
                CategoryRail(
                    tabs = cats,
                    selected = category,
                    onSelect = {
                        category = it
                        // 换分类回到顶部：停在半路会让人以为"这一类只有两件"
                    },
                    modifier = Modifier.width(96.dp).fillMaxHeight(),
                )
                // ---- 右：商品 ----
                Box(Modifier.weight(1f).fillMaxHeight()) {
                    if (visible.isEmpty()) {
                        EmptyView(
                            if (keyword.isNotBlank()) "没有匹配「$keyword」的商品" else "这一类暂无商品",
                            Modifier.align(Alignment.TopCenter).padding(top = 60.dp),
                        )
                    } else {
                        LazyColumn(
                            state = listState,
                            modifier = Modifier.fillMaxSize(),
                            contentPadding = PaddingValues(start = 12.dp, end = 12.dp, top = 4.dp, bottom = 12.dp),
                            verticalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            items(visible, key = { it.id }) { p ->
                                ProductRow(
                                    product = p,
                                    price = priceFor(p),
                                    pickedQty = picked[p.id]?.qty ?: 0,
                                    pickedUnit = picked[p.id]?.unit,
                                    onAdd = { editing = p },
                                )
                            }
                        }
                    }
                }
            }
        }

        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        // ---- 底部：汇总 + 加入清单 ----
        val kinds = picked.size
        val total = picked.values.sumOf { it.lineTotal }
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                if (kinds == 0) {
                    Text(
                        "点右侧「＋」挑商品，可一次挑多件",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    Text(
                        "已选 $kinds 种",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(
                        "¥" + formatMoney(total.toString()),
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Bold,
                        color = Color(MoneyOrange),
                    )
                }
            }
            Button(
                onClick = { onConfirm(picked.values.toList()) },
                enabled = picked.isNotEmpty(),
                modifier = Modifier.height(48.dp).widthIn(min = 128.dp),
                shape = MaterialTheme.shapes.medium,
                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF00A56E)),
            ) {
                Text(
                    if (kinds == 0) "加入清单" else "加入清单（$kinds）",
                    fontWeight = FontWeight.Bold,
                    color = Color.White,
                )
            }
        }
    }

    editing?.let { p ->
        val exist = picked[p.id]
        QtyUnitDialog(
            productName = p.name,
            productColor = p.nameColor,
            defaultUnit = exist?.unit ?: p.unit.ifBlank { "件" },
            initialQty = exist?.qty ?: 1,
            price = priceFor(p),
            onConfirm = { qty, unit ->
                picked[p.id] = PickedLine(
                    productId = p.id,
                    name = p.name,
                    qty = qty,
                    unit = unit.ifBlank { "件" },
                    price = priceFor(p),
                    nameColor = p.nameColor,
                    imageUrl = p.imageUrl,
                )
                editing = null
            },
            onRemove = if (exist != null) {
                { picked.remove(p.id); editing = null }
            } else null,
            onDismiss = { editing = null },
        )
    }
}

// ---------------------------------------------------------------- 左侧分类栏

private const val ALL_CATEGORY = "全部"
private const val NO_CATEGORY = "未分类"

/** 一个商品属于哪个分类（空/纯空格 = 未分类）。 */
private fun categoryOf(p: ProductDto): String = p.category.trim().ifBlank { NO_CATEGORY }

/**
 * 分类清单：**由商品算出来**，不是手写枚举；**顺序由名册定**（派单员排过的那一列）。
 *
 * 排序规则有意为之（v3.43 起顺序改由 `product_categories.sort_order` 决定 ——
 * 用户要的是"顺序我说了算"，不再按商品数推）：
 * - 「全部」永远第一；
 * - 名册里**且真的有商品**的分类，按名册顺序；
 * - 名册里没有、但有商品的分类名（老数据 / 别处直接写库）**排在名册后面**、按商品数倒序
 *   —— ⚠️ 不许因为它不在名册里就把商品藏起来；
 * - 名册里**没有商品**的分类不出现（空页签是纯噪音；它会留在「分类管理」页里）；
 * - 「未分类」永远最后，且**只在真有正经分类时才出现**（全是未分类时它和「全部」内容一样）。
 */
internal fun categoryTabs(products: List<ProductDto>, ordered: List<String> = emptyList()): List<String> {
    val counts = linkedMapOf<String, Int>()
    products.forEach { p -> counts[categoryOf(p)] = (counts[categoryOf(p)] ?: 0) + 1 }
    val inRail = counts.keys.filter { it != NO_CATEGORY }.toSet()
    val out = mutableListOf(ALL_CATEGORY)
    // ① 名册顺序里、且真的有商品的
    ordered.map { it.trim() }.filter { it.isNotEmpty() && it in inRail }.distinct().forEach { out += it }
    // ② 名册外的（老数据）：按商品数倒序，稳定地排在后面
    counts.entries
        .filter { it.key != NO_CATEGORY && it.key !in out }
        .sortedByDescending { it.value }
        .forEach { out += it.key }
    // ③ 未分类：只在真有正经分类时出现。
    //    —— 这一条是单测 `全部商品都没分类时只剩全部一个分类` 抓出来的（第一版写错了）。
    if (counts.containsKey(NO_CATEGORY) && out.size > 1) out += NO_CATEGORY
    return out
}

@Composable
private fun CategoryRail(
    tabs: List<String>,
    selected: String,
    onSelect: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    LazyColumn(
        modifier = modifier.background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.45f)),
    ) {
        itemsIndexed(tabs) { _, name ->
            val on = name == selected
            Box(
                // 选中态：整块换成白底 + 左侧一条语义色竖条（外卖 App 的通用写法，
                // 一眼看出现在在哪一类），未选中是半透明灰底。
                Modifier
                    .fillMaxWidth()
                    .height(52.dp)
                    .background(if (on) MaterialTheme.colorScheme.surface else Color.Transparent)
                    .clickable { onSelect(name) },
                contentAlignment = Alignment.CenterStart,
            ) {
                if (on) {
                    Box(
                        Modifier
                            .fillMaxHeight()
                            .width(4.dp)
                            .background(MaterialTheme.colorScheme.primary),
                    )
                }
                Text(
                    name,
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = if (on) FontWeight.Bold else FontWeight.Normal,
                    color = if (on) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(horizontal = 12.dp),
                )
            }
        }
    }
}

// ---------------------------------------------------------------- 右侧商品行

@Composable
private fun ProductRow(
    product: ProductDto,
    price: String,
    pickedQty: Int,
    pickedUnit: String?,
    onAdd: () -> Unit,
) {
    val color = remember(product.nameColor) { parseNameColor(product.nameColor) }
    Surface(
        color = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(14.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            Modifier.padding(10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            // 商品图；没有图就用名称色块 + 图标（与商品管理页同一套观感）
            Box(
                Modifier.size(56.dp).clip(RoundedCornerShape(12.dp)),
                contentAlignment = Alignment.Center,
            ) {
                if (!product.imageUrl.isNullOrBlank()) {
                    AsyncImage(
                        model = resolveStaticUrl(product.imageUrl),
                        contentDescription = product.name,
                        contentScale = ContentScale.Crop,
                        modifier = Modifier.fillMaxSize(),
                    )
                } else {
                    Box(Modifier.fillMaxSize().background(color), contentAlignment = Alignment.Center) {
                        Icon(
                            Icons.Default.Inventory2,
                            contentDescription = null,
                            tint = Color.White,
                            modifier = Modifier.size(26.dp),
                        )
                    }
                }
            }
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    product.name,
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = FontWeight.SemiBold,
                    color = color,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                Spacer(Modifier.height(2.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        "¥" + formatMoney(price),
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.Bold,
                        color = Color(MoneyOrange),
                    )
                    Text(
                        " / " + product.unit.ifBlank { "件" },
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    if (!product.isActive) {
                        Spacer(Modifier.width(6.dp))
                        Text(
                            "已下架",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                    }
                }
                if (pickedQty > 0) {
                    Spacer(Modifier.height(2.dp))
                    Text(
                        "已选 $pickedQty ${pickedUnit ?: product.unit}",
                        style = MaterialTheme.typography.labelMedium,
                        color = Color(0xFF00A56E),
                        fontWeight = FontWeight.SemiBold,
                    )
                }
            }
            Spacer(Modifier.width(8.dp))
            // 圆形「＋」（外卖 App 的通用形态）；已选过就显示数量角标
            Box {
                FilledIconButton(
                    onClick = onAdd,
                    colors = IconButtonDefaults.filledIconButtonColors(
                        containerColor = if (pickedQty > 0) Color(0xFF00A56E) else Color(0xFF1E6FFF),
                        contentColor = Color.White,
                    ),
                    modifier = Modifier.size(36.dp),
                ) {
                    Icon(
                        if (pickedQty > 0) Icons.Default.Check else Icons.Default.Add,
                        contentDescription = if (pickedQty > 0) "已选，点此修改" else "添加",
                        modifier = Modifier.size(20.dp),
                    )
                }
                if (pickedQty > 0) {
                    Box(
                        Modifier
                            .align(Alignment.TopEnd)
                            .offset(x = 6.dp, y = (-6).dp)
                            .clip(CircleShape)
                            .background(Color(0xFFFF4D4F))
                            .padding(horizontal = 5.dp, vertical = 1.dp),
                    ) {
                        Text(
                            pickedQty.toString(),
                            style = MaterialTheme.typography.labelSmall.copy(fontSize = 10.sp),
                            color = Color.White,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------- 数量 + 单位

/** 选品清单里的一项（数量与单位都定好了）。 */
data class PickedLine(
    val productId: Long,
    val name: String,
    val qty: Int,
    val unit: String,
    val price: String,
    val nameColor: String? = null,
    val imageUrl: String? = null,
) {
    val lineTotal: Double get() = (price.toDoubleOrNull() ?: 0.0) * qty
}

/**
 * 常用的计量单位。
 *
 * 为什么给一排快捷项而不是只让用户打字：这些是**同一件事在库里的既定写法**
 * （商品库、库存、订单显示都用它们）。让每个人自由手输的结果是
 * 同一件货出现"件 / 件装 / 1件"三种写法，报表按单位分组时就成了三行。
 * 需要别的写法时仍可自己填（最后一个「自定义」）。
 */
private val COMMON_UNITS = listOf("件", "箱", "袋", "桶", "包", "瓶", "斤", "个")

/**
 * 数量 + 单位 小窗（用户明确要求："点击确认商品的时候，弹个小窗，
 * 我们可以选择对应的数量，并且后面是要有对应的单位的"）。
 *
 * 商品名不需要填（从目录里选的），所以标题就是商品名。
 */
@Composable
fun QtyUnitDialog(
    productName: String,
    productColor: String?,
    defaultUnit: String,
    initialQty: Int,
    price: String,
    onConfirm: (Int, String) -> Unit,
    onDismiss: () -> Unit,
    onRemove: (() -> Unit)? = null,
) {
    var qty by remember { mutableStateOf(initialQty.coerceAtLeast(1)) }
    var unit by remember { mutableStateOf(defaultUnit.ifBlank { "件" }) }
    var custom by remember { mutableStateOf(unit !in COMMON_UNITS) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = {
            Text(
                productName,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
                color = parseNameColor(productColor),
                fontWeight = FontWeight.Bold,
            )
        },
        text = {
            Column {
                // ---- 数量 ----
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("数量", style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
                    StepButton(Icons.Default.Remove, "减", enabled = qty > 1) {
                        qty = (qty - 1).coerceAtLeast(1)
                    }
                    OutlinedTextField(
                        value = qty.toString(),
                        onValueChange = { v ->
                            qty = v.filter { c -> c.isDigit() }.take(4).toIntOrNull()?.coerceIn(1, 9999) ?: 1
                        },
                        singleLine = true,
                        textStyle = MaterialTheme.typography.titleMedium.copy(
                            fontWeight = FontWeight.Bold,
                            color = Color(0xFF1E6FFF),
                        ),
                        keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(
                            keyboardType = androidx.compose.ui.text.input.KeyboardType.Number,
                        ),
                        modifier = Modifier.width(92.dp),
                    )
                    StepButton(Icons.Default.Add, "加", enabled = qty < 9999) {
                        qty = (qty + 1).coerceAtMost(9999)
                    }
                }
                Spacer(Modifier.height(14.dp))
                // ---- 单位 ----
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("单位", style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
                    Text(
                        "下单和送货单上显示的就是它",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Spacer(Modifier.height(8.dp))
                // 两行流式排列（不用 FlowRow，避免额外实验 API 依赖）
                COMMON_UNITS.chunked(4).forEach { rowUnits ->
                    Row(
                        Modifier.fillMaxWidth().padding(bottom = 8.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        rowUnits.forEach { u ->
                            UnitChip(u, selected = !custom && unit == u) {
                                custom = false
                                unit = u
                            }
                        }
                    }
                }
                UnitChip("自定义", selected = custom) {
                    custom = true
                    if (unit in COMMON_UNITS) unit = ""
                }
                if (custom) {
                    Spacer(Modifier.height(8.dp))
                    SoTextField(
                        value = unit,
                        onValueChange = { unit = it.take(8) },
                        placeholder = "例如：托、筐、扎",
                    )
                }
                Spacer(Modifier.height(8.dp))
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                Spacer(Modifier.height(8.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("小计", style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                    Text(
                        "¥" + formatMoney(((price.toDoubleOrNull() ?: 0.0) * qty).toString()),
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                        color = Color(MoneyOrange),
                    )
                }
            }
        },
        confirmButton = {
            TextButton(onClick = { onConfirm(qty, unit.trim().ifBlank { "件" }) }) { Text("确定") }
        },
        dismissButton = {
            if (onRemove != null) {
                TextButton(onClick = onRemove) {
                    Text("移除", color = MaterialTheme.colorScheme.error)
                }
            } else {
                TextButton(onClick = onDismiss) { Text("取消") }
            }
        },
    )
}

@Composable
private fun StepButton(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    label: String,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    FilledTonalIconButton(
        onClick = onClick,
        enabled = enabled,
        colors = IconButtonDefaults.filledTonalIconButtonColors(
            containerColor = Color(0xFFE8F2FF),
            contentColor = Color(0xFF1E6FFF),
        ),
    ) {
        Icon(icon, contentDescription = label)
    }
}

@Composable
private fun UnitChip(text: String, selected: Boolean, onClick: () -> Unit) {
    val bg = if (selected) Color(0xFF1E6FFF) else MaterialTheme.colorScheme.surfaceVariant
    val fg = if (selected) Color.White else MaterialTheme.colorScheme.onSurfaceVariant
    Box(
        Modifier
            .height(36.dp)
            .widthIn(min = 56.dp)
            .clip(RoundedCornerShape(10.dp))
            .background(bg)
            .border(
                width = 1.dp,
                color = if (selected) Color(0xFF1E6FFF) else MaterialTheme.colorScheme.outlineVariant,
                shape = RoundedCornerShape(10.dp),
            )
            .clickable { onClick() }
            .padding(horizontal = 12.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(text, style = MaterialTheme.typography.bodyMedium, color = fg, fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal)
    }
}

/** 商品名颜色（`#RRGGBB`）；坏值时退回主题色，不让用户看到一片黑或崩溃。 */
internal fun parseNameColor(raw: String?): Color = try {
    Color(android.graphics.Color.parseColor(raw ?: "#1565C0"))
} catch (_: Exception) {
    Color(0xFF1565C0)
}

/** 关闭按钮（右上角），选品页与其它全屏弹层共用同一形态。 */
@Composable
fun SheetCloseButton(onClick: () -> Unit) {
    IconButton(onClick = onClick) {
        Icon(Icons.Default.Close, contentDescription = "关闭")
    }
}
