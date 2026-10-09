package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.*
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.ArrearsUnitCreateRequest
import com.tapmoay.sorders.data.remote.dto.ArrearsUnitDto
import com.tapmoay.sorders.data.remote.dto.ArrearsUnitEditRequest
import com.tapmoay.sorders.data.remote.dto.CustomerBalanceRowDto
import com.tapmoay.sorders.data.remote.dto.arrearsCreditLimitOf
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.util.trimMoneyZeros
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import java.time.LocalDate

/**
 * 刚被删掉的那一条挂账单位（够画「已删除「X」+ 撤销」这一行用）。
 *
 * 本页只有一种东西可删，所以不像地址页那样再记一个 `kind`。
 */
data class RecentlyDeleted(val id: Long, val name: String)

class ArrearsUnitsViewModel(private val container: AppContainer) : ViewModel() {

    var units by mutableStateOf<List<ArrearsUnitDto>>(emptyList())
    var loading by mutableStateOf(false)

    /**
     * 页面级错误：**只有 [load] 写它**（整页换 `ErrorView` + 重试）。
     *
     * ⛔ 表单的校验 / 保存失败绝不许写这里 —— 2026-09-21 那个坑就是这么来的：
     * 「点保存没有任何反应」和「关掉之后整页列表全没了」是同一句话造出来的两个假象
     * （规范 :458-478）。
     */
    var loadError by mutableStateOf<String?>(null)

    /**
     * 每个单位「现在欠着多少」（`unit_id` ⇒ 客户欠款表里的那一行）。
     *
     * 额度（[ArrearsUnitDto.creditLimit]）是"允许欠多少"，而用户真正要看的是"现在欠着多少"——
     * 这一格的数据来自 `GET /reports/customer-balances`（与「客户欠款」报表同一份时点账，
     * 2026-10-09 财务方向测试 TB-01 补的）。⛔ 不许在这儿拿订单/账本自己算余额：那是第二份钱算法。
     */
    var balances by mutableStateOf<Map<Long, CustomerBalanceRowDto>>(emptyMap())

    /**
     * 余额这一路**自己的**错误：只在列表顶上多画一句「余额没取到…+ 重试」。
     *
     * ⛔ 绝不许写 [loadError] —— 那会把整页名册换成错误页。单位还在、额度还在，
     * 只是"欠了多少"这一格没取到，不该让整页消失（与表单错同一条规矩，见 [formError]）。
     */
    var balanceError by mutableStateOf<String?>(null)

    /** 余额那一路是不是正在取（只用来禁用「重试」，不参与整页 loading）。 */
    var balanceLoading by mutableStateOf(false)
    var acting by mutableStateOf(false)
    var actionResult by mutableStateOf<String?>(null)

    /** 表单级错误：跟着抽屉同生共死，画在抽屉里、提交键上方（`FormErrorLine`）。 */
    var formError by mutableStateOf<String?>(null)
    var showSheet by mutableStateOf(false)
    var editing by mutableStateOf<ArrearsUnitDto?>(null)
    var draftName by mutableStateOf("")
    var draftPhone by mutableStateOf("")
    var draftRemark by mutableStateOf("")

    /**
     * 信用额度（选填，FEAT-0015）：**空串 = 不限额**，不是 0。
     *
     * ⛔ 别把它默认成 `"0"`、也别在提交时把空串当 0 —— 这两个动作都会把
     * 「老板没管过这个单位」变成「这个单位一分钱都不许赊」，界面上立刻出现一串假超限。
     * 它跟着表单同生共死（[openCreate] / [openEdit] 都会重设）。
     */
    var draftCreditLimit by mutableStateOf("")

    /**
     * 刚删掉的那一条（非空 = 列表头顶画一行「已删除「X」+ 撤销」）。
     *
     * 只记**一条**是有意的：撤回的意思是「我手滑了」，不是"最近删除"文件夹。
     * 后端是真软删（`is_deleted` + 名字改成 `xxx_del{id}` 把唯一名释放出来），
     * 所以这里给的是真能救回来的「撤销」，不是安慰按钮。
     */
    var recentlyDeleted by mutableStateOf<RecentlyDeleted?>(null)

    init {
        load()
    }

    fun load() {
        loading = units.isEmpty()
        loadError = null
        balanceError = null
        viewModelScope.launch {
            coroutineScope {
                // 名册与余额**并发**跑：名册决定整页画什么（它失败才是整页错误），
                // 余额只是卡上多一行 —— 两条路各自记各自的错，谁都别把对方拖下水。
                val unitsJob = async { container.repo.arrearsUnits() }
                val balanceJob = async { fetchBalances() }
                try {
                    units = unitsJob.await()
                } catch (e: Exception) {
                    loadError = toApiException(e).message
                } finally {
                    loading = false
                }
                // fetchBalances 自己吞掉异常（写 balanceError），这里只是等它跑完。
                balanceJob.await()
            }
        }
    }

    /** 只重取余额那一路（页面已经画着名册，只是那一行没取到）。 */
    fun retryBalances() {
        if (balanceLoading) return
        balanceError = null
        viewModelScope.launch { fetchBalances() }
    }

    /**
     * 取各单位「现在欠着多少」。
     *
     * 客户欠款表是**时点账**（`as_of = min(窗口末, 今天)`，窗口起点不参与余额），
     * 所以要"现在的余额"就传 `mode = "day"` + 今天；`includeOrders = false` 只要余额那一行、
     * 不要逐单明细（这一页不画明细）。
     */
    private suspend fun fetchBalances() {
        balanceLoading = true
        try {
            val dto = container.repo.customerBalancesReport(
                mode = "day",
                date = LocalDate.now().toString(),
                dateFrom = null,
                dateTo = null,
                includeOrders = false,
            )
            // 只认挂着名册单位的那种行（`kind == "unit"`）：`unit_name` 是名字快照、没有额度，
            // 贴到卡上会变成"这个单位欠了钱"的假象（见 Dtos.kt:3053-3056 那段约定）。
            balances = dto.rows
                .filter { it.kind == UNIT_KIND }
                .mapNotNull { r -> r.unitId?.let { id -> id to r } }
                .toMap()
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            balanceError = toApiException(e).message
        } finally {
            balanceLoading = false
        }
    }

    fun openCreate() {
        editing = null
        draftName = ""; draftPhone = ""; draftRemark = ""; draftCreditLimit = ""
        // 打开表单要**清掉上一次的表单错误**：否则会看到"我还没填，红字已经说我填错了"。
        formError = null
        showSheet = true
    }

    fun openEdit(u: ArrearsUnitDto) {
        editing = u
        draftName = u.name
        draftPhone = u.phone
        draftRemark = u.remark
        // null（后端没设过额度）= 空框；⛔ 不许写成 "0.00"（那是另一回事：额度 0）。
        // 预填走 `trimMoneyZeros`（可编辑金额框的预填规则）：`"5000.00"` → `"5000"`，
        // 用户不动它直接保存，后端 Decimal("5000") 与 Decimal("5000.00") 数值相等 ⇒ 不会记一条假变动。
        draftCreditLimit = trimMoneyZeros(u.creditLimit)
        formError = null
        showSheet = true
    }

    /** 关抽屉。保存途中（acting）不关：关掉就看不到结果了。 */
    fun closeSheet() {
        if (acting) return
        showSheet = false
    }

    fun save() {
        if (draftName.isBlank()) {
            formError = "请填写单位名称"
            return
        }
        // 联系电话是可选的，但**填了就得是个能打通的号**（7~12 位数字）。
        // 规则唯一实现在 core/InputRules.kt（输入框那边已经在过滤非数字字符）。
        InputRules.phoneError(draftPhone.trim())?.let {
            formError = it
            return
        }
        // 信用额度是**选填**的：留空合法（= 不限额，后端 `credit_limit: null` 也是合法值），
        // 但填了就必须是个金额。校验规则唯一实现在 core/InputRules.kt，与其它金额框同一条。
        val limitRaw = draftCreditLimit.trim()
        InputRules.moneyError(limitRaw)?.let {
            formError = "信用额度：$it"
            return
        }
        acting = true
        formError = null
        viewModelScope.launch {
            try {
                val cur = editing
                if (cur == null) {
                    // 新增：留空 ⇒ credit_limit 这个键**根本不发**（后端默认 = 不限额）。
                    container.repo.createArrearsUnit(
                        ArrearsUnitCreateRequest(
                            draftName.trim(), draftPhone.trim(), draftRemark.trim(),
                            creditLimit = limitRaw.ifBlank { null },
                        )
                    )
                } else {
                    // 编辑：走 [ArrearsUnitEditRequest]（不是 updateArrearsUnit）——
                    // 「留空 = 不限额」必须真的发出**字面 null**，而 `String? = null` 的键会被序列化丢掉。
                    container.repo.editArrearsUnit(
                        cur.id,
                        ArrearsUnitEditRequest(
                            name = draftName.trim(),
                            phone = draftPhone.trim(),
                            remark = draftRemark.trim(),
                            creditLimit = arrearsCreditLimitOf(limitRaw),
                        ),
                    )
                }
                actionResult = if (cur == null) "挂账单位已新增" else "挂账单位已更新"
                showSheet = false
                load()
            } catch (e: Exception) {
                // 保存失败留在表单里（抽屉不关），用户改完接着按保存。
                formError = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    fun delete(u: ArrearsUnitDto) {
        if (acting) return
        acting = true
        viewModelScope.launch {
            try {
                container.repo.deleteArrearsUnit(u.id)
                // 撤回要的"那一条"就是刚删的这个（名字用删之前的：后端此刻已经把它改成 `xxx_del{id}`）。
                recentlyDeleted = RecentlyDeleted(u.id, u.name)
                actionResult = "已删除「" + u.name + "」"
                load()
            } catch (e: Exception) {
                // 删不掉是**意料之中**的一种结果（它名下还有没收钱的挂账单 / 有客户档案挂着 /
                // 有收款单记在它名下），后端那三句话就是给用户看的原文 ⇒ 走 snackbar 如实报。
                // ⛔ 不许写 loadError：那会把整页列表顶掉，用户会以为"删一下把整个页面搞没了"。
                actionResult = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    /** 撤回上一次删除：真调后端的 restore（不是只把那一行塞回列表）。 */
    fun undoDelete() {
        val rd = recentlyDeleted ?: return
        if (acting) return
        acting = true
        viewModelScope.launch {
            try {
                container.repo.restoreArrearsUnit(rd.id)
                recentlyDeleted = null
                actionResult = "已恢复「" + rd.name + "」"
                load()
            } catch (e: Exception) {
                actionResult = "恢复失败：" + toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    companion object {
        /** 客户欠款表里"挂了名册单位"的那种行。 */
        private const val UNIT_KIND = "unit"
    }
}
