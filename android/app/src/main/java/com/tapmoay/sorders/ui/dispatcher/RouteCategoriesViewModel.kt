package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.RouteCategoryDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.moveItemTo
import com.tapmoay.sorders.ui.common.submittableIds
import kotlinx.coroutines.launch
/**
 * 线路分类管理（2026-10-04，**每个人自己那一份**：货主 / 批发商 / 派单员各管各的）。
 *
 * ## 为什么照抄地点分组那一套
 * 用户 2026-10-04 原话：「**干脆给线路联系人以及地点，这3个的界面玩个框了框的位置加一个分类显示**…
 * 可以去参考账本管理的那些代码」—— 地点与联系人早有名册（`place_categories` / `contact_categories`），
 * **线路这一档是这天新加的**：此前 `shipper_addresses` 连 `category` 列都没有（迁移 013 才补上）。
 * 所以这里与 `PlaceCategoriesViewModel` / `ContactCategoriesViewModel` 是**同一台状态机**
 * （顺序整份提交、改名级联、删之前挡一道）：差别只有级联目标 —— 那两档挂的是地点
 * （`shipper_locations.category`）与联系人（`shipper_contacts.category`），这边挂的是线路
 * （`shipper_addresses.category`）。
 *
 * ⚠️ 为什么不做成"一份代码两个泛型"：两边的 DTO、repo 方法、文案、条数名字都不同，
 *    而泛型化会把仓库里其余五张名册（地点/商品/开销/运费/模板）排除在外，只统一了这两张 ——
 *    真正共用的那部分（搬运 `moveItemTo`、提交口径 `submittableIds`）本来就已经在 `ui/common/CategoryRoster.kt` 里了。
 *
 * ## 顺序为什么是"整份提交"
 * 后端 `/route-categories/reorder` 要的是**完整顺序**（`ids[0]` 排最前）：
 * 只传一部分的话，"没提到的那些该排哪儿"没有答案 —— 后端会直接 400。
 */
class RouteCategoriesViewModel(private val container: AppContainer) : ViewModel() {

    var rows by mutableStateOf<List<RouteCategoryDto>>(emptyList())
        private set
    var loading by mutableStateOf(false)
        private set
    var loadError by mutableStateOf<String?>(null)
        private set
    /** 动作失败（重名、还有线路挂着不让删…）：提示条弹一次。 */
    var error by mutableStateOf<String?>(null)
    var actionResult by mutableStateOf<String?>(null)
    var acting by mutableStateOf(false)
        private set

    var draftName by mutableStateOf("")

    var renaming by mutableStateOf<RouteCategoryDto?>(null)
    var renameText by mutableStateOf("")
    var deleting by mutableStateOf<RouteCategoryDto?>(null)

    init { load() }

    fun load() {
        loading = rows.isEmpty()
        loadError = null
        viewModelScope.launch {
            try {
                rows = container.repo.routeCategories()
            } catch (e: Exception) {
                loadError = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun create() {
        val name = draftName.trim()
        if (name.isEmpty()) return
        acting = true
        error = null
        viewModelScope.launch {
            try {
                container.repo.createRouteCategory(name)
                actionResult = "已新建分类：" + name
                draftName = ""
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    /**
     * 排到第几位（1 起）—— 与「商品分类管理」「地点分组」**同一个语义**（用户要求直接复用那套）。
     *
     * ⚠️ 搬运交给 `moveItemTo` 那一份纯函数，不在这里再写一遍 `add/removeAt` ——
     *    那是最容易差一格的地方，而它有单测。
     */
    fun moveTo(id: Long, position: Int) {
        val next = moveItemTo(rows, { it.id }, id, position)
        if (next === rows) return  // 没变化（同一位置）：不发请求
        // ⚠️ 先本地换位、再发请求（2026-10-06 改）：拖动时行要**跟着手指走** ——
        //    等一个往返再换位的话，手指早就离开那一格了。响应回来时若没有更新的提交，再以服务端那份为准。
        rows = next
        submit(next)
    }

    /**
     * 长按拖动：把某一行往前/往后挪 `steps` 格（正数往后）—— 与商品分类管理页那套同一语义。
     *
     * 「拖了多少像素 = 几格」的换算在 `ui/dispatcher/ProductCategoriesViewModel.kt` 的
     * `dragSteps()` 里（那一页与这三档共用同一个函数）；这里只负责"挪几格"。
     */
    fun moveBy(id: Long, steps: Int) {
        if (steps == 0) return
        val idx = rows.indexOfFirst { it.id == id }
        if (idx < 0) return
        moveTo(id, idx + 1 + steps)  // `moveTo` 的位次是 1 起
    }

    /** 提交编号：拖动时会连着发几次整份顺序，晚到的旧响应不许把新顺序覆盖回去。 */
    private var submitSeq = 0

    private fun submit(next: List<RouteCategoryDto>) {
        // 只提交名册里的行（规则与另外四张名册同一处：`ui/common/CategoryRoster.kt`）
        val ids = submittableIds(next) { it.id }
        val seq = ++submitSeq
        acting = true
        error = null
        viewModelScope.launch {
            try {
                val fresh = container.repo.reorderRouteCategories(ids)
                if (seq == submitSeq) rows = fresh
            } catch (e: Exception) {
                error = toApiException(e).message
                if (seq == submitSeq) load()
            } finally {
                acting = false
            }
        }
    }

    fun openRename(c: RouteCategoryDto) {
        renaming = c
        renameText = c.name
    }

    fun rename() {
        val target = renaming ?: return
        val name = renameText.trim()
        if (name.isEmpty() || name == target.name) {
            renaming = null
            return
        }
        acting = true
        error = null
        viewModelScope.launch {
            try {
                container.repo.updateRouteCategory(target.id, name = name)
                actionResult = "已改名为：" + name
                renaming = null
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    fun confirmDelete() {
        val target = deleting ?: return
        acting = true
        error = null
        viewModelScope.launch {
            try {
                container.repo.deleteRouteCategory(target.id)
                actionResult = "已删除分类：" + target.name
                deleting = null
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
                deleting = null
            } finally {
                acting = false
            }
        }
    }
}
