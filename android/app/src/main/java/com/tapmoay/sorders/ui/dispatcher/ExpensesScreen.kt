package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.ExpenseLink
import com.tapmoay.sorders.data.remote.dto.ExpenseCategoryDto
import com.tapmoay.sorders.data.remote.dto.ExpenseDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.ui.theme.ProductPurple
import com.tapmoay.sorders.util.formatMoney
import java.time.LocalDate
import kotlinx.coroutines.launch

/** 左侧分类栏里那个"不筛分类"的档（与商品管理的 `ALL_CATEGORY` 同一个意思）。 */
private const val ALL_CATEGORY = "全部"

/**
 * 开销管理（2026-09-20 用户第六轮重写）。
 *
 * ## 页面形状（用户口述，逐条对着做）
 *
 * > 这个开销管理，前一部分为**新增开销**（就相当于新增订单一样）……下面开销记录我们**按照商品记录**，
 * > 有个分类（商品分类我们已经做好了），开销分类**也有个分类管理**；右边就是该分类的记录。
 * > 同时我们也可以**按照时间**进行 —— 同样以**右上角时间药丸**的形式。关于开销的卡片也做相应改动：
 * > 对于一些**需要明确的信息给凸显出来**，不需要明显的就保持原样；这个关联跟**分类**是有关系的
 * > （燃油/维修主要是车辆 → 首要突出车辆），**要具体问题具体判断，不能一刀切**；
 * > 关联订单号放在**点详情**的时候看。
 *
 * 所以这一页从上到下 / 从左到右是：
 * 顶栏（标题 + **时间药丸**）→ **左边分类栏**（可维护名册，顺序由「分类管理」定）→
 * 右边记录（卡片：**按分类突出主关联** + 金额最大 + 日期；其余弱化；「详情」看全部）；
 * 底部两个按钮：**分类管理**（描边次按钮）+ **新增开销**（实底主按钮，进单独一页）。
 *
 * ⛔ 这一页**没有**内嵌的新增表单了：用户选了"按钮 → 进单独一页填"（像新增订单那样）。
 * ⛔ 卡片**不许**按分类名 `when(...)` 判该突出什么：那是把"名册"复制一份到客户端，
 *    用户新加一个分类就失效（突出什么由 `expense_categories.link_kind` 带下来）。
 */
class ExpensesViewModel(private val container: AppContainer) : ViewModel() {

    var expenses by mutableStateOf<List<ExpenseDto>>(emptyList())
        private set
    var categories by mutableStateOf<List<ExpenseCategoryDto>>(emptyList())
        private set
    var loading by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
    var loadError by mutableStateOf<String?>(null)

    /** 左栏选中的分类（`ALL_CATEGORY` = 不筛）。 */
    var selectedCategory by mutableStateOf(ALL_CATEGORY)

    // ⚠️ `rangeFrom/rangeTo` **必须声明在 `init {}` 之前**：init 会调 `switchPreset(今天)`，
    //    而它要写这两个字段 —— 写在 init 之后就是"打开这一页直接崩"
    //    （判据：`_tools/qa/_check_vm_state_before_init.py`，账本页栽过一次）。
    var rangeFrom by mutableStateOf<String?>(null)
        private set
    var rangeTo by mutableStateOf<String?>(null)
        private set

    // ---- 右上角时间药丸（与账本页同一份控件）----
    var preset by mutableStateOf(DatePresets.TODAY)
        private set
    var customFrom by mutableStateOf<String?>(null)
        private set
    var customTo by mutableStateOf<String?>(null)
        private set
    var showDatePresets by mutableStateOf(false)

    // ⛔ 这里原来还有一个 `showCustomRange`（自定义区间弹层的开关）：2026-09-21 精简轮把它
    //    收进了 `ui/common/Components.kt::DateFilterDialogs`（五个页面共用那一份状态机）——
    //    页面从来不需要读它，只需要"要不要画"。谁再想加回来，先看那个函数。

    /**
     * **窗口定下来了没有**（2026-09-21）。
     *
     * 用户报的毛病是"点进去闪两下才跳到有数的那一段"——根子是**先按今天拉了一次**、
     * 再异步退档，于是最坏画三帧（今天·加载 → 今天·空态 → 前天·有数据）。
     * 现在先探测、定下来只取一次数；这一位为假时整页 loading。
     * ⚠️ 必须声明在 `init` **之前**（`init` 会写它，写在后面就是"打开这一页必崩"）。
     */
    var windowSettled by mutableStateOf(false)
        private set

    /** 详情弹层里那一笔（null = 没开）。 */
    var detailTarget by mutableStateOf<ExpenseDto?>(null)
        private set

    // ---- 撤销 / 恢复（2026-10-10 BUG-0034 / 台账 TA-16）----

    /** 撤销的二次确认目标（非空 = 那个确认框弹着）。 */
    var pendingCancel by mutableStateOf<ExpenseDto?>(null)

    /**
     * 确认框**自己**里面的失败原因。
     *
     * ⛔ 不许写页面级 [error]：页面级错误在这块弹层**下面**，用户看到的是"弹层一直在、
     *    点了没反应"（客户收款页真机实测过两次，见 `DangerConfirmDialog` 的注释）。
     */
    var actionError by mutableStateOf<String?>(null)

    /** 动作回执（走 snackbar）。 */
    var actionResult by mutableStateOf<String?>(null)

    /** 刚撤销的那一笔 —— snackbar 上那颗「撤回」用（**手边那一下**）。 */
    var lastCancelled by mutableStateOf<ExpenseDto?>(null)

    /** 正在提交：一次网络往返期间再点一次等于发两遍（撤销这类动作第二遍必然被后端拒）。 */
    var acting by mutableStateOf(false)

    /**
     * 「显示已撤销」档（回收站）。默认关。
     *
     * ⚠️ 两档是**二选一**、不是"含已撤销"：顶上那颗合计是拿这几行加出来的，
     *    把已撤销的混进来，那一格就说不清算的是"花了多少"还是"撤销了多少"。
     * ⛔ 这一档也是「恢复」唯一的界面入口（不许只把恢复藏在 AI 撤回卡里）。
     */
    var showDeleted by mutableStateOf(false)
        private set

    /**
     * 用户**手动**挑过时间了没有 —— 挑过就不再自动退档（与账本页同一条规矩：
     * "默认"只在用户还没表态时替他选）。
     */
    private var userPickedPreset = false

    /** 分类名 → 这一类"卡片突出哪一项"（详情里也要显示中文名）。 */
    fun linkKindOf(category: String): String =
        categories.firstOrNull { it.name == category }?.linkKind ?: "none"

    /** 左栏那一列：全部 + 名册（名册外的兜底行由服务端排在最后，id=0）。 */
    fun categoryTabs(): List<String> = listOf(ALL_CATEGORY) + categories.map { it.name }

    fun periodWord(): String = when {
        // 还没盘点完 → 先写「…」：这时写任何档位都是假话（窗口还没定），
        // 而"今天 → 前天"那一下正是用户说的"闪两下"里最扎眼的一半。
        !windowSettled -> "…"
        preset != DatePresets.CUSTOM -> preset
        customFrom == null || customTo == null -> DatePresets.ALL
        else -> customFrom!!.take(10).substring(5) + "~" + customTo!!.take(10).substring(5)
    }

    /** 这一段、这一类一共花了多少（服务端已经按窗口筛过，这里只把看得见的加起来）。 */
    fun total(): Double = expenses.sumOf { it.amount.toDoubleOrNull() ?: 0.0 }

    /**
     * 打开 / **从「新增开销」回来**时拉一次。
     *
     * ⚠️ 加载放在这里、不放在 `init`：从新增页 `popBackStack()` 回来时这一屏会重新进组合，
     *    `LaunchedEffect(Unit)` 会再跑一次 —— 于是刚记的那笔立刻出现在列表里。
     *    写在 init 里就只在第一次创建 VM 时拉一次，回来看到的是**没有刚记那笔**的旧列表
     *    （用户会以为没存上，然后再记一遍）。
     */
    private var started = false

    fun start() {
        loadCategories()
        // ⚠️ **先盘点、再取数**（2026-09-21 用户报的"闪两下"）：原来是先 `load()` 拉今天
        //    （多半是空的）再异步退档 —— 最坏画三帧（今天·加载 → 今天·空态 → 前天·有数据）。
        //    现在第一次进来只探测，定下来之后才取那一次数；[windowSettled] 为假时整页 loading。
        if (!started) {
            started = true
            viewModelScope.launch {
                if (!userPickedPreset) {
                    switchPreset(DatePresets.pickWindow(DatePresets.AUTO_LADDER) { periodHasData(it) })
                } else {
                    load()
                }
                windowSettled = true
            }
        } else {
            load()
        }
    }

    init {
        // 默认窗口 = 今天（用户上一轮对账本页的要求，这里同样适用）；真正的拉数在 start()
        preset = DatePresets.TODAY
        val r = DatePresets.rangeOf(DatePresets.TODAY, LocalDate.now())
        rangeFrom = r?.first
        rangeTo = r?.second
    }

    fun switchPreset(label: String) {
        preset = label
        val r = DatePresets.rangeOf(label, LocalDate.now())
        rangeFrom = r?.first
        rangeTo = r?.second
        load()
    }

    fun applyPreset(label: String) {
        userPickedPreset = true
        switchPreset(label)
    }

    fun applyCustomRange(from: String?, to: String?) {
        userPickedPreset = true
        customFrom = from
        customTo = to
        preset = if (from == null && to == null) DatePresets.ALL else DatePresets.CUSTOM
        rangeFrom = from
        rangeTo = to
        load()
    }

    private suspend fun periodHasData(label: String): Boolean {
        val r = DatePresets.rangeOf(label, LocalDate.now()) ?: return true
        return try {
            container.repo.expenses(dateFrom = r.first, dateTo = r.second).isNotEmpty()
        } catch (e: Exception) {
            false
        }
    }

    /** 默认窗口落到"真的记过开销的那一段"：今天 → 昨天 → 前天 → 近 7 天 → 全部。 */
    fun loadCategories() {
        viewModelScope.launch {
            try {
                categories = container.repo.expenseCategories()
            } catch (e: Exception) {
                error = toApiException(e).message
            }
        }
    }

    fun load() {
        loading = expenses.isEmpty()
        loadError = null
        viewModelScope.launch {
            try {
                expenses = container.repo.expenses(
                    category = selectedCategory.takeIf { it != ALL_CATEGORY },
                    dateFrom = rangeFrom,
                    dateTo = rangeTo,
                    // 二选一档：默认只看"还活着"的，切到回收站档就只看已撤销的
                    deletedOnly = showDeleted,
                )
            } catch (e: Exception) {
                loadError = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun selectCategory(name: String) {
        selectedCategory = name
        load()
    }

    fun openDetail(e: ExpenseDto) {
        detailTarget = e
    }

    fun closeDetail() {
        detailTarget = null
    }

    /** 记完一笔回来刷新（新增页在 NavGraph 里回退时调）。 */
    fun refreshAfterCreate() {
        loadCategories()
        load()
    }

    /** 切「显示已撤销」档（回收站）：换档就换一次数（两档是二选一，不是叠加）。 */
    fun toggleDeleted() {
        showDeleted = !showDeleted
        load()
    }

    /**
     * 撤销一笔开销（**软删**，不是真删）。
     *
     * 撤销之后这一笔从所有合计里退回来（利润表期间费用 / 车辆成本表窗口开销 / 收支页流出），
     * 名册里这个分类的在用笔数也少一笔；记录本身还在，随时能 [restore] 放回来。
     */
    fun cancel(e: ExpenseDto) {
        if (acting) return
        acting = true
        actionError = null
        viewModelScope.launch {
            try {
                container.repo.deleteExpense(e.id)
                lastCancelled = e
                pendingCancel = null
                load()
                // 在用笔数变了，左栏名册的计数要跟着变
                loadCategories()
            } catch (ex: Exception) {
                actionError = toApiException(ex).message
            } finally {
                acting = false
            }
        }
    }

    /** 把一笔已撤销的开销原样放回来（金额/分类/关联的司机/车辆/订单都不变）。 */
    fun restore(e: ExpenseDto) {
        if (acting) return
        acting = true
        viewModelScope.launch {
            try {
                container.repo.restoreExpense(e.id)
                actionResult = "已恢复这笔开销（¥" + formatMoney(e.amount) + "）"
                load()
                loadCategories()
            } catch (ex: Exception) {
                actionResult = toApiException(ex).message
            } finally {
                acting = false
            }
        }
    }

    /** snackbar 上那颗「撤回」：把刚撤销的那一笔放回来。 */
    fun restoreLastCancelled() {
        val e = lastCancelled ?: return
        lastCancelled = null
        restore(e)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ExpensesScreen(
    container: AppContainer,
    onBack: () -> Unit,
    onOpenOrder: (Long) -> Unit = {},
    onCreate: () -> Unit = {},
    onManageCategories: () -> Unit = {},
) {
    val vm: ExpensesViewModel = appViewModel { ExpensesViewModel(container) }
    val snackbar = remember { SnackbarHostState() }
    OneShotSnackbar(snackbar, vm.error, onConsumed = { vm.error = null })
    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })
    // 撤销之后那条 snackbar 自带一个「撤回」—— 与客户收款页同形的"手边那一下"。
    // ⚠️ 它只是**顺手**：真正的回收站档是列表顶上那颗「显示已撤销」（撤销完再回来也找得到）。
    LaunchedEffect(vm.lastCancelled) {
        val e = vm.lastCancelled ?: return@LaunchedEffect
        val res = snackbar.showSnackbar(
            message = "已撤销这笔开销（¥" + formatMoney(e.amount) + "）",
            actionLabel = "撤回",
            withDismissAction = false,
        )
        if (res == SnackbarResult.ActionPerformed) vm.restoreLastCancelled()
    }
    // 打开 / 从「新增开销」回来都拉一次（见 VM 里 start() 的注释）
    LaunchedEffect(Unit) { vm.start() }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background,
                ),
                title = { Text("开销管理", style = MaterialTheme.typography.titleLarge) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    DatePresetPill(label = vm.periodWord(), onClick = { vm.showDatePresets = true })
                },
            )
        },
        bottomBar = {
            // 与商品管理同一套底部导航：左「分类管理」描边 + 右「新增开销」实底。
            // 两个动作各占一边，视线不用跑两趟；也**没有**右下角 FAB 压着列表尾巴。
            Surface(color = MaterialTheme.colorScheme.background) {
                Row(
                    Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    OutlinedButton(
                        onClick = onManageCategories,
                        modifier = Modifier.weight(1f).height(46.dp),
                    ) {
                        Icon(Icons.Default.Category, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("分类管理")
                    }
                    Button(
                        onClick = onCreate,
                        modifier = Modifier.weight(1f).height(46.dp),
                        colors = ButtonDefaults.buttonColors(containerColor = Color(MoneyOrange)),
                    ) {
                        Icon(Icons.Default.Add, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("新增开销")
                    }
                }
            }
        },
    ) { padding ->
        Row(Modifier.fillMaxSize().padding(padding)) {
            // ---- 左：开销分类（版式是共用的 MasterRail，见 CategoryRail）----
            // ⚠️ **必须给宽度**：`MasterRail` 自己不设宽（它按可用宽度铺满），不传就是
            //    "左栏占满整屏、右边一个字都看不见"（真机上抓到过）。92dp 与商品/库存那两处同宽。
            CategoryRail(
                tabs = vm.categoryTabs(),
                selected = vm.selectedCategory,
                onSelect = { vm.selectCategory(it) },
                modifier = Modifier.width(92.dp).fillMaxHeight(),
            )
            // ---- 右：这一类、这一段的记录 ----
            Box(Modifier.weight(1f).fillMaxHeight()) {
                when {
                    // ⚠️ 「先盘点、再取数」那一帧：窗口定下来之前整页 loading
                    //    （2026-09-21 用户：「它会闪两下再跳到前天……闪两下已经不行了」）。
                    !vm.windowSettled -> LoadingBox()
                    vm.loading -> LoadingBox()
                    vm.loadError != null -> ErrorView(vm.loadError.orEmpty(), onRetry = { vm.load() })
                    else -> LazyColumn(
                        Modifier.fillMaxSize(),
                        contentPadding = PaddingValues(16.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        item {
                            SectionCard {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Text(
                                        vm.selectedCategory + " · " + vm.periodWord(),
                                        style = MaterialTheme.typography.bodyMedium,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        modifier = Modifier.weight(1f),
                                    )
                                    // 「显示已撤销」档（回收站）：已撤销的开销**不算数**，默认看不见；
                                    // 这一档既是它们的落点，也是「恢复」唯一的界面入口。
                                    TextButton(onClick = { vm.toggleDeleted() }) {
                                        Text(if (vm.showDeleted) "只看未撤销" else "显示已撤销")
                                    }
                                }
                                Spacer(Modifier.height(2.dp))
                                Text(
                                    "¥" + formatMoney(vm.total().toString()),
                                    style = MaterialTheme.typography.headlineSmall,
                                    fontWeight = FontWeight.Bold,
                                    // 回收站档里这一格是**已经不算数**的钱：换灰，别用"花了多少"的橙
                                    color = if (vm.showDeleted) MaterialTheme.colorScheme.onSurfaceVariant
                                    else Color(MoneyOrange),
                                )
                                Text(
                                    if (vm.showDeleted) "已撤销 " + vm.expenses.size + " 笔 · 这些钱现在不算数"
                                    else "共 " + vm.expenses.size + " 笔",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                        if (vm.expenses.isEmpty()) {
                            item {
                                EmptyView(
                                    "这一段没有" + (if (vm.selectedCategory == ALL_CATEGORY) "" else vm.selectedCategory) +
                                        (if (vm.showDeleted) "被撤销的" else "") + "开销",
                                    Modifier.fillMaxWidth(),
                                )
                            }
                        } else {
                            items(vm.expenses, key = { it.id }) { e ->
                                ExpenseCard(
                                    e = e,
                                    acting = vm.acting,
                                    onDetail = { vm.openDetail(e) },
                                    // 点「撤销」先弹二次确认（失败原因画在那个弹层自己里面）
                                    onCancel = { vm.pendingCancel = e; vm.actionError = null },
                                    onRestore = { vm.restore(e) },
                                )
                            }
                        }
                        item { Spacer(Modifier.height(12.dp)) }
                    }
                }
            }
        }
    }

    // 时间档位清单 + 自定义区间：两个弹层的状态机在 `DateFilterDialogs` 里（五个页面共用一份）
    DateFilterDialogs(
        showPresets = vm.showDatePresets,
        onDismissPresets = { vm.showDatePresets = false },
        preset = vm.preset,
        customFrom = vm.customFrom,
        customTo = vm.customTo,
        onPickPreset = { vm.applyPreset(it) },
        onApplyCustom = { f, t -> vm.applyCustomRange(f, t) },
    )
    vm.detailTarget?.let { e ->
        ExpenseDetailDialog(
            e = e,
            linkKindLabel = ExpenseLink.label(e.linkKind),
            onOpenOrder = { onOpenOrder(it) },
            onDismiss = { vm.closeDetail() },
        )
    }
    // 撤销的二次确认（既有的危险确认控件）。文案必须把"这不是删掉、还能恢复"说清楚 ——
    // 用户 2026-09-20 定的硬规矩：所有删除一律软删 + 必须有恢复路径。
    vm.pendingCancel?.let { e ->
        DangerConfirmDialog(
            title = "撤销这笔开销？",
            message = "撤销之后这一笔会从所有合计里退回来：利润表的期间费用、车辆成本表的窗口开销、" +
                "收支页的流出都不再算它，名册里这个分类的在用笔数也少一笔。\n" +
                "⛔ 不是删掉 —— 开销记录还在（列表顶上那颗「显示已撤销」里），" +
                "随时能点「恢复」原样放回来（金额、分类、关联的司机/车辆/订单都不变）。",
            confirmText = "撤销",
            onConfirm = { vm.cancel(e) },
            onDismiss = { vm.pendingCancel = null; vm.actionError = null },
            error = vm.actionError,
            enabled = !vm.acting,
        )
    }
}

/**
 * 开销卡片（**按分类突出主关联**，见 [ExpenseLink]）。
 *
 * 版式：
 * ```
 * [分类]                              ¥1,200.00     ← 分类（左、加粗）+ 金额（右、最大最粗、橙）
 * 车辆 粤L12345 · 09-20                             ← 突出项 + 日期
 * 司机 王建国 · 订单 SO2026…                        ← 其余关联（弱化；有才显示）
 * 备注……                                            ← 备注（弱化）
 *                                        详情 ›     ← 全部信息在详情里（含订单来源）
 * ```
 * ⚠️ 金额**只有一个**、日期**只有一处**：卡片上重复出现的信息必然会出现"两处对不上"。
 */
@Composable
private fun ExpenseCard(
    e: ExpenseDto,
    acting: Boolean,
    onDetail: () -> Unit,
    onCancel: () -> Unit,
    onRestore: () -> Unit,
) {
    val primary = ExpenseLink.primary(e)
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Surface(
                color = Color(ProductPurple).copy(alpha = 0.12f),
                shape = MaterialTheme.shapes.small,
            ) {
                Text(
                    e.category.ifBlank { "未分类" },
                    style = MaterialTheme.typography.labelLarge,
                    fontWeight = FontWeight.Bold,
                    color = Color(ProductPurple),
                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp),
                )
            }
            Spacer(Modifier.weight(1f))
            Text(
                "¥" + formatMoney(e.amount),
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold,
                color = Color(MoneyOrange),
                textAlign = TextAlign.End,
            )
        }
        Spacer(Modifier.height(6.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (primary != null) {
                Icon(
                    if (primary.kind == ExpenseLink.VEHICLE) Icons.Default.DirectionsCar else Icons.Default.PersonPin,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(15.dp),
                )
                Spacer(Modifier.width(4.dp))
                Text(
                    primary.label + " " + primary.text,
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    // ⚠️ 这一行**必须**有 weight：这里是"可伸缩的那个"，右边日期是"必须保宽的固定项"。
                    // 漏掉它的后果（2026-09-22 真机截图，411dp 下就能看见）：长单号把日期挤成一条缝，
                    // 一个 `2026-09-19` 被折成 `202` / `6-0` / `9-1` / `9` 四行。
                    modifier = Modifier.weight(1f),
                )
                Spacer(Modifier.width(8.dp))
            }
            Text(
                e.expDate.take(10),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        val secondary = ExpenseLink.secondary(e)
        if (secondary.isNotEmpty()) {
            Spacer(Modifier.height(2.dp))
            Text(
                secondary.joinToString(" · ") { it.label + " " + it.text },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        if (e.note.isNotBlank()) {
            Spacer(Modifier.height(2.dp))
            Text(
                e.note,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 2,
            )
        }
        if (e.isDeleted) {
            Spacer(Modifier.height(4.dp))
            Hint(
                "已撤销" + (e.deletedAt?.take(10)?.let { "（" + it + "）" } ?: "") +
                    " —— 这笔钱现在不算数，点「恢复」原样放回来",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
            // 撤销/恢复就在**这一行上**（手边的入口）；恢复只出现在回收站档里。
            if (e.isDeleted) {
                TextButton(onClick = onRestore, enabled = !acting) { Text("恢复") }
            } else {
                TextButton(onClick = onCancel, enabled = !acting) {
                    Text("撤销", color = MaterialTheme.colorScheme.error)
                }
            }
            TextButton(onClick = onDetail) {
                Text("详情")
                Icon(Icons.Default.ChevronRight, contentDescription = null, modifier = Modifier.size(16.dp))
            }
        }
    }
}

/**
 * 开销详情：**全部字段** + 订单来源（用户：「我们点击详情进行查看的时候，
 * 还是可以查看证明这个订单到底是哪里来的」）。
 */
@Composable
private fun ExpenseDetailDialog(
    e: ExpenseDto,
    linkKindLabel: String,
    onOpenOrder: (Long) -> Unit,
    onDismiss: () -> Unit,
) {
    CardAlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("开销详情") },
        text = {
            Column {
                DetailRow("分类", e.category.ifBlank { "未分类" })
                DetailRow("金额", "¥" + formatMoney(e.amount))
                DetailRow("日期", e.expDate.take(10))
                DetailRow("这类开销主要关联", linkKindLabel)
                DetailRow("车辆", e.vehicleName?.ifBlank { null } ?: "—")
                DetailRow("司机", e.driverName?.ifBlank { null } ?: "—")
                DetailRow("关联订单", e.orderNo?.ifBlank { null } ?: "（不是从订单来的）")
                if (e.note.isNotBlank()) DetailRow("备注", e.note)
                if (e.orderId != null) {
                    Spacer(Modifier.height(8.dp))
                    OutlinedButton(
                        onClick = { onOpenOrder(e.orderId!!) },
                        modifier = Modifier.fillMaxWidth(),
                    ) { Text("看这一单") }
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("关闭") } },
    )
}

/** 详情里的一行：左标签固定宽度、右值可换行（值长的时候不会把标签挤没）。 */
@Composable
private fun DetailRow(label: String, value: String) {
    Row(Modifier.fillMaxWidth().padding(vertical = 3.dp)) {
        Text(
            label,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.width(96.dp),
        )
        Text(value, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
    }
}
