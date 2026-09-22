package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.clickable
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
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.CashFlowDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.CashIn
import com.tapmoay.sorders.ui.theme.CashOut
import com.tapmoay.sorders.util.formatMoney
import kotlinx.coroutines.launch

/**
 * 「收支」里点某一路进来的**流水明细**（同一个时间窗口、同一类）。
 *
 * ## 为什么要它
 * 总览页回答"每一路多少"，用户紧接着要问的必然是"**那几笔是哪几笔**"——
 * 少了这一步，"收入来源明细"这句话只做了一半。
 *
 * ## 口径
 * · **窗口由总览页带过来**（route 参数），不在这里重新挑：换一次窗口再进来看到的数
 *   会与刚才那一路的合计对不上，用户以为账错了。
 * · 明细行数有上限（服务端一页 1000 条）→ 真被截断时说清楚（`TruncationNote`），
 *   ⛔ 不许把"看得见的几行"当成全部。
 * · 金额一律用服务端给的那一列，**不在这一页再求一次和**（总览页那三个数就是权威）。
 * · 挂在本单上的流水可以点进订单详情（`orderId` 非空才可点 —— 与账本/开销两页同一条规矩）。
 */
class LedgerCashDetailViewModel(
    private val container: AppContainer,
    val direction: String,
    val bizType: String,
    private val dateFrom: String?,
    private val dateTo: String?,
) : ViewModel() {

    var rows by mutableStateOf<List<CashFlowDto>>(emptyList())
        private set
    var loading by mutableStateOf(true)
        private set
    var loadError by mutableStateOf<String?>(null)
        private set

    /** 被截断时的上限值（`null` = 没截断）。 */
    var truncatedLimit by mutableStateOf<Int?>(null)
        private set

    fun load() {
        loading = rows.isEmpty()
        loadError = null
        viewModelScope.launch {
            try {
                val page = container.repo.cashFlowsPage(
                    direction = direction,
                    bizType = bizType,
                    dateFrom = dateFrom,
                    dateTo = dateTo,
                )
                rows = page.rows
                truncatedLimit = if (page.meta.hasMore) page.meta.limit else null
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
fun LedgerCashDetailScreen(
    container: AppContainer,
    direction: String,
    bizType: String,
    dateFrom: String?,
    dateTo: String?,
    onBack: () -> Unit,
    onOpenOrder: (Long) -> Unit = {},
) {
    val vm: LedgerCashDetailViewModel = appViewModel {
        LedgerCashDetailViewModel(container, direction, bizType, dateFrom, dateTo)
    }
    LaunchedEffect(Unit) { vm.load() }
    val isIncome = ReportFinance.isIncome(vm.direction)
    val accent = Color(if (isIncome) CashIn else CashOut)

    Scaffold(
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background,
                ),
                title = {
                    Text(
                        // 中文名只有一份（`ReportFinance.bizLabel`）；认不出来就原样显示枚举名
                        ReportFinance.bizLabel(vm.bizType).ifBlank { "未标注" },
                        style = MaterialTheme.typography.titleLarge,
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            when {
                vm.loading -> LoadingBox()
                vm.loadError != null -> ErrorView(vm.loadError.orEmpty(), onRetry = { vm.load() })
                else -> LazyColumn(
                    Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    item {
                        SectionCard {
                            Text(
                                (if (isIncome) "收入" else "支出") + " · " +
                                    (ReportFinance.bizLabel(vm.bizType).ifBlank { "未标注" }),
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            Spacer(Modifier.height(2.dp))
                            Text(
                                vm.rows.size.toString() + " 笔（这一段）",
                                style = MaterialTheme.typography.titleMedium,
                                fontWeight = FontWeight.Bold,
                                color = accent,
                            )
                            Text(
                                "窗口：" + windowWord(dateFrom, dateTo),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                    items(vm.rows, key = { it.id }) { f ->
                        FlowRowCard(f = f, accent = accent, onOpenOrder = onOpenOrder)
                    }
                    if (vm.truncatedLimit != null) {
                        item {
                            // ⚠️ 这一页**故意没有时间控件**（窗口由「收支」带过来，见文件头）——
                            //    所以这里唯一诚实的说法是"这份明细**可能不全**"，
                            //    ⛔ 不能承诺"用上面那个时间筛一下"（这一页上面没有时间控件）。
                            //    与「各批发商价格」那一页是同一个道理（`_check_page_truncation_wiring`
                            //    的白名单里专门为这种情况收下了这句话）。
                            TruncationNote(
                                vm.truncatedLimit,
                                "这一类流水可能不全（一页最多显示 " +
                                    vm.truncatedLimit + " 笔）—— 想看得更细，" +
                                    "回「收支」把右上角的时间换成更短的一段",
                            )
                        }
                    }
                }
            }
        }
    }
}

/** 窗口怎么写（与「收支」页右上角那颗药丸同一套说法：没给就是"全部"）。 */
private fun windowWord(from: String?, to: String?): String =
    if (from == null && to == null) "全部" else (from.orEmpty() + " ~ " + to.orEmpty())

/**
 * 一笔流水。
 *
 * 版式（与账本/开销两页的明细行同形）：
 * ```
 * 09-20  客户收款（现金）              +¥1,200.00
 *        张三 · 单号 SO2026…                     ← 点得进订单详情
 * ```
 * ⚠️ 进/出用**符号 + 语义色**双写：老人看不清颜色时，符号还在。
 */
@Composable
private fun FlowRowCard(f: CashFlowDto, accent: Color, onOpenOrder: (Long) -> Unit) {
    val income = ReportFinance.isIncome(f.direction)
    SectionCard(
        modifier = Modifier.clickable(enabled = f.orderId != null) {
            f.orderId?.let(onOpenOrder)
        },
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(
                    dayWord(f.flowDate) + "  " + ReportFinance.bizLabel(f.bizType).ifBlank { "未标注" },
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    (f.partyName.orEmpty().ifBlank { "—" }) +
                        if (f.orderId != null) " · 点开订单" else "",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(
                (if (income) "+¥" else "−¥") + formatMoney(f.amount),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                color = accent,
            )
            if (f.orderId != null) {
                Icon(
                    Icons.Default.ChevronRight, contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

/** `2026-09-20` → `09-20`（年份在同一段窗口里是多余的；空值原样显示）。 */
private fun dayWord(flowDate: String): String =
    if (flowDate.length >= 10) flowDate.substring(5, 10) else flowDate
