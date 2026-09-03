package com.tapmoay.sorders.ui.login

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.ApiClient
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.Session
import com.tapmoay.sorders.data.remote.dto.RegisterRequest
import com.tapmoay.sorders.data.remote.dto.SendSmsRequest
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

class RegisterViewModel(private val container: AppContainer) : ViewModel() {

    var phone by mutableStateOf("")
    var username by mutableStateOf("")
    var password by mutableStateOf("")
    var code by mutableStateOf("")
    var loading by mutableStateOf(false)
    var sending by mutableStateOf(false)
    var countdown by mutableStateOf(0)
    var error by mutableStateOf<String?>(null)
    var tip by mutableStateOf<String?>(null)

    private var countdownJob: Job? = null

    fun sendSms() {
        if (phone.trim().length != 11) {
            error = "请输入 11 位手机号"
            return
        }
        sending = true
        error = null
        viewModelScope.launch {
            try {
                container.api.authApi.sendSms(SendSmsRequest(phone.trim()))
                tip = "验证码已发送（开发环境可能未配置短信服务，可查看后端日志）"
                countdown = 60
                countdownJob?.cancel()
                countdownJob = launch {
                    while (countdown > 0) {
                        delay(1000)
                        countdown--
                    }
                }
            } catch (e: Exception) {
                error = ApiClient.toApiException(e).message
            } finally {
                sending = false
            }
        }
    }

    fun register(onDone: (Session) -> Unit) {
        when {
            username.trim().length < 3 -> error = "用户名至少 3 个字符"
            password.length < 6 -> error = "密码至少 6 位"
            code.trim().length < 4 -> error = "请输入验证码"
            else -> {
                loading = true
                error = null
                viewModelScope.launch {
                    try {
                        val token = container.api.authApi.register(
                            RegisterRequest(
                                username = username.trim(),
                                password = password,
                                phone = phone.trim(),
                                verificationCode = code.trim(),
                            )
                        )
                        val session = Session(token.access_token, token.role, token.user_id, username.trim(), "")
                        container.tokenStore.save(session)
                        onDone(session)
                    } catch (e: Exception) {
                        error = ApiClient.toApiException(e).message
                    } finally {
                        loading = false
                    }
                }
            }
        }
    }
}
