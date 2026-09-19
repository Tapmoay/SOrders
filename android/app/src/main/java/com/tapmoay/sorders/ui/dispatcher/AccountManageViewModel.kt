package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.*
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.api.UserCreateRequest
import com.tapmoay.sorders.data.remote.api.UserUpdateRequest
import com.tapmoay.sorders.data.remote.dto.UserDto
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.launch

/** 账户管理可选的账号角色（派单员建号用） */
enum class AccountRoleKind(
    val key: String,
    val label: String,
    val role: String,
    val isMember: Boolean = false,
    val vehicleType: String? = null,
) {
    SHIPPER("shipper", "货主", "shipper"),
    MEMBER("member", "批发商", "shipper", isMember = true),
    DRIVER_SMALL("driver_small", "小车司机", "driver", vehicleType = "small"),
    DRIVER_LARGE("driver_large", "大车司机", "driver", vehicleType = "large"),
    DRIVER_TRAILER("driver_trailer", "挂车司机", "driver", vehicleType = "trailer"),
    DISPATCHER("dispatcher", "派单员", "dispatcher");

    companion object {
        fun fromKey(key: String): AccountRoleKind = entries.firstOrNull { it.key == key } ?: SHIPPER

        /** 由 UserDto 反推展示/编辑角色 */
        fun fromDto(u: UserDto): AccountRoleKind = when {
            u.role == "dispatcher" -> DISPATCHER
            u.role == "driver" && u.vehicleType == "trailer" -> DRIVER_TRAILER
            u.role == "driver" && u.vehicleType == "large" -> DRIVER_LARGE
            u.role == "driver" && u.vehicleType == "small" -> DRIVER_SMALL
            u.role == "driver" -> DRIVER_LARGE
            u.isMember -> MEMBER
            else -> SHIPPER
        }

        /** UserDto → 展示标签 */
        fun labelOf(u: UserDto): String = fromDto(u).label
    }
}

class AccountManageViewModel(
    private val container: AppContainer,
) : ViewModel() {

    var users by mutableStateOf<List<UserDto>>(emptyList())
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var acting by mutableStateOf(false)
    var actionResult by mutableStateOf<String?>(null)

    // 底部弹窗草稿
    var showSheet by mutableStateOf(false)
    var editing by mutableStateOf<UserDto?>(null)
    var draftName by mutableStateOf("")
    var draftPhone by mutableStateOf("")
    var draftPassword by mutableStateOf("")
    var draftRoleKey by mutableStateOf(AccountRoleKind.SHIPPER.key)

    // 必填校验错误（非空 = 红边 + 提示）
    var nameError by mutableStateOf<String?>(null)
    var phoneError by mutableStateOf<String?>(null)
    var passwordError by mutableStateOf<String?>(null)

    // 删除确认
    var deleting by mutableStateOf<UserDto?>(null)
    var deletingBusy by mutableStateOf(false)

    init { load() }

    fun load() {
        loading = users.isEmpty()
        error = null
        viewModelScope.launch {
            try {
                users = container.repo.usersAll()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun openCreate() {
        editing = null
        draftName = ""
        draftPhone = ""
        draftPassword = ""
        draftRoleKey = AccountRoleKind.SHIPPER.key
        nameError = null
        phoneError = null
        passwordError = null
        showSheet = true
    }

    fun openEdit(u: UserDto) {
        editing = u
        draftName = u.fullName
        draftPhone = u.phone
        draftPassword = ""
        draftRoleKey = AccountRoleKind.fromDto(u).key
        nameError = null
        phoneError = null
        passwordError = null
        showSheet = true
    }

    /** 手机号输入过滤：仅数字、最多 11 位（超位直接截断，不满足即不能填入） */
    fun onPhoneChange(v: String) {
        draftPhone = v.filter { it.isDigit() }.take(11)
        phoneError = null
    }

    /** 校验必填项；全过返回 true（红边提示由各 error 状态承载） */
    fun validate(): Boolean {
        nameError = if (draftName.trim().isEmpty()) "必填信息" else null
        phoneError = when {
            draftPhone.isEmpty() -> "必填信息"
            draftPhone.length != 11 -> "请输入 11 位手机号"
            !draftPhone.startsWith("1") -> "请输入 11 位手机号"
            else -> null
        }
        passwordError = when {
            draftPassword.isEmpty() -> if (editing != null) null else "必填信息"
            draftPassword.length < 6 -> "密码至少 6 位"
            else -> null
        }
        return nameError == null && phoneError == null && passwordError == null
    }

    private fun buildCreateRequest(kind: AccountRoleKind): UserCreateRequest {
        val billing = when {
            kind.role != "driver" -> null
            kind.vehicleType == "trailer" -> "PIECE"
            else -> "SALARY"
        }
        return UserCreateRequest(
            phone = draftPhone.trim(),
            password = draftPassword,
            fullName = draftName.trim(),
            role = kind.role,
            isMember = kind.isMember,
            vehicleType = kind.vehicleType,
            billingMode = billing,
        )
    }

    /** 保存（新增或编辑）：校验通过才提交；成功后回调（创建带账号密码文案） */
    fun save(onSaved: (String) -> Unit) {
        if (!validate()) return
        acting = true
        error = null
        val cur = editing
        viewModelScope.launch {
            try {
                val kind = AccountRoleKind.fromKey(draftRoleKey)
                if (cur == null) {
                    val u = container.repo.createUser(buildCreateRequest(kind))
                    onSaved("账号：" + u.phone + "　密码：" + draftPassword)
                } else {
                    container.repo.updateUser(
                        cur.id,
                        UserUpdateRequest(
                            phone = draftPhone.trim(),
                            fullName = draftName.trim(),
                            password = draftPassword.ifBlank { null },
                            role = kind.role,
                            isMember = kind.isMember,
                            vehicleType = kind.role.let { if (it == "driver") kind.vehicleType else null },
                            billingMode = if (kind.role == "driver") {
                                if (kind.vehicleType == "trailer") "PIECE" else "SALARY"
                            } else null,
                        )
                    )
                    onSaved("已更新账号：" + draftPhone.trim())
                }
                showSheet = false
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    /** 停用 / 启用 */
    fun toggleActive(u: UserDto) {
        viewModelScope.launch {
            try {
                container.repo.updateUser(u.id, UserUpdateRequest(isActive = !u.isActive))
                actionResult = if (u.isActive) "已停用：" + u.phone else "已启用：" + u.phone
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            }
        }
    }

    /** 删除（确认后调用；删除后原手机号可重新建号） */
    fun confirmDelete() {
        val u = deleting ?: return
        deletingBusy = true
        viewModelScope.launch {
            try {
                container.repo.deleteUser(u.id)
                actionResult = "已删除：" + u.phone
                deleting = null
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
                deleting = null
            } finally {
                deletingBusy = false
            }
        }
    }

    fun dismissDelete() {
        deleting = null
    }
}
