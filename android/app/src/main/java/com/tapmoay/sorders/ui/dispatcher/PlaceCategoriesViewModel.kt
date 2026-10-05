package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.PlaceCategoryDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.moveItemTo
import com.tapmoay.sorders.ui.common.submittableIds
import kotlinx.coroutines.launch
/**
 * 地点分组管理（**每个人自己那一份**：货主和派单员各管各的）。
 *
 * ## 顺序为什么是"整份提交"
 * 后端 `/place-categories/reorder` 要的是**完整顺序**（`ids[0]` 排最前）：
 * 只传一部分的话，"没提到的那些该排哪儿"没有答案。所以 [move] 每次都把
 * **整份 ids** 发上去 —— 上移一格也一样。这比"把某一格 +1/-1"多传几个数字，
 * 但语义是幂等的（重复提交同一份结果相同），并发点两下也不会互相踩。
 */
class PlaceCategoriesViewModel(private val container: AppContainer) : ViewModel() {

    var rows by mutableStateOf<List<PlaceCategoryDto>>(emptyList())
        private set
    var loading by mutableStateOf(false)
        private set
    var loadError by mutableStateOf<String?>(null)
        private set
    /** 动作失败（重名、还有地点挂着不让删…）：提示条弹一次。 */
    var error by mutableStateOf<String?>(null)
    var actionResult by mutableStateOf<String?>(null)
    var acting by mutableStateOf(false)
        private set

    var draftName by mutableStateOf("")

    var renaming by mutableStateOf<PlaceCategoryDto?>(null)
    var renameText by mutableStateOf("")
    var deleting by mutableStateOf<PlaceCategoryDto?>(null)

    init { load() }

    fun load() {
        loading = rows.isEmpty()
        loadError = null
        viewModelScope.launch {
            try {
                rows = container.repo.placeCategories()
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
                container.repo.createPlaceCategory(name)
                actionResult = "已新建分组：" + name
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
     * 排到第几位（1 起）—— 与「商品分类管理」**同一个语义**（用户要求直接复用那套）。
     *
     * ⚠️ 搬运本身交给 `moveItemTo` 那一份纯函数（列表内"抽出来插到第 N 位"，
     *    与商品分类共用同一份），不在这里再写一遍 `add/removeAt` ——
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

    private fun submit(next: List<PlaceCategoryDto>) {
        // 只提交名册里的行（规则与另外三个名册同一处：`ui/common/CategoryRoster.kt`）
        val ids = submittableIds(next) { it.id }
        val seq = ++submitSeq
        acting = true
        error = null
        viewModelScope.launch {
            try {
                val fresh = container.repo.reorderPlaceCategories(ids)
                if (seq == submitSeq) rows = fresh
            } catch (e: Exception) {
                error = toApiException(e).message
                if (seq == submitSeq) load()
            } finally {
                acting = false
            }
        }
    }

    fun openRename(c: PlaceCategoryDto) {
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
                container.repo.updatePlaceCategory(target.id, name = name)
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
                container.repo.deletePlaceCategory(target.id)
                actionResult = "已删除分组：" + target.name
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
