package com.tapmoay.sorders.ui.dispatcher

import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.ProductCategoryDto
import com.tapmoay.sorders.ui.common.CategoryRosterViewModel
import kotlin.math.abs
import kotlin.math.roundToInt

// ⚠️ `moveItemTo`（四种排序方式共用的那一份）**已搬到 `ui/common/CategoryRoster.kt`**：
//    它被四个名册页用着，却住在这个页面文件里 —— 共用规则不许寄生在某一页。
//    老的商品专用包装 `moveCategoryTo` 随之删除（它只剩"给这一页换个参数写法"的作用）。

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
 *
 * ⚠️ 那套状态机（拉名册 / 草稿排序 / 提交整份 / 建改名删）**已经不在这个文件里**：
 * 它与开销、运费两页共用一份 `ui/common/CategoryRosterViewModel.kt`（原来三页各抄了约 45 行）。
 * 这里只剩「这一页是什么」——拉哪个接口、提交到哪个接口。
 */
class ProductCategoriesViewModel(container: AppContainer) :
    CategoryRosterViewModel<ProductCategoryDto>(container) {

    init {
        // ⚠️ 由**子类**来调：基类的 init 早于子类初始化，而 load() 在 Main.immediate 下
        //    会同步跑到第一个挂起点（见基类文件头）。
        load()
    }

    override fun idOf(item: ProductCategoryDto) = item.id

    override fun nameOf(item: ProductCategoryDto) = item.name

    override suspend fun fetchAll() = container.repo.productCategories()

    override suspend fun reorder(ids: List<Long>) = container.repo.reorderProductCategories(ids)

    override suspend fun create(name: String) {
        container.repo.createProductCategory(name)
    }

    override suspend fun rename(id: Long, name: String) {
        container.repo.updateProductCategory(id, name = name)
    }

    override suspend fun delete(id: Long) {
        container.repo.deleteProductCategory(id)
    }
}
