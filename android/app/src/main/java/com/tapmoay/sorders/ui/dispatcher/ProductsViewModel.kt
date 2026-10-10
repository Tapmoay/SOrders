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

    /**
     * 沽清（下架）/ 上架 —— 卡片上第二个大按钮那个动作。
     *
     * ⚠️ **2026-10-03（CHG-0025 / P29）起它只由确认弹层调用**：以前它是卡片的 `onClick`
     *    直接调的，E2E 走查时**一次误触**就把一件商品静默下架了（同一页的「删除」反倒有确认）。
     *    弹层是 `ui/common/ProductCardKit.kt::ProductActiveConfirmDialog`，
     *    页面上那句 `onToggle` 现在只负责**打开弹层**（红线 `_check_product_active_confirm.py` 盯着）。
     *
     * `acting` 这一位以前没设过：请求在飞的那一会儿卡片上的按钮还是能点的，
     * 第二次点击发的是同一个值（用户看到的是"点了没反应"）。
     */
    fun toggleActive(p: ProductDto) {
        acting = true
        error = null
        viewModelScope.launch {
            try {
                container.api.productApi.updateProduct(
                    p.id,
                    ProductUpdateRequest(isActive = !p.isActive),
                )
                actionResult = p.name + (if (p.isActive) " 已沽清" else " 已上架")
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    // ⛔ 删除搬去编辑页了（用户 2026-09-21：⋮ 里的功能进编辑页）——
    //    现在只有 `ProductFormViewModel.delete()` 一处会删商品。

    // ---------------------------------------------------------------- 回收站
    //
    // 2026-10-10 BUG-0035（测试台账 TA-11 / TA-03）：删除确认弹窗一直承诺
    // 「列表顶端的『回收站』里可以把它恢复回来」，而这一屏从来没有那个入口 ——
    // 用户 2026-09-20 的硬规矩是「所有删除一律软删 + 界面上要有一个手边的恢复入口」，
    // 商品这一格是欠账（`restoreProduct` 此前在 `ui/` 下零调用点）。下面这一份状态就是那个入口。

    /** 回收站那一档是否打开（页面顶部 `SegmentedPicker(在用 / 回收站)` 的第二档）。 */
    var recycleBin by mutableStateOf(false)
        private set

    /** 回收站里的商品。顺序由后端定：`deleted_at` 倒序（刚删的在最上面，用户要找的就是它）。 */
    var binItems by mutableStateOf<List<ProductDto>>(emptyList())
    var binLoading by mutableStateOf(false)

    /**
     * 回收站**取数**失败。
     *
     * ⚠️ 与 [error] 分开：`error` 会被提示条消费掉（一闪就没），而"没取到"必须留在页面上配一个「重试」
     * —— 否则「回收站是空的」会把一次网络失败说成「你没有删过商品」（两句完全不同的结论）。
     */
    var binError by mutableStateOf<String?>(null)

    /** 正在恢复哪一个（按 id 记；那一行的按钮据此禁用，避免连点两次发两个恢复请求）。 */
    var restoringId by mutableStateOf<Long?>(null)

    /**
     * 切换「在用 / 回收站」。
     *
     * 清空旧列表再拉（照 `DriverBillingRulesViewModel.switchRecycleBin` 的体例）：
     * 不换掉旧内容的话，上一档的数据会停留在屏幕上被当成这一档的内容。
     */
    fun switchRecycleBin(bin: Boolean) {
        if (bin == recycleBin) return
        recycleBin = bin
        binItems = emptyList()
        binError = null
        if (bin) loadBin()
    }

    /**
     * 拉回收站。
     *
     * ⚠️ 请求是异步的：回来时用户可能已经切回「在用」了 —— 那样会把回收站的结果当成在用列表画出来
     * （表现是"删掉的商品又回来了"）。所以**按页签核对一次**（同 `DriverBillingRulesViewModel.load`）。
     */
    fun loadBin() {
        val bin = recycleBin
        binLoading = binItems.isEmpty()
        binError = null
        viewModelScope.launch {
            try {
                val list = container.repo.deletedProducts()
                if (bin == recycleBin) binItems = list
            } catch (e: Exception) {
                if (bin == recycleBin) binError = toApiException(e).message
            } finally {
                if (bin == recycleBin) binLoading = false
            }
        }
    }

    /**
     * 从回收站恢复一件商品（`POST /products/{id}/restore`）。
     *
     * ⚠️ 「恢复到上架还是下架」**由后端算**（它读删除日志里的 `was_active`，删之前刻意下架的商品
     *    恢复后仍然下架）。这里只把后端回来的 `isActive` 如实写进提示语 —— 客户端不重算这件事。
     *
     * 恢复成功后**自动切回「在用」**并把列表重拉一次：弹窗承诺的是"列表顶端的回收站里能把它
     * 恢复回来"，恢复完停在一个空档里会让人再找一次"它去哪了"；提示语写清它回到了哪儿、什么状态。
     */
    fun restoreFromBin(p: ProductDto) {
        if (restoringId != null) return
        restoringId = p.id
        binError = null
        viewModelScope.launch {
            try {
                val back = container.repo.restoreProduct(p.id)
                binItems = binItems.filterNot { it.id == p.id }
                recycleBin = false
                load()
                actionResult = "「" + back.name + "」已恢复到商品列表（" +
                    (if (back.isActive) "上架" else "沽清") + "）"
            } catch (e: Exception) {
                binError = toApiException(e).message
            } finally {
                restoringId = null
            }
        }
    }
}
