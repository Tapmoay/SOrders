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
import kotlin.math.abs
import kotlin.math.roundToInt
import kotlinx.coroutines.launch

/**
 * 把 [id] 那一项挪到第 [position] 位（**1-based**；0 与越界都夹到两端）。**纯函数，有单测。**
 *
 * 拖动与"填数字"两种排序**共用这一处** —— 两条路只是"目标位置"的来源不同，
 * 到位之后做的事一模一样。抽成顶层函数是为了能被单测直接调：
 * 藏在 ViewModel 里就只能靠模拟器点，而这里恰好是最容易写错一格的地方。
 *
 * ⚠️ 没变化时**原样返回同一个列表实例**（调用方靠这个判断要不要写回状态）。
 */
internal fun moveCategoryTo(
    list: List<ProductCategoryDto>,
    id: Long,
    position: Int,
): List<ProductCategoryDto> {
    val from = list.indexOfFirst { it.id == id }
    if (from < 0 || list.size < 2) return list
    val to = (position - 1).coerceIn(0, list.lastIndex)
    if (to == from) return list
    return list.toMutableList().apply { add(to, removeAt(from)) }
}

/**
 * 拖动位移 → 要挪几格（正数往下）。**纯函数，有单测。**
 *
 * ## 两个细节，都是写单测时才定下来的
 * 1. **半行就翻**（不是"必须划满一行"）：手指划过一行的一半就该换位，
 *    取整会让手感变成"拖了没反应"，像卡住。
 * 2. **上下必须对称**：`roundToInt()` 对 ±0.5 是**不对称**的
 *    （`(+0.5).roundToInt() == 1` 而 `(-0.5).roundToInt() == 0`，Java 的 round 是
 *    "向正无穷取整"）—— 直接用会让"往上拖"比"往下拖"多要一点位移，
 *    用户感觉是"上边黏"。所以先取绝对值再补符号。
 *    （这条是单测抓出来的：`assertEquals(-1, dragSteps(-50f, 100f))` 第一版是红的。）
 *
 * [rowHeightPx] <= 0 时返回 0（量不出行高就不猜，也避免除零）。
 */
internal fun dragSteps(offsetY: Float, rowHeightPx: Float): Int {
    if (rowHeightPx <= 0f) return 0
    val rows = offsetY / rowHeightPx
    val mag = abs(rows).roundToInt()
    return if (rows < 0f) -mag else mag
}

/**
 * 商品分类管理页的状态。
 *
 * ## 排序是**本地草稿**，点「保存顺序」才提交
 * 理由：后端要求**整份顺序**（`ProductCategoryReorder` 的注释解释了为什么不做"上移一格"）。
 * 如果每拖一下就发一次请求，用户连拖三下就是三次全量重排 ——
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

    /**
     * 排序：把某一项挪到第 [position] 位（1-based；填 0 或越界会被夹到两端）。
     * **数字排序与拖动都走这里**（见 `moveCategoryTo` 的注释）。
     */
    fun moveTo(id: Long, position: Int) {
        val next = moveCategoryTo(categories, id, position)
        if (next === categories) return // 没变（找不到 / 本来就在那儿）—— 别把状态写一遍
        categories.clear()
        categories.addAll(next)
        dirty = categories.map { it.id } != savedOrder
    }

    /** 拖动用：按"挪了几格"挪（正数往下）。 */
    fun moveBy(id: Long, steps: Int) {
        val idx = categories.indexOfFirst { it.id == id }
        if (idx < 0) return
        moveTo(id, idx + 1 + steps)
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
