package com.tapmoay.sorders.ui.common

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.launch

/**
 * 「分类名册」页面的**共用内核**：拉名册 → 本地草稿排序 → 提交整份顺序 → 建 / 改名 / 删除。
 *
 * ### 为什么要有它
 * 开销 / 运费 / 商品三页的这套状态机原来**各写了一遍**（每页约 45 行，共 135 行），
 * 而且**已经走散过**：
 *
 * | 走散的地方 | 后果（都不报错） |
 * | --- | --- |
 * | 商品页的「建 / 改名 / 删除」之后**就地重刷**（自己 `clear`/`addAll`/`savedOrder`/`dirty`），另两页走 `load()` | 同一件事两种写法：就地那版**不清 `loadError`** —— 之前加载失败过一次的页面，成功建完一条之后仍然整页停在错误页上，看不到新建的东西 |
 * | `dirty` 的判据、撤销、提交编号三处各写一遍 | 见 [CategoryRoster]（那三条**纯规则**现在也在 `ui/common`，与这里配套） |
 *
 * 现在"这一页是什么"由子类交代（[fetchAll] / [reorder] / [create] / [rename] / [delete] /
 * [idOf] / [nameOf]），"怎么把名册管好"只有这一份。
 *
 * ### ⚠️ 子类必须自己写 `init { load() }`
 * 基类的 `init` **先于**子类属性初始化执行，而 `viewModelScope` 用的是 `Dispatchers.Main.immediate`
 * —— 在 UI 线程上 `launch` 的协程体会**同步**跑到第一个挂起点。基类里调 [load] 就等于在子类
 * 还没准备好时去调 [fetchAll]，所以这一步刻意留给子类（一行，换来的是没有"构造期半成品"）。
 *
 * ### 哪些状态必须保持公开可写
 * [notice] / [error] / [loadError] / [editing] / [deleting] 都是 UI **会写**的
 * （`OneShotSnackbar(onConsumed = { vm.notice = null })`、弹窗的 `onDismiss = { vm.editing = null }`），
 * 所以它们不能收成 `protected set`；[dirty] 相反——只有这里能算，UI 只读。
 */
abstract class CategoryRosterViewModel<T : Any>(
    protected val container: AppContainer,
) : ViewModel() {

    /** 页面上那一列（顺序即展示顺序；[dirty] 时它是**草稿**）。 */
    val categories = mutableStateListOf<T>()

    var loading by mutableStateOf(true)
    var busy by mutableStateOf(false)
    var loadError by mutableStateOf<String?>(null)
    var error by mutableStateOf<String?>(null)

    /** 一次性提示（Snackbar）。UI 消费时会清空它，所以是公开可写的。 */
    var notice by mutableStateOf<String?>(null)

    /** 建 / 改名弹窗：`(id 或 null=新建, 当前名字)`。 */
    var editing by mutableStateOf<Pair<Long?, String>?>(null)

    /** 删除确认弹窗里那一条。 */
    var deleting by mutableStateOf<T?>(null)

    /** 顺序改过没有（页面靠它决定要不要显示「撤销改动 / 保存顺序」）。 */
    var dirty by mutableStateOf(false)
        private set

    private var savedOrder: List<Long> = emptyList()

    // ------------------------------------------------------------ 子类交代的部分

    /** 这一条的主键（三页都是 `id`）。 */
    protected abstract fun idOf(item: T): Long

    /** 这一条的名字（改名弹窗预填、删除提示都用它）。 */
    protected abstract fun nameOf(item: T): String

    /** 拉整份名册。 */
    protected abstract suspend fun fetchAll(): List<T>

    /** 提交**整份**顺序，返回后端认可的新名册（后端可能顺手规范化）。 */
    protected abstract suspend fun reorder(ids: List<Long>): List<T>

    protected abstract suspend fun create(name: String)

    protected abstract suspend fun rename(id: Long, name: String)

    protected abstract suspend fun delete(id: Long)

    /** 改名成功后的提示：默认按"只改了名字"写，**级联改了别处**的页面覆盖它（把连带影响说出来）。 */
    protected open fun renamedNotice(name: String): String = "已改名为「$name」"

    // ------------------------------------------------------------ 读

    fun load() {
        // 已有内容时不闪骨架（刷新而已）；首次进入才是真加载
        loading = categories.isEmpty()
        loadError = null
        viewModelScope.launch {
            try {
                replaceAll(fetchAll())
            } catch (e: Exception) {
                loadError = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    /**
     * 名册换了之后**统一从这里写回**：列表、已保存顺序、草稿标记**三件事一起定**。
     *
     * ⚠️ 别在别处单独动 `categories`/`savedOrder`/`dirty` —— 漏掉其中一件就是
     * 「顺序存完了『未保存』还亮着」那类无声故障（[CategoryRoster] 的文件头有完整清单）。
     */
    private fun replaceAll(list: List<T>) {
        categories.clear()
        categories.addAll(list)
        savedOrder = list.map { idOf(it) }
        dirty = false
    }

    // ------------------------------------------------------------ 草稿排序

    /** 挪到第 [position] 位（**1-based**；0 与越界都夹到两端）。填数字与上下移都走它。 */
    fun moveTo(id: Long, position: Int) {
        val next = moveItemTo(categories, ::idOf, id, position)
        if (next === categories) return // 没变（找不到 / 本来就在那儿）—— 别把状态写一遍
        categories.clear()
        categories.addAll(next)
        dirty = orderChanged(categories, savedOrder, ::idOf)
    }

    /** 按"挪了几格"挪（正数往下）。 */
    fun moveBy(id: Long, steps: Int) {
        val idx = categories.indexOfFirst { idOf(it) == id }
        if (idx < 0) return
        moveTo(id, idx + 1 + steps)
    }

    fun revertOrder() {
        if (savedOrder.isEmpty()) return
        val back = revertedOrder(categories, savedOrder, ::idOf)
        categories.clear()
        categories.addAll(back)
        dirty = false
    }

    fun saveOrder() {
        // ⚠️ 只提交**名册里的**（id > 0）：名册外的合成行（老数据）后端不认识，带上就被整体拒绝
        val ids = submittableIds(categories, ::idOf)
        if (ids.isEmpty()) return
        busy = true
        error = null
        viewModelScope.launch {
            try {
                replaceAll(reorder(ids))
                notice = "顺序已保存"
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                busy = false
            }
        }
    }

    // ------------------------------------------------------------ 建 / 改名 / 删

    fun openCreate() {
        editing = null to ""
    }

    fun openRename(item: T) {
        editing = idOf(item) to nameOf(item)
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
                    create(name)
                    notice = "已新建分类「$name」"
                } else {
                    rename(id, name)
                    notice = renamedNotice(name)
                }
                editing = null
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                busy = false
            }
        }
    }

    fun askDelete(item: T) {
        deleting = item
    }

    fun confirmDelete(item: T) {
        busy = true
        error = null
        viewModelScope.launch {
            try {
                delete(idOf(item))
                deleting = null
                notice = "已删除分类「${nameOf(item)}」"
                load()
            } catch (e: Exception) {
                // 后端会因为"还有东西挂着"而拒绝 —— 那句话带数量，原样给用户看
                error = toApiException(e).message
                deleting = null
            } finally {
                busy = false
            }
        }
    }
}
