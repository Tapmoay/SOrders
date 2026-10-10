package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.submittableIds
import kotlinx.coroutines.launch

/**
 * 名册面板里的一行。
 *
 * 两份新名册（账号 / 车辆）的 DTO 字段同名，只有"挂着几个"那一格叫法不同
 * （`user_count` / `vehicle_count`），所以在 VM 这一层先归一成这一行 ——
 * 面板只写一份（`ui/dispatcher/CategoryRostersPanel.kt`），不抄第二遍。
 */
data class RosterRow(
    val id: Long,
    val name: String,
    val count: Int,
    val sortOrder: Int = 0,
    /**
     * 上层分类（`null` = 大类本身）。**只两级**，后端不让建第三层（2026-10-11 CHG-0112）。
     * 车辆那份名册是平表，这一格永远是 null。
     */
    val parentId: Long? = null,
)

/**
 * 账号分类 / 车辆分类两份名册的**共用内核**（2026-10-05，用户：
 * 「在这个位置也加个分类，默认是显示，全部，同样也是左边侧边栏，
 *   然后左边侧边栏同样也是可以新增分类的」）。
 *
 * 三条规矩与既有的七份名册**一模一样**（后端那边也是同一套）：
 * 1. 改名要级联（后端做），删还有东西挂着的分类会被拒（后端做，界面把话原样显示）；
 * 2. 顺序**整份提交**：`/reorder` 要的是完整顺序，只传一部分后端会 400。
 *    所以上移一格也把整份 ids 发上去 —— 幂等，连点两下不会互相踩；
 * 3. 名册里**没有**的分类名不是错误（老数据、别的入口写进去的），
 *    面板只显示名册有的那些，列表页照样把账号/车辆显示出来。
 *
 * ⛔ 抽屉那几格不显示条数（用户 2026-09-19 的裁定）；[RosterRow.count] 只在
 * 这个管理面板里用 —— 删之前要让人看见影响面。
 */
abstract class RosterViewModel(protected val container: AppContainer) : ViewModel() {

    var rows by mutableStateOf<List<RosterRow>>(emptyList())
        private set
    var loading by mutableStateOf(false)
        private set
    var loadError by mutableStateOf<String?>(null)
        private set
    /** 动作失败（重名、还有东西挂着不让删…）：贴在面板上。 */
    var error by mutableStateOf<String?>(null)
    var actionResult by mutableStateOf<String?>(null)
    var acting by mutableStateOf(false)
        private set

    var draftName by mutableStateOf("")

    /**
     * 「新建」那一格要挂到哪个大类下面（`null` = 建一个大类本身）。
     *
     * 只有**账号分类**有二级（车辆那份是平表，面板上连这个选择器都不画）——
     * 所以它放在共用内核里，由面板按 `parentChoices` 决定要不要显示。
     */
    var draftParentId by mutableStateOf<Long?>(null)
    var renaming by mutableStateOf<RosterRow?>(null)
    var renameText by mutableStateOf("")
    var deleting by mutableStateOf<RosterRow?>(null)

    /** 刚删掉的那一格（撤销要用它的名字与位置）。名册没有回收站，撤销 = 重建一格。 */
    var undoRow by mutableStateOf<RosterRow?>(null)
        private set

    init { load() }

    protected abstract suspend fun fetch(): List<RosterRow>
    protected abstract suspend fun createRow(name: String, parentId: Long? = null)
    protected abstract suspend fun renameRow(id: Long, name: String)
    protected abstract suspend fun deleteRow(id: Long)
    protected abstract suspend fun reorderRows(ids: List<Long>): List<RosterRow>

    /** 撤销删除：按原来的名字与位置重建一格（名册是硬删，见 [RosterRow] 上面那段）。 */
    protected abstract suspend fun restoreRow(name: String, sortOrder: Int, parentId: Long? = null)

    fun load() {
        loading = rows.isEmpty()
        loadError = null
        viewModelScope.launch {
            try {
                rows = fetch()
            } catch (e: Exception) {
                loadError = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun create() {
        val name = draftName.trim()
        if (name.isEmpty() || acting) return
        acting = true
        error = null
        viewModelScope.launch {
            try {
                createRow(name, draftParentId)
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

    /** 上 / 下移一格：**提交整份顺序**（见类注释第 2 条）。 */
    fun move(index: Int, delta: Int) {
        val target = index + delta
        if (index !in rows.indices || target !in rows.indices) return
        val next = rows.toMutableList()
        val tmp = next[index]
        next[index] = next[target]
        next[target] = tmp
        submit(next)
    }

    private fun submit(next: List<RosterRow>) {
        acting = true
        error = null
        viewModelScope.launch {
            try {
                // 只把「名册内的行」发上去（id > 0）—— 共用件 submittableIds，
                // ⛔ 不要在这里自己 map 一遍（名册外的合成行会被一起发过去，判据盯着这条）。
                rows = reorderRows(submittableIds(next) { it.id })
            } catch (e: Exception) {
                error = toApiException(e).message
                load()
            } finally {
                acting = false
            }
        }
    }

    fun openRename(row: RosterRow) {
        renaming = row
        renameText = row.name
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
                renameRow(target.id, name)
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
                deleteRow(target.id)
                actionResult = "已删除分类：" + target.name
                // 删掉的那一格留在手边：名册是硬删，撤销只能按原名重建（见 restoreRow）。
                undoRow = target
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

    /**
     * 撤销刚刚那次删除：按原来的名字与位置重建一格。
     *
     * ⚠️ 重建出来的是**新的一行**，编号和原来不一样（名册没有回收站）——
     * 但挂在分类上的账号/车辆不会受影响：后端不允许删还有东西挂着的分类，
     * 能删掉的一定是空分类。
     */
    fun undoDelete() {
        val gone = undoRow ?: return
        if (acting) return
        acting = true
        error = null
        viewModelScope.launch {
            try {
                restoreRow(gone.name, gone.sortOrder)
                actionResult = "已还原分类：" + gone.name
                undoRow = null
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    fun dismissUndo() {
        undoRow = null
    }

    /** 表单里「＋ 新建分类…」用：建完把新名字回调出去，直接选中它。 */
    fun createThen(name: String, onDone: (String) -> Unit) {
        val clean = name.trim()
        if (clean.isEmpty() || acting) return
        acting = true
        error = null
        viewModelScope.launch {
            try {
                createRow(clean, draftParentId)
                load()
                onDone(clean)
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }
}

/** 账号分类名册（**全店一份**：账户 / 司机 / 货主 / 批发商四个名册页共用）。 */
class UserCategoriesViewModel(container: AppContainer) : RosterViewModel(container) {
    override suspend fun fetch(): List<RosterRow> =
        container.repo.userCategories().map {
            RosterRow(it.id, it.name, it.userCount, it.sortOrder, it.parentId)
        }

    override suspend fun createRow(name: String, parentId: Long?) {
        container.repo.createUserCategory(name, parentId = parentId)
    }

    override suspend fun renameRow(id: Long, name: String) {
        container.repo.updateUserCategory(id, name = name)
    }

    override suspend fun deleteRow(id: Long) {
        container.repo.deleteUserCategory(id)
    }

    override suspend fun restoreRow(name: String, sortOrder: Int, parentId: Long?) {
        // 名册没有回收站：撤销 = 按原名重建一格（新编号）。
        // **归属也要带回来**：删掉的是一个子类时，撤销必须还建在同一个大类下面
        // （否则它会静默变成一个与原来无关的大类）。
        container.repo.restoreUserCategory(name, sortOrder, parentId)
    }

    override suspend fun reorderRows(ids: List<Long>): List<RosterRow> =
        container.repo.reorderUserCategories(ids).map {
            RosterRow(it.id, it.name, it.userCount, it.sortOrder, it.parentId)
        }
}

/** 车辆分类名册（**全店一份**：车辆管理页）。 */
class VehicleCategoriesViewModel(container: AppContainer) : RosterViewModel(container) {
    override suspend fun fetch(): List<RosterRow> =
        container.repo.vehicleCategories().map { RosterRow(it.id, it.name, it.vehicleCount, it.sortOrder) }

    /** 车辆分类是**平表**（没有两级）：`parentId` 收下但不用 —— 见 [RosterRow.parentId]。 */
    override suspend fun createRow(name: String, parentId: Long?) {
        container.repo.createVehicleCategory(name)
    }

    override suspend fun renameRow(id: Long, name: String) {
        container.repo.updateVehicleCategory(id, name = name)
    }

    override suspend fun deleteRow(id: Long) {
        container.repo.deleteVehicleCategory(id)
    }

    override suspend fun restoreRow(name: String, sortOrder: Int, parentId: Long?) {
        // 名册没有回收站：撤销 = 按原名重建一格（新编号）。
        container.repo.restoreVehicleCategory(name, sortOrder)
    }

    override suspend fun reorderRows(ids: List<Long>): List<RosterRow> =
        container.repo.reorderVehicleCategories(ids).map { RosterRow(it.id, it.name, it.vehicleCount, it.sortOrder) }
}
