package com.tapmoay.sorders.ui.dispatcher

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
import com.tapmoay.sorders.util.formatMoney
import kotlinx.coroutines.launch

/** 派单端退货申请的两档：全部 / 待处理（`status=` 直接透给后端）。 */
val DISPATCH_RETURN_TABS = listOf(
    ReturnTab("all", "全部"),
    ReturnTab("pending", "待处理"),
)

/**
 * 「全部」那一档的下标。从消息中心带 `?focus=` 进来时**先切到它**：
 * 那张申请可能已经被办理/驳回（不在「待处理」里），在待处理档里找必然落空。
 */
private const val TAB_ALL = 0

/**
 * 派单端「退货申请」待办页（2026-09-21）。
 *
 * ## 这一页是**唯一**会真的退货的地方
 * 用户口径：「批发商只是一个申请，**派单员才是实际性的操作**。派单员进行完了之后，
 * 整个才进行库存才会发生一个改变和变动」。
 * 所以这里两个按钮的分量完全不同：
 *  · **办理退货** → 调 `fulfillReturnRequest`，后端在那一刻才动库存、账本、退款、订单状态；
 *  · **驳回** → 只改申请单的状态（理由**必填**，那是货主唯一能拿到的答复）。
 *
 * ⛔ **数量锁死**：这一页从界面上就没有改数量的地方 —— 办理取的是申请单上那几行
 *    （后端也是从申请单里取，不是从请求体里取）。要改数量只能驳回、让货主重提。
 * ⛔ 中文状态名一律用后端的 `statusLabel`。
 *
 * ## 从消息中心**直达某一条**（2026-09-21 用户要求：「其实本来就要做到直达的」）
 * 派单员收到「退货申请待处理」那条站内信时，点它就直接落在这一页并**定位到那一张**
 * （路由 `?focus=<申请单号>`，payload 里的 `request_id`）：那一条排到最前、打上标记、
 * 列表滚到它。拉回来的列表里没有它时**照常显示列表**，只在上面加一行说明 ——
 * ⛔ 不白屏、也不假装定位到了。
 *
 * ⚠️ 列表内核（档位 / 加载 / 定位 / 实时刷新）在 [ReturnRequestsViewModel]（2026-09-21 收口）：
 *    它和货主那一页原来是**逐字抄的两遍**（约 90 行），而那四条是**规则**不是样式。
 *    这一页只剩下"档位顺序 + 拉哪个接口 + 能做什么动作"。
 */
class DispatcherReturnRequestsViewModel(
    container: AppContainer,
    initialFocusRequestId: Long = 0L,
) : ReturnRequestsViewModel(
    container = container,
    initialFocusRequestId = initialFocusRequestId,
    tabs = DISPATCH_RETURN_TABS,
    tabAllIndex = TAB_ALL,
    // 默认就是「待处理」—— 这一页本来就是待办页
    defaultTabIndex = 1,
) {

    /** 办理退货：二次确认的目标 */
    var fulfillTarget by mutableStateOf<ReturnRequestDto?>(null)

    /**
     * 两个弹层**各自**的错误（表单级）。
     * 规则见 `Components.kt::FormErrorLine`：表单的错误必须与表单同生共死 ——
     * 画在页面上会被弹窗遮罩盖住，表现就是"点了没反应"；关掉弹层又整页被 `ErrorView` 顶掉。
     * 需要它是有真实场景的：两个派单员同时点「办理」，后一个会被后端拒
     * （"这张退货申请已经办完了"），那句话必须出现在他自己那个弹层里。
     */
    var fulfillFormError by mutableStateOf<String?>(null)
    var rejectFormError by mutableStateOf<String?>(null)

    /** 驳回：目标 + 理由（必填） */
    var rejectTarget by mutableStateOf<ReturnRequestDto?>(null)
    var rejectReason by mutableStateOf("")

    /** 派单员看待办（`status=` 就是当前档位的 key）。 */
    override suspend fun fetchPage(statusKey: String): ReturnRequestsPage {
        val dto = container.repo.returnRequestTodo(status = statusKey)
        return ReturnRequestsPage(dto.items, dto.pendingCount)
    }

    // ---- 办理退货（★ 真的退货：库存/账本/退现/订单状态都在这一刻变）----

    fun askFulfill(req: ReturnRequestDto) {
        fulfillTarget = req
        fulfillFormError = null
    }

    fun cancelFulfill() {
        fulfillTarget = null
        fulfillFormError = null
    }

    fun confirmFulfill() {
        val req = fulfillTarget ?: return
        acting = true
        fulfillFormError = null
        viewModelScope.launch {
            try {
                val r = container.repo.fulfillReturnRequest(req.id)
                // 回执必须**如实**：退了多少钱、是整单还是部分退（部分退的话订单还是「已送达」）、
                // 后端给的告警一条不落 —— 这几句话是派单员对外答复货主的依据。
                actionResult = buildString {
                    append("已退货 ¥").append(formatMoney(r.returned.returnedAmount))
                    val refund = r.returned.refundAmount.toDoubleOrNull() ?: 0.0
                    if (refund > 0.0) append("，并退给客户 ¥").append(formatMoney(r.returned.refundAmount))
                    append(
                        if (r.returned.fullyReturned) {
                            "；整单退完，订单已变为「已退货」"
                        } else {
                            "；这是部分退货，订单仍是已送达"
                        },
                    )
                    r.returned.warnings.forEach { append("；").append(it) }
                }
                fulfillTarget = null
                load()
            } catch (e: Exception) {
                // 后端的中文原样显示在这个弹层里（"这张退货申请已经办完了，不能办理"等）
                fulfillFormError = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    // ---- 驳回（理由必填）----

    fun askReject(req: ReturnRequestDto) {
        rejectTarget = req
        rejectReason = ""
        rejectFormError = null
    }

    fun cancelReject() {
        rejectTarget = null
        rejectReason = ""
        rejectFormError = null
    }

    /** 理由空着就不许提交（后端也要求必填，界面这一道是为了给出一句能照着改的话）。 */
    val canReject: Boolean get() = rejectReason.isNotBlank() && !acting

    fun confirmReject() {
        val req = rejectTarget ?: return
        if (rejectReason.isBlank()) {
            rejectFormError = "请填写驳回理由 —— 这是货主唯一能拿到的答复"
            return
        }
        acting = true
        rejectFormError = null
        viewModelScope.launch {
            try {
                container.repo.rejectReturnRequest(req.id, rejectReason.trim())
                actionResult = "已驳回这张退货申请（货主会收到你写的理由）"
                rejectTarget = null
                rejectReason = ""
                load()
            } catch (e: Exception) {
                rejectFormError = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }
}
