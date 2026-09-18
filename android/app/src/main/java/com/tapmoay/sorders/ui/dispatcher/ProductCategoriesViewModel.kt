package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.ProductCategoryDto
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.launch

/**
 * 商品分类管理页的状态。
 *
 * ## 排序是**本地草稿**，点「保存顺序」才提交
 * 理由：后端要求**整份顺序**（`ProductCategoryReorder` 的注释解释了为什么不做"上移一格"）。
 * 如果每点一次上下移就发一次请求，用户连点三下就是三次全量重排 ——
 * 中间任何一次失败都会留下"顺序半新半旧"的状态，而屏幕上看起来只是"没动"。
 */
class ProductCategoriesViewModel(private val container: AppContainer) : ViewModel() {

    val categories = mutableStateListOf<ProductCategoryDto>()
    var loading by mutableStateOf(true)
    var busy by mutableStateOf(false)
    /** 加载失败（留在页面上 + 重试），与一次性提示分开 —— 见 `WholesalePricingViewModel` 的说明。 */
    var loadError by mutableStateOf<String?>(null)
    var error by mutableStateOf<String?>(null)
    var notice by mutableStateOf<String?>(null)

    /** (id 或 null=新建, 当前名字) */
    var editing by mutableStateOf<Pair<Long?, String>?>(null)
    var deleting by mutableStateOf<ProductCategoryDto?>(null)

    /** 顺序是否改过还没保存 */
    var dirty by mutableStateOf(false)
        private set

    private var savedOrder: List<Long> = emptyList()

    init {
        load()
    }

    fun load() {
        loading = categories.isEmpty()
        loadError = null
        viewModelScope.launch {
            try {
                val list = container.repo.productCategories()
                categories.clear()
                categories.addAll(list)
                savedOrder = list.map { it.id }
                dirty = false
            } catch (e: Exception) {
                loadError = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun openCreate() {
        editing = null to ""
    }

    fun openRename(c: ProductCategoryDto) {
        editing = c.id to c.name
    }

    fun move(index: Int, delta: Int) {
        val target = index + delta
        if (index !in categories.indices || target !in categories.indices) return
        val item = categories.removeAt(index)
        categories.add(target, item)
        dirty = categories.map { it.id } != savedOrder
    }

    fun revertOrder() {
        if (savedOrder.isEmpty()) return
        val byId = categories.associateBy { it.id }
        val restored = savedOrder.mapNotNull { byId[it] }
        // 保存顺序里可能有刚新建、还没刷进来的分类 —— 追到后面，不要丢
        val extra = categories.filter { it.id !in savedOrder }
        categories.clear()
        categories.addAll(restored + extra)
        dirty = false
    }

    fun saveOrder() {
        if (categories.isEmpty()) return
        busy = true
        error = null
        viewModelScope.launch {
            try {
                val list = container.repo.reorderProductCategories(categories.map { it.id })
                categories.clear()
                categories.addAll(list)
                savedOrder = list.map { it.id }
                dirty = false
                notice = "顺序已保存"
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                busy = false
            }
        }
    }

    fun submit(id: Long?, rawName: String) {
        val name = rawName.trim()
        if (name.isBlank()) {
            error = "分类名不能为空"
            return
        }
        busy = true
        error = null
        viewModelScope.launch {
            try {
                if (id == null) {
                    container.repo.createProductCategory(name)
                    notice = "已新建分类「$name」"
                } else {
                    container.repo.updateProductCategory(id, name = name)
                    notice = "已改名为「$name」"
                }
                editing = null
                val list = container.repo.productCategories()
                categories.clear()
                categories.addAll(list)
                savedOrder = list.map { it.id }
                dirty = false
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                busy = false
            }
        }
    }

    fun askDelete(c: ProductCategoryDto) {
        deleting = c
    }

    fun confirmDelete(c: ProductCategoryDto) {
        busy = true
        error = null
        viewModelScope.launch {
            try {
                container.repo.deleteProductCategory(c.id)
                deleting = null
                notice = "已删除分类「${c.name}」"
                val list = container.repo.productCategories()
                categories.clear()
                categories.addAll(list)
                savedOrder = list.map { it.id }
                dirty = false
            } catch (e: Exception) {
                // 后端会因为"还有商品挂着"而拒绝 —— 那句话要原样给用户看（它带了数量）
                error = toApiException(e).message
                deleting = null
            } finally {
                busy = false
            }
        }
    }
}
