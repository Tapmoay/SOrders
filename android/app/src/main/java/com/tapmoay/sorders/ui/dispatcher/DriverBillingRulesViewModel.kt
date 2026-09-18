package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.DriverBillingRuleDto
import com.tapmoay.sorders.data.remote.dto.DriverBillingRuleRequest
import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.launch
import java.math.BigDecimal

/**
 * 司机计费规则模板（派单员）。
 *
 * ### 三条约定
 * 1. **后端的中文原因原样显示**。400（"这份规则一分钱都不给"）、409（重名）、
 *    "还有 N 个司机挂着这份规则" 都是后端写好的、用户能照着改的话——
 *    `toApiException(e).message` 抠的就是它（`core/ApiClient.kt:117-132`），这里只负责摆到眼前。
 *    所以编辑失败时**弹窗不关**、删除被拦时**确认框不关**：把话显示在用户正在操作的那个框里，
 *    而不是飘一条 Snackbar 让他自己回想刚才填了什么。
 * 2. **前端的轻校验只是"早一步"**：措辞与后端 `schemas/driver_billing_rule.py` 里的校验**逐字一致**，
 *    这样"早看到"和"晚看到"是同一句话，不会出现两套说法。它拦不住的（比如重名）仍由后端拦。
 * 3. **空金额 = 0，不是"不改"**。后端对 `null` 的解释是"这一项不改"
 *    （`patch.get("salary") is not None`），而界面上的空框意思是"这一项是 0"——
 *    两者不是一回事，所以提交前把空框归成 "0"（见 `DriverBillingRuleRequest` 的注释）。
 */
class DriverBillingRulesViewModel(private val container: AppContainer) : ViewModel() {

    var rules by mutableStateOf<List<DriverBillingRuleDto>>(emptyList())

    /** true = 正在看回收站（软删的那些）。 */
    var recycleBin by mutableStateOf(false)

    var loading by mutableStateOf(false)
    var acting by mutableStateOf(false)

    /** 最近一次加载是否失败（空列表时给「重试」按钮用；错误正文走 Snackbar）。 */
    var loadFailed by mutableStateOf(false)

    /** 一次性提示（Snackbar 消费）：成功/信息/失败都走它 —— 与运费模板页同一套做法。 */
    var actionResult by mutableStateOf<String?>(null)
    var error by mutableStateOf<String?>(null)

    // ---- 新建 / 编辑弹窗 ----
    var showDialog by mutableStateOf(false)
    var editing by mutableStateOf<DriverBillingRuleDto?>(null)

    /** 弹窗内的错误（后端 400/409 原文）：**弹窗不关**，用户能对着这句话改。 */
    var dialogError by mutableStateOf<String?>(null)

    var draftName by mutableStateOf("")
    /** "" = 通用；small/large/trailer。 */
    var draftVehicle by mutableStateOf("")
    var draftSalary by mutableStateOf("")
    var draftPieceAmount by mutableStateOf("")
    var draftPieceUnit by mutableStateOf("order")
    var draftCommissionBase by mutableStateOf("none")
    var draftCommissionRate by mutableStateOf("")
    /**
     * 只对哪些商品抽成（空 = 不限商品）。用户 2026-09-18：「哪些商品是要抽成的」。
     *
     * 只有"按商品金额抽成"才有这回事——按整单运费抽成时，范围这个框连显示都不显示
     * （后端 `validate_rule_params` 也会拒："按运费抽成时没有商品范围这回事"）。
     */
    var draftScopeIds by mutableStateOf<Set<Long>>(emptySet())
    var draftRemark by mutableStateOf("")

    /** 抽成商品可选项（商品库全量）。拉不到就只显示"不限"，不让用户以为商品库里没货。 */
    var products by mutableStateOf<List<ProductDto>>(emptyList())

    // ---- 删除确认 ----
    var deleteTarget by mutableStateOf<DriverBillingRuleDto?>(null)

    /** 删除被拦的原因（"还有 N 个司机挂着这份规则…"）：显示在确认框里，**框不关**。 */
    var deleteError by mutableStateOf<String?>(null)

    init {
        load()
    }

    /**
     * 拉抽成商品的可选项。失败**不弹错**：商品库拉不到时那份规则照样能存
     * （范围留空 = 不限商品），为它挡一屏错误不值得——但会退化成"只有不限"这一档，
     * 所以文案上写清楚"没拉到商品库时只能不限"。
     */
    fun loadProducts() {
        if (products.isNotEmpty()) return
        viewModelScope.launch {
            try {
                products = container.repo.products()
            } catch (_: Exception) {
                products = emptyList()
            }
        }
    }

    fun load() {
        val bin = recycleBin
        viewModelScope.launch {
            loading = true
            try {
                val list = container.repo.driverBillingRules(deletedOnly = bin)
                // ⚠️ 请求是异步的，回来时用户可能已经切了页签——那样会把"在用"的结果
                //    填进回收站的列表里（看着像"删了的又回来了"）。所以按页签核对一次。
                if (bin == recycleBin) {
                    rules = list
                    loadFailed = false
                }
            } catch (e: Exception) {
                if (bin == recycleBin) {
                    loadFailed = true
                    error = toApiException(e).message
                }
            } finally {
                if (bin == recycleBin) loading = false
            }
        }
    }

    /** 切换「在用 / 回收站」。清空旧列表再拉，免得旧数据停留在屏幕上被当成新页签的内容。 */
    fun switchRecycleBin(bin: Boolean) {
        if (bin == recycleBin) return
        recycleBin = bin
        rules = emptyList()
        loadFailed = false
        load()
    }

    // ------------------------------------------------------------------ 新建 / 编辑

    fun openCreate() {
        editing = null
        draftName = ""
        draftVehicle = ""
        draftSalary = ""
        draftPieceAmount = ""
        draftPieceUnit = "order"
        draftCommissionBase = "none"
        draftCommissionRate = ""
        draftScopeIds = emptySet()
        draftRemark = ""
        dialogError = null
        loadProducts()
        showDialog = true
    }

    fun openEdit(r: DriverBillingRuleDto) {
        editing = r
        draftName = r.name
        draftVehicle = r.vehicleType.orEmpty()
        draftSalary = trimZero(r.salary)
        draftPieceAmount = trimZero(r.pieceAmount)
        draftPieceUnit = r.pieceUnit.ifBlank { "order" }
        draftCommissionBase = r.commissionBase.ifBlank { "none" }
        draftCommissionRate = trimZero(r.commissionRate)
        draftScopeIds = r.commissionProductIds.toSet()
        draftRemark = r.remark
        dialogError = null
        loadProducts()
        showDialog = true
    }

    fun save() {
        if (acting) return
        validateDraft()?.let {
            dialogError = it
            return
        }
        val body = DriverBillingRuleRequest(
            name = draftName.trim(),
            vehicleType = draftVehicle,
            salary = amountText(draftSalary),
            pieceAmount = amountText(draftPieceAmount),
            pieceUnit = draftPieceUnit,
            commissionBase = draftCommissionBase,
            commissionRate = amountText(draftCommissionRate),
            // 不是"按商品金额抽成"时**显式清空范围**：留着一份上次选的范围会让人以为它生效了，
            // 而后端对"按运费 + 有范围"是直接拒绝的。
            commissionProductIds = if (draftCommissionBase == "goods") draftScopeIds.sorted() else emptyList(),
            remark = draftRemark.trim(),
        )
        val cur = editing
        acting = true
        dialogError = null
        viewModelScope.launch {
            try {
                if (cur == null) container.repo.createDriverBillingRule(body)
                else container.repo.updateDriverBillingRule(cur.id, body)
                actionResult = if (cur == null) "已创建「${body.name}」" else "已保存「${body.name}」"
                showDialog = false
                load()
            } catch (e: Exception) {
                // 400/409 的中文原因留在弹窗里：用户正对着那几格输入框，改完再点保存就行。
                dialogError = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    // ------------------------------------------------------------------ 删除 / 恢复

    fun requestDelete(r: DriverBillingRuleDto) {
        deleteTarget = r
        deleteError = null
    }

    fun confirmDelete() {
        val r = deleteTarget ?: return
        if (acting) return
        acting = true
        deleteError = null
        viewModelScope.launch {
            try {
                container.repo.deleteDriverBillingRule(r.id)
                deleteTarget = null
                actionResult = "已删除「${r.name}」（回收站里能找回来）"
                load()
            } catch (e: Exception) {
                // 后端会回「还有 N 个司机挂着这份规则，先给他们换掉或解挂再删」——
                // 原样显示，别改写成"删除失败"：那句话就是用户下一步该做的事。
                deleteError = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    fun restore(r: DriverBillingRuleDto) {
        if (acting) return
        acting = true
        viewModelScope.launch {
            try {
                container.repo.restoreDriverBillingRule(r.id)
                actionResult = "已恢复「${r.name}」"
                load()
            } catch (e: Exception) {
                // 409（回收站外面已经有一份同名的）也要原样说清楚。
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    // ------------------------------------------------------------------ 轻校验

    /**
     * 措辞与后端 `schemas/driver_billing_rule.py::validate_rule_params` **逐字一致**——
     * 早一步和晚一步看到的是同一句话，用户不会以为是两条规则。
     *
     * @return null = 通过；非 null = 要显示在弹窗里的中文原因。
     */
    fun validateDraft(): String? {
        if (draftName.isBlank()) return "规则名称不能为空（AI 和界面都按名字找它）"
        val salary = amountOf(draftSalary) ?: return "固定工资只能填数字（不带单位，比如 8000）"
        val piece = amountOf(draftPieceAmount) ?: return "每单金额只能填数字（不带单位，比如 200）"
        val rate = amountOf(draftCommissionRate) ?: return "提成比例只能填数字（比如 5 表示 5%）"
        if (salary.signum() < 0 || piece.signum() < 0 || rate.signum() < 0) return "金额和比例不能是负数"
        if (rate > BigDecimal("100")) return "提成比例不能超过 100%"
        if (rate.signum() > 0 && draftCommissionBase == "none") {
            return "填了提成比例，就要选提成基数（按运费还是按商品金额）——否则这份规则一分钱都算不出来"
        }
        if (draftCommissionBase != "none" && rate.signum() <= 0) {
            return "选了提成基数，就要填提成比例（百分比）"
        }
        if (salary.signum() <= 0 && piece.signum() <= 0 && rate.signum() <= 0) {
            return "这份规则一分钱都不给（固定工资/每单金额/提成 至少要填一个）"
        }
        return null
    }

    companion object {
        /**
         * 金额文本 → BigDecimal。空 = 0（界面的空框意思是 0，不是"不改"）。
         * 认不出数字返回 null（调用方给中文提示）。
         *
         * 用 BigDecimal 而不是 Double：金额比较（>100、<=0）在 Double 下会被二进制小数咬到，
         * 而这里判错了会拦住一份合法的规则。
         */
        fun amountOf(raw: String): BigDecimal? {
            val s = raw.trim().replace(",", "").replace("，", "")
            if (s.isEmpty()) return BigDecimal.ZERO
            return try {
                BigDecimal(s)
            } catch (_: NumberFormatException) {
                null
            }
        }

        /** 提交用的金额文本：空 → "0"（转发后端前归一，见类注释第 3 条）。 */
        fun amountText(raw: String): String {
            val s = raw.trim().replace(",", "").replace("，", "")
            return s.ifEmpty { "0" }
        }

        /** 后端给的是 "8000.00" 这种两位小数；回填输入框时去掉多余的 0，省得用户去删。 */
        fun trimZero(raw: String): String {
            val v = raw.trim()
            if (v.isEmpty()) return ""
            val bd = amountOf(v) ?: return v
            if (bd.signum() == 0) return ""
            return bd.stripTrailingZeros().toPlainString()
        }
    }
}
