package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.ContactCategoryDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.moveItemTo
import com.tapmoay.sorders.ui.common.submittableIds
import kotlinx.coroutines.launch
/**
 * 联系人分类管理（FEAT-0007，**每个人自己那一份**：货主 / 批发商 / 派单员各管各的）。
 *
 * ## 为什么照抄地点分组那一套
 * 用户原话：「我们的联系人好像是可以做分类的吧，同样以**左边为分类右边为列表**的形式展示出来。
 * 如果没有分类功能的话，则添加新的分类功能」，以及「**对分类管理的话啊，就像我们的复用地点管理一样**」。
 * 所以这里与 `PlaceCategoriesViewModel` 是**同一台状态机**（顺序整份提交、改名级联、删之前挡一道）：
 * 差别只有级联目标 —— 那边挂的是地点（`shipper_locations.category`），这边挂的是联系人（`shipper_contacts.category`）。
 *
 * ⚠️ 为什么不做成"一份代码两个泛型"：两边的 DTO、repo 方法、文案、条数名字都不同，
 *    而泛型化会把仓库里其余四张名册（商品/开销/运费/模板）排除在外，只统一了这两张 ——
 *    真正共用的那部分（搬运 `moveItemTo`、提交口径 `submittableIds`）本来就已经在 `ui/common/CategoryRoster.kt` 里了。
 *
 * ## 顺序为什么是"整份提交"
 * 后端 `/contact-categories/reorder` 要的是**完整顺序**（`ids[0]` 排最前）：
 * 只传一部分的话，"没提到的那些该排哪儿"没有答案 —— 后端会直接 400。
 */
class ContactCategoriesViewModel(private val container: AppContainer) : ViewModel() {

    var rows by mutableStateOf<List<ContactCategoryDto>>(emptyList())
        private set
    var loading by mutableStateOf(false)
        private set
    var loadError by mutableStateOf<String?>(null)
        private set
    /** 动作失败（重名、还有联系人挂着不让删…）：提示条弹一次。 */
    var error by mutableStateOf<String?>(null)
    var actionResult by mutableStateOf<String?>(null)
    var acting by mutableStateOf(false)
        private set

    var draftName by mutableStateOf("")

    var renaming by mutableStateOf<ContactCategoryDto?>(null)
    var renameText by mutableStateOf("")
    var deleting by mutableStateOf<ContactCategoryDto?>(null)

    init { load() }

    fun load() {
        loading = rows.isEmpty()
        loadError = null
        viewModelScope.launch {
            try {
                rows = container.repo.contactCategories()
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
                container.repo.createContactCategory(name)
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

    /** 上/下移一格：**提交整份顺序**（见类注释）。 */
    fun move(index: Int, delta: Int) {
        val target = index + delta
        if (index !in rows.indices || target !in rows.indices) return
        val next = rows.toMutableList()
        val tmp = next[index]
        next[index] = next[target]
        next[target] = tmp
        submit(next)
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
        submit(next)
    }

    private fun submit(next: List<ContactCategoryDto>) {
        // 只提交名册里的行（规则与另外四张名册同一处：`ui/common/CategoryRoster.kt`）
        val ids = submittableIds(next) { it.id }
        acting = true
        error = null
        viewModelScope.launch {
            try {
                rows = container.repo.reorderContactCategories(ids)
            } catch (e: Exception) {
                error = toApiException(e).message
                load()
            } finally {
                acting = false
            }
        }
    }

    fun openRename(c: ContactCategoryDto) {
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
                container.repo.updateContactCategory(target.id, name = name)
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
                container.repo.deleteContactCategory(target.id)
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
