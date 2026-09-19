package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.*
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.api.PriceRuleDto
import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.data.remote.dto.UserDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.util.formatMoney
import com.tapmoay.sorders.util.trimMoneyZeros
import kotlinx.coroutines.launch

/** 价格矩阵的两个**方向**（同一份数据，两种看法）。 */
enum class PriceAxis {
    /** 按批发商：这个批发商，每个商品多少钱。（入口：批发商管理 → 定价） */
    BY_SHIPPER,

    /** 按商品：这个商品，每个批发商多少钱。（入口：商品管理 → 卡片 ⋮ → 各批发商价格） */
    BY_PRODUCT,
}

/**
 * 矩阵里的一行 = 一个"对手方"。
 *
 * 按批发商看时对手方是**商品**，按商品看时对手方是**批发商** ——
 * 两个方向的**操作完全一样**（填一个价 → 保存 / 清除特价），所以共用同一个页面与状态，
 * 只是"行里显示谁"不同。这也是用户要的"操作与逻辑匹配"：
 * 逻辑是"按（批发商 × 商品）存一个价"，那么两个方向都该能直接设这个价。
 */
data class PriceTarget(
    val id: Long,
    val name: String,
    val sub: String,
    /** 商品有自定义名字颜色；批发商没有（null = 用默认色）。 */
    val nameColor: String?,
    /** 没设专属价时实际生效的价（按商品看时所有行都一样 = 这个商品的默认售价）。 */
    val defaultPrice: String,
)

/**
 * 「价格矩阵」页的状态：**一个商品 × 一个批发商 = 一个价**。
 *
 * ## 为什么两个方向共用一个 ViewModel（2026-09-19）
 * 用户原话：「同一个商品，这个批发商的价格和那个批发商的价格是不一样的，
 * 关于这个部分的逻辑做一下调整，包括一些操作也做一下调整，保证操作与逻辑匹配，
 * 并且是那种不是很复杂的操作」。
 *
 * 逻辑本来就是按（批发商 × 商品）存的，但**原来只有一个方向**：要设"这个商品给 A、B、C
 * 各多少钱"，只能进 A 的页面填一次、再进 B、再进 C（批量调价只能给同一口价或按百分比）。
 * 现在两个方向都在：`BY_SHIPPER`（老的入口）与 `BY_PRODUCT`（新入口），
 * 操作一模一样 —— 这才是"操作与逻辑匹配"。
 */
class PriceMatrixViewModel(
    private val container: AppContainer,
    private val axis: PriceAxis,
    private val focusId: Long,
) : ViewModel() {

    var targets by mutableStateOf<List<PriceTarget>>(emptyList())
    /** 对手方 id → 该组合的已存专属价（按批发商看时 key = productId；按商品看时 key = shipperId）。 */
    var rules by mutableStateOf<Map<Long, PriceRuleDto>>(emptyMap())
    var loading by mutableStateOf(true)
    /** **动作**失败：提示条弹一次就该消失。 */
    var error by mutableStateOf<String?>(null)
    /**
     * **加载**失败：要一直留在页面上（配合重试按钮），所以**不能**被提示条消费掉。
     *
     * 为什么要拆成两个字段（2026-09-18）：原来共用一个 `error`，
     * 而提示条是"消费即清"的语义 —— 拆开之前，加载失败会先弹一次提示条、把 error 清掉，
     * **整页的「加载失败 + 重试」当场消失**，用户掉进一个空列表且无法重试。
     */
    var loadError by mutableStateOf<String?>(null)
    var acting by mutableStateOf(false)
    var actionResult by mutableStateOf<String?>(null)

    /** 对手方 id → 用户当前输入 */
    val drafts = mutableStateMapOf<Long, String>()

    /** 页面标题（按批发商时带名字）。 */
    var title by mutableStateOf(if (axis == PriceAxis.BY_PRODUCT) "各批发商价格" else "批发商定价")

    /** 标题下面那句说明（按商品看时必须说清"没设特价的按什么价下单"）。 */
    var subtitle by mutableStateOf("")

    /**
     * 按商品看时，**被过滤掉的停用/已删批发商有几个**。
     *
     * ⚠️ 不能默默滤掉：账号软删之后 `users.phone` 会变成 `xxx_del{id}`、`is_active=false`，
     * 而名册接口**不按启用状态过滤**（本机就有上百个 `_del` 账号）。给他们设价是白设
     * （人已经登不进来、也下不了单），所以列表里不显示，但要**如实说有几个被隐藏**。
     */
    var hiddenInactive by mutableStateOf(0)

    /** 批发商名册是否被服务端截断（`X-Truncated`）—— 截断时界面必须说出来。 */
    var truncated by mutableStateOf(false)
    var pageLimit by mutableStateOf<Int?>(null)

    /** 批发商列表（只有"按批发商"模式的批量调价要用）。 */
    var members by mutableStateOf<List<UserDto>>(emptyList())
    var showBatch by mutableStateOf(false)

    init {
        load()
    }

    fun load() {
        loading = targets.isEmpty()
        loadError = null
        viewModelScope.launch {
            try {
                when (axis) {
                    PriceAxis.BY_SHIPPER -> loadByShipper()
                    PriceAxis.BY_PRODUCT -> loadByProduct()
                }
            } catch (e: Exception) {
                loadError = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    /** 按批发商：行 = 商品。 */
    private suspend fun loadByShipper() {
        // 商品取**含下架**：给下架商品预设一个价是合理的（重新上架就生效），
        // 而且下架商品在别处（选品页）看不到，不在这里给个出口就没地方设了。
        val ps = container.repo.products(includeInactive = true)
        // 只取**这个批发商**的规则（服务端筛，不是拉全表再 filter）
        val rs = container.repo.priceRules(shipperId = focusId).associateBy { it.productId }
        targets = ps.map { p ->
            PriceTarget(
                id = p.id,
                name = p.name,
                sub = "默认 ¥" + formatMoney(p.defaultUnitPrice) + "/" + p.unit.ifBlank { "件" } +
                    " · 库存 " + p.stock + " " + p.unit.ifBlank { "件" },
                nameColor = p.nameColor,
                defaultPrice = p.defaultUnitPrice,
            )
        }
        rules = rs
        // 名字：路由上只带了 id，名字从名册里找（找不到就留空，标题会退回"批发商"）
        val m = runCatching { container.repo.members() }.getOrNull()
            ?.firstOrNull { it.id == focusId }
        val label = m?.fullName?.takeIf { it.isNotBlank() } ?: m?.phone ?: m?.username ?: ""
        title = "批发商定价 · " + label.ifBlank { "批发商" }
        // ⚠️ 界面文案里不许写 Markdown（`_check_ai_guardrails.py` 扫 ui/**）：
        //    星号会**字面**显示给用户。这一轮已经在别处栽过一次，这里用「」强调。
        subtitle = "每一行是这个批发商买「这个商品」时实际付的单价：填了就按填的走，" +
            "留空按商品的默认售价。"
    }

    /** 按商品：行 = 批发商（只看启用中的）。 */
    private suspend fun loadByProduct() {
        val p: ProductDto = container.repo.product(focusId)
        val page = container.repo.usersPage(role = "shipper", memberOnly = true)
        val active = page.rows.filter { it.isActive }
        hiddenInactive = page.rows.size - active.size
        truncated = page.meta.hasMore
        pageLimit = page.meta.limit
        val rs = container.repo.priceRules(productId = focusId).associateBy { it.shipperId }
        targets = active.map { u ->
            PriceTarget(
                id = u.id,
                name = u.fullName?.takeIf { it.isNotBlank() } ?: u.phone ?: u.username,
                sub = u.phone,
                nameColor = null,
                defaultPrice = p.defaultUnitPrice,
            )
        }
        rules = rs
        title = "各批发商价格"
        subtitle = "「" + p.name + "」默认售价 ¥" + formatMoney(p.defaultUnitPrice) +
            "/" + p.unit.ifBlank { "件" } + "；下面每一行是「这个批发商」买它时付的价，留空按默认价。"
    }

    /**
     * 输入框里显示什么：草稿 > 已存专属价 > 空（空 = 用默认价）。
     *
     * ⚠️ 已存价要过一遍 [trimMoneyZeros]：库里是 `Numeric(14,4)`，直接显示会是 `12.5000`。
     * **不能**用 `formatMoney`（它只留两位小数，会把 12.3456 显示成 12.35 —— 在一个可编辑的
     * 价框里等于骗人：用户不改直接保存，价就真的变了）。
     */
    fun fieldValue(t: PriceTarget): String =
        drafts[t.id] ?: trimMoneyZeros(rules[t.id]?.specialUnitPrice)

    /** 这一行**当前实际生效**的价（页面上大字显示的那个）。 */
    fun effectivePrice(t: PriceTarget): String =
        drafts[t.id]?.takeIf { it.isNotBlank() } ?: rules[t.id]?.specialUnitPrice ?: t.defaultPrice

    fun savePrice(t: PriceTarget) {
        val raw = drafts[t.id]?.trim().orEmpty()
        if (raw.isBlank()) {
            error = "请输入价格"
            return
        }
        val v = raw.toDoubleOrNull()
        if (v == null || v < 0) {
            error = "请输入正确的价格"
            return
        }
        acting = true
        error = null
        viewModelScope.launch {
            try {
                val existing = rules[t.id]
                if (existing != null) {
                    container.repo.updatePriceRule(existing.id, raw)
                } else {
                    // 按批发商看时 focusId = 批发商、t.id = 商品；按商品看时反过来。
                    val shipperId = if (axis == PriceAxis.BY_SHIPPER) focusId else t.id
                    val productId = if (axis == PriceAxis.BY_SHIPPER) t.id else focusId
                    container.repo.createPriceRule(shipperId, productId, raw)
                }
                // ⚠️ 存完**清掉这一行的草稿**：`fieldValue` 是 `drafts[id] ?: rules[id]`
                //    —— 草稿永远第一优先。留着它，之后别人（批量调价 / 另一台设备）改了价
                //    再 `load()`，界面显示的还是你上次敲的数，而库里已经是另一个数。
                drafts.remove(t.id)
                actionResult = t.name + " 的价已保存"
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    fun clearPrice(t: PriceTarget) {
        val existing = rules[t.id] ?: return
        acting = true
        error = null
        viewModelScope.launch {
            try {
                container.repo.deletePriceRule(existing.id)
                drafts.remove(t.id)
                actionResult = t.name + " 已恢复默认价"
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    fun loadMembers() {
        viewModelScope.launch {
            try {
                members = container.repo.members()
            } catch (_: Exception) {
            }
        }
    }

    /** 批量调价：多个批发商 × 多个商品，一次写入（只有"按批发商"模式有这个入口）。 */
    fun batchPrice(
        shipperIds: List<Long>,
        productIds: List<Long>,
        mode: String,
        value: String?,
        onDone: (Int) -> Unit,
    ) {
        acting = true
        error = null
        viewModelScope.launch {
            try {
                val res = container.repo.batchPriceRules(shipperIds, productIds, mode, value)
                // 批量调价可能改到**这一页任意一行**，所以草稿要全部清掉
                // （不清的话，界面上那些你敲过但没保存的数字会盖住刚写进去的新价）。
                drafts.clear()
                actionResult = "批量调价成功（" + res.count + " 条）"
                onDone(res.count)
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }
}
