package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.*
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.OrderTemplateCategoryDto
import com.tapmoay.sorders.data.remote.dto.OrderTemplateDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.*
// 语义色取主题里那一份（⛔ 不在页面里另写十六进制）：ShipperTeal = 货主/湖蓝、MoneyOrange = 钱/金橙。
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.ui.theme.ShipperTeal
import com.tapmoay.sorders.util.formatMoney
import kotlinx.coroutines.launch

/**
 * 「预订单」页 —— **专门管理预设好的订单**（2026-09-22 用户要求）。
 *
 * ## 用户原话（两轮）
 * > 「其实我们**还可以再增加一个叫做「预定单」界面**，**专门去管理**预设的订单 ——
 * > 就是**预设好的订单**，这个**参数没有变**，**直接下单就可以了**。」
 * >
 * > 「不是你这个预订单**怎么不能新建一个预订单呢**？其实说白了，这个预订单就**相当于一个模板**，
 * > 而且这个模板我们是要**做一个分类**的 —— 也是一样的，**左边是分类管理**，就是**复用**嘛，
 * > 复用那些**商品管理**的形式；**我右边就是订单**，我们可以**删除**、可以**编辑**、
 * > 可以**用这个单下单**，还可以**新建一个订单**。」
 *
 * ## 版式：左边分类、右边预设单（复用商品管理那一套）
 * 左栏是 `ui/common` 那一份分类导航条（`CategoryRail` + `categoryTabsOf` / `categoryNameOf`）——
 * ⛔ **不许在这里自己再写一份"这个预设单属于哪一类"**：商品管理 / 库存管理 / 选品页 / 开销 / 运费
 * 五处共用同一份判据，各写一份就会出现"同一张单在这页属于周单、在那页属于未分类"。
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
 * ## 建 / 改 / 删 / 恢复
 * · **建与改在单独的页面**（`OrderTemplateFormScreen`，`Routes.DISPATCH_ORDER_TEMPLATE_FORM`）——
 *   起因就是用户那句「**怎么不能新建一个预订单呢**」：原来只能看/删/去下单，建与改只能找 AI。
 * · **删一律软删**（用户定的硬规矩），并且**两个恢复入口**：删完那一下的 snackbar「撤回」
 *   （手边那一下）＋ 底栏「回收站」（过一会儿才想起来的那个）。
 *   ⛔ 只有前者是不够的：snackbar 会飘走，飘走了那张单就再也找不回来了。
 */
class OrderTemplatesViewModel(private val container: AppContainer) : ViewModel() {

    var rows by mutableStateOf<List<OrderTemplateDto>>(emptyList())
        private set

    /** 分类名册（左栏那一列的名字与顺序；顺序由「分类管理」页决定）。 */
    var categories by mutableStateOf<List<OrderTemplateCategoryDto>>(emptyList())
        private set

    var loading by mutableStateOf(true)
        private set
    var loadError by mutableStateOf<String?>(null)
    var actionResult by mutableStateOf<String?>(null)

    /** 左栏选中的分类（[ALL_CATEGORY] = 全部）。 */
    var tab by mutableStateOf(ALL_CATEGORY)

    /** 现在看的是不是**回收站**（软删的那几张）。 */
    var showTrash by mutableStateOf(false)
        private set

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
                rows = container.repo.orderTemplates(deletedOnly = showTrash)
                // 名册与列表一起刷：刚在「分类管理」里建/改名/排序过，回来必须看得见
                // （⛔ 只刷一半会造出"这个分类下还没有预设单"的假象 —— 与地址库那次同一个坑）。
                categories = container.repo.orderTemplateCategories()
            } catch (e: Exception) {
                loadError = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun openTrash() {
        showTrash = true
        tab = ALL_CATEGORY
        rows = emptyList()   // 让 loading 立刻亮起来（回收站通常只有几张，但别闪一下空态）
        load()
    }

    fun closeTrash() {
        showTrash = false
        tab = ALL_CATEGORY
        rows = emptyList()
        load()
    }

    /** 左栏那一列：**由名册与列表算出来**（判据只有一处，见文件头）。 */
    fun tabs(): List<String> = categoryTabsOf(rows.map { it.category }, categories.map { it.name })

    /** 当前分类下要显示的那几张（回收站模式下不分类，全列）。 */
    fun visible(): List<OrderTemplateDto> =
        if (tab == ALL_CATEGORY) rows else rows.filter { categoryNameOf(it.category) == tab }

    /** 这一张的分类名（空 = 未分类，卡片上就不画那个小标签）。 */
    fun categoryLabelOf(t: OrderTemplateDto): String? =
        t.category.trim().ifBlank { null }

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
        restore(t, quiet = true)
    }

    /** 从回收站恢复一张（也是 `restoreLastDeleted` 的落点 —— 只有一份实现）。 */
    fun restore(t: OrderTemplateDto, quiet: Boolean = false) {
        viewModelScope.launch {
            try {
                container.repo.restoreOrderTemplate(t.id)
                // 恢复的名字可能带着 `_del{id}` 后缀去掉之后的原名，所以提示用后端回来的那个
                if (!quiet) actionResult = "已恢复「${t.name}」"
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
    /** 「分类管理」（左栏那一列的名字与顺序）。 */
    onManageCategories: () -> Unit = {},
    /** 「新建预订单」/ 卡片上的「编辑」——都去同一张表单页（id 为空 = 新建）。 */
    onOpenForm: (Long?) -> Unit = {},
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
        topBar = { AppTopBar(title = if (vm.showTrash) "预订单 · 回收站" else "预订单", onBack = onBack) },
        bottomBar = {
            // 回收站里不摆那三个动作（在回收站里"新建一张单"是另一个语境的动作，会让人误以为
            // 是在回收站里新建）。只留返回：顶栏那个返回已经够了，所以底栏整条不画。
            if (!vm.showTrash) {
                TemplatesBottomBar(
                    onCategories = onManageCategories,
                    onCreate = { onOpenForm(null) },
                    onTrash = { vm.openTrash() },
                )
            }
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            // 「预设单是什么」——**按提示的形式**（用户 2026-09-22：「这个解释没必要…或者说你可以
            // 把这个解释**绑到那个提示当中**…开个按钮它就显示、关闭按钮它就不显示」）。
            // ⛔ 所以它走 `Hint`（总开关关掉就不显示），不是常驻 `Text`。
            Hint(
                "预设单就是你常用那一单的模板：选好货主与商品，下次点「用这张下单」直接带进下单页",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 8.dp),
            )
            when {
                vm.loading -> LoadingBox()
                vm.loadError != null -> ErrorView(vm.loadError.orEmpty(), onRetry = { vm.load() })
                vm.showTrash -> TrashList(vm)
                else -> Row(Modifier.weight(1f)) {
                    // 左：分类栏（共用那一份实现：与商品/库存/运费同一个观感）
                    CategoryRail(
                        tabs = vm.tabs(),
                        selected = vm.tab,
                        onSelect = { vm.tab = it },
                        modifier = Modifier.width(96.dp).fillMaxHeight(),
                    )
                    val list = vm.visible()
                    if (list.isEmpty()) {
                        Box(Modifier.weight(1f).fillMaxHeight()) {
                            EmptyView(
                                if (vm.tab == ALL_CATEGORY) {
                                    "还没有预订单" +
                                        "\n点底栏那个「新建预订单」存一张常用的"
                                } else {
                                    "「" + vm.tab + "」下还没有预订单"
                                },
                                Modifier.align(Alignment.TopCenter).padding(top = 60.dp),
                            )
                        }
                    } else {
                        LazyColumn(
                            Modifier.weight(1f).fillMaxHeight(),
                            contentPadding = PaddingValues(start = 12.dp, end = 12.dp, top = 4.dp, bottom = 16.dp),
                            verticalArrangement = Arrangement.spacedBy(10.dp),
                        ) {
                            items(list, key = { it.id }) { t ->
                                TemplateCard(
                                    t = t,
                                    category = vm.categoryLabelOf(t),
                                    onPlace = { onPlaceOrder(t) },
                                    onEdit = { onOpenForm(t.id) },
                                    onDelete = { vm.askDelete(t) },
                                )
                            }
                        }
                    }
                }
            }
        }
    }

    vm.pendingDelete?.let { t ->
        DangerConfirmDialog(
            title = "删除预设单「" + t.name + "」？",
            message = "它会从列表里移进回收站（删完还能从底栏的「回收站」放回来）。",
            confirmText = "删除",
            onConfirm = { vm.confirmDelete() },
            onDismiss = { vm.cancelDelete() },
        )
    }
}

/**
 * 回收站：软删的那几张 + 一个「恢复」。
 *
 * 为什么要有它（用户定的硬规矩）：**删除一律软删 + 界面上要有一个手边的撤销入口**。
 * 只有删完那一下的 snackbar「撤回」是不够的 —— 手一滑点掉、或者过一会儿才想起来，
 * 那张单就再也找不回来了（回收站就是"过一会儿"的那个入口）。
 */
@Composable
private fun TrashList(vm: OrderTemplatesViewModel) {
    val list = vm.rows
    Column(Modifier.fillMaxSize()) {
        // ⚠️ 这句放在"空/不空"分支**之前**：它说的是"这个地方是什么"，空的时候同样要看得到
        //    （而且空态那句 `EmptyView` 是**永远显示**的，两个不冲突）。
        Hint(
            "这里是你删掉的预设单：点「恢复」放回列表，名字也会还原成删之前那个",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 8.dp),
        )
        if (list.isEmpty()) {
            EmptyView("回收站是空的\n删掉的预设单会先放这里，随时能恢复")
            return@Column
        }
        LazyColumn(
            Modifier.fillMaxSize(),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            items(list, key = { it.id }) { t ->
                TrashRow(t, onRestore = { vm.restore(t) })
            }
        }
    }
}

/**
 * 预订单的**底部三格**：左「分类管理」· 中「新建预订单」（语义色圆钮）· 右「回收站」。
 *
 * 形态照 `FreightTemplatesScreen.kt::FreightBottomBar` 与 `ProductsScreen.kt::ProductsBottomBar`
 * （用户 2026-09-19 与 2026-09-22 两轮定的：左右是**无边框的「图标 + 文字」**、中间是
 * **语义色圆钮 + 一行文字**，主操作居中、拇指够得着，底栏自己加 `navigationBarsPadding()`）。
 *
 * ⚠️ **它本该在这一轮被提成 `ui/common/` 的共用件**（运费那一页的文件头写着「若第三页也要，
 * 就把它提成共用件 —— 那时两处一起换」，而这一页正是第三处）。本轮**没有提**，理由是硬的：
 * 另外两处被别的线的判据**逐字钉着**（`_check_sheet_form_pages.py` 断言 `FreightBottomBar(`
 * 与 `FreightBottomCell(`、`_reverse_verify_sheet_form_pages.py` 与 `_reverse_verify_product_card.py`
 * 各有一条注入锚在那两个函数签名上），提共用件就得连带改别人三条锚点。
 * 等三条线都收工、那两个注入锚愿意一起搬的时候再提 —— 记在 `docs/AI_WORK_CLAIM.md` 的交叉点里。
 */
@Composable
private fun TemplatesBottomBar(
    onCategories: () -> Unit,
    onCreate: () -> Unit,
    onTrash: () -> Unit,
) {
    Surface(shadowElevation = 8.dp) {
        Row(
            Modifier
                .fillMaxWidth()
                .navigationBarsPadding()
                .padding(horizontal = 8.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            TemplatesBottomCell(Icons.Default.Tune, "分类管理", onCategories, Modifier.weight(1f))
            Column(
                Modifier.weight(1f).clickable(onClick = onCreate).padding(vertical = 4.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                FilledIconButton(
                    onClick = onCreate,
                    modifier = Modifier.size(52.dp),
                    colors = IconButtonDefaults.filledIconButtonColors(
                        containerColor = Color(TemplateBlue),
                        contentColor = Color.White,
                    ),
                ) {
                    Icon(Icons.Default.Add, contentDescription = "新建预订单", modifier = Modifier.size(26.dp))
                }
                Spacer(Modifier.height(2.dp))
                Text(
                    "新建预订单",
                    style = MaterialTheme.typography.labelMedium,
                    fontWeight = FontWeight.Bold,
                    color = Color(TemplateBlue),
                )
            }
            TemplatesBottomCell(Icons.Default.DeleteOutline, "回收站", onTrash, Modifier.weight(1f))
        }
    }
}

/** 底栏左右那两格：图标 + 文字，**没有边框**（与商品管理、运费模板那两栏同一个形态）。 */
@Composable
private fun TemplatesBottomCell(
    icon: ImageVector,
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier.clickable(onClick = onClick).padding(vertical = 2.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Icon(
            icon, contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(22.dp),
        )
        Spacer(Modifier.height(2.dp))
        Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

/**
 * 一张预设单。
 *
 * ## 版式（2026-09-22 用户第二轮：「卡片的样式不明确，需要**加一些语义色和图标**，
 * 这些**排版**要拍好一点，**重要信息就稍微加粗**」）
 *
 * 照全项目"事实行"那一份零件（`ui/common/ProductCardKit.kt::ProductFact(s)`）：
 * **图标 + 小灰标签 + 加粗的语义色值**，一个一行。于是这一张卡自带层次：
 *
 * | 信息 | 图标 | 语义色 |
 * | --- | --- | --- |
 * | 分类 | `Folder` | **靛蓝**（预订单功能色，与工作台那一格同色） |
 * | 货主 | `Person` | **湖蓝**（与「货主管理」同色） |
 * | 送到 | `Place` | **蓝**（与派单作业/地址同色） |
 * | 收货人 | `Badge` | **绿**（与送达同色） |
 * | 商品 | `Inventory2` | **紫**（与「商品管理」同色） |
 * | 参考运费 | `Payments` | **金橙**（钱只有这一个色） |
 *
 * ⛔ 一色一功能：别把上面几个改成同一个色（那样"扫一眼"就没用了），
 *   也别用橙色表达非钱的东西。
 * 动作横排：「删」在**最左**（相反操作），「编辑 / 用这张下单」在**右**（主操作最右，右手够得着）。
 */
@Composable
private fun TemplateCard(
    t: OrderTemplateDto,
    category: String?,
    onPlace: () -> Unit,
    onEdit: () -> Unit,
    onDelete: () -> Unit,
) {
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            // 圆底 + 语义色图标（iOS 风那种"精致不裸奔"，全项目共用的 `TintedIcon`）
            TintedIcon(Icons.Default.BookmarkAdded, Color(TemplateBlue), size = 20.dp, container = 40.dp)
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                // 名字是主角：加粗 + 大一号
                Text(
                    t.name,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    maxLines = 1,
                )
                // ⚠️ 名字下面**不再重复写货主**（第一版写了一句「货主：下单时再选」，而下面
                //    事实行里已经有一条「货主」——同一件事写两遍是纯噪音）。
                Text(
                    if (t.lines.isEmpty()) "还没选商品" else "共 " + t.lines.size + " 样货",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        Spacer(Modifier.height(8.dp))
        // 事实行：**图标带语义色，文字一律不上色**，值靠右（2026-09-22 用户第二轮修正：
        // 「文字就不需要加颜色了，这样反而显得太花了」+「文字往右边，不要在一起」）。
        // ⛔ 所以这里**没有**用 `ui/common` 那份 `ProductFacts`：那一份把"值"也染成语义色
        //    （商品卡上一屏只有两个数字，染色是对的），而这一页一屏六行，六种颜色就花了。
        //    共用的东西是**观感**（图标 + 标签 + 值各一行、值靠右），不是那个染色的实现。
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            category?.let { TemplateFactRow(Icons.Default.Folder, "分类", it, Color(TemplateBlue)) }
            TemplateFactRow(
                Icons.Default.Person, "货主",
                t.shipperName?.takeIf { it.isNotBlank() } ?: "下单时再选",
                Color(ShipperTeal),
            )
            if (t.address.isNotBlank()) {
                TemplateFactRow(Icons.Default.Place, "送到", t.address, Color(0xFF1E6FFF), maxLines = 2)
            }
            val receiver = (t.receiverName + " " + t.receiverPhone).trim()
            if (receiver.isNotBlank()) {
                TemplateFactRow(Icons.Default.Badge, "收货人", receiver, Color(0xFF00B578))
            }
            TemplateFactRow(Icons.Default.Inventory2, "商品", goodsText(t), Color(0xFF8455E6))
            TemplateFactRow(
                Icons.Default.Payments, "参考运费",
                if (t.freightFee == null) "不预设" else "¥" + formatMoney(t.freightFee),
                Color(MoneyOrange),
            )
        }
        if (t.remark.isNotBlank()) {
            Spacer(Modifier.height(6.dp))
            InfoRow("备注", t.remark)
        }
        Spacer(Modifier.height(10.dp))
        // ⚠️ 三个动作挤在一行（1080px 的屏）：次要的两个用**文字按钮**（不带图标）。
        //    第一版三个都带图标，真机上「用这张下单」直接被挤出屏幕**看不见**（实测 dump 到）——
        //    而它恰恰是这一页的主操作。主操作仍然是右边那个实底按钮（右手够得着）。
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = onDelete) { Text("删") }
            TextButton(onClick = onEdit) { Text("编辑") }
            Spacer(Modifier.weight(1f))
            Button(onClick = onPlace, modifier = Modifier.height(40.dp)) {
                Icon(Icons.Default.AddShoppingCart, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(4.dp))
                Text("用这张下单")
            }
        }
    }
}

/** 回收站里的那一行也带语义色与图标（与在用的卡片同一套观感，只是动作换成「恢复」）。 */
@Composable
private fun TrashRow(t: OrderTemplateDto, onRestore: () -> Unit) {
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            TintedIcon(
                Icons.Default.DeleteOutline,
                MaterialTheme.colorScheme.onSurfaceVariant,
                size = 18.dp,
                container = 40.dp,
            )
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(t.name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold, maxLines = 1)
                Text(
                    goodsText(t),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            TextButton(onClick = onRestore) {
                Icon(Icons.Default.Restore, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(4.dp))
                Text("恢复")
            }
        }
    }
}

/**
 * 一张卡上的一行事实：**图标（带语义色）+ 标签（小灰字）+ 值（靠右、不上色、加粗）**。
 *
 * ⚠️ 两条是用户 2026-09-22 第二轮明确纠正的，别改回去：
 * 1. **文字不上色**（原话：「文字就不需要加颜色了，这样的反而显得太花了」）——
 *    语义色只留给**图标**；值得强调的用**加粗**，不是用颜色。
 * 2. **值靠右**（原话：「文字往右边，不要在一起」）—— 标签贴左、值贴右，
 *    中间用 `weight(1f)` 撑开；⛔ 别写成"图标+标签+值挤在左边"那种。
 */
@Composable
private fun TemplateFactRow(
    icon: ImageVector,
    label: String,
    value: String,
    tint: Color,
    /** 最多几行。**地址给 2 行**（一行放不下就省略，而"送到哪"是这张卡第二重要的信息）。 */
    maxLines: Int = 1,
) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Icon(icon, contentDescription = null, tint = tint, modifier = Modifier.size(15.dp))
        Spacer(Modifier.width(6.dp))
        Text(
            label,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.width(8.dp))
        Text(
            value,
            style = MaterialTheme.typography.bodyMedium,
            // ⚠️ **不加颜色**：这一页一屏六行，六种颜色就花了（用户点名）。
            color = MaterialTheme.colorScheme.onSurface,
            fontWeight = FontWeight.SemiBold,
            // ⚠️ `weight(1f)` + `TextAlign.End` 是**两件事一起**才对的：
            //    · 靠右是用户要的（「文字往右边」）；
            //    · `weight` 是长值能被截断而不是把标签挤出去（红线
            //      `_check_adaptive_layout.py`：`maxLines=1 + Ellipsis` 却不给 weight 的算"新增"）。
            //    第一版用 `Spacer(weight)` 撑开、值本身不给 weight —— 正好踩在那条红线上。
            modifier = Modifier.weight(1f),
            textAlign = TextAlign.End,
            maxLines = maxLines,
            overflow = TextOverflow.Ellipsis,
        )
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
internal const val TemplateBlue = 0xFF3949ABL
