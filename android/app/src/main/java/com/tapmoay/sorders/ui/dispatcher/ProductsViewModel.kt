package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.*
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.api.ProductCreateRequest
import com.tapmoay.sorders.data.remote.api.ProductUpdateRequest
import com.tapmoay.sorders.data.remote.dto.ProductCategoryDto
import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.data.remote.dto.ProductTierDto
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.launch
import java.io.File

/** 批发价草稿行 */
data class TierDraft(val label: String = "", val price: String = "")

class ProductsViewModel(private val container: AppContainer) : ViewModel() {

    var products by mutableStateOf<List<ProductDto>>(emptyList())
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    /**
     * **加载**失败：要留在页面上（配合整页 ErrorView + 重试），**不能**被提示条消费掉。
     * 拆字段的理由见 `WholesalePricingViewModel` 的同一处注释。
     */
    var loadError by mutableStateOf<String?>(null)
    /** 分类名册（决定下单页左侧顺序）。商品编辑页从这里选分类，也能就地新建。 */
    var categories by mutableStateOf<List<ProductCategoryDto>>(emptyList())
    var acting by mutableStateOf(false)
    var actionResult by mutableStateOf<String?>(null)

    var showDialog by mutableStateOf(false)
    var editing by mutableStateOf<ProductDto?>(null)
    var draftName by mutableStateOf("")
    var draftPrice by mutableStateOf("")
    var draftCost by mutableStateOf("")
    var draftStock by mutableStateOf("")
    var draftUnit by mutableStateOf("")
    /** 商品分类：选品页左侧的分组名（空 = 未分类）。 */
    var draftCategory by mutableStateOf("")
    var draftAlert by mutableStateOf("")
    var draftColor by mutableStateOf("#1565C0")
    var draftActive by mutableStateOf(true)
    /** 本地已选图片路径（保存时上传）；null=未换图 */
    var draftImageLocal by mutableStateOf<String?>(null)
    /** 删除表情：需要清除原图时置 true（本轮先只支持换图，不做删图） */
    val draftTiers = mutableStateListOf<TierDraft>()

    val colorOptions = listOf(
        "#1565C0" to "物流蓝",
        "#2E7D32" to "绿",
        "#C62828" to "红",
        "#F9A825" to "黄",
        "#6A1B9A" to "紫",
        "#00838F" to "青",
        "#EF6C00" to "橙",
        "#5D4037" to "棕",
        "#37474F" to "灰",
    )

    init {
        load()
    }

    fun load() {
        loading = products.isEmpty()
        loadError = null
        viewModelScope.launch {
            try {
                products = container.repo.products()
                categories = container.repo.productCategories()
            } catch (e: Exception) {
                loadError = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun openCreate() {
        editing = null
        draftName = ""
        draftPrice = ""
        draftCost = ""
        draftStock = ""
        draftUnit = ""
        draftCategory = ""
        draftAlert = ""
        draftColor = "#1565C0"
        draftActive = true
        draftImageLocal = null
        draftTiers.clear()
        showDialog = true
    }

    fun openEdit(p: ProductDto) {
        editing = p
        draftName = p.name
        draftPrice = com.tapmoay.sorders.util.formatMoney(p.defaultUnitPrice)
        draftCost = com.tapmoay.sorders.util.formatMoney(p.costPrice)
        draftStock = if (p.stock > 0) p.stock.toString() else ""
        draftUnit = p.unit
        draftCategory = p.category
        draftAlert = if (p.lowStockAlert > 0) p.lowStockAlert.toString() else ""
        draftColor = p.nameColor ?: "#1565C0"
        draftActive = p.isActive
        draftImageLocal = null
        draftTiers.clear()
        p.tierPrices.forEach { draftTiers.add(TierDraft(it.label, it.unitPrice)) }
        showDialog = true
    }

    fun addTier() {
        val idx = draftTiers.size + 1
        draftTiers.add(TierDraft("批发价" + cjkNum(idx), ""))
    }

    fun removeTier(index: Int) {
        if (index in draftTiers.indices) draftTiers.removeAt(index)
    }

    private fun cjkNum(n: Int): String = when (n) {
        1 -> "一"; 2 -> "二"; 3 -> "三"; 4 -> "四"; 5 -> "五"
        6 -> "六"; 7 -> "七"; 8 -> "八"; 9 -> "九"; else -> n.toString()
    }

    fun save() {
        if (draftName.isBlank()) {
            error = "请填写商品名称"
            return
        }
        if (draftPrice.toDoubleOrNull() == null) {
            error = "请输入正确的售价"
            return
        }
        if (draftCost.isNotBlank() && draftCost.toDoubleOrNull() == null) {
            error = "请输入正确的成本价"
            return
        }
        if (draftStock.isNotBlank() && draftStock.toIntOrNull() == null) {
            error = "库存请输入整数"
            return
        }
        val cost = draftCost.trim().ifBlank { "0" }
        val stock = draftStock.trim().ifBlank { null }?.toIntOrNull()
        val tiers = draftTiers
            .filter { it.price.isNotBlank() && it.price.toDoubleOrNull() != null }
            .map { ProductTierDto(label = it.label.trim().ifBlank { "批发价" }, unitPrice = it.price.trim()) }

        acting = true
        error = null
        viewModelScope.launch {
            try {
                val cur = editing
                    if (cur == null) {
                        container.api.productApi.createProduct(
                            ProductCreateRequest(
                                name = draftName.trim(),
                                defaultUnitPrice = draftPrice.trim(),
                                costPrice = cost,
                                nameColor = draftColor,
                                tierPrices = tiers,
                                stock = stock,
                                unit = draftUnit.trim().ifBlank { null },
                                category = draftCategory.trim(),
                                lowStockAlert = draftAlert.trim().ifBlank { null }?.toIntOrNull(),
                            )
                        )
                    } else {
                        container.api.productApi.updateProduct(
                            cur.id,
                            ProductUpdateRequest(
                                name = draftName.trim(),
                                defaultUnitPrice = draftPrice.trim(),
                                costPrice = cost,
                                nameColor = draftColor,
                                isActive = draftActive,
                                tierPrices = tiers,
                                unit = draftUnit.trim().ifBlank { null },
                                category = draftCategory.trim(),
                                lowStockAlert = draftAlert.trim().ifBlank { null }?.toIntOrNull(),
                            ),
                        )
                    }
                // 换图：重新拉取商品拿 id 再上传
                if (draftImageLocal != null) {
                    val pid = if (cur == null) {
                        container.repo.products().firstOrNull { it.name.trim() == draftName.trim() }?.id
                    } else cur.id
                    if (pid != null) {
                        val f = File(draftImageLocal!!)
                        if (f.exists()) container.repo.uploadProductImage(pid, f)
                    }
                }
                actionResult = if (cur == null) "商品已新增" else "商品已更新"
                showDialog = false
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    fun toggleActive(p: ProductDto) {
        viewModelScope.launch {
            try {
                container.api.productApi.updateProduct(
                    p.id,
                    ProductUpdateRequest(isActive = !p.isActive),
                )
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            }
        }
    }

    fun delete(p: ProductDto) {
        acting = true
        viewModelScope.launch {
            try {
                container.api.productApi.deleteProduct(p.id)
                actionResult = "商品已删除"
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }
}
