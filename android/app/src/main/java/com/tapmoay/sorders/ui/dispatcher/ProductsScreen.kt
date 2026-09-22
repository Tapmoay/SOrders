package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.ProductCostHistoryDto
import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.ProductPurple
import com.tapmoay.sorders.ui.theme.QuickPriceGreen
import com.tapmoay.sorders.util.formatDateTime
import com.tapmoay.sorders.util.trimMoneyZeros

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProductsScreen(
    container: AppContainer,
    onBack: () -> Unit,
    onOpenCategories: () -> Unit = {},
    /** 打开「批量操作」页（底栏第三格）。 */
    onOpenBatch: () -> Unit = {},
    /** 打开「商品排序」页（顶栏右上角；用户 2026-09-21：「那个排序你没加啊」）。 */
    onOpenSort: () -> Unit = {},
    /**
     * 打开**新增 / 编辑商品页**（`productId = null` → 新增）。
     *
     * 2026-09-21 起商品表单是**单独一页**（`Routes.PRODUCT_FORM`），不再是这一页里的抽屉：
     * 表单状态也跟着搬去了 `ProductFormViewModel` —— 这一页不再背一份"正在编辑的草稿"。
     */
    onOpenForm: (Long?) -> Unit = {},
) {
    val vm: ProductsViewModel = appViewModel { ProductsViewModel(container) }
    val snackbar = remember { SnackbarHostState() }
    /**
     * 快捷改价（卡片右侧「改价」）：non-null = 弹窗开着。
     *
     * ⚠️ 必须声明在**函数级**（Scaffold 之外）—— 弹窗渲染在整个 Scaffold 之后，
     *    声明在 content lambda 里的话外面看不见（第一版就是这么写的，编译报 Unresolved）。
     */
    var quickPriceFor by remember { mutableStateOf<ProductDto?>(null) }
    /** 成本价历史弹窗（`⋮ → 成本价历史`）：状态在 VM 里（要拉数据），这里只读它。 */

    // ⚠️ **加载放在这里、不放在 VM 的 init**：从「新增/编辑商品」那一页 `popBackStack()` 回来时
    //    这一屏会重新进组合，`LaunchedEffect(Unit)` 会再跑一次 —— 刚存的那个商品立刻出现在列表里。
    //    写在 init 里就只在第一次创建 VM 时拉一次，回来看到的是**没有刚存那个**的旧列表
    //    （用户会以为没存上，然后再建一个 → 同名商品）。
    LaunchedEffect(Unit) { vm.start() }

    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })

    // 失败**必须**看得见：这个页面的错误以前只在"列表为空"时才渲染成整页 ErrorView，
    // 于是列表有数据时的上下架/删除失败**界面上毫无变化**——用户以为点漏了，反复点。
    // ⚠️ 消费的是**动作错误**（vm.error）；加载错误走 vm.loadError（它还要驱动整页 ErrorView）。
    OneShotSnackbar(snackbar, vm.error, onConsumed = { vm.error = null })

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = { Text("商品管理") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                // ⛔ 顶栏原来挂着一个「分类管理」按钮、右下角挂着一个「＋」悬浮球。
                //    2026-09-19 用户要求两个动作合并成**底部一条导航栏**
                //    （「给那个商品管理界面的下面加个导航栏，左边分组管理、右边商品新增，
                //     那个 + 把它改成商品新增…两个导航栏做得美观一点」）：
                //    悬浮球压在列表最后一张卡上、顶栏按钮又和返回键挤在一行，
                //    两个动作各在一个角上，视线要跑两趟。
                // ✅ 2026-09-21 顶栏**重新有了一个按钮**：「排序」——
                //    它与底栏那三个不是一类：那三个是"日常增改"，排序是"偶尔调一次次序"，
                //    而且它有自己的一整页（`Routes.PRODUCT_SORT`）。放顶栏不会与底栏抢位置。
                actions = {
                    TextButton(onClick = onOpenSort) {
                        Icon(Icons.Default.SwapVert, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(4.dp))
                        Text("排序")
                    }
                },
            )
        },
        bottomBar = {
            ProductsBottomBar(
                onCategories = onOpenCategories,
                onAdd = { onOpenForm(null) },
                onBatch = onOpenBatch,
            )
        },
    ) { padding ->
        // 分类清单与当前选中的分类：**与选品页同一套实现**
        // （`categoryTabs` / `categoryOf` / `CategoryRail` 都在 `ui/common/ProductPicker.kt` 里，
        //  这一页只是把同一根导航条用在自己的列表左边）
        val cats = remember(vm.products, vm.categories) {
            categoryTabs(vm.products, vm.categories.map { it.name })
        }
        var category by remember { mutableStateOf(ALL_CATEGORY) }
        // 选中的分类可能因为改名/改商品分类而消失 —— 那就退回「全部」，
        // 否则用户会停在一个**导航条上已经不存在的分类**上、右边一片空白且无法解释
        LaunchedEffect(cats) {
            if (category !in cats) category = ALL_CATEGORY
        }
        val keyword = vm.query.trim()
        val visible = remember(vm.products, category, keyword) {
            vm.products
                .filter { category == ALL_CATEGORY || categoryOf(it) == category }
                // 名称搜索（用户 2026-09-19：「商品管理的页面要有个搜索的框啊，方便我们找商品」）：
                // 与库存页同一个判据（本地 + 与左边分类 **AND**）。
                .filter { keyword.isEmpty() || it.name.contains(keyword, ignoreCase = true) }
        }

        Column(Modifier.fillMaxSize().padding(padding)) {
            // 搜索框**横跨整页**（在分类条上面）—— 与库存管理页同一版式。
            // 放右栏会被压成半宽，而且分类为空时它会跟着消失；而"找不到某个商品"正是最需要它的时候。
            OutlinedTextField(
                value = vm.query,
                onValueChange = { vm.query = it },
                placeholder = { Text("搜索商品名称", style = MaterialTheme.typography.bodySmall) },
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
            Box(Modifier.weight(1f)) {
            when {
                vm.loading -> LoadingBox()
                vm.loadError != null && vm.products.isEmpty() -> ErrorView(vm.loadError.orEmpty(), onRetry = { vm.load() })
                vm.products.isEmpty() -> EmptyView("暂无商品，点下方「商品新增」", Modifier.align(Alignment.Center))
                else -> Row(Modifier.fillMaxSize()) {
                    // 左：分类（独立滚动，不会把右边的商品一起带走）—— 与选品页同宽、同观感
                    CategoryRail(
                        tabs = cats,
                        selected = category,
                        onSelect = { category = it },
                        modifier = Modifier.width(92.dp).fillMaxHeight(),
                    )
                    // 右：商品
                    Box(Modifier.weight(1f).fillMaxHeight()) {
                        if (visible.isEmpty()) {
                            // 「搜不到」和「这一类是空的」是两句不同的话 —— 说不清用户会以为商品丢了
                            EmptyView(
                                if (keyword.isNotEmpty()) "没有名称含「$keyword」的商品" else "「$category」下暂无商品",
                                Modifier.align(Alignment.Center),
                            )
                        } else {
                            // ⚠️ 这里原来末尾有一句 `item { Spacer(Modifier.height(72.dp)) }` 给悬浮球让位。
                            //    动作已经搬到底部导航栏、而 Scaffold 的 padding 已经扣掉了那条栏的高度，
                            //    再留 72dp 就是列表底下凭空多一块空白。
                            LazyColumn(
                                Modifier.fillMaxSize(),
                                contentPadding = PaddingValues(start = 10.dp, end = 10.dp, top = 10.dp, bottom = 12.dp),
                                verticalArrangement = Arrangement.spacedBy(8.dp),
                            ) {
                                items(visible, key = { it.id }) { p ->
                                    ProductCard(
                                        p = p,
                                        acting = vm.acting,
                                        onEdit = { onOpenForm(p.id) },
                                        onToggle = { vm.toggleActive(p) },
                                        onQuickPrice = { quickPriceFor = p },
                                    )
                                }
                            }
                        }
                    }
                }
            }
            }
        }
    }

    // 快捷改价（只改默认售价）
    quickPriceFor?.let { p ->
        QuickPriceDialog(
            p = p,
            busy = vm.acting,
            onConfirm = { price -> vm.updateDefaultPrice(p, price) { quickPriceFor = null } },
            onDismiss = { quickPriceFor = null },
        )
    }

    // ⛔ 成本价历史的弹窗**搬去编辑页**了（用户 2026-09-21：「那 3 点的这个功能到编辑里面去」）：
    //    卡片右上角那个「⋮」已经删掉，它里面的三项（各批发商价格 / 成本价历史 / 删除）
    //    现在是 `ProductFormScreen` 里的三行。这一页不再持有 `costHistory*` 那三个状态，
    //    也**不许**在这里挂第二次（红线 `_check_product_card_single_source.py` 盯着）。
}

// ⛔ 这里原来还有 `if (vm.showDialog) { ModalBottomSheet { … } }` —— 商品的新增/编辑抽屉。
// 2026-09-21 它换成了**单独一页**（`Routes.PRODUCT_FORM` → `ProductFormScreen`）：
// 参考图就是整页，而且这一页要进二级选择页（单位 / 分组），抽屉里再叠弹层是两层 modal 压着。
// 表单状态（那份"正在编辑的草稿"）也跟着搬去了 `ProductFormViewModel`。

/**
 * 商品管理的**底部导航栏**：左边「分类管理」、右边「商品新增」（用户 2026-09-19 要求）。
 *
 * 原话：「给那个商品管理界面的下面加个导航栏，左边分别是那个分组管理、右边是商品的
 * 添加按钮，就是那个 + 把它改成商品新增…两个导航栏做得美观一点」。
 *
 * ## 为什么从"两个角"搬到底部一条栏
 * 搬之前是**顶栏一个「分类管理」文字按钮 + 右下角一个「＋」悬浮球**：
 * 两个动作各占一个角，视线在屏幕上要跑两趟；悬浮球还压着列表最后一张卡
 * （所以列表尾巴上被迫留了 72dp 空白）。收到一条栏里之后两个动作并排、
 * 都能写全名（悬浮球只能画一个 +），列表也不再被遮。
 *
 * ## 为什么两个按钮**一实一虚**（"美观"落在这里）
 * 它们不是平级的：新增商品是日常动作、分类管理是偶尔才动一次的设置。
 * 所以右边用实底主按钮（[PrimaryActionButton]，与"提交订单"同一个组件）、
 * 左边用描边次按钮 —— 一眼能看出哪个是主操作。
 * 宽度也按主次分（`weight(1f)` : `weight(1.4f)`），不是两个等宽的方块。
 *
 * 颜色用**商品管理的语义色紫** `ProductPurple`（一色一功能）：这一栏里的两个动作
 * 都属于商品管理，紫是这一块的识别色（卡片上那个「改价」也是它）。
 * ⛔ 不要用钱的橙：同屏「售价」那个数字已经是橙的，会撞色（用户当天刚为这件事改过一次）。
 */
@Composable
private fun ProductsBottomBar(onCategories: () -> Unit, onAdd: () -> Unit, onBatch: () -> Unit) {
    Surface(shadowElevation = 8.dp) {
        Row(
            Modifier
                .fillMaxWidth()
                // 底部系统导航条留白：这一栏不是 M3 的 NavigationBar，不会自己处理 insets
                .navigationBarsPadding()
                .padding(horizontal = 8.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            // 左右两格：**无边框的「图标 + 文字」**（不是描边按钮）——
            // 参考图那一栏就是这么分主次的：描边按钮摆三个会变成三个并排的框。
            BottomCell(
                icon = Icons.Default.Category,
                label = "分类管理",
                onClick = onCategories,
                modifier = Modifier.weight(1f),
            )
            // 中间：**语义色圆钮 + 文字**（照参考图；主操作居中，单手拇指够得着）
            Column(
                Modifier.weight(1f).clickable(onClick = onAdd).padding(vertical = 4.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                FilledIconButton(
                    onClick = onAdd,
                    modifier = Modifier.size(52.dp),
                    colors = IconButtonDefaults.filledIconButtonColors(
                        containerColor = Color(ProductPurple),
                        contentColor = Color.White,
                    ),
                ) {
                    Icon(Icons.Default.Add, contentDescription = "商品新增", modifier = Modifier.size(26.dp))
                }
                Spacer(Modifier.height(2.dp))
                Text(
                    "商品新增",
                    style = MaterialTheme.typography.labelMedium,
                    fontWeight = FontWeight.Bold,
                    color = Color(ProductPurple),
                )
            }
            BottomCell(
                icon = Icons.Default.Checklist,
                label = "批量操作",
                onClick = onBatch,
                modifier = Modifier.weight(1f),
            )
        }
    }
}

/** 底栏左右那两格：图标 + 文字，**没有边框**（用户 2026-09-21：「底部栅格组排直接照抄」）。 */
@Composable
private fun BottomCell(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier.clickable(onClick = onClick).padding(vertical = 2.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Icon(
            icon,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(22.dp),
        )
        Spacer(Modifier.height(2.dp))
        Text(
            label,
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/**
 * 商品卡：**一眼看完"卖多少钱、还剩多少"**，三个动作在卡片底部（改价 / 沽清 / 编辑）。
 *
 * ## 外观全部来自共用零件（`ui/common/ProductCardKit.kt`）
 * 这一页**只负责"这一页有哪些动作、点开哪一页"**：图、名称色、售价行、库存行、
 * 两行的先后、库存的颜色，一行都不在这里 —— 另外四个渲染商品的页面用的是同一套
 * （用户 2026-09-21 第二轮：「其他地方你也得改，最好是采用（通）用的继承，
 * 上次你改一个地方，它就其他跟着改了」）。
 * ⚠️ 想改"卡片上显示什么"→ 改那个文件；**不要**在这一页里手拼字符串（红线盯着）。
 *
 * ## 那三个按钮为什么在卡片底部而不是右上角「⋮」（用户 2026-09-21）
 * 上一版是「⋮ → 下拉菜单」（那是用户 2026-09-19 定的：三个 `IconButton` 横排把
 * 商品名和数字挤成两行灰字）。这一轮用户改主意了，原话：
 * 「**改价**那个也是个**很大的按钮**，还有一个**沽清、也就是下架**，还有一个**编辑**，3 个」
 * 「**那 3 个点啊，就到编辑里面选** —— 那 3 点的这个功能到编辑里面去」。
 * 所以⋮整个删掉、三个动作摊成**一排等宽大按钮**（好点、看得见），
 * 原来藏在⋮里的三项（各批发商价格 / 成本价历史 / 删除商品）搬进**编辑页**。
 *
 * ## 信息为什么用"图标 + 语义色"（用户 2026-09-19）
 * 原话：「那些信息是在商品管理中非常重要的，不一定非要等编辑才能看得到，
 * 我们要用对应的语义色和图标在它的名字的下面进行显示，让人一眼就能看出来」。
 *
 * | 信息 | 颜色 | 图标 | 为什么是这个色 / 为什么在卡上 |
 * |---|---|---|---|
 * | 售价 | 金橙 `MoneyOrange` | `Sell` | 系统里"钱"的语义色（账本/报表/小计同色） |
 * | 库存 | 蓝青 `#00BCD4`（= 库存管理模块色） | `Inventory2` | 跨端同功能同色：这个数字属于库存管理 |
 *
 * ⚠️ **库存还会按状态变色**：0 → 红（没货了）、≤ 报警阈值 → 黄。这两个颜色不是装饰，
 * 是"这一行要你处理"的信号：派单员扫列表时靠它决定先看哪几个。
 *
 * ⛔ **成本价与分类都不在卡上**（都是用户 2026-09-19 明确要求去掉的）：
 * 成本是内部数、不参与对客户报价，只在「⋮ → 编辑」里看和改；
 * 分类已经由**左边那根导航条**表达，同一件事在一屏说两遍只占地方。
 */
@Composable
private fun ProductCard(
    p: ProductDto,
    acting: Boolean,
    onEdit: () -> Unit,
    onToggle: () -> Unit,
    onQuickPrice: () -> Unit,
) {
    SectionCard {
        // ---- 大图 + 名称 + **售价** + **库存**（库存在售价的正下方）----
        // 用户 2026-09-21 第一轮：「图片要大一点、卡片大点…售价在上面的」；
        // 第二轮：「你还是把**库存**给移到**现在的那个售价的下面**啊，这样子**美观一点**」
        //          （原来是"图片下面横跨整卡"，读起来要先横着跳一次、再竖着找一次）。
        //
        // ⛔ 这一段**没有一个字是这一页自己写的**：图 / 名称色 / 事实 / 两行的先后
        //    全部来自 `ui/common/ProductCardKit.kt`（`ProductLine` + `productFacts`）。
        //    另外四个页面（库存 / 批量 / 排序 / 选品）同源 —— 下次改"显示哪两个数字、什么顺序"，
        //    改的是那个文件里的 `productFacts`，不是这一页。
        // 「已沽清」角标也是**共用的那一个**（`ProductSoldOutBadge`）：这一轮之前
        // 卡片上写「已沽清」（灰底）、选品页写「已下架」（红字）—— 同一个状态两个词两种颜色。
        val soldOut: (@Composable () -> Unit)? = if (p.isActive) null else ({ ProductSoldOutBadge() })
        ProductLine(
            name = p.name,
            nameColor = p.nameColor,
            facts = productFacts(p.defaultUnitPrice, p.unit, p.stock, p.lowStockAlert),
            thumb = {
                ProductThumb(
                    imageUrl = p.imageUrl,
                    nameColor = p.nameColor,
                    size = 88.dp,
                    shape = MaterialTheme.shapes.medium,
                )
            },
            badge = soldOut,
        )

        Spacer(Modifier.height(10.dp))

        // ---- 第三行：三个等宽大按钮（用户 2026-09-21：「改价…也是个很大的按钮，
        //      还有一个沽清、还有一个编辑」）----
        //
        // ⛔ 这一版**把右上角的「⋮」整个删掉了**：用户要求那三点里的功能
        //    （各批发商价格 / 成本价历史 / 删除）搬进**编辑页**，卡片上只留这三个动作。
        //    （原来那套"三个以上收进 ⋮"是用户 2026-09-19 定的；这一轮他改了主意，
        //     设计规范 §4.2 已同步改成"卡片上是几个明确的动作按钮、其余进编辑页"。）
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            CardAction(
                label = "改价",
                icon = Icons.Default.CurrencyYuan,
                color = Color(QuickPriceGreen),
                enabled = !acting,
                onClick = onQuickPrice,
                modifier = Modifier.weight(1f),
            )
            CardAction(
                label = if (p.isActive) "沽清" else "上架",
                icon = if (p.isActive) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                color = if (p.isActive) MaterialTheme.colorScheme.error else com.tapmoay.sorders.ui.theme.Success,
                enabled = !acting,
                onClick = onToggle,
                modifier = Modifier.weight(1f),
            )
            CardAction(
                label = "编辑",
                icon = Icons.Default.Edit,
                color = Color(ProductPurple),
                filled = true,
                enabled = !acting,
                onClick = onEdit,
                modifier = Modifier.weight(1f),
            )
        }
    }
}

/**
 * 商品卡底部的一个动作按钮：**三个等宽**、图标 + 文字（用户 2026-09-21 要求"很大的按钮"）。
 *
 * [filled] = 实底（主操作，卡片上只有「编辑」用它）；其余是描边。
 * 颜色仍按**语义**给：改价=低饱和绿（用户 2026-09-19 点名要的）、沽清=红、上架=绿、编辑=模块紫。
 */
@Composable
private fun CardAction(
    label: String,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    color: Color,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    filled: Boolean = false,
    enabled: Boolean = true,
) {
    if (filled) {
        Button(
            onClick = onClick,
            enabled = enabled,
            modifier = modifier.height(46.dp),
            shape = MaterialTheme.shapes.medium,
            colors = ButtonDefaults.buttonColors(containerColor = color, contentColor = Color.White),
            contentPadding = PaddingValues(horizontal = 4.dp),
        ) {
            Icon(icon, contentDescription = null, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(4.dp))
            Text(label, style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.Bold, maxLines = 1)
        }
    } else {
        OutlinedButton(
            onClick = onClick,
            enabled = enabled,
            modifier = modifier.height(46.dp),
            shape = MaterialTheme.shapes.medium,
            border = BorderStroke(1.5.dp, color),
            colors = ButtonDefaults.outlinedButtonColors(contentColor = color),
            contentPadding = PaddingValues(horizontal = 4.dp),
        ) {
            Icon(icon, contentDescription = null, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(4.dp))
            Text(label, style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.Bold, maxLines = 1)
        }
    }
}

/**
 * 成本价历史（只读）：**这个商品的价格从什么时候到什么时候是多少**。
 *
 * 用户 2026-09-19：「我们保留的时候不仅保留成本价，还保留这个成本价存在的时间，
 * 比如说他是从什么时候开始变的、从什么时候结束的，精确到小时和分钟，
 * 这样子的话，我们就能方便且精确地算出来在这段时间的毛利率是多少」。
 *
 * 三件事必须说清楚，少一件这张表就会骗人：
 * 1. **时间要换算到设备时区**（后端发的是 naive UTC）—— 直接用会早 8 小时，
 *    而"这段时间"算错 8 小时正是这个功能要消灭的东西（见 `util/TimeFmt.kt`）；
 * 2. **最后一段写「至今」**，不是一个空白或一个假的结束时间；
 * 3. **来源要标出来**（建商品 / 进货 / 编辑 / 老数据回填）—— 尤其 `BACKFILL`：
 *    那一段的起点是"商品创建时间"，是**推断**出来的，不是真的那一刻改的价，
 *    不标出来用户会拿它去对账。
 */
@Composable
internal fun CostHistoryDialog(
    p: ProductDto,
    rows: List<ProductCostHistoryDto>,
    loading: Boolean,
    onDismiss: () -> Unit,
) {
    val unit = p.unit.ifBlank { "件" }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("成本价历史", maxLines = 1, overflow = TextOverflow.Ellipsis) },
        text = {
            Column {
                Text(
                    p.name,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Spacer(Modifier.height(10.dp))
                when {
                    loading -> Row(verticalAlignment = Alignment.CenterVertically) {
                        CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                        Spacer(Modifier.width(8.dp))
                        Text("加载中…", style = MaterialTheme.typography.bodySmall)
                    }
                    rows.isEmpty() -> Text(
                        "这个商品还没有成本价记录。入库时填「进货价」、或在编辑页填成本价，之后每次改动都会记一段。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    else -> Column(
                        Modifier.heightIn(max = 360.dp).verticalScroll(rememberScrollState()),
                        verticalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        rows.forEach { h ->
                            CostHistoryRow(h, unit)
                        }
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("关闭") } },
    )
}

@Composable
internal fun CostHistoryRow(h: ProductCostHistoryDto, unit: String) {
    val live = h.effectiveTo == null
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                "¥" + trimMoneyZeros(h.costPrice) + " / " + unit,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Bold,
                color = Color(QuickPriceGreen),
                modifier = Modifier.weight(1f),
            )
            if (live) {
                Surface(color = Color(0xFFE3F1E8), shape = MaterialTheme.shapes.small) {
                    Text(
                        "至今",
                        style = MaterialTheme.typography.labelSmall,
                        color = Color(QuickPriceGreen),
                        modifier = Modifier.padding(horizontal = 6.dp, vertical = 1.dp),
                    )
                }
            }
        }
        Spacer(Modifier.height(2.dp))
        Text(
            formatDateTime(h.effectiveFrom) + " 起" +
                (h.effectiveTo?.let { " ～ " + formatDateTime(it) } ?: "（仍在使用）"),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        val src = when (h.source) {
            "CREATE" -> "建商品时填的"
            "PURCHASE" -> "进货时录的"
            "BACKFILL" -> "老数据回填（起点取商品创建时间，是推断值）"
            else -> "在编辑页改的"
        }
        Text(src, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
    }
}

/**
 * 快捷改价弹窗：**只改默认售价**，不动别的字段。
 *
 * 为什么单独做一个（而不是复用商品编辑抽屉）：用户要的是"方便、快捷" ——
 * 改售价是最高频的动作，而走抽屉要先点开、滚到价格段、再保存。
 * 这里保存走的是 `PATCH /products/{id}` 的**部分更新**（只放 `default_unit_price`），
 * 所以不会顺手改掉别的字段。
 */
@Composable
private fun QuickPriceDialog(
    p: ProductDto,
    busy: Boolean,
    onConfirm: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    // 预填时去掉尾部多余的 0（后端单价是 Numeric(14,4)，直接显示会是 "12.5000"）；
    // ⚠️ 用 trimMoneyZeros 而不是 formatMoney —— 后者只留两位小数，会把 12.3456 显示成 12.35
    var price by remember { mutableStateOf(trimMoneyZeros(p.defaultUnitPrice)) }
    val unit = p.unit.ifBlank { "件" }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("改默认售价", maxLines = 1, overflow = TextOverflow.Ellipsis) },
        text = {
            Column {
                Text(p.name, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = price,
                    // 单价规则唯一实现在 core/InputRules.kt（4 位小数：库里的单价列是 Numeric(14,4)）
                    onValueChange = { price = InputRules.priceInput(it) },
                    label = { Text("售价（元 / $unit）") },
                    singleLine = true,
                    keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(
                        keyboardType = androidx.compose.ui.text.input.KeyboardType.Decimal,
                    ),
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(6.dp))
                Text(
                    "只改这一个价，不动名称、成本、库存、分类。批发商的专属价在「各批发商价格」里单独设。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        },
        confirmButton = {
            TextButton(
                enabled = !busy && price.toDoubleOrNull() != null,
                onClick = { onConfirm(price) },
            ) { Text(if (busy) "保存中…" else "保存") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}

// ⛔ 这里原来定义着商品卡上那两个数字（`ProductFacts(p)` / `Fact(...)` / `stockColor(p)`）。
//
// 2026-09-21 全部收进 `ui/common/ProductCardKit.kt` —— 因为"售价怎么拼""库存什么颜色"
// 这两件事在商品管理页与选品页**各有一份**，而"名称色的兜底值"全库一度有 **5 份**。
// 「为什么一个一行」「为什么成本不在卡上」（设计规范 §4.1）那两段理由也一起搬了过去：
// **改卡片上显示什么之前，先读那个文件顶上的说明。**

// ⛔ 这里原来还有一个 private 的 `NewCategoryDialog`（只有那个抽屉在用）。
// 2026-09-21 抽屉改成单独一页之后，它换成 `ui/common/CategoryPickerSheet.kt` 里的
// `CategoryNameDialog`（**名册页与选择页共用的那一份**）—— 商品表单里那个
// 「新建分组」走的就是它，见 `ProductFormScreen` 的分类选择页。
