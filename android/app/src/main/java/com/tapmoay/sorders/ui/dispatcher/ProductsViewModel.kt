package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.*
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.api.ProductUpdateRequest
import com.tapmoay.sorders.data.remote.dto.ProductCategoryDto
import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.launch

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

    /**
     * 按**名称**搜商品（用户 2026-09-19：「商品管理的页面要有个搜索的框啊，方便我们找商品」）。
     *
     * 与库存页的搜索是同一套判据（本地过滤 + 与左侧分类 **AND**）：
     * 商品名册的量级是几百，本地过滤比每次打字都打后端快，也不会让键盘卡顿。
     */
    var query by mutableStateOf("")
    var acting by mutableStateOf(false)
    var actionResult by mutableStateOf<String?>(null)

    /**
     * 这一屏每次进组合时拉一次（页面里是 `LaunchedEffect(Unit) { vm.start() }`）。
     *
     * ⚠️ **加载不放在 `init`**：从「新增/编辑商品」那一页 `popBackStack()` 回来时这一屏会重新进组合，
     *    `LaunchedEffect(Unit)` 会再跑一次 —— 刚存的那个商品立刻出现在列表里。
     *    写在 `init` 里就只在第一次创建 VM 时拉一次，回来看到的是**没有刚存那个**的旧列表
     *    （用户会以为没存上，然后再建一个 → 建出同名商品）。
     *    与账本「记一笔账」、开销「新增开销」两处是同一个套路。
     *
     * ## 表单状态搬走了（2026-09-21 商品管理改版第 1 期）
     * 这个 VM 里原来还有一整份"正在编辑的草稿"（`draftName` / `draftPrice` / … 11 个字段）、
     * `openCreate` / `openEdit` / `save` 与 `colorOptions` —— 它们跟着商品表单一起
     * 搬去了 `ProductFormViewModel`（表单现在是**单独一页**，有自己的路由与生命周期）。
     * 列表页不该背着一份草稿，也不该在返回时被重组碰到它。
     */
    fun start() {
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

    // ⛔ 删除搬去编辑页了（用户 2026-09-21：⋮ 里的功能进编辑页）——
    //    现在只有 `ProductFormViewModel.delete()` 一处会删商品。
}
