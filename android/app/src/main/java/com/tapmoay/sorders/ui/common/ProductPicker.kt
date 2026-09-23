package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.util.formatMoney

/**
 * 外卖式的**全屏选品页**（货主下单 / 派单员代理下单共用同一个）。
 *
 * ## 为什么不是原来那个列表弹窗
 * 原来的是"一列商品 + 每行一个添加按钮"，点一次弹一次数量框、关一次、再点开——
 * 商品一多就要来回滚，而且**选不了第二件**（弹窗已经关了）。
 * 现在按外卖 App 的组织方式：
 * - 左侧分类竖排（**一屏能看完全部分类**，不用横向滑）、右侧商品列表，各自独立滚动；
 * - 点「＋」弹**只填数量**的小窗（用户 2026-09-19 改的，理由见下面那段）；
 * - 可以一次挑好几件，底部汇总「已选 N 种 · 合计 ¥X」再一起加入清单。
 *
 * ## 小窗里的单位：**只显示、不给改**（2026-09-19 定，2026-09-23 补上"显示"）
 * 用户 2026-09-19 的原话：「那个单位不要出现啊，他是默认是已经配好了的只要填数量就可以了。那个单位是
 * 派单员在设置的时候会给这个商品设置单位，货主去下单的时候他是不能去更改单位的不然
 * 会出现认知判断错误」。
 *
 * ⚠️ 那条禁的是**能改的入口**（一个能改的字段就是一个会被改错的字段：同一件货这次记"3 箱"、
 * 下次记"3 件"，库存与对账按单位分组时就成了两行，而且**两边都不报错**）——
 * 不是"不许看见单位"。所以 2026-09-23 用户圈着标题右边那块空地说
 * 「放在最右边…那个显示单位也就这个商品的单位」时，做法是：
 * **单位只读地显示在标题行最右边**（`UnitTag`），`QtyDialog` 收一个 `unit` 只为显示，
 * **不回传、没有输入框**。单位的唯一来源仍然是商品库（`products.unit`，派单员在
 * 「商品管理」里设的），下单的人（货主 / 代理下单的派单员）手上依旧没有选它的入口。
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
 * @param single **只挑一件**（2026-09-20 账本「记一笔账」要的：一条账本行就是一件商品）。
 *   默认 false = 下单那种"一次挑多件"，**那边一个字都不变**。
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
    /** 只挑一件：再挑一件是**换掉**而不是累加（见文件头 `single` 的说明）。 */
    single: Boolean = false,
    /**
     * **要不要报价**（默认 true ＝ 下单页那套，一个字都不变）。
     *
     * 预订单（订单模板）传 false：那一页选商品**根本不会存价**（预设单只存"哪几样、各多少"，
     * 金额在下单那一刻按商品价现算）。在"不入库的价格"上画一个数 —— 哪怕它此刻是对的 ——
     * 用户也会以为它被存下来了；而它其实取决于"下单时选的货主"，与这张模板无关。
     */
    showPrice: Boolean = true,
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
            single = single,
            showPrice = showPrice,
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
    /** 只挑一件（见 [ProductPickerSheet] 的 `single`）：再挑一件是**换掉**。 */
    single: Boolean = false,
    /** 要不要报价（见 [ProductPickerSheet] 的 `showPrice`）。false = 只挑"哪几样、各多少"。 */
    showPrice: Boolean = true,
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
                                    // ⚠️ 不报价时传空串：`ProductRow` 只在非空时画那一行价
                                    //    （预订单那边的选品就是这个模式，见 `showPrice` 的说明）
                                    price = if (showPrice) priceFor(p) else "",
                                    pickedQty = picked[p.id]?.qty ?: 0,
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
                        if (single) "点右侧「＋」挑商品（只挑一件）" else "点右侧「＋」挑商品，可一次挑多件",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    Text(
                        "已选 $kinds 种",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    // ⚠️ **不报价的调用方**（预订单）显示件数而不是金额：那个页面里的价
                    //    **根本不会入库**（预设单只存"哪几样、各多少"），画一个金额出来
                    //    只会让人以为它被存下来了。见 `showPrice` 的说明。
                    if (showPrice) {
                        Text(
                            "¥" + formatMoney(total.toString()),
                            style = MaterialTheme.typography.titleLarge,
                            fontWeight = FontWeight.Bold,
                            color = Color(MoneyOrange),
                        )
                    } else {
                        Text(
                            "共 " + picked.values.sumOf { it.qty } + " 件",
                            style = MaterialTheme.typography.titleLarge,
                            fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.primary,
                        )
                    }
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
                    when {
                        single -> "用这件"
                        kinds == 0 -> "加入清单"
                        else -> "加入清单（$kinds）"
                    },
                    fontWeight = FontWeight.Bold,
                    color = Color.White,
                )
            }
        }
    }

    editing?.let { p ->
        val exist = picked[p.id]
        // 单位**不由用户给**：取商品库里的（派单员在商品管理里设的），空则退回「件」。
        // ⚠️ 这里的 `unitOrDefault` 是"商品那一侧"的兜底（空 → 「件」）—— 与订单行快照
        //    那条 `qtyWithUnit`（空就只给数字、不编一个「件」）是**两条规矩**，别合并，
        //    见 `Units.kt` 顶上那段。传进小窗只为**显示**在标题右边，不回传。
        val unit = unitOrDefault(p.unit)
        QtyDialog(
            productName = p.name,
            productColor = p.nameColor,
            initialQty = exist?.qty ?: 1,
            price = if (showPrice) priceFor(p) else "",
            unit = unit,
            onConfirm = { qty ->
                // ⚠️ 单选模式（账本「记一笔账」）：先清空再放下这一件 —— 再挑一件是**换掉**。
                //    不清空的话用户会挑出"两件商品、账上却只记了一件"，而界面看着完全正常。
                if (single) picked.clear()
                picked[p.id] = PickedLine(
                    productId = p.id,
                    name = p.name,
                    qty = qty,
                    unit = unit,
                    price = if (showPrice) priceFor(p) else "",
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

// ⚠️ 这三个（以及 `categoryTabs` / `CategoryRail`）是 **internal** 而不是 private：
//    「商品管理」页现在也是"左边分类、右边商品"（用户 2026-09-19 要求跟选品页一致），
//    它必须用**同一套**分类定义与同一根导航条 —— 各写一份的话，
//    同屏两个页面会出现"同一件商品在选品页属于日化、在商品管理页属于未分类"。
internal const val ALL_CATEGORY = "全部"
internal const val NO_CATEGORY = "未分类"

/** 一个商品属于哪个分类（空/纯空格 = 未分类）。 */
internal fun categoryOf(p: ProductDto): String = categoryNameOf(p.category)

/**
 * 同上，但直接吃**分类名**。
 *
 * 为什么要多这一层（2026-09-19）：库存管理页也改成了"左边分类、右边商品"，
 * 而它手里的是 `InventorySummaryItemDto`（不是 `ProductDto`）。
 * 让那一页自己去 trim/兜底的话，同屏两个页面就会出现"同一件商品在这里属于日化、
 * 在那里属于未分类" —— 这正是这个文件顶上那段注释警告过的事。
 * 所以判据拆成"名字 → 档位"（这里）与"商品 → 档位"（[categoryOf]）两层，**只有一份实现**。
 */
internal fun categoryNameOf(raw: String?): String = raw?.trim().orEmpty().ifBlank { NO_CATEGORY }

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
internal fun categoryTabs(products: List<ProductDto>, ordered: List<String> = emptyList()): List<String> =
    categoryTabsOf(products.map { it.category }, ordered)

/** [categoryTabs] 的"按分类名"入口 —— 库存页的行不是 `ProductDto`，用它。**同一份实现**。 */
internal fun categoryTabsOf(names: List<String?>, ordered: List<String> = emptyList()): List<String> {
    val counts = linkedMapOf<String, Int>()
    names.forEach { n -> counts[categoryNameOf(n)] = (counts[categoryNameOf(n)] ?: 0) + 1 }
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

/**
 * 商品分类那一列 —— 只是 [MasterRail] 的一层薄包装（**版式只有一份实现**）。
 *
 * 2026-09-19：用户连着要了三个"像商品管理那样"的两栏界面（库存、司机运费结算、下单地址库），
 * 左边那一列的样子必须是同一个，所以把版式提到 `Components.kt::MasterRail`，
 * 这里只做"分类名 → RailItem"的翻译。原来那段 Box/Text 是**照抄一份**的写法，
 * 抄第三遍时行高就会各自跑偏。
 */
@Composable
internal fun CategoryRail(
    tabs: List<String>,
    selected: String,
    onSelect: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    MasterRail(
        items = tabs.map { RailItem(key = it, label = it) },
        selectedKey = selected,
        onSelect = onSelect,
        modifier = modifier,
    )
}

// ---------------------------------------------------------------- 右侧商品行

@Composable
private fun ProductRow(
    product: ProductDto,
    price: String,
    pickedQty: Int,
    onAdd: () -> Unit,
) {
    val unit = unitOrDefault(product.unit)
    Surface(
        color = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(14.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
        modifier = Modifier.fillMaxWidth(),
    ) {
        // ⛔ 行主体是**共用的那一个**（`ProductCardKit::ProductLine`）：图是缩略图槽、
        //    ＋按钮是后置槽、售价那行来自 `productPriceFact`（钱的格式化唯一一处）。
        //    ⚠️ 这一页**只给售价、不给库存**：货主也在看这一页（下单），
        //    内部库存不露给客户 —— "显示哪几条事实"是**业务口径**，各页自己挑（见零件文件顶上）。
        ProductLine(
            name = product.name,
            nameColor = product.nameColor,
            facts = listOfNotNull(
                // ⚠️ `price.isBlank()` 时**这一行事实整条不画**（预订单那种"不报价"的调用方）：
                //    直接传空串进去会渲染成「¥0/件」—— 一个凭空造出来的价。
                if (price.isBlank()) null else productPriceFact(price, product.unit),
                if (pickedQty > 0) pickedFact(pickedQty, unit) else null,
            ),
            modifier = Modifier.padding(10.dp),
            dense = true,
            // 商品图：**缩略图那一份零件**，这一页用 `solid = true`
            //（名称色实底 + 白图标）—— 它是"挑东西"，色块帮着扫；
            // 管理列表那一页是浅灰底 + 名称色图标（安静，不盖数字）。
            thumb = {
                ProductThumb(
                    imageUrl = product.imageUrl,
                    nameColor = product.nameColor,
                    size = 56.dp,
                    solid = true,
                )
            },
            badge = if (product.isActive) null else ({ ProductSoldOutBadge() }),
            trailing = {
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
            },
        )
    }
}

/**
 * 「已选 N 袋」也是这一行的一条**事实**（同一个零件画、同一个行距）。
 *
 * ⚠️ 它**留在选品页**、不进 `ProductCardKit`：它说的是"**这一次挑选**"，
 * 不是商品本身的属性（另外四个页面没有"已选"这回事）。零件给的是
 * 「事实怎么画」这一条版式，**[ProductFact] 这个数据结构是公开的、
 * 谁都可以为"自己那一页的概念"造一条** —— 前提是别去改"商品本身该显示什么"。
 */
private fun pickedFact(qty: Int, unit: String): ProductFact = ProductFact(
    icon = Icons.Default.CheckCircle,
    label = "已选",
    value = "$qty $unit",
    color = Color(0xFF00A56E),
)

// ---------------------------------------------------------------- 数量

/**
 * 选品清单里的一项。
 *
 * [unit] 不是用户选的：它来自商品库（`products.unit`），见文件头
 * 「为什么小窗里没有单位了」。留在这个 data class 里是因为它要跟着**行**走 ——
 * 加入清单那一刻商品库的单位是多少，这一行就记多少（后端也会按商品库兜底）。
 */
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
 * **只填数量**的小窗（2026-09-19 起这里没有"选单位"的入口）。
 *
 * 为什么不给选单位：单位是派单员在「商品管理」里给商品设好的，下单的人改它只会改错 ——
 * 详见文件头「小窗里的单位：只显示、不给改」。商品名不用填（从目录里选的），所以标题就是商品名。
 *
 * [unit] **只用来显示**（标题行最右边那个小标签），不回传：单位跟着商品走，
 * `onConfirm` 只回数量。空串 = 不显示（调用方已经用 `unitOrDefault` 兜过一次）。
 *
 * ## 版式（2026-09-23 用户点名改的那一版）
 * 一行标题（商品名在左、**单位在最右**）+ 一行「数量 + 步进器」+ 一条分隔线 + 一行「小计」。
 * 步进器与数量判据都在 `ui/common/QtyStepper.kt`（**唯一一份**：下单页那个行编辑弹窗
 * `LineEditDialog` 用的是同一个）。原来这里自己画过一份"淡蓝实心圆 + 92dp 框"，
 * 与下单页那份（灰紫圆 + 96dp 框）已经不是同一个形态了。
 */
@Composable
fun QtyDialog(
    productName: String,
    productColor: String?,
    initialQty: Int,
    price: String,
    onConfirm: (Int) -> Unit,
    onDismiss: () -> Unit,
    onRemove: (() -> Unit)? = null,
    unit: String = "",
) {
    var qty by remember { mutableStateOf(initialQty.coerceAtLeast(1)) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    productName,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    color = productNameColor(productColor),
                    fontWeight = FontWeight.Bold,
                    // 名字吃剩余宽度、单位贴最右（名字长到换行时单位也仍然在右边那一列）
                    modifier = Modifier.weight(1f),
                )
                // ⚠️ 用户 2026-09-23 圈出来的就是这块空位：「放在最右边…那个显示单位
                //    也就这个商品的单位」。只读标签，见 `UnitTag` 的注释。
                UnitTag(unit, modifier = Modifier.padding(start = 10.dp))
            }
        },
        text = {
            Column {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("数量", style = MaterialTheme.typography.bodyLarge)
                    Spacer(Modifier.width(12.dp))
                    // 整组随对话框宽度拉伸（数字框居中，`+` 永远不会被长数量挤出去）
                    QtyStepper(qty = qty, onQtyChange = { qty = it }, modifier = Modifier.weight(1f))
                }
                Spacer(Modifier.height(14.dp))
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                Spacer(Modifier.height(10.dp))
                // ⚠️ 不报价时（预订单）连"小计"都不画：它算出来的那个数**不会入库**，
                //    画出来就是在暗示"这个价会被存下来"。见 [ProductPickerSheet] 的 `showPrice`。
                if (price.isNotBlank()) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            "小计",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.weight(1f),
                        )
                        Text(
                            "¥" + formatMoney(((price.toDoubleOrNull() ?: 0.0) * qty).toString()),
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Bold,
                            color = Color(MoneyOrange),
                        )
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = { onConfirm(qty) }) { Text("确定") }
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

// ⛔ 这里原来有一个 `StepButton`（`FilledTonalIconButton` 淡蓝实心圆）。
// 2026-09-23 收进 `ui/common/QtyStepper.kt` 的 `QtyStepper` —— 同一组东西当时全库有
// **两份**（这里一份 + 下单页行编辑弹窗一份），而且两边的配色、框宽、数字对齐都不一样。

// ⛔ 这里原来定义着 `parseNameColor(raw)`（选品页自己的"名称色"判据）。
// 2026-09-21 收进 `ui/common/ProductCardKit.kt::productNameColor` —— 同一件事当时全库有
// **5 份**（这里一份 + 商品管理页 2 处 + 代理下单页 + 批量调价页各一份内联写法），
// 而且其中 4 份**没有 try/catch**：库里一个脏颜色值就能让整页崩。

/** 关闭按钮（右上角），选品页与其它全屏弹层共用同一形态。 */
@Composable
fun SheetCloseButton(onClick: () -> Unit) {
    IconButton(onClick = onClick) {
        Icon(Icons.Default.Close, contentDescription = "关闭")
    }
}
