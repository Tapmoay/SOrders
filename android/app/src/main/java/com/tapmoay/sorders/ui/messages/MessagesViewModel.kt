package com.tapmoay.sorders.ui.messages

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.NotificationDto
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.launch

class MessagesViewModel(private val container: AppContainer) : ViewModel() {

    var messages by mutableStateOf<List<NotificationDto>>(emptyList())
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    val unreadCount get() = container.realtimeHub.unreadCount

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
        viewModelScope.launch {
            try {
                messages = container.repo.notifications(limit = 100)
            } catch (e: Exception) {
                if (!silent) error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun markRead(m: NotificationDto) {
        if (m.readAt != null) return
        viewModelScope.launch {
            try {
                val updated = container.repo.markRead(m.id)
                messages = messages.map { if (it.id == m.id) updated else it }
                container.realtimeHub.syncUnreadFromApi()
            } catch (_: Exception) {
            }
        }
    }

    fun markAllRead() {
        viewModelScope.launch {
            try {
                container.repo.readAll()
                messages = messages.map { it.copy(readAt = it.readAt ?: "now") }
                container.realtimeHub.syncUnreadFromApi()
            } catch (_: Exception) {
            }
        }
    }

    fun delete(m: NotificationDto) {
        viewModelScope.launch {
            try {
                container.api.notificationApi.delete(m.id)
                messages = messages.filter { it.id != m.id }
            } catch (_: Exception) {
            }
        }
    }
}
