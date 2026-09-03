package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.*
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.api.PriceRuleDto
import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.launch

/** 批发商定价：每个批发商可对每个商品自定义价格（price_rules 特殊价） */
class WholesalePricingViewModel(
    private val container: AppContainer,
    val shipperId: Long,
) : ViewModel() {

    var products by mutableStateOf<List<ProductDto>>(emptyList())
    /** productId -> 该批发商的已存特价 */
    var rules by mutableStateOf<Map<Long, PriceRuleDto>>(emptyMap())
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var acting by mutableStateOf(false)
    var actionResult by mutableStateOf<String?>(null)
    /** productId -> 用户当前输入 */
    val drafts = mutableStateMapOf<Long, String>()

    init { load() }

    fun load() {
        loading = products.isEmpty()
        error = null
        viewModelScope.launch {
            try {
                val ps = container.repo.products(includeInactive = true)
                val rs = container.repo.priceRules()
                    .filter { it.shipperId == shipperId }
                    .associateBy { it.productId }
                products = ps
                rules = rs
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun fieldValue(p: ProductDto): String =
        drafts[p.id] ?: rules[p.id]?.specialUnitPrice ?: ""

    fun savePrice(p: ProductDto) {
        val raw = drafts[p.id]?.trim().orEmpty()
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
                val existing = rules[p.id]
                if (existing != null) {
                    container.repo.updatePriceRule(existing.id, raw)
                } else {
                    container.repo.createPriceRule(shipperId, p.id, raw)
                }
                actionResult = p.name + " 特价已保存"
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    fun clearPrice(p: ProductDto) {
        val existing = rules[p.id] ?: return
        acting = true
        error = null
        viewModelScope.launch {
            try {
                container.repo.deletePriceRule(existing.id)
                drafts.remove(p.id)
                actionResult = p.name + " 特价已清除（恢复默认价）"
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }
}
