package com.tapmoay.sorders.ui.login

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.BuildConfig
import com.tapmoay.sorders.core.ApiClient
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.Session
import com.tapmoay.sorders.data.remote.dto.LoginRequest
import kotlinx.coroutines.launch

class LoginViewModel(private val container: AppContainer) : ViewModel() {

    var phone by mutableStateOf("")
    var password by mutableStateOf("")
    var showPassword by mutableStateOf(false)
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)

    fun login(onDone: (Session) -> Unit) {
        if (phone.isBlank() || password.isBlank()) {
            error = "请输入手机号/用户名和密码"
            return
        }
        loading = true
        error = null
        viewModelScope.launch {
            try {
                val token = container.api.authApi.login(
                    LoginRequest(password = password, phone = phone.trim())
                )
                val session = Session(
                    token = token.access_token,
                    role = token.role,
                    userId = token.user_id,
                    username = phone.trim(),
                    fullName = "",
                )
                container.tokenStore.save(session)
                container.socketManager.connect(
                    com.tapmoay.sorders.core.ApiEndpoint.baseUrl,
                    token.access_token,
                    container.realtimeHub.lastNotificationId.value,
                )
                container.realtimeHub.syncUnreadFromApi()
                onDone(session)
            } catch (e: Exception) {
                error = ApiClient.toApiException(e).message
            } finally {
                loading = false
            }
        }
    }
}