package com.tapmoay.sorders.ui.shipper

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.ReturnRequestDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.ReturnRequestsPage
import com.tapmoay.sorders.ui.common.ReturnRequestsViewModel
import com.tapmoay.sorders.ui.common.ReturnTab
import kotlinx.coroutines.launch

/** 「我的退货申请」的两档：待处理 / 全部（`status=` 直接透给后端）。 */
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
 *
 * ⚠️ 列表内核（档位 / 加载 / 定位 / 实时刷新）在 [ReturnRequestsViewModel]（2026-09-21 收口）：
 *    它和派单员那一页原来是**逐字抄的两遍**（约 90 行），而那四条是**规则**不是样式。
 *    这一页只剩下"档位顺序 + 拉哪个接口 + 能做什么动作"。
 */
class ShipperReturnRequestsViewModel(
    container: AppContainer,
    /** 路由上带的 `?focus=`（0 = 从工作台进来的，不定位任何一条）。 */
    initialFocusRequestId: Long = 0L,
) : ReturnRequestsViewModel(
    container = container,
    initialFocusRequestId = initialFocusRequestId,
    tabs = SHIPPER_RETURN_TABS,
    tabAllIndex = TAB_ALL,
    // 默认「待处理」：货主最关心的是"还没办的"
    defaultTabIndex = 0,
) {

    /** 撤回二次确认的目标 */
    var withdrawTarget by mutableStateOf<ReturnRequestDto?>(null)

    /**
     * 撤回弹层**自己**的错误（表单级）。
     * 规则见 `Components.kt::FormErrorLine`：表单的错误必须与表单同生共死，
     * 否则"点了没反应"（错误被弹窗遮罩盖住）、关掉弹层又整页被 `ErrorView` 顶掉。
     */
    var withdrawFormError by mutableStateOf<String?>(null)

    /** 货主看自己的申请（`status=` 就是当前档位的 key）。 */
    override suspend fun fetchPage(statusKey: String): ReturnRequestsPage {
        val dto = container.repo.myReturnRequests(status = statusKey)
        return ReturnRequestsPage(dto.items, dto.pendingCount)
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
