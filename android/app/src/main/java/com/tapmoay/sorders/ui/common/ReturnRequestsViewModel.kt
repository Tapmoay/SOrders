package com.tapmoay.sorders.ui.common

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.ReturnRequestDto
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

/** 「退货申请」两端共用的一个档位（`key` 直接透给后端的 `status=`）。 */
data class ReturnTab(val key: String, val label: String)

/** [ReturnRequestsViewModel.fetchPage] 的返回值：这一页的列表 + 后端给的待处理张数。 */
data class ReturnRequestsPage(val items: List<ReturnRequestDto>, val pendingCount: Int)

/**
 * 「退货申请」两端（**派单员待办** / **货主我的申请**）共用的**列表内核**。
 *
 * ### 为什么必须共用（2026-09-21 精简轮）
 * 两个页面原来各写了约 90 行**逐字相同**的东西：档位状态、`load()`、`applyFocus`、`selectTab`、
 * 以及"货主提了 / 派单员办完之后自动重拉"。它们**不是样式，是规则**：
 *
 * 1. **带 `?focus=` 进来时必须先切到「全部」档再拉** —— 否则"已经办完的那一条"在「待处理」里
 *    必然找不到，界面就变成「明明有这条，却告诉用户没找到」；
 * 2. **定位不到时必须给一行说明**（见 [RETURN_REQUEST_FOCUS_MISS]），不白屏、也不假装定位成功；
 * 3. **找到的那一条排到最前并打标记**（[focusReturnRequestFirst]，两端做法必须一样）；
 * 4. **实时刷新**：货主提了 / 派单员办完之后列表自己冒出来，不靠用户手动退出再进。
 *
 * 两端只差三件事 —— **档位表**、**拉哪个接口**、**各自能做什么动作** —— 那三件留在子类里。
 * 抄两份的代价很具体：上面四条只要有一份没跟上，就只有一个角色会遇到那个毛病，而另一个不会。
 */
abstract class ReturnRequestsViewModel(
    /** 拉数据与实时刷新都从它走（子类只决定拉哪个接口）。 */
    protected val container: AppContainer,
    /** 路由上带的 `?focus=`（0 = 从工作台那一格进来的，不定位任何一条）。 */
    initialFocusRequestId: Long,
    /** 本角色的档位表（两端的**顺序不同**，见各自页面）。 */
    private val tabs: List<ReturnTab>,
    /** 「全部」那一档的下标：带定位进来时先切到它（理由见类注释第 1 条）。 */
    private val tabAllIndex: Int,
    defaultTabIndex: Int,
) : ViewModel() {

    /** 当前档位（[tabs] 的下标）。 */
    var tab by mutableStateOf(defaultTabIndex)

    var items by mutableStateOf<List<ReturnRequestDto>>(emptyList())

    /** 待处理的张数（后端给的 `pending_count`，**不要自己数**：切到「全部」时列表里不止待处理的）。 */
    var pendingCount by mutableStateOf(0)

    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)

    /** 有一次动作正在提交（按钮据此禁用，避免连点两次）。 */
    var acting by mutableStateOf(false)

    /** 一次性结果提示（Snackbar）：撤回/办理/驳回的结果都走它，文案里带真实数字。 */
    var actionResult by mutableStateOf<String?>(null)

    /** 要定位/高亮的那一张（0 = 没有）。列表里那一行据此打标记。 */
    var focusRequestId by mutableStateOf(initialFocusRequestId)
        private set

    /**
     * 定位**没找到**时给用户的一行说明（不是错误页：列表照常显示全部）。
     * ⛔ 它必须说出来 —— 悄悄按普通列表显示，用户会以为自己点错了消息。
     */
    var focusNotice by mutableStateOf<String?>(null)
        private set

    private var loadJob: Job? = null

    init {
        // ⚠️ 带定位进来时**先用「全部」档拉**：那一条可能已经被办理/驳回/撤回（不在「待处理」里了），
        //    在待处理档里找必然落空 —— 那就变成"明明有这条，却告诉用户没找到"。
        //    （档位跟着切过去也是对的：用户看到的就是「全部」这一档。）
        if (initialFocusRequestId > 0L) tab = tabAllIndex
        load()
        // 另一端动了这条申请之后，后端会推站内信；走到这里就把列表重拉一次 ——
        // 否则用户要手动退出再进来才看得到"已经办完了 / 货主又提了一张"。
        viewModelScope.launch {
            container.realtimeHub.refreshOrders.collect { load() }
        }
    }

    /**
     * 屏幕进来时调一次（`LaunchedEffect(focusRequestId)`）。
     *
     * 正常情况下这个值与构造参数相同 —— 每次导航都会新建这个 ViewModel，于是这里什么都不做
     * （不会多拉一次接口）。只有 ViewModel 被**复用**时才会真的重新定位，
     * 这样"带 focus 进来一定定位"在两个分支上都成立，不靠"VM 一定是新的"这种假设。
     */
    fun applyFocus(requestId: Long) {
        if (requestId == focusRequestId) return
        focusRequestId = requestId
        focusNotice = null
        if (requestId > 0L) tab = tabAllIndex
        load()
    }

    fun selectTab(index: Int) {
        if (tab != index) {
            tab = index
            // 换档就重新拉（两档的过滤在后端，不是本地筛）
            load()
        }
    }

    fun load() {
        loadJob?.cancel()
        loadJob = viewModelScope.launch {
            loading = items.isEmpty()
            error = null
            try {
                val page = fetchPage(tabs[tab].key)
                val focused = focusReturnRequestFirst(page.items, focusRequestId)
                items = focused.items
                pendingCount = page.pendingCount
                focusNotice = if (focusRequestId > 0L && !focused.found) {
                    // 文案的唯一出处：`ui/common/ReturnRequestFocus.kt`（两页共用一句）
                    RETURN_REQUEST_FOCUS_MISS
                } else {
                    null
                }
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    /** 拉一页：两端接口不同（派单员看**待办**、货主看**自己的**）。[statusKey] 就是当前档位的 key。 */
    protected abstract suspend fun fetchPage(statusKey: String): ReturnRequestsPage
}
