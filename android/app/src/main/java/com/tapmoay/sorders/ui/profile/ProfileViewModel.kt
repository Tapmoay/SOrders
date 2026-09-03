package com.tapmoay.sorders.ui.profile

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.ApiClient
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.UserDto
import kotlinx.coroutines.launch

class ProfileViewModel(private val container: AppContainer) : ViewModel() {

    var user by mutableStateOf<UserDto?>(null)
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)

    init {
        loadMe()
    }

    fun loadMe() {
        loading = true
        error = null
        viewModelScope.launch {
            try {
                val me = container.api.userApi.me()
                user = me
                // 同步姓名到会话存储
                container.tokenStore.save(
                    com.tapmoay.sorders.core.Session(
                        token = container.tokenStore.cachedToken() ?: return@launch,
                        role = me.role,
                        userId = me.id,
                        username = me.username,
                        fullName = me.fullName,
                    )
                )
            } catch (e: Exception) {
                error = ApiClient.toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun logout(onDone: () -> Unit) {
        viewModelScope.launch {
            container.socketManager.disconnect()
            container.tokenStore.clear()
            onDone()
        }
    }
}
