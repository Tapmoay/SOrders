package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.*
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.api.ProductCreateRequest
import com.tapmoay.sorders.data.remote.api.ProductUpdateRequest
import com.tapmoay.sorders.data.remote.dto.ProductCategoryDto
import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.launch
import java.io.File

class ProductsViewModel(private val container: AppContainer) : ViewModel() {
    var products by mutableStateOf<List<ProductDto>>(emptyList())
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    /**
     * **加载**失败：要留在页面上（配合整页 ErrorView + 重试），**不能**被提示条消费掉。
     * 拆字段的理由见 `PriceMatrixViewModel` 的同一处注释。
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
        showDialog = true
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

        acting = true
        error = null
        viewModelScope.launch {
            try {
                val cur = editing
                // ⚠️ 新增时必须**接住 createProduct 返回的 id**（2026-09-19 审计）：
                //    原来返回的 ProductDto（含新 id）被直接丢掉，上传图片时改成
                //    `products().firstOrNull { it.name == 草稿名 }?.id` —— 而 `products.name`
                //    **没有唯一约束、创建也不查重**，于是"库里已有同名商品"时那个 id 指向**旧商品**：
                //    新商品没图、旧商品被打上新图，两边都不报错。
                val createdId: Long
                val localImage = draftImageLocal          // 先取快照，别在挂起点之后再读可变状态
                if (cur == null) {
                    createdId = container.api.productApi.createProduct(
                        ProductCreateRequest(
                            name = draftName.trim(),
                            defaultUnitPrice = draftPrice.trim(),
                            costPrice = cost,
                            nameColor = draftColor,
                            stock = stock,
                            unit = draftUnit.trim().ifBlank { null },
                            category = draftCategory.trim(),
                            lowStockAlert = draftAlert.trim().ifBlank { null }?.toIntOrNull(),
                        )
                    ).id
                } else {
                    createdId = cur.id
                    container.api.productApi.updateProduct(
                            cur.id,
                            ProductUpdateRequest(
                                name = draftName.trim(),
                                defaultUnitPrice = draftPrice.trim(),
                                costPrice = cost,
                                nameColor = draftColor,
                                isActive = draftActive,
                                unit = draftUnit.trim().ifBlank { null },
                                category = draftCategory.trim(),
                                lowStockAlert = draftAlert.trim().ifBlank { null }?.toIntOrNull(),
                            ),
                        )
                }
                // 图片上传用**上面接住的那个 id**（不再按名字去全表猜）。
                // ⚠️ 也不再在挂起点之后读 `draftImageLocal!!`（2026-09-19 审计）：用户可以在
                //    "商品已经建好、图片还没传完"这段时间点「移除图片」把状态改成 null，
                //    那一刻 `!!` 抛 NPE → 被下面的 `catch (Exception)` 收成"未知错误"、
                //    `showDialog = false` 被跳过 → **商品其实已建成，界面却说未知错误、弹窗不关**，
                //    用户再点一次保存就建出第二条同名商品。
                val imagePath = localImage
                if (imagePath != null) {
                    val f = File(imagePath)
                    if (f.exists()) container.repo.uploadProductImage(createdId, f)
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

    /**
     * 就地新建一个分类，并**选中它**（商品编辑页的分类下拉里那个「＋ 新建分类…」）。
     *
     * 为什么不让用户直接手打分类名（原来那样）：
     * 手打能造出只差一个空格的"同名"分类，下单页左侧就多出一格，而列表上看不出差别。
     * 新建这条路不能堵死（派单员建商品时才发现缺一个分类是常事），所以要有一个**明确**的入口。
     *
     * ⚠️ 重名（后端 409）时**直接选中已有的那个**：用户想要的是"归类到这个名字"，
     *    而不是"再建一个"。报错让他自己回去找那一条，是把后端的一句话变成了他的一次往返。
     */
    fun createCategoryAndSelect(rawName: String, onDone: () -> Unit) {
        val name = rawName.trim().take(8)
        if (name.isBlank()) {
            error = "分类名不能为空"
            return
        }
        acting = true
        error = null
        viewModelScope.launch {
            try {
                try {
                    container.repo.createProductCategory(name)
                    actionResult = "已新建分类「$name」"
                } catch (e: Exception) {
                    val msg = toApiException(e).message.orEmpty()
                    if (!msg.contains("已经存在")) throw e
                    actionResult = "已经有分类「$name」了，直接用它"
                }
                categories = container.repo.productCategories()
                draftCategory = name
                onDone()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    /**
     * **快捷改价**：只改默认售价，不动别的字段（商品卡右侧那个「改价」用的）。
     *
     * 为什么走 `PATCH` 的部分更新语义（只放 `default_unit_price`）而不是"读出来整套再写回去"：
     * 改售价是最高频的动作，而"整套写回"会把这期间别人改过的名称/成本/库存**悄悄覆盖掉**
     * （两个人同时在改同一个商品时必炸，而且看不出来）。
     */
    fun updateDefaultPrice(p: ProductDto, raw: String, onDone: () -> Unit) {
        val v = raw.trim()
        val n = v.toDoubleOrNull()
        if (n == null || n < 0) {
            error = "请输入正确的售价"
            return
        }
        acting = true
        error = null
        viewModelScope.launch {
            try {
                container.api.productApi.updateProduct(p.id, ProductUpdateRequest(defaultUnitPrice = v))
                actionResult = p.name + " 售价已改为 ¥" + com.tapmoay.sorders.util.formatMoney(v)
                onDone()
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
