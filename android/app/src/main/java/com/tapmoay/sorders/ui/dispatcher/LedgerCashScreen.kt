package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
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
import com.tapmoay.sorders.data.remote.dto.CashFlowBreakdownDto
import com.tapmoay.sorders.data.remote.dto.CashFlowBreakdownRowDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.CashIn
import com.tapmoay.sorders.ui.theme.CashOut
import com.tapmoay.sorders.util.formatMoney
import java.time.LocalDate
import kotlinx.coroutines.launch

/**
 * 「收支」—— 账本管理里那一格（2026-09-22 用户要求）。
 *
 * ## 用户原话
 * > 「在**账本管理新建一个区域，这个区域就是支出和收入**……支出主要是**给供应商/厂商付尾款**、
 * > 买装备/设备付的款、邮费等等；我记得**好像有个开销管理**吧，干脆把我们两个**整合在一起**。
 * > **收入**也要**跟现在的系统做一个合并**，但**具体的收入来源要明细一下** ——
 * > 这个系统其实做的**就是收入这一个环节**。」
 *
 * ## 三个决定（别再折腾）
 * 1. **一路一行，不是三个数**。用户要的是"收入**来源**明细"：客户收款/挂账结清/预收款…每路一行、
 *    带金额与笔数；点一行进**那一类的流水明细**（同一时间窗口带过去）。
 *    汇总（净额/收入/支出三个数）仍然画在最上面那张卡上，但它是"封面"，不是全部内容。
 * 2. ⛔ **金额一律取服务端**（`GET /cash-flows/breakdown`）：它与 `/summary` 在**后端共用同一套
 *    筛选与同一个 SQL 侧求和**，所以"分项加起来"必然等于"汇总"。
 *    客户端拉一页流水自己按 `biz_type` 分类求和会**同时**踩两个坑：列表被截断（少算，实测 62%）
 *    与分类口径走散。这件事在 2026-09-19 的审计里定过案（见 `CashFlowSummaryDto` 的注释）。
 * 3. **中文名只有一份**：`ReportFinance.bizLabel()`（后端只给枚举名 `RECEIPT_CASH` 这种）。
 *    认不出来的 `biz_type` 原样显示 —— 编一个"其他"会把"账上出现了我没见过的东西"藏起来，
 *    而这一页恰恰是用来发现它的。
 *
 * ## 「开销管理」去哪了
 * 它**没有被删**，也不再与这一页**并列占一格**（那正是用户说的"整合在一起"）：
 * 支出那张卡底部有「开销管理」入口（记一笔开销、分类管理都在那一页）。
 * ⛔ 谁要把它加回账本管理入口页，先看 `Modules.ledgerHomeEntries` 上面那段注释。
 */
class LedgerCashViewModel(private val container: AppContainer) : ViewModel() {

    var data by mutableStateOf<CashFlowBreakdownDto?>(null)
        private set
    var loading by mutableStateOf(false)
        private set
    var loadError by mutableStateOf<String?>(null)

    // ⚠️ 窗口那几个字段**必须声明在 `init {}` 之前**：init 会写 `rangeFrom/rangeTo`，
    //    写在后面就是"打开这一页直接崩"（判据 `_tools/qa/_check_vm_state_before_init.py`）。
    var rangeFrom by mutableStateOf<String?>(null)
        private set
    var rangeTo by mutableStateOf<String?>(null)
        private set

    var preset by mutableStateOf(DatePresets.TODAY)
        private set
    var customFrom by mutableStateOf<String?>(null)
        private set
    var customTo by mutableStateOf<String?>(null)
        private set
    var showDatePresets by mutableStateOf(false)

    /** **窗口定下来了没有**（与账本/开销页同一条规矩：先盘点、再取数，不许"闪两下"）。 */
    var windowSettled by mutableStateOf(false)
        private set

    /** 用户**手动**挑过档位没有 —— 挑过就永不自动改（不许抢方向盘）。 */
    private var userPickedPreset = false
    private var started = false

    fun periodWord(): String = when {
        // 还没盘点完就先写「…」：这时写任何档位都是假话
        !windowSettled -> "…"
        preset != DatePresets.CUSTOM -> preset
        customFrom == null || customTo == null -> DatePresets.ALL
        else -> customFrom!!.take(10).substring(5) + "~" + customTo!!.take(10).substring(5)
    }

    fun start() {
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

    /** 这一段有没有钱动过（自动退档用；分项端点一次就把"有没有"说清了）。 */
    private suspend fun periodHasData(label: String): Boolean {
        val r = DatePresets.rangeOf(label, LocalDate.now()) ?: return true
        return try {
            container.repo.cashFlowBreakdown(dateFrom = r.first, dateTo = r.second).count > 0
        } catch (e: Exception) {
            false
        }
    }

    fun load() {
        loading = data == null
        loadError = null
        viewModelScope.launch {
            try {
                data = container.repo.cashFlowBreakdown(dateFrom = rangeFrom, dateTo = rangeTo)
            } catch (e: Exception) {
                loadError = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LedgerCashScreen(
    container: AppContainer,
    onBack: () -> Unit,
    onOpenDetail: (direction: String, bizType: String, from: String?, to: String?) -> Unit = { _, _, _, _ -> },
    onOpenExpenses: () -> Unit = {},
    onOpenSuppliers: () -> Unit = {},
) {
    val vm: LedgerCashViewModel = appViewModel { LedgerCashViewModel(container) }
    LaunchedEffect(Unit) { vm.start() }
    val d = vm.data

    Scaffold(
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background,
                ),
                title = { Text("收支", style = MaterialTheme.typography.titleLarge) },
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
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            when {
                // ⚠️ 「先盘点、再取数」那一帧：窗口定下来之前整页 loading（一次都不画错窗口）
                !vm.windowSettled -> LoadingBox()
                vm.loading -> LoadingBox()
                vm.loadError != null -> ErrorView(vm.loadError.orEmpty(), onRetry = { vm.load() })
                d == null -> LoadingBox()
                else -> LazyColumn(
                    Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    item { NetCard(d = d, period = vm.periodWord()) }
                    item {
                        CashGroupCard(
                            title = "收入",
                            subtitle = "钱从哪来（每一路都能点进去看流水）",
                            rows = d.income,
                            total = d.incomeTotal,
                            accent = Color(CashIn),
                            emptyWord = "这一段没有进账",
                            onOpen = { onOpenDetail("in", it.bizType, vm.rangeFrom, vm.rangeTo) },
                        )
                    }
                    item {
                        CashGroupCard(
                            title = "支出",
                            subtitle = "钱花到哪去了（每一路都能点进去看流水）",
                            rows = d.expense,
                            total = d.expenseTotal,
                            accent = Color(CashOut),
                            emptyWord = "这一段没有出账",
                            onOpen = { onOpenDetail("out", it.bizType, vm.rangeFrom, vm.rangeTo) },
                            // 「开销管理」并入这里（用户：「干脆把我们两个整合在一起」）：
                            // ⛔ 它不是被删了 —— 记一笔开销、分类管理都在那一页。
                            // 「供应商 / 应付」也挂在这里（2026-09-22）：用户点名"支出主要是给供应商付尾款"，
                            // 所以这一块的两件事（一次性开销 / 往来欠款）都从支出卡底部进。
                            footer = {
                                Column {
                                    CashRowShell(onClick = onOpenExpenses) {
                                        Icon(
                                            Icons.Default.Receipt, contentDescription = null,
                                            modifier = Modifier.size(18.dp), tint = Color(CashOut),
                                        )
                                        Spacer(Modifier.width(8.dp))
                                        Column(Modifier.weight(1f)) {
                                            Text("开销管理", style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.SemiBold)
                                            Text(
                                                "按分类看开销、记一笔开销、改分类（8 类物流开销在那里）",
                                                style = MaterialTheme.typography.bodySmall,
                                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                            )
                                        }
                                        Icon(Icons.Default.ChevronRight, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                                    }
                                    CashRowShell(onClick = onOpenSuppliers) {
                                        Icon(
                                            Icons.Default.Storefront, contentDescription = null,
                                            modifier = Modifier.size(18.dp), tint = Color(CashOut),
                                        )
                                        Spacer(Modifier.width(8.dp))
                                        Column(Modifier.weight(1f)) {
                                            Text("供应商 / 应付款", style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.SemiBold)
                                            Text(
                                                "欠供应商/厂商多少、付尾款、采购设备与邮费（可分次付款）",
                                                style = MaterialTheme.typography.bodySmall,
                                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                            )
                                        }
                                        Icon(Icons.Default.ChevronRight, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                                    }
                                }
                            },
                        )
                    }
                }
            }
        }
    }

    // 时间档位清单 + 自定义区间：两个弹层的状态机在 `DateFilterDialogs`（多个页面共用一份）
    DateFilterDialogs(
        showPresets = vm.showDatePresets,
        onDismissPresets = { vm.showDatePresets = false },
        preset = vm.preset,
        customFrom = vm.customFrom,
        customTo = vm.customTo,
        onPickPreset = { vm.applyPreset(it) },
        onApplyCustom = { f, t -> vm.applyCustomRange(f, t) },
    )
}

/**
 * 顶上那张「封面」卡：净额 + 两边合计。
 *
 * ⚠️ 三个数**全部取服务端**（同一窗口、同一套筛选）；这一页任何地方都不做算术。
 */
@Composable
private fun NetCard(d: CashFlowBreakdownDto, period: String) {
    SectionCard {
        Text(period, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.height(2.dp))
        Text("净额", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(
            "¥" + formatMoney(d.net),
            style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.Bold,
        )
        Spacer(Modifier.height(6.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("收入 ", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(
                "¥" + formatMoney(d.incomeTotal),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
                color = Color(CashIn),
            )
            // 段间竖分隔线（设计规范里横排两组数就是这么分的）
            Text(
                "  |  ",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.outlineVariant,
            )
            Text("支出 ", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(
                "¥" + formatMoney(d.expenseTotal),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
                color = Color(CashOut),
            )
        }
        Text(
            "这一段一共 " + d.count + " 笔流水（点下面每一路看明细）",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/**
 * 一组（收入 / 支出）：标题 + 合计 + 每一路一行 + 可选的底部入口。
 *
 * ⚠️ 两组**共用这一个**：抄成两份的话，收入那边改了、支出这边忘了，
 *    两个看起来一样的卡片会慢慢长得不一样（这个仓库栽过多次）。
 */
@Composable
private fun CashGroupCard(
    title: String,
    subtitle: String,
    rows: List<CashFlowBreakdownRowDto>,
    total: String,
    accent: Color,
    emptyWord: String,
    onOpen: (CashFlowBreakdownRowDto) -> Unit,
    footer: (@Composable () -> Unit)? = null,
) {
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Text(
                    subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(
                "¥" + formatMoney(total),
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.Bold,
                color = accent,
            )
        }
        Spacer(Modifier.height(8.dp))
        if (rows.isEmpty()) {
            Text(
                emptyWord,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        } else {
            rows.forEachIndexed { i, r ->
                if (i > 0) HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                CashRowShell(onClick = { onOpen(r) }) {
                    Column(Modifier.weight(1f)) {
                        // 中文名只有一份（`ReportFinance.bizLabel`）；认不出来就原样显示枚举名
                        Text(
                            ReportFinance.bizLabel(r.bizType).ifBlank { "未标注" },
                            style = MaterialTheme.typography.bodyLarge,
                            fontWeight = FontWeight.SemiBold,
                        )
                        Text(
                            r.count.toString() + " 笔",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Text(
                        "¥" + formatMoney(r.amount),
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold,
                        color = accent,
                    )
                    Icon(
                        Icons.Default.ChevronRight, contentDescription = null,
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
        if (footer != null) {
            if (rows.isNotEmpty()) HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            footer()
        }
    }
}

/** 一行可点内容的统一外壳（左边距与各行对齐、整行可点）。 */
@Composable
private fun CashRowShell(onClick: () -> Unit, content: @Composable RowScope.() -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
        content = content,
    )
}
