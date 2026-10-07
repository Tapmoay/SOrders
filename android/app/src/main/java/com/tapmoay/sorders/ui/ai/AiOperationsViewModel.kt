package com.tapmoay.sorders.ui.ai

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.AiOperationDto
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

/**
 * 「AI 操作流水」页（台账 L-52 / CHG-0082）。
 *
 * ## 为什么这一页要有自己的 ViewModel
 * 用户要的是"**翻得到**"：往前翻页、切页回来、只看失败 —— 这三件事都必须**在离开页面之后还留着**
 * （本项目的 ViewModel 是 Activity 级的，切页不销毁；见 `ReportCenterViewModel` 里同一笔老账）。
 *
 * ## 三条口径
 * 1. **「只看失败」走服务端**（`ok=false`），不在本地过滤：本地把这一页的成功行滤掉之后，
 *    "还有更早的"这个判断跟着失真 —— 界面会说"没有了"，而库里还有一堆失败记录没取。
 * 2. **截断位必须说出来**：[truncated] / [limit] 跟着行一起回来（`X-Truncated` / `X-Result-Limit`），
 *    页面照实显示，绝不把"看得见的这几十条"当成全部。
 * 3. **翻页是追加不是重来**：[loadMore] 用 `skip = 已加载条数` 接在后面；只有换筛选条件才从头来。
 */
class AiOperationsViewModel(private val container: AppContainer) : ViewModel() {

    var rows by mutableStateOf<List<AiOperationDto>>(emptyList())
        private set
    var loading by mutableStateOf(false)
        private set
    var loadingMore by mutableStateOf(false)
        private set
    /** 这一页的数据没加载出来时的整页错误（表单/翻页的小错不走这里）。 */
    var error by mutableStateOf<String?>(null)
        private set
    /** 只看失败的（服务端 `ok=false`）。 */
    var onlyFailed by mutableStateOf(false)
        private set
    /** 最近一页后端说"还有更早的"（响应头 `X-Truncated`）。 */
    var truncated by mutableStateOf(false)
        private set
    /** 后端这一页的上限（响应头 `X-Result-Limit`）；读不到时是 null，截断提示就不说条数。 */
    var limit by mutableStateOf<Int?>(null)
        private set

    /** 还有更早的没取（且当前没有请求在飞）。 */
    val canLoadMore: Boolean get() = truncated && !loading && !loadingMore

    /** 取第一页（切筛选条件、点刷新、重试都走它）。 */
    fun load() {
        if (loading) return
        loading = true
        error = null
        viewModelScope.launch {
            try {
                val page = container.repo.aiOperationsPage(limit = PAGE, onlyFailed = onlyFailed)
                rows = page.rows
                truncated = page.meta.hasMore
                limit = page.meta.limit
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    /**
     * 切换「全部 / 只看失败」——**清空再取**，不在旧 rows 上过滤（理由见类注释第 1 条）。
     *
     * ⛔ 名字不能叫 `setOnlyFailed`：`var onlyFailed` 的 setter 编译出来就是 `setOnlyFailed(Z)V`，
     * 同名函数＝JVM 签名撞车（2026-10-08 编译期实测报 Platform declaration clash）。
     */
    fun applyOnlyFailed(value: Boolean) {
        if (onlyFailed == value) return
        onlyFailed = value
        rows = emptyList()
        truncated = false
        limit = null
        load()
    }

    /** 往前翻一页（接在已加载的后面）。 */
    fun loadMore() {
        if (!canLoadMore) return
        loadingMore = true
        viewModelScope.launch {
            try {
                val page = container.repo.aiOperationsPage(
                    limit = PAGE,
                    skip = rows.size,
                    onlyFailed = onlyFailed,
                )
                // 翻页期间可能又来了新行（新行在前，使 skip 窗口整体后移）⇒ 同一 id 会重复出现，
                // 而 LazyColumn 的 key 撞了会直接崩，所以按 id 去重后再追加。
                val seen = rows.map { it.id }.toHashSet()
                rows = rows + page.rows.filter { it.id !in seen }
                truncated = page.meta.hasMore
                limit = page.meta.limit
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loadingMore = false
            }
        }
    }

    private companion object {
        /** 一页 60 条（后端上限 1000）：一屏约 5 条，够滚十几屏，再多就是让用户等网络。 */
        const val PAGE = 60
    }
}
