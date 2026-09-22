package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.api.ProductCreateRequest
import com.tapmoay.sorders.data.remote.api.ProductUpdateRequest
import com.tapmoay.sorders.data.remote.dto.ProductCategoryDto
import com.tapmoay.sorders.data.remote.dto.ProductCostHistoryDto
import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.DEFAULT_PRODUCT_NAME_COLOR
import com.tapmoay.sorders.ui.common.DEFAULT_UNIT
import com.tapmoay.sorders.util.trimMoneyZeros
import kotlinx.coroutines.launch
import java.io.File

/**
 * 「新增 / 编辑商品」那一页的状态（2026-09-21 商品管理改版第 1 期，P7）。
 *
 * ## 它原来是商品管理页 ViewModel 里的一段
 * 表单状态（`draftName` / `draftPrice` / … 11 个字段）与 `save()` 原来住在
 * [ProductsViewModel] 里，因为那一屏原来是**一个底部抽屉**。改成**单独一页**之后
 * （用户：「这是他的新建商品的界面，我们也改一下我们的新建商品的界面——不是很好看，也太乱了」），
 * 它有了自己的路由与生命周期，也就该有自己的 ViewModel：
 * 列表页不该背着一份"正在编辑的草稿"，而且列表页的 VM 会被列表页的重组反复碰到。
 *
 * ## ⛔ 这一版修掉的两个**会改到钱 / 会撒谎**的地方
 * 1. **编辑从"整份回传"改成"只发改动的键"**。原来 `save()` 一次把 8 个字段全发上去，
 *    值来自**打开那一刻**的草稿 —— 你开着编辑页这段时间里，别人改了这条商品的任何字段
 *    （或你自己在商品卡上快捷改过价），一保存就**静默写回旧值**，界面上看不出来。
 *    后端本来就是 `exclude_unset` 的部分更新，同一个 VM 里的「快捷改价」「上架/下架」
 *    也一直是只发一个键 —— 所以这不是加严，是**追平到同一个口径**。
 * 2. **预填金额用 `trimMoneyZeros` 而不是 `formatMoney`**（设计规范 §4.0 早就写了这一条，
 *    但编辑抽屉漏了）：库里 `default_unit_price` 是 `Numeric(14,4)`，
 *    `formatMoney` 只留两位 —— 一个 `12.3456` 元的商品，**点开编辑再保存就被改成 12.35**，
 *    而这是钱。用去尾零的写法之后，"没碰过的价"才算真的没变（配合下面的 [moneySame]）。
 */
class ProductFormViewModel(
    private val container: AppContainer,
    private val productId: Long?,
) : ViewModel() {

    /** 新增（true）还是编辑（false）。 */
    val isNew: Boolean = productId == null

    var loading by mutableStateOf(!isNew)
    var loadError by mutableStateOf<String?>(null)
    var saving by mutableStateOf(false)

    /** 表单里的错（校验 + 接口失败）：画在表单里（`FormErrorLine`），不是整页错误。 */
    var error by mutableStateOf<String?>(null)

    /** 本页提示条（"已添加，可以接着录"这种，不离开页面）。 */
    var notice by mutableStateOf<String?>(null)

    /** 保存完该退出这一页了（页面观察它 → `popBackStack()`）。 */
    var closeRequested by mutableStateOf(false)

    // ---------------------------------------------------------------- 草稿
    var name by mutableStateOf("")
    var price by mutableStateOf("")
    var cost by mutableStateOf("")
    /** 库存**只在新增时可填**（`PATCH /products` 根本不收 stock：库存只能走出入库流水）。 */
    var stock by mutableStateOf("")
    var unit by mutableStateOf(DEFAULT_UNIT)
    var category by mutableStateOf("")
    var alert by mutableStateOf("")
    var color by mutableStateOf(DEFAULT_PRODUCT_NAME_COLOR)
    var active by mutableStateOf(true)

    /** 本地新选的图片路径（保存时上传）；null = 没换图。 */
    var imageLocal by mutableStateOf<String?>(null)

    /** 用户点了「移除图片」（**编辑时这才是一次真的改动**：会写 `image_url=""`）。 */
    var imageCleared by mutableStateOf(false)

    /** 分类名册（选择页要用；改名/新建之后要重拉）。 */
    var categories by mutableStateOf<List<ProductCategoryDto>>(emptyList())

    /**
     * 名称颜色的候选（商品名在列表/选品页上的颜色）。
     *
     * ⚠️ 它原来在 [ProductsViewModel] 里（列表页与编辑页共用同一个 VM）。表单独立成页之后
     * 搬到这里 —— 列表页不画这个色板，留着就是一份没人读的常量。
     */
    val colorOptions = listOf(
        // ⚠️ 第一个**必须**引 `DEFAULT_PRODUCT_NAME_COLOR`，不要再抄一遍 `"#1565C0"`：
        //    它是"没设过颜色"的兜底值，抄一份就会出现"兜底改了、色板没改"（两处不一致而看不出来）
        DEFAULT_PRODUCT_NAME_COLOR to "物流蓝",
        "#2E7D32" to "绿",
        "#C62828" to "红",
        "#F9A825" to "黄",
        "#6A1B9A" to "紫",
        "#00838F" to "青",
        "#EF6C00" to "橙",
        "#5D4037" to "棕",
        "#37474F" to "灰",
    )

    /** 打开时的原值（编辑时用来算"哪些键真的改了"）。新增时为 null。 */
    private var baseline: ProductDto? = null

    /** 只读地把它露出去：编辑页的「成本价历史」弹窗要拿它显示商品名与单位。 */
    val loaded: ProductDto? get() = baseline

    /** 这个商品**当前**的图片（编辑时来自服务端；被"移除"或换成新图之后为空）。 */
    val currentImageUrl: String? get() = if (imageCleared) null else baseline?.imageUrl

    init {
        if (isNew) {
            viewModelScope.launch { loadCategories() }
        } else {
            load()
        }
    }

    fun load() {
        loading = true
        loadError = null
        viewModelScope.launch {
            try {
                fill(container.api.productApi.getProduct(productId!!))
                loadCategories()
            } catch (e: Exception) {
                loadError = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    private suspend fun loadCategories() {
        categories = container.repo.productCategories()
    }

    private fun fill(p: ProductDto) {
        baseline = p
        name = p.name
        // ⚠️ 去尾零（**不是** formatMoney）：见类注释第 2 条
        price = trimMoneyZeros(p.defaultUnitPrice)
        cost = trimMoneyZeros(p.costPrice)
        stock = if (p.stock > 0) p.stock.toString() else ""
        unit = p.unit.ifBlank { DEFAULT_UNIT }
        category = p.category
        alert = if (p.lowStockAlert > 0) p.lowStockAlert.toString() else ""
        color = p.nameColor ?: DEFAULT_PRODUCT_NAME_COLOR
        active = p.isActive
        imageLocal = null
        imageCleared = false
    }

    /** 图片：选了本地图（会覆盖服务端那张）。 */
    fun pickImage(path: String) {
        imageLocal = path
        imageCleared = false
    }

    /** 图片：移除（新增时=取消这次选择；编辑时=真的把服务端那张清掉，见 [changed]）。 */
    fun removeImage() {
        imageLocal = null
        if (!isNew) imageCleared = true
    }

    /**
     * 保存。
     *
     * @param andContinue 「保存并再添加一个」（只有新增时给这个按钮）：存完之后**留住这一页**、
     *   清掉"每个商品都不一样"的那几项（名称/售价/成本/库存/图片），
     *   **保留**"一批货通常一样"的那几项（单位/分组/名称颜色/上架/报警阈值）——
     *   一次录二十个货的人最不想重填的就是后者。
     */
    fun save(andContinue: Boolean) {
        val cleanName = name.trim()
        if (cleanName.isBlank()) { error = "请填写商品名称"; return }
        if (price.trim().toBigDecimalOrNull() == null || price.trim().toBigDecimalOrNull()!!.signum() < 0) {
            error = "请输入正确的售价"; return
        }
        val cleanCost = cost.trim().ifBlank { "0" }
        if (cleanCost.toBigDecimalOrNull() == null) { error = "请输入正确的成本价"; return }
        if (isNew && stock.isNotBlank() && stock.trim().toIntOrNull() == null) {
            error = "库存请输入整数"; return
        }

        saving = true
        error = null
        viewModelScope.launch {
            // 先取快照，别在挂起点之后再读可变状态（下面上传图片要用它）
            val localImage = imageLocal
            val cleanUnit = unit.trim().ifBlank { DEFAULT_UNIT }
            val cleanCategory = category.trim()
            val alertInt = alert.trim().ifBlank { null }?.toIntOrNull()
            try {
                if (isNew) {
                    val created = container.api.productApi.createProduct(
                        ProductCreateRequest(
                            name = cleanName,
                            defaultUnitPrice = price.trim(),
                            costPrice = cleanCost,
                            nameColor = color,
                            stock = stock.trim().ifBlank { null }?.toIntOrNull(),
                            unit = cleanUnit,
                            category = cleanCategory,
                            lowStockAlert = alertInt,
                        ),
                    )
                    // ⚠️ 图片上传用**接住的这个 id**（2026-09-19 审计）：原来按名字去全表猜，
                    //    而 `products.name` 没有唯一约束 —— 同名商品时新商品没图、旧商品被打上新图。
                    uploadIfPicked(created.id, localImage)
                    if (andContinue) {
                        resetForNext()
                        notice = "已添加「$cleanName」，可以接着录下一个"
                    } else {
                        closeRequested = true
                    }
                } else {
                    val req = changed()
                    if (req == null) {
                        // 一个键都没改：**不发请求**（后端也会因为 `old == value` 不记日志，
                        // 但白跑一趟会让"保存中…"闪一下，用户以为改了什么）
                        closeRequested = true
                        return@launch
                    }
                    container.api.productApi.updateProduct(productId!!, req)
                    uploadIfPicked(productId, localImage)
                    closeRequested = true
                }
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                saving = false
            }
        }
    }

    private suspend fun uploadIfPicked(id: Long, path: String?) {
        if (path == null) return
        val f = File(path)
        if (f.exists()) container.repo.uploadProductImage(id, f)
    }

    /**
     * 「保存并再添加一个」：清掉**每个商品都不一样**的那几项，留住**一批货通常一样**的那些。
     *
     * 清：名称 / 售价 / 成本 / 初始库存 / 图片。
     * 留：单位 / 分组 / 名称颜色 / 上架 / 报警阈值 —— 一次录二十个货的人最不想重填的就是它们。
     */
    private fun resetForNext() {
        name = ""
        price = ""
        cost = ""
        stock = ""
        imageLocal = null
        imageCleared = false
        error = null
    }

    /**
     * 成本价历史（只读）：编辑页那一行「成本价历史 >」用。
     *
     * ⚠️ 它**原来在 `ProductsViewModel` 里**（商品卡的 `⋮ → 成本价历史`）；用户 2026-09-21 要求
     * 「那 3 点的这个功能到编辑里面去」，于是连状态带弹窗一起搬到这里。列表页不再持有它 ——
     * 两边各留一份就会出现"在编辑页看的历史是旧的"。
     */
    var showCostHistory by mutableStateOf(false)
    var costHistory by mutableStateOf<List<ProductCostHistoryDto>>(emptyList())
    var costHistoryLoading by mutableStateOf(false)

    fun openCostHistory() {
        val id = productId ?: return
        showCostHistory = true
        costHistory = emptyList()
        costHistoryLoading = true
        viewModelScope.launch {
            try {
                costHistory = container.repo.productCostHistory(id)
            } catch (e: Exception) {
                // 拉失败要**说出来**，不能显示成"这个商品没有成本记录"——
                // 那两句是完全不同的结论（一句是网络问题，一句是账实不符）
                error = toApiException(e).message
                showCostHistory = false
            } finally {
                costHistoryLoading = false
            }
        }
    }

    /**
     * 删除商品（**软删**：后端只是打标记，`POST /products/{id}/restore` 能恢复）。
     *
     * ⚠️ 用户 2026-09-20 定的硬规矩：**所有删除一律软删 + 界面上要有一个手边的恢复入口**。
     * 所以删完回列表之后，列表顶端那条**撤销条**（`ProductsScreen` 的 `undoDelete`）要能把它捞回来 ——
     * 只把恢复藏在 AI 撤回卡里是不算的。
     */
    fun delete(onDone: (String) -> Unit) {
        val id = productId ?: return
        val name = baseline?.name ?: name
        saving = true
        error = null
        viewModelScope.launch {
            try {
                container.api.productApi.deleteProduct(id)
                onDone(name)
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                saving = false
            }
        }
    }

    // ---------------------------------------------------------------- 差异
    //
    // ⛔ 「哪些键真的改了」只有这一处实现（纯函数，在文件末尾，有单测
    //    `ProductFormDiffTest`）。整份回传的后果见类注释第 1 条。

    private fun draft() = ProductDraft(
        name = name,
        price = price,
        cost = cost,
        unit = unit,
        category = category,
        alert = alert,
        color = color,
        active = active,
        imageCleared = imageCleared,
    )

    private fun changed(): ProductUpdateRequest? {
        val b = baseline ?: return null
        return productEdits(b, draft())
    }

    // ---------------------------------------------------------------- 就地新建分类

    /**
     * 就地新建一个分类，并**选中它**（选择页里那个「新建分组」）。
     *
     * ⚠️ 重名（后端 409）时**直接选中已有的那个**：用户想要的是"归到这个名字"，
     * 而不是"再建一个"。报错让他自己回去找那一条，是把后端的一句话变成了他的一次往返。
     */
    fun createCategoryAndSelect(rawName: String) {
        val clean = rawName.trim().take(8)
        if (clean.isBlank()) { error = "分组名不能为空"; return }
        saving = true
        error = null
        viewModelScope.launch {
            try {
                try {
                    container.repo.createProductCategory(clean)
                    notice = "已新建分组「$clean」"
                } catch (e: Exception) {
                    val msg = toApiException(e).message.orEmpty()
                    if (!msg.contains("已经存在")) throw e
                    notice = "已经有分组「$clean」了，直接用它"
                }
                loadCategories()
                category = clean
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                saving = false
            }
        }
    }
}

/**
 * 用户在表单里填的这一份（**与 Compose 状态解耦的纯数据**）—— 好让 [productEdits] 能被单测。
 */
internal data class ProductDraft(
    val name: String,
    val price: String,
    val cost: String,
    val unit: String,
    val category: String,
    val alert: String,
    val color: String,
    val active: Boolean,
    /** 用户点过「移除图片」（只有它才写 `image_url=""`；换成新图走上传端点）。 */
    val imageCleared: Boolean = false,
)

/**
 * **只算出真正改动过的键**；一个都没改 → `null`（调用方据此**不发请求**）。
 *
 * ## 为什么这是一个必须单测的纯函数
 * 它守的是**钱**：这一版之前编辑页一次把 8 个字段全发上去，而值来自"打开那一刻"的草稿 ——
 * 你开着编辑页的这段时间里别人改了这条商品的任何字段（或你自己在商品卡上快捷改过价），
 * 一保存就**静默写回旧值**，界面上什么都看不出来。
 *
 * 三处容易写错、都钉在 `ProductFormDiffTest` 里：
 * 1. **金额要按数值比、不能按字符串比**：库里是 `Numeric(14,4)`（`"12.3400"`），
 *    草稿来自去尾零（`"12.34"`）—— 字符串比会让"没改价"被判成改过（每次保存都发一次价）；
 * 2. **单位空串要兜成「件」再比**：不然"没填单位"会被当成改动，把库里的值覆盖成空；
 * 3. **报警阈值 `""` 与 `0` 是同一件事**（`lowStockAlert = 0` 表示不报警）。
 */
internal fun productEdits(baseline: ProductDto, d: ProductDraft): ProductUpdateRequest? {
    val name = d.name.trim()
    val price = d.price.trim()
    val cost = d.cost.trim().ifBlank { "0" }
    val unit = d.unit.trim().ifBlank { DEFAULT_UNIT }
    val category = d.category.trim()
    val alert = d.alert.trim().ifBlank { null }?.toIntOrNull() ?: 0
    val color = d.color.trim().ifBlank { DEFAULT_PRODUCT_NAME_COLOR }

    var dirty = false

    val nameOut = if (name != baseline.name) { dirty = true; name } else null
    val priceOut = if (!moneySame(price, baseline.defaultUnitPrice)) { dirty = true; price } else null
    val costOut = if (!moneySame(cost, baseline.costPrice)) { dirty = true; cost } else null
    val unitOut = if (unit != baseline.unit) { dirty = true; unit } else null
    val categoryOut = if (category != baseline.category) { dirty = true; category } else null
    val activeOut = if (d.active != baseline.isActive) { dirty = true; d.active } else null
    val colorOut = if (color != (baseline.nameColor ?: DEFAULT_PRODUCT_NAME_COLOR)) { dirty = true; color } else null
    val alertOut = if (alert != baseline.lowStockAlert) { dirty = true; alert } else null
    // 图片：只有"点过移除"才写；换成新图走上传端点（不在这条 PATCH 里）
    val imageOut = if (d.imageCleared) { dirty = true; "" } else null

    if (!dirty) return null
    return ProductUpdateRequest(
        name = nameOut,
        defaultUnitPrice = priceOut,
        costPrice = costOut,
        unit = unitOut,
        category = categoryOut,
        isActive = activeOut,
        nameColor = colorOut,
        lowStockAlert = alertOut,
        imageUrl = imageOut,
    )
}

/**
 * 两个金额串是不是**同一个价**。
 *
 * 逐位比字符串是不行的：库里是 `Numeric(14,4)`（`"12.3400"`），草稿来自去尾零（`"12.34"`），
 * 字符串不同、钱完全一样 —— 那会让每次"没改价"的保存都被判成改过。
 * 用 `BigDecimal.compareTo` 比（**不用 Double**：`util/Money.kt` 顶上写着"算钱不许用 Double"）。
 */
internal fun moneySame(a: String, b: String?): Boolean {
    val x = a.trim().ifBlank { "0" }
    val y = (b ?: "0").trim().ifBlank { "0" }
    val bx = x.toBigDecimalOrNull() ?: return x == y
    val by = y.toBigDecimalOrNull() ?: return x == y
    return bx.compareTo(by) == 0
}
