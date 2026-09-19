package com.tapmoay.sorders.ui.messages

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.NotificationBatchDeleteRequest
import com.tapmoay.sorders.data.remote.dto.NotificationDto
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.launch
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonPrimitive

/**
 * 消息中心。
 *
 * ### 一条纪律：**服务器说什么，界面就显示什么**（v3.32 修）
 * 以前增删改之后直接在本地列表上做手脚（`messages = messages.filter { … }` / `= emptyList()`），
 * 服务器到底删没删、删了几条**完全不看**。这个写法在「列表里混着不属于自己的消息」时
 * 会变成一个**看起来成功、重启后又回来**的假象——用户报的就是这个：
 *
 * > 点了「清空」→ 界面空了 → 退出重进 → 消息全回来了。
 *
 * 根因有两层，两层都已修：
 * 1. **后端**：派单员不带 `recipient_id` 查列表时收件人过滤写漏了（`else` 挂在了内层 if 上），
 *    列表返回**所有人的消息**，而「清空」只删自己的 → 别人的那些永远删不掉（见 `notifications.py`）。
 * 2. **客户端**（本文件）：本地乐观置空，把"服务器没删干净"整件事遮住了。
 *
 * 现在每一次改动都**以服务器回包为准重新拉一次列表**：拉回来的就是真相，
 * 拉不回来（失败）也要回到真相并把人话错误显示出来，绝不停在一个骗人的界面上。
 */
class MessagesViewModel(private val container: AppContainer) : ViewModel() {

    var messages by mutableStateOf<List<NotificationDto>>(emptyList())
        private set
    var loading by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    /**
     * 服务器上**还有更早的消息**（响应头 `X-Truncated: 1`，2026-09-19 审计 R14-8 补）。
     *
     * 为什么必须让界面知道：这条接口原来是一条硬 `.limit(200)`，没有分页、也不回报截断 ——
     * 于是第 201 条以前的旧消息在 App 里**一个入口都没有**（里面还有「账本导出完成」这种
     * payload 里带唯一下载链接的通知），用户以为消息中心就是全部。
     */
    var hasMore by mutableStateOf(false)
        private set
    var loadingMore by mutableStateOf(false)
        private set

    /** 一次性提示（界面用 Snackbar 显示后置回 null）。成功/失败都用它说人话。 */
    var notice by mutableStateOf<String?>(null)

    /** 多选模式：true=长按进入批量删除；可为空集合 */
    var selectionMode by mutableStateOf(false)
        private set
    var selectedIds by mutableStateOf<Set<Long>>(emptySet())
        private set
    val unreadCount get() = container.realtimeHub.unreadCount

    /** 正在提交（清空/批量删）：界面据此禁用按钮，防重复点两次删两遍。 */
    var busy by mutableStateOf(false)
        private set

    init {
        load()
        // 新消息到达时增量刷新
        viewModelScope.launch {
            container.realtimeHub.newMessages.collect { load(silent = true) }
        }
    }

    fun load(silent: Boolean = false) {
        if (!silent) loading = messages.isEmpty()
        error = null
        viewModelScope.launch { fetch(silent) }
    }

    /**
     * 加载更早的一页（「加载更多」）。
     *
     * 游标是**当前列表里最后一条的 id**（后端按 id 倒序 = 时间倒序，只回 id 小于它的）。
     * 两种翻页写法里选了游标而不是 offset：offset 在"翻页过程中来了新消息"时
     * 会把同一条重复显示或整条跳过（消息是**不断新增**的表，这正是 offset 最不擅长的场景）。
     */
    fun loadMore() {
        if (loadingMore || !hasMore || messages.isEmpty()) return
        viewModelScope.launch {
            loadingMore = true
            try {
                val page = container.repo.notificationsPage(limit = PAGE_SIZE, beforeId = messages.last().id)
                val known = messages.map { it.id }.toSet()
                // 去重后追加：服务端游标已经排除了边界重复，但"翻页期间消息被删/新增"时仍可能撞上
                messages = messages + page.rows.filter { it.id !in known }
                hasMore = page.hasMore
            } catch (e: Exception) {
                notice = toApiException(e).message ?: "加载更早的消息失败"
            } finally {
                loadingMore = false
            }
        }
    }

    /** 真正拉一次列表；[silent] 时不动 loading（用于改动后的静默对齐）。 */
    private suspend fun fetch(silent: Boolean) {
        try {
            val page = container.repo.notificationsPage(limit = PAGE_SIZE)
            messages = page.rows
            hasMore = page.hasMore
        } catch (e: Exception) {
            if (!silent) error = toApiException(e).message
        } finally {
            loading = false
        }
    }

    fun markRead(m: NotificationDto) {
        if (m.readAt != null) return
        viewModelScope.launch {
            try {
                container.repo.markRead(m.id)
                container.realtimeHub.syncUnreadFromApi()
            } catch (e: Exception) {
                // 以前这里是空的 catch —— 点别人的消息会 404，界面上却毫无反馈
                notice = toApiException(e).message ?: "这条消息没能标记已读"
            }
            // 无论成败都回到服务器真相：成功是因为 read_at 以服务器为准，
            // 失败是因为本地那份"已读"是假的。
            fetch(silent = true)
        }
    }

    fun markAllRead() {
        if (busy) return
        viewModelScope.launch {
            busy = true
            try {
                // 用**服务端回报的条数**，不要用本地列表数出来的那个。
                // 原因：「已把 N 条标为已读」是一句**事实陈述**，而本地列表只有最近 100 条、
                // 还可能因为红点没同步而显示 0——按本地数说就会出现"明明标了 3 条，它说没有未读"。
                // 端点的返回体是 `{"updated": n}`（见后端 notifications.py 的 mark_all_read）。
                val n = container.repo.readAll()["updated"]?.jsonPrimitive?.intOrNull
                container.realtimeHub.syncUnreadFromApi()
                fetch(silent = true)
                notice = when {
                    // 端点没回这个数就**别编一个**，说结果不说数字
                    n == null -> "已全部标为已读"
                    n == 0 -> "没有未读消息"
                    else -> "已把 $n 条未读标为已读"
                }
            } catch (e: Exception) {
                notice = toApiException(e).message ?: "标记已读失败"
                fetch(silent = true)
            } finally {
                busy = false
            }
        }
    }

    // ---------- 删除（单条 / 批量 / 清空） ----------

    fun delete(m: NotificationDto) {
        if (busy) return
        viewModelScope.launch {
            busy = true
            try {
                container.api.notificationApi.delete(m.id)
                container.realtimeHub.syncUnreadFromApi()
                fetch(silent = true)
            } catch (e: Exception) {
                notice = toApiException(e).message ?: "删除失败"
                fetch(silent = true)
            } finally {
                busy = false
            }
        }
    }

    /** 进入多选模式：选中该条 */
    fun enterSelection(id: Long) {
        selectionMode = true
        selectedIds = setOf(id)
    }

    fun toggleSelect(id: Long) {
        selectedIds = if (id in selectedIds) selectedIds - id else selectedIds + id
        if (selectedIds.isEmpty()) selectionMode = false
    }

    fun exitSelection() {
        selectionMode = false
        selectedIds = emptySet()
    }

    /** 批量删除勾选消息 */
    fun deleteSelected() {
        val ids = selectedIds.toList()
        if (ids.isEmpty() || busy) return
        viewModelScope.launch {
            busy = true
            try {
                val r = container.api.notificationApi.batchDelete(
                    NotificationBatchDeleteRequest(ids = ids),
                )
                container.realtimeHub.syncUnreadFromApi()
                fetch(silent = true)
                // 回包里的条数就是真的删掉了几条——比"确定删了 N 条"诚实
                // （列表里若混着不属于自己的消息，后端只会删掉自己的那些）
                notice = if (r.deleted < ids.size) {
                    "已删除 ${r.deleted} 条（选中的 ${ids.size} 条里有 ${ids.size - r.deleted} 条不属于当前账户）"
                } else {
                    "已删除 ${r.deleted} 条消息"
                }
            } catch (e: Exception) {
                notice = toApiException(e).message ?: "删除失败"
                fetch(silent = true)
            } finally {
                busy = false
                exitSelection()
            }
        }
    }

    /** 一键清空全部消息 */
    fun clearAll() {
        if (busy) return
        viewModelScope.launch {
            busy = true
            try {
                val r = container.api.notificationApi.batchDelete(
                    NotificationBatchDeleteRequest(all = true),
                )
                container.realtimeHub.syncUnreadFromApi()
                // ⚠️ 这里**不能**写 `messages = emptyList()`：
                // 那正是"清空成功、重启又回来"的来源。列表重新拉一次，剩多少就显示多少。
                fetch(silent = true)
                notice = when {
                    r.deleted == 0 -> "没有可清空的消息"
                    messages.isEmpty() -> "已清空全部消息（${r.deleted} 条）"
                    // 还有剩 = 服务器上还有这次没删掉的，如实说出来，别假装清空了
                    else -> "已删除 ${r.deleted} 条，仍有 ${messages.size} 条未清空"
                }
            } catch (e: Exception) {
                notice = toApiException(e).message ?: "清空失败"
                fetch(silent = true)
            } finally {
                busy = false
                exitSelection()
            }
        }
    }
}

/**
 * 一页多少条。
 *
 * 100 而不是 200：后端一次最多给 200，但**首屏**只要填满一屏多一点就够，
 * 剩下的靠「加载更多」按需取 —— 一个 2336 条消息的账号首屏就应该快。
 */
private const val PAGE_SIZE = 100
