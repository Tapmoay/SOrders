package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.AddressDto
import com.tapmoay.sorders.data.remote.dto.FreightCategoryDto
import com.tapmoay.sorders.data.remote.dto.FreightTemplateDto
import com.tapmoay.sorders.data.remote.dto.FreightTemplateRequest
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.launch

/** 分类栏第一格（与商品/开销/库存那几页同一个词）。 */
internal const val FREIGHT_TAB_ALL = "全部"
/** 没有挂任何分类的价目（老数据、或还没来得及归类）。 */
internal const val FREIGHT_TAB_NONE = "未分类"

/**
 * 这条价目在 [tab] 这一格下出不出现。
 *
 * ⚠️ 与商品那套**不一样**：一条价目可以挂**多个**分类（用户 2026-09-21：「一个模板可以有多个分类」），
 * 所以它是"在哪几类下都出现"，而不是"属于某一类"。这条规则**只有这一处实现**（有单测）——
 * 各页各写一遍的话，同一条价目在分类栏里会出现/消失得不一致。
 */
internal fun underFreightTab(t: FreightTemplateDto, tab: String): Boolean = when (tab) {
    FREIGHT_TAB_ALL -> true
    FREIGHT_TAB_NONE -> t.categoryNames.isEmpty()
    else -> t.categoryNames.contains(tab)
}

class FreightTemplatesViewModel(private val container: AppContainer) : ViewModel() {

    var templates by mutableStateOf<List<FreightTemplateDto>>(emptyList())
        private set
    var categories by mutableStateOf<List<FreightCategoryDto>>(emptyList())
        private set
    /** 线路库（「地址与联系人 → 常用线路」）：价目按**路线**定价，所以表单里是选不是打。 */
    var routes by mutableStateOf<List<AddressDto>>(emptyList())
        private set

    var loading by mutableStateOf(true)
        private set
    var error by mutableStateOf<String?>(null)
    var acting by mutableStateOf(false)
        private set
    var actionResult by mutableStateOf<String?>(null)

    /** 左边选中哪一格（`全部` / 某个分类名 / `未分类`）。 */
    var tab by mutableStateOf(FREIGHT_TAB_ALL)

    // ---- 新建/编辑草稿 ----
    /** 新建 / 编辑那条**底部抽屉**开着没有（2026-09-22 从居中弹窗改成抽屉）。 */
    var showSheet by mutableStateOf(false)
    var editing by mutableStateOf<FreightTemplateDto?>(null)
    var draftName by mutableStateOf("")
    var draftRouteId by mutableStateOf<Long?>(null)
    var draftPriceName by mutableStateOf("")
    var draftFee by mutableStateOf("")
    var draftRemark by mutableStateOf("")
    var draftCategoryIds by mutableStateOf<Set<Long>>(emptySet())

    /**
     * 抽屉里那一行红字（校验没过，或保存被服务端退回）。
     *
     * ⚠️ 刻意**不**写进页面级的 [error]：那个走的是**抽屉背后**的 snackbar，
     * 而抽屉是另一个窗口、正好把它盖住 —— 表现就是"点了保存**没有任何反应**"。
     * 同一个坑 2026-09-21 在「新增地点」上踩过（见 `Components.kt::FormErrorLine` 的注释），
     * 规矩是：**表单的错误必须和表单同生共死**（画在抽屉里、[openCreate]/[openEdit] 时清掉）。
     */
    var formError by mutableStateOf<String?>(null)

    var deleteTarget by mutableStateOf<FreightTemplateDto?>(null)

    init {
        load()
        viewModelScope.launch { runCatching { categories = container.repo.freightCategories() } }
        viewModelScope.launch { runCatching { routes = container.repo.addresses() } }
    }

    fun load() {
        viewModelScope.launch {
            try {
                templates = container.repo.freightTemplates()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    /** 分类栏的格子：**由名册算出来**（不是手写枚举）—— 派单员建一个分类，这里立刻多一格。 */
    fun tabs(): List<String> {
        val out = mutableListOf(FREIGHT_TAB_ALL)
        out += categories.map { it.name }
        // 「未分类」只在真有价目没归类时才出现（空页签是纯噪音）
        if (templates.any { it.categoryNames.isEmpty() }) out += FREIGHT_TAB_NONE
        return out
    }

    fun visible(): List<FreightTemplateDto> = templates.filter { underFreightTab(it, tab) }

    /** 线路在下拉里怎么显示（起点 → 终点；没有起点就只显示终点）。 */
    fun routeLabel(a: AddressDto): String {
        val from = (a.originAddress ?: "").trim()
        val to = a.detailAddress.trim()
        return if (from.isBlank()) to else from + " → " + to
    }

    fun routeLabelOf(t: FreightTemplateDto): String {
        val from = t.fromPlace.trim()
        val to = t.toPlace.trim()
        return when {
            from.isBlank() && to.isBlank() -> "（还没选线路）"
            from.isBlank() -> to
            else -> from + " → " + to
        }
    }

    fun openCreate() {
        editing = null
        draftName = ""
        draftRouteId = null
        draftPriceName = ""
        draftFee = ""
        draftRemark = ""
        // 在某一类下点「新建」时，默认就挂这一类（用户十有八九是在给这一类加价目）
        draftCategoryIds = categories.firstOrNull { it.name == tab }?.let { setOf(it.id) } ?: emptySet()
        formError = null
        showSheet = true
    }

    fun openEdit(t: FreightTemplateDto) {
        editing = t
        draftName = t.name
        draftRouteId = t.routeId
        draftPriceName = t.priceName
        draftFee = t.fee
        draftRemark = t.remark
        draftCategoryIds = t.categoryIds.toSet()
        formError = null
        showSheet = true
    }

    fun toggleCategory(id: Long) {
        draftCategoryIds = if (id in draftCategoryIds) draftCategoryIds - id else draftCategoryIds + id
    }


    fun save() {
        if (draftName.trim().isEmpty()) {
            formError = "请填写价目名称（比如「蔬菜 · 城南 → 城北」）"
            return
        }
        if (draftRouteId == null) {
            formError = "请选一条线路（价目是按路线定价的）—— 线路在「地址与联系人」里维护"
            return
        }
        acting = true
        formError = null
        viewModelScope.launch {
            try {
                val body = FreightTemplateRequest(
                    name = draftName.trim(),
                    routeId = draftRouteId,
                    priceName = draftPriceName.trim(),
                    // ⛔ 不再发 vehicle_type / driver_ids：价目不匹配车型也不匹配司机（归规则勾选）
                    fee = draftFee.trim().ifBlank { "0" },
                    remark = draftRemark.trim(),
                    categoryIds = draftCategoryIds.toList(),
                )
                val cur = editing
                if (cur == null) container.repo.createFreightTemplate(body)
                else container.repo.updateFreightTemplate(cur.id, body)
                actionResult = if (cur == null) "价目已创建" else "价目已更新"
                showSheet = false
                load()
            } catch (e: Exception) {
                // 保存失败 → **抽屉里**那一行红字（不是页面级 error：那会走抽屉背后的 snackbar）
                formError = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    fun requestDelete(t: FreightTemplateDto) {
        deleteTarget = t
    }

    fun confirmDelete() {
        val t = deleteTarget ?: return
        acting = true
        viewModelScope.launch {
            try {
                container.repo.deleteFreightTemplate(t.id)
                actionResult = "价目已删除（可在审计里恢复）"
                deleteTarget = null
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }
}
