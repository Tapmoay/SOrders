package com.tapmoay.sorders.ui.shipper

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.api.ShipperPriceDto
import com.tapmoay.sorders.data.remote.api.ShipperPriceProductDto
import com.tapmoay.sorders.data.remote.api.ShipperPriceSetRequest
import com.tapmoay.sorders.data.remote.dto.ContactDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.util.formatMoney
import com.tapmoay.sorders.util.moneyToDouble
import com.tapmoay.sorders.util.trimMoneyZeros
import kotlinx.coroutines.launch

/** 草稿表里「给全部下游的默认价」那一格的键（联系人编号从 1 开始，0 不会撞上）。 */
const val SHIPPER_PRICE_DEFAULT_KEY: Long = 0L

/**
 * 货主端「下游定价」（台账 L-38 / CHG-0077）—— 批发商货主**给下游货主定价**。
 *
 * ## 一段话看懂这一页
 * 批发商（高级货主）从派单员那里拿货是一个价（`supply_unit_price`，**只作参考**），
 * 他卖给下游货主是另一个价（本页写的 `unit_price`）—— **两个价的差额归他自己**，
 * 公司那本账一个字节都不动（后端 `shipper_prices` 是独立表，不写 orders.paid / cash_flows / ledgers）。
 *
 * ## 三条铁律（都是从后端契约里抄来的，不是本页自己定的）
 * 1. **写的人永远是登录人自己**：请求体里**没有** `shipper_id`（后端从 token 取货主），
 *    所以本页也没有"替谁定价"这种入口 —— 名字/电话只用来认人，不参与写入。
 * 2. **改价、删价都不追改历史订单**：老单按下单那一刻的快照算（`order_products.shipper_unit_price`）。
 *    所以删除只影响"以后下的单"，页面上那句话必须原样说给用户听。
 * 3. **删是软删**：删掉的行进回收站（`include_deleted=true` 才看得到），
 *    恢复只让这条价重新生效，**不放回任何已经算过的钱**。
 *
 * ## 两道闸门（不是本页自己编的，是后端 `_require_member` / `_require_downstream` 的原话）
 * 身份 `is_member`（是不是批发商）＋ 他自己的开关 `downstream_ledger_enabled`
 * （「我的 → 管下游的账」）。⛔ 两个标记来自 **同一次 `users/me`**（`UserDto` 里都有），
 * 不再多打一个请求；不满足就**只显示后端那两句中文说明、一条列表都不拉**。
 *
 * ## 价格只写不算
 * 这一页**没有任何一分钱是客户端算的**：`unit_price` 原样填、原样提交，
 * 算法（行金额、差额、快照）全在后端 `order_money` 那一处。
 */
class ShipperPricesViewModel(private val container: AppContainer) : ViewModel() {

    // ===== 身份：两个标记来自同一次 users/me =====
    var isMember by mutableStateOf(false)
        private set
    var downstreamEnabled by mutableStateOf(true)
        private set

    /** 界面那道闸门：**身份 + 他自己的开关**，两个都要（后端两道 403 就是这两条）。 */
    val canManageDownstream: Boolean get() = isMember && downstreamEnabled

    // ===== 这一页要看的价 =====
    var loaded by mutableStateOf(false)
        private set
    var loading by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
    var actionResult by mutableStateOf<String?>(null)

    /** 我能定价的商品（后端只给"我下过单的 ∪ 派单员给我设过专属价的"，且不在回收站）。 */
    var products by mutableStateOf<List<ShipperPriceProductDto>>(emptyList())
        private set

    /** 我的联系人（下游客户）。取不到就空着 —— 默认价照样能设，不该整页失败。 */
    var contacts by mutableStateOf<List<ContactDto>>(emptyList())
        private set

    /** 当前展开着的那件商品（null = 全都收起）。 */
    var openProductId by mutableStateOf<Long?>(null)
        private set
    var prices by mutableStateOf<List<ShipperPriceDto>>(emptyList())
        private set
    var pricesLoading by mutableStateOf(false)
        private set
    var includeDeleted by mutableStateOf(false)
        private set

    /**
     * 编辑框里的字（键 = [SHIPPER_PRICE_DEFAULT_KEY] 或联系人编号）。
     *
     * ⛔ 草稿必须留在 VM 里：留在 `remember` 里的话，切一下商品、转个屏，
     *    用户刚打的价就没了，而他以为已经保存了。
     */
    private val drafts = mutableStateMapOf<Long, String>()

    var submitting by mutableStateOf(false)
        private set

    /** 表单错误（保存/删除的失败原因）—— 与表单同生共死，清在每次新动作的开头。 */
    var formError by mutableStateOf<String?>(null)
        private set
    var deleteTarget by mutableStateOf<ShipperPriceDto?>(null)
        private set
    var acting by mutableStateOf(false)
        private set

    init {
        load()
    }

    fun load() {
        if (loading) return
        loading = true
        error = null
        viewModelScope.launch {
            try {
                val me = container.repo.me()
                isMember = me.isMember
                downstreamEnabled = me.downstreamLedgerEnabled
                if (canManageDownstream) {
                    products = container.repo.priceableProducts()
                    // 联系人失败不整页失败：没有联系人时"默认价"那一格仍然要能用。
                    contacts = runCatching { container.repo.contacts() }.getOrElse { emptyList() }
                }
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
                loaded = true
            }
        }
    }

    /** 展开/收起一件商品。收起时把草稿清掉 —— 留着会让下次展开时冒出上一次打了一半的字。 */
    fun toggleProduct(productId: Long) {
        if (openProductId == productId) {
            openProductId = null
            prices = emptyList()
            drafts.clear()
            formError = null
            return
        }
        openProductId = productId
        drafts.clear()
        formError = null
        loadPrices()
    }

    // ⛔ 名字不能叫 setIncludeDeleted：属性 includeDeleted 的 setter 占着那个 JVM 签名（编译期直接红）。
    fun toggleIncludeDeleted(value: Boolean) {
        if (includeDeleted == value) return
        includeDeleted = value
        loadPrices()
    }

    private fun loadPrices() {
        val pid = openProductId ?: return
        pricesLoading = true
        viewModelScope.launch {
            try {
                prices = container.repo.shipperPrices(productId = pid, includeDeleted = includeDeleted)
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                pricesLoading = false
            }
        }
    }

    /** 某件商品、某个人（null = 默认价）现在生效的那一行；没设过就是 null。 */
    fun priceOf(productId: Long, contactId: Long?): ShipperPriceDto? =
        prices.firstOrNull { it.productId == productId && it.contactId == contactId }

    fun draftFor(key: Long): String = drafts[key].orEmpty()

    fun setDraft(key: Long, value: String) {
        drafts[key] = value
        if (formError != null) formError = null
    }

    /**
     * 保存一条价（`contactId = null` 就是该商品的默认下游价）。
     *
     * 客户端只做一件事：**确认它是个大于 0 的数**。0 元的价看着像"设过了"，
     * 实际等于白送 —— 后端也是 `gt=0`，两边同一口径（客户端先拦一道是为了少一次往返）。
     */
    fun save(product: ShipperPriceProductDto, contactId: Long?, key: Long) {
        if (submitting) return
        val raw = draftFor(key).trim()
        if (raw.isEmpty()) {
            formError = "先填一个单价"
            return
        }
        if (moneyToDouble(raw) <= 0.0) {
            formError = "单价要大于 0 元"
            return
        }
        submitting = true
        formError = null
        viewModelScope.launch {
            try {
                // ⛔ 提交的是 trimMoneyZeros（去尾零、保四位精度），不是 formatMoney：
                //    后者会把 12.3456 印成 12.35 —— 用户不改直接保存，价就真的变了。
                val sent = trimMoneyZeros(raw)
                container.repo.setShipperPrice(
                    ShipperPriceSetRequest(
                        productId = product.productId,
                        contactId = contactId,
                        unitPrice = sent,
                    )
                )
                drafts.remove(key)
                // 显示走 formatMoney（每一处 ¥ 都要过显示漏斗）；⛔ 提交上去的仍是上面那个 sent。
                actionResult = "已保存：" + product.productName + who(contactId) + " ¥" + formatMoney(sent)
                refreshAfterWrite()
            } catch (e: Exception) {
                // 后端的原话（"只有批发商（高级货主）…"这类）原样显示，不自己编文案。
                formError = toApiException(e).message
            } finally {
                submitting = false
            }
        }
    }

    fun askDelete(row: ShipperPriceDto) {
        formError = null
        deleteTarget = row
    }

    fun cancelDelete() {
        deleteTarget = null
        formError = null
    }

    fun confirmDelete() {
        val row = deleteTarget ?: return
        if (acting) return
        acting = true
        formError = null
        viewModelScope.launch {
            try {
                container.repo.deleteShipperPrice(row.id)
                deleteTarget = null
                // ⛔ 这句话必须说：删价**不追改已经算过的钱**，用户最容易误以为"删了就少收"。
                actionResult = "已删除这条价 —— 以后下的单按新价算，已经算过的钱一分不动"
                refreshAfterWrite()
            } catch (e: Exception) {
                formError = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    /** 从回收站恢复一条价（不做二次确认：它不删任何东西，点错了再删一次就是）。 */
    fun restore(row: ShipperPriceDto) {
        if (acting) return
        acting = true
        formError = null
        viewModelScope.launch {
            try {
                container.repo.restoreShipperPrice(row.id)
                actionResult = "已恢复这条价 —— 只让它重新生效，不放回任何已经算过的钱"
                refreshAfterWrite()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    fun dismissFormError() {
        formError = null
    }

    /** 写完一条价：刷新当前商品的明细 + 商品列表上的"默认价 / N 个专人价"两处计数。 */
    private suspend fun refreshAfterWrite() {
        loadPrices()
        products = runCatching { container.repo.priceableProducts() }.getOrElse { products }
    }

    private fun who(contactId: Long?): String {
        if (contactId == null) return "（默认价）"
        val name = contacts.firstOrNull { it.id == contactId }?.displayName.orEmpty()
        return if (name.isBlank()) "（专人价）" else "（" + name + "）"
    }
}
