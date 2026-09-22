package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.*
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.DatePresets
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import java.time.LocalDate

class ReportCenterViewModel(
    private val container: AppContainer,
    initialTab: Int,
) : ViewModel() {

    var tab by mutableStateOf(initialTab.coerceIn(0, 5))

    /**
     * 时间**档位**（`DatePresets` 那一套：今天 / 昨天 / 前天 / 这周 / 上周 / 近 7 天 / 本月 / 上月 /
     * 近一年 / 自定义）——顶栏右上角那颗药丸上写的就是它，点开是共用的档位清单。
     *
     * ⚠️ 2026-09-22 之前这里是 `mode`（day/week/month）+ `anchor`（锚点日）：
     * 页面里铺一条「完整时段 + 按日/按周/按月」的导航，**点那条时段会直接弹系统日历**
     * （用户：「点击商品经营的时候有时候会弹出一个日历吧……这个也是个**小bug**」——
     * 那条可点区域的实测尺寸是 761×126 px，正压在顶栏下面，随手一点就弹）。
     * 换成档位之后：**页面里没有时间控件**，只有顶栏那颗药丸 + 我们的弹层。
     */
    var preset by mutableStateOf(DatePresets.TODAY)
    var customFrom by mutableStateOf<String?>(null)
    var customTo by mutableStateOf<String?>(null)

    var loading by mutableStateOf(false)

    /**
     * 时间窗口**定下来没有**（`DatePresets.pickWindow` 的配套门）。
     *
     * 为 `false` 时页面**整页 loading、连那颗药丸都不画** —— 一次都不许画错窗口
     * （用户 2026-09-21：「它会**闪两下**再跳到「前天」……闪两下已经不行了」）。
     */
    var windowSettled by mutableStateOf(false)
        private set

    var error by mutableStateOf<String?>(null)
    var chartType by mutableStateOf("line")

    var turnover by mutableStateOf<TurnoverReportDto?>(null)
    var products by mutableStateOf<ProductReportDto?>(null)
    var drivers by mutableStateOf<DriverPerformanceDto?>(null)
    var exceptions by mutableStateOf<List<ExceptionOrderDto>>(emptyList())
    var operationLogs by mutableStateOf<List<OperationLogDto>>(emptyList())

    /**
     * 审计日志"这一页不是全部"＝更早的还有。
     *
     * 判据是响应头 `X-Truncated`（2026-09-19 后端补的头，走 `AppRepository.pageMeta()`）——
     * 不说出来的后果不是"少看几条"，而是用户据此判断**"我那次改动没被记录"**。
     */
    var operationLogsTruncated by mutableStateOf(false)

    /** 本次服务器上限（`X-Result-Limit`）；null = 老后端没回报，界面不许自己编一个数。 */
    var operationLogsLimit by mutableStateOf<Int?>(null)
    // 客户账分组（营业纵览）
    var shipperAccounts by mutableStateOf<List<LedgerAccountOut>>(emptyList())
    var memberAccounts by mutableStateOf<List<LedgerAccountOut>>(emptyList())
    // 营业纵览挂账TOP（后端 turnover 已含）；客户经营页独立汇总
    var customerArrears by mutableStateOf<List<ReportArrearsUnitDto>>(emptyList())
    // 资金收支
    var cashFlows by mutableStateOf<List<CashFlowDto>>(emptyList())

    /** 资金流水明细"这一页不是全部"＝这一窗口更早的没取到（判据同样是响应头 `X-Truncated`）。 */
    var cashFlowsTruncated by mutableStateOf(false)
    var cashFlowsLimit by mutableStateOf<Int?>(null)
    /** 资金汇总（流入/流出/净额/笔数）——**服务端算的**，不在这里求和。 */
    var cashFlowSummary by mutableStateOf<CashFlowSummaryDto?>(null)
    var expenses by mutableStateOf<List<ExpenseDto>>(emptyList())
    // 商品明细筛选
    var productSearch by mutableStateOf("")
    var productSort by mutableStateOf("amount") // amount | qty | profit | damage
    var productShowAll by mutableStateOf(false)

    var actionResult by mutableStateOf<String?>(null)
    var exporting by mutableStateOf(false)

    var resolveTarget by mutableStateOf<ExceptionOrderDto?>(null)
    var resolveNote by mutableStateOf("")
    var resolving by mutableStateOf(false)

    val pendingExceptionCount: Int get() = exceptions.count { it.exceptionResolvedAt == null }

    /** 药丸上的字：档位名（自定义时写那一段日期：`09-01~09-20`）。 */
    val periodLabel: String
        get() = if (preset == DatePresets.CUSTOM) {
            DatePresets.customLabel(customFrom, customTo)
        } else {
            preset
        }

    /**
     * 这一次要看的窗口 `(from, to)` —— **六个页签共用这一处**（页面、导出、探测都用它）。
     * 算法在 [ReportFinance.windowOf]（纯函数 + 单测）：自定义用那段区间，其余档位问
     * `DatePresets.rangeOf`，「全部」落成 `2000-01-01~今天`。
     */
    val dateRange: Pair<String, String>
        get() = ReportFinance.windowOf(preset, customFrom, customTo, LocalDate.now())

    /** 筛选后的商品明细（按当前排序） */
    val filteredProducts: List<ProductReportItemDto> get() {
        val items = products?.items.orEmpty()
        val base = if (productSearch.isBlank()) items else items.filter { it.productName.contains(productSearch, ignoreCase = true) }
        return when (productSort) {
            "qty" -> base.sortedByDescending { it.qty }
            "profit" -> base.sortedByDescending { (it.amount.toDoubleOrNull() ?: 0.0) - (it.cost.toDoubleOrNull() ?: 0.0) }
            "damage" -> base.sortedByDescending { it.damageQty }
            else -> base // amount 已在后端排序
        }
    }

    init {
        // 「异常与审计」这一页**没有时间导航**（固定近 30 天）→ 没有窗口要定，直接就画。
        if (tab == 5) {
            windowSettled = true
            load()
        } else {
            settleWindowThenLoad()
        }
    }

    /**
     * **先把窗口定下来，再取那一次数**（用户 2026-09-21：「闪两下已经不行了，不美观，且占用性能」）。
     *
     * 这条规矩本来只长在"看账/看订单"的页面上，**报表中心当时漏了** —— 于是它一直写死
     * 「按日 + 今天」：今天只要还没有已送达的单，一进去整页都是
     * 「¥0.00 / 0 单 / 毛利 0 行 / 收款率 0%」。用户 2026-09-22 报的就是这个：
     * > 修一下**报告中心没有任何数据**的bug。
     *
     * 阶梯用仓库里那条长的（[DatePresets.ORDER_PRESET_LADDER]：今天→昨天→前天→这周→上周→近 7 天→本月→上月），
     * 一档一档**探测**（打的就是本页第一屏自己要打的那个接口、用的就是那一档的区间），
     * 第一个有数的就是它。全都没数 → 保持默认（今天），把"真没有"如实画出来。
     */
    private fun settleWindowThenLoad() {
        viewModelScope.launch {
            val today = LocalDate.now()
            val picked = DatePresets.pickWindow(DatePresets.ORDER_PRESET_LADDER) { label ->
                val span = DatePresets.rangeOf(label, today) ?: return@pickWindow false
                windowHasData(span.first, span.second)
            }
            // 都没数时 `pickWindow` 给的是「全部」→ 保持默认（今天），把"真没有"如实画出来
            if (picked != DatePresets.ALL) preset = picked
            windowSettled = true
            load()
        }
    }

    /**
     * 这一段有没有数（探测）。
     *
     * ⚠️ 判据必须与页面自己的取数**同源**：探测打的就是本页第一屏要打的那个接口
     * （`GET /reports/turnover`）、用的就是**同一段区间**（`date_from`/`date_to`）。
     * 换个便宜的近似接口 = "探到了、进去还是空"，正是上一轮那个 bug 的翻版。
     * ⚠️ 网络/接口出错一律当"这一档没数"继续往后退：**不能因为一次失败把整页卡在 loading 上**。
     * ⚠️ 协程被取消时**原样抛出**（把 `CancellationException` 当成业务失败吞掉，
     *    会接着往下做一件用户已经不要的事）。
     */
    private suspend fun windowHasData(from: String, to: String): Boolean = try {
        val r = container.repo.turnoverReport(ReportFinance.LEGACY_MODE, from, from, to)
        ReportFinance.hasData(r.totalOrders, r.totalAmount)
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        false
    }

    /**
     * 用户自己挑了档位（今天 / 昨天 / … / 自定义）。
     *
     * ⚠️ 名字**不能**叫 `setPreset` 之外的 `setXxx(与某个 var 同名)`：`var preset` 的属性 setter
     *    在 JVM 上就是 `setPreset(String)`，再写一个同名的 `fun setPreset` 会编译报
     *    `Platform declaration clash`（运费结算页的 `pickMonth`、上一版的 `pickMode` 都是这个坑）。
     */
    fun applyPreset(label: String) {
        preset = label
        load()
    }

    /** 用户自己选了一段自定义区间（两头都给了才算；两头都没选 = 清掉，与账本页同一套语义）。 */
    fun applyCustomRange(from: String?, to: String?) {
        if (from != null && to != null) {
            preset = DatePresets.CUSTOM
            customFrom = from
            customTo = to
        }
        load()
    }

    fun load() {
        loading = true
        error = null
        viewModelScope.launch {
            try {
                when (tab) {
                    0 -> {
                        val (f, t) = dateRange
                        turnover = container.repo.turnoverReport(ReportFinance.LEGACY_MODE, f, f, t)
                        shipperAccounts = container.repo.ledgerAccounts(f, t, "shipper")
                        memberAccounts = container.repo.ledgerAccounts(f, t, "member")
                        // 「异常订单数」这一行原来读的是"异常页签加载出来的列表"，而那只在切到
                        // 「异常与审计」时才赋值 → 从工作台直接进营业纵览时**恒显示 0 单**；
                        // 先看过异常页再回来又会显示近 30 天的数（同屏其它数字是当天/周/月的）。
                        // 现在这一页**自己**去取，口径写明是"近 30 天待处理"（2026-09-19 审计）。
                        val today = LocalDate.now()
                        exceptions = container.repo.exceptionOrders(
                            today.minusDays(30).toString(), today.toString(),
                        )
                    }
                    1 -> {
                        val (f, t) = dateRange
                        products = container.repo.productReport(ReportFinance.LEGACY_MODE, f, f, t)
                    }
                    2 -> {
                        // ⚠️ 取数窗口必须与**标题/导出**同源（2026-09-19 审计 R13-R2）：
                        //    这里原来自己算了一遍（`month -> d.withDayOfMonth(1) to d`，即 1 号到**锚点当天**），
                        //    而标题与导出走整月。锚点选 8/15 时，页面按 8/1~8/15 取数（16 单）、
                        //    标题写"8 月"、导出给整月（34 单）—— 同一个页面两个数，用户对不上账。
                        //    现在六个页签共用 `dateRange` 这一处。
                        val (from, to) = dateRange
                        drivers = container.repo.driverPerformance(from, to)
                    }
                    3 -> {
                        // 客户经营：货主账/批发商账 + 挂账未收
                        val (f, t) = dateRange
                        shipperAccounts = container.repo.ledgerAccounts(f, t, "shipper")
                        memberAccounts = container.repo.ledgerAccounts(f, t, "member")
                        customerArrears = container.repo.arrearsSummary(f, t)
                    }
                    4 -> {
                        // 资金收支：明细用于列表，**金额一律取服务端汇总**（2026-09-19 审计）——
                        // 原来在客户端对"这一页流水"求和，而列表有 limit（默认 200）：
                        // 实测同一窗口 200 条 → 流入 ¥18,842、273 条 → ¥48,905.50（少算 62%），
                        // 而同一页 Excel 导出是 SQL 侧全窗口求和 → 页面一个数、导出一个数。
                        val (f, t) = dateRange
                        // 截断位跟着行一起回来（`X-Truncated`/`X-Result-Limit`）：明细被截断时
                        // 界面要说出来，否则用户会把"看得见的几行"当成整个窗口的明细。
                        val flowPage = container.repo.cashFlowsPage(dateFrom = f, dateTo = t)
                        cashFlows = flowPage.rows
                        cashFlowsTruncated = flowPage.meta.hasMore
                        cashFlowsLimit = flowPage.meta.limit
                        cashFlowSummary = container.repo.cashFlowSummary(dateFrom = f, dateTo = t)
                        expenses = container.repo.expenses(dateFrom = f, dateTo = t)
                    }
                    else -> {
                        // 异常与审计
                        val today = LocalDate.now()
                        exceptions = container.repo.exceptionOrders(today.minusDays(30).toString(), today.toString())
                        val logPage = container.repo.operationLogsPage(60)
                        operationLogs = logPage.rows
                        operationLogsTruncated = logPage.meta.hasMore
                        operationLogsLimit = logPage.meta.limit
                    }
                }
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    /**
     * 导出当前报表为 Excel（保存到系统下载目录），返回保存路径；失败返回 null。
     *
     * ⚠️ 页签→kind 的映射在 [ReportFinance] 里（纯函数 + 单测）—— 它**错过一次**：
     * 导出一张"名字对、内容错"的表（客户经营的文件里装着异常审计），导出还提示"成功"。
     * ⚠️ 2026-09-22 起 `date_from/date_to` 对**六个 kind 全生效**（后端 `reports.py::_span` 一处判），
     *    所以这里不再按页签挑"要不要给区间" —— **给的就是页面上那一段**，
     *    否则"我看到的"和"我导出的"又会是两个区间（这类错页面上看不出来）。
     */
    fun exportCurrent(onDone: (ByteArray?) -> Unit) {
        if (exporting) return
        exporting = true
        viewModelScope.launch {
            val kind = ReportFinance.exportKind(tab)
            // 异常与审计页固定看近 30 天（那个页面没有时间导航），导出必须跟着同一段走
            val (from, to) = if (tab == 5) {
                val today = LocalDate.now()
                today.minusDays(30).toString() to today.toString()
            } else {
                dateRange
            }
            try {
                val bytes = container.repo.exportReport(
                    kind = kind,
                    mode = ReportFinance.LEGACY_MODE,
                    date = from,
                    dateFrom = from,
                    dateTo = to,
                ).bytes()
                onDone(bytes)
            } catch (e: Exception) {
                actionResult = "导出失败：" + toApiException(e).message
                onDone(null)
            } finally {
                exporting = false
            }
        }
    }

    fun openResolve(target: ExceptionOrderDto) {
        resolveTarget = target
        resolveNote = ""
    }

    fun confirmResolve() {
        val t = resolveTarget ?: return
        resolving = true
        viewModelScope.launch {
            try {
                container.repo.resolveException(t.id, resolveNote.trim().ifBlank { null })
                actionResult = "已标记解决"
                resolveTarget = null
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                resolving = false
            }
        }
    }
}