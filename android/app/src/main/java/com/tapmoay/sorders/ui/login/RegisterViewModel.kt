package com.tapmoay.sorders.ui.login

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.ApiClient
import com.tapmoay.sorders.core.ApiEndpoint
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.core.Session
import com.tapmoay.sorders.core.TokenStore
import com.tapmoay.sorders.data.remote.dto.RegisterRequest
import com.tapmoay.sorders.core.AppContainer
import kotlinx.coroutines.launch

/**
 * 自助注册（FEAT-0017，2026-10-11 用户要求）：「登录界面……输入电话号码，必须是正确的形式，
 * 然后再输入密码，就可以登录/注册一个账号了，注册，然后默认账号是货主」。
 *
 * ## 为什么单独一个 VM（而不是塞进 [LoginViewModel]）
 * 两件事的**成功路径**不一样：登录是"用已有凭据换 token"，注册是"建号 + 拿 token"，
 * 而注册多一个字段（姓名）、多一条客户端预校验（手机号形状）、且**注册成功同样要进首页**。
 * 塞进一个 VM 会让 error / loading 两个状态互相踩（注册报的错显示在登录框下面）。
 *
 * ## 客户端先拦一道，但**不是**唯一一道
 * [InputRules.mobileError] 与后端 `core/phone.py` 的 `^1\\d{10}$` 是**同一条规则的两端**
 * （见 InputRules 里的注释）。这里拦一次只是省一次往返、把话说得更早；
 * ⛔ 真正的门在后端（后端的 422 文案会原样显示，见 [ApiClient.toApiException]）。
 */
class RegisterViewModel(private val container: AppContainer) : ViewModel() {

    var phone by mutableStateOf("")
    var password by mutableStateOf("")
    var fullName by mutableStateOf("")
    var showPassword by mutableStateOf(false)
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)

    /**
     * 提交注册。成功时把会话落盘、连上长连接（与登录**完全同一套收尾**），再调 [onDone]。
     *
     * ⚠️ 这里的收尾顺序照抄 [LoginViewModel.login]：**save → connect → syncUnread → onDone**。
     * 少任何一步的表现都很隐蔽：漏 connect 会"注册完收不到推送"，漏 save 会在重启后掉登录。
     * ⛔ 不要为了"少写几行"把它改成"注册成功后再调一次登录"：后端已经把 token 给回来了。
     */
    fun register(onDone: (Session) -> Unit) {
        val id = phone.trim()
        val name = fullName.trim()
        // 客户端预校验：形状不对/密码太短都不发请求（说人话，且与后端同口径）
        InputRules.mobileError(id)?.let { error = it; return }
        if (password.length < MIN_PASSWORD) {
            error = "密码至少 $MIN_PASSWORD 位"
            return
        }
        loading = true
        error = null
        viewModelScope.launch {
            try {
                val token = container.api.authApi.register(
                    RegisterRequest(phone = id, password = password, full_name = name)
                )
                val session = Session(
                    token = token.access_token,
                    role = token.role,
                    userId = token.user_id,
                    username = id,
                    fullName = name,
                )
                container.tokenStore.save(session)
                container.hintPrefs.onLogin()
                container.socketManager.connect(
                    ApiEndpoint.baseUrl,
                    token.access_token,
                    container.realtimeHub.lastNotificationId.value,
                )
                container.realtimeHub.syncUnreadFromApi()
                onDone(session)
            } catch (e: Exception) {
                // 后端的中文原文（"该手机号已存在" / 手机号形状 / 429 限流）会原样透出：
                // ApiClient.httpMessage 对含中文的 detail 直接返回，见 core/ApiClient.kt
                error = ApiClient.toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    companion object {
        /** 与后端 `schemas/user.py::UserCreate.password` 的口径一致（6~128） */
        const val MIN_PASSWORD = 6
    }
}
