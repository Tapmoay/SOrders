package com.tapmoay.sorders.ui.shipper

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.ReturnRequestDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.RETURN_REQUEST_FOCUS_MISS
import com.tapmoay.sorders.ui.common.focusReturnRequestFirst
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

/** 「我的退货申请」的两档：待处理 / 全部（`status=` 直接透给后端）。 */
data class ReturnTab(val key: String, val label: String)

val SHIPPER_RETURN_TABS = listOf(
    ReturnTab("pending", "待处理"),
    ReturnTab("all", "全部"),
)

/**
 * 「全部」那一档的下标。从消息中心带 `?focus=` 进来时**先切到它**：
 * 办完/驳回/自动关闭之后那一条不在「待处理」里（见类注释）。
 */
private const val TAB_ALL = 1

/**
 * 货主端「我的退货申请」（2026-09-21）。
 *
 * ## 这一页回答的是"我提的申请怎么样了"
 * 货主**只能申请**：这一页上没有一个字是"账已经变了"。
 * 三种结果各自要看得见（用户口径："货主提了就等着"）：
 *  · 待派单员处理 → 还能撤回；
 *  · 已驳回 → **必须显示驳回原因**（那是货主唯一能拿到的答复，后端也是必填的）；
 *  · 已办理 → 显示办理人和时间（钱和货是那一刻变的）。
 *
 * ⛔ 中文状态名一律用后端的 `statusLabel`，这一页**不写**状态映射（加了新状态就会显示原始码）。
 *
 * ## 从消息中心**直达某一条**（2026-09-21 用户要求：「其实本来就要做到直达的」）
 * 路由上可以带一个 `?focus=<申请单号>`（`Routes.shipperReturnRequests(id)`）：
 * 进来就把那一条**排到列表最前**并打标记，列表滚到它；拉回来的列表里**没有**它
 * （已被清理/超出这一页的条数/不是这个账户的）时**照常显示列表**，只在上面加一行说明 ——
 * ⛔ 不白屏、也不假装定位到了。
 */
class ShipperReturnRequestsViewModel(
    private val container: AppContainer,
    /** 路由上带的 `?focus=`（0 = 从工作台进来的，不定位任何一条）。 */
    initialFocusRequestId: Long = 0L,
) : ViewModel() {

    /** 当前档位（`SHIPPER_RETURN_TABS` 的下标）。 */
    var tab by mutableStateOf(0)

    var items by mutableStateOf<List<ReturnRequestDto>>(emptyList())

    /** 待处理的张数（后端给的 `pending_count`，不要自己数：切到「全部」时列表里不止待处理的）。 */
    var pendingCount by mutableStateOf(0)

    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var acting by mutableStateOf(false)
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

    /** 撤回二次确认的目标 */
    var withdrawTarget by mutableStateOf<ReturnRequestDto?>(null)

    /**
     * 撤回弹层**自己**的错误（表单级）。
     * 规则见 `Components.kt::FormErrorLine`：表单的错误必须与表单同生共死，
     * 否则"点了没反应"（错误被弹窗遮罩盖住）、关掉弹层又整页被 `ErrorView` 顶掉。
     */
    var withdrawFormError by mutableStateOf<String?>(null)

    private var loadJob: Job? = null

    init {
        // ⚠️ 带定位进来时**先用「全部」档拉**：办完/驳回/自动关闭之后那一条已经不在
        //    「待处理」里了，在待处理档里找必然落空 —— 那就变成"明明有这条，却告诉用户没找到"。
        //    （档位跟着切过去也是对的：用户看到的就是"全部"这一档，不会再被过滤掉。）
        if (initialFocusRequestId > 0L) tab = TAB_ALL
        load()
        // 派单员办理/驳回之后，后端会给这个货主推一条站内信（type = order.return_request.*），
        // 走到这里就把列表重拉一次 —— 否则货主要手动退出再进来才看得到"已经办完了"。
        viewModelScope.launch {
            container.realtimeHub.refreshOrders.collect { load() }
        }
    }

    /**
     * 屏幕进来时调一次（`LaunchedEffect(focusRequestId)`）。
     *
     * 正常情况下这个值与构造参数相同 —— 每次导航都会新建这个 ViewModel，于是这里什么都不做
     * （不会多拉一次接口）。只有 ViewModel 被**复用**时（同一实例被再进入一次）才会真的重新定位，
     * 这样"带 focus 进来一定定位"在两个分支上都成立，不靠"VM 一定是新的"这种假设。
     */
    fun applyFocus(requestId: Long) {
        if (requestId == focusRequestId) return
        focusRequestId = requestId
        focusNotice = null
        if (requestId > 0L) tab = TAB_ALL
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
                val dto = container.repo.myReturnRequests(status = SHIPPER_RETURN_TABS[tab].key)
                val focused = focusReturnRequestFirst(dto.items, focusRequestId)
                items = focused.items
                pendingCount = dto.pendingCount
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

    // ---- 撤回（状态变更，不是删除）----

    fun askWithdraw(req: ReturnRequestDto) {
        withdrawTarget = req
        withdrawFormError = null
    }

    fun cancelWithdraw() {
        withdrawTarget = null
        withdrawFormError = null
    }

    fun confirmWithdraw() {
        val req = withdrawTarget ?: return
        acting = true
        withdrawFormError = null
        viewModelScope.launch {
            try {
                container.repo.withdrawReturnRequest(req.id)
                actionResult = "已撤回退货申请（申请记录留着，派单员看得到你提过又撤了）"
                withdrawTarget = null
                load()
            } catch (e: Exception) {
                // 后端的中文原样显示在这个弹层里（例如"这张退货申请已经被驳回了，不能撤回"）
                withdrawFormError = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }
}
