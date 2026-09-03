package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.*
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.api.UserCreateRequest
import com.tapmoay.sorders.data.remote.api.UserUpdateRequest
import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.data.remote.dto.UserDto
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.launch

enum class UserPool(val key: String, val role: String, val memberOnly: Boolean, val title: String) {
    DRIVERS("drivers", "driver", false, "司机管理"),
    SHIPPERS("shippers", "shipper", false, "货主管理"),
    MEMBERS("members", "shipper", true, "批发商管理");

    companion object {
        fun fromKey(key: String): UserPool = entries.firstOrNull { it.key == key } ?: DRIVERS
    }
}

class UsersManageViewModel(
    private val container: AppContainer,
    val pool: UserPool,
) : ViewModel() {

    var users by mutableStateOf<List<UserDto>>(emptyList())
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var acting by mutableStateOf(false)
    var actionResult by mutableStateOf<String?>(null)

    var showDialog by mutableStateOf(false)
    var editing by mutableStateOf<UserDto?>(null)
    var draftPhone by mutableStateOf("")
    var draftName by mutableStateOf("")
    var draftPassword by mutableStateOf("")
    var draftVehicleType by mutableStateOf("large")
    var draftBillingMode by mutableStateOf("SALARY")
    var draftSalary by mutableStateOf("")

    init {
        load()
    }

    fun load() {
        loading = users.isEmpty()
        error = null
        viewModelScope.launch {
            try {
                users = if (pool.memberOnly) container.repo.members()
                else container.repo.shippersOrDrivers(pool.role)
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun openCreate() {
        editing = null
        draftPhone = ""
        draftName = ""
        draftPassword = ""
        draftVehicleType = "large"
        draftBillingMode = "SALARY"
        draftSalary = ""
        showDialog = true
    }

    fun openEdit(u: UserDto) {
        editing = u
        draftPhone = u.phone
        draftName = u.fullName
        draftPassword = ""
        draftVehicleType = if (u.vehicleType == "trailer") "trailer" else "large"
        draftBillingMode = u.billingMode ?: (if (u.vehicleType == "trailer") "PIECE" else "SALARY")
        draftSalary = u.salary ?: ""
        showDialog = true
    }

    fun save() {
        if (draftPhone.trim().length < 5) {
            error = "请填写手机号"
            return
        }
        val cur = editing
        if (cur == null && draftPassword.length < 6) {
            error = "初始密码至少 6 位"
            return
        }
        acting = true
        error = null
        viewModelScope.launch {
            try {
                if (cur == null) {
                    container.repo.createUser(
                        UserCreateRequest(
                            phone = draftPhone.trim(),
                            password = draftPassword,
                            fullName = draftName.trim(),
                            role = pool.role,
                            isMember = pool.memberOnly,
                            vehicleType = if (pool.role == "driver") draftVehicleType.ifBlank { null } else null,
                            billingMode = draftBillingMode,
                            salary = if (pool.role == "driver") draftSalary.trim().ifBlank { null } else null,
                        )
                    )
                } else {
                    container.repo.updateUser(
                        cur.id,
                        UserUpdateRequest(
                            phone = draftPhone.trim().ifBlank { null },
                            fullName = draftName.trim().ifBlank { null },
                            password = draftPassword.ifBlank { null },
                            vehicleType = if (pool.role == "driver") draftVehicleType.ifBlank { null } else null,
                            billingMode = draftBillingMode,
                            salary = if (pool.role == "driver") draftSalary.trim().ifBlank { null } else null,
                        ),
                    )
                }
                actionResult = if (cur == null) "已新增" else "已更新"
                showDialog = false
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    fun toggleActive(u: UserDto) {
        viewModelScope.launch {
            try {
                container.repo.updateUser(u.id, UserUpdateRequest(isActive = !u.isActive))
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            }
        }
    }

    /** 货主池：设为/取消批发商；批发商池：取消批发商 */
    fun toggleMember(u: UserDto) {
        viewModelScope.launch {
            try {
                container.repo.updateUser(u.id, UserUpdateRequest(isMember = !u.isMember))
                actionResult = if (u.isMember) "已取消批发商资格" else "已设为批发商"
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            }
        }
    }

    /** 货主 ↔ 司机 互换（后端 swap 接口） */
    fun swapRole(u: UserDto) {
        viewModelScope.launch {
            try {
                container.repo.swapRole(u.id)
                actionResult = "已转为" + (if (u.role == "shipper") "司机" else "货主")
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            }
        }
    }
    /** 商品维度批量调价（批发商管理页入口：同一商品可同时修改多个批发商） */
    var products by mutableStateOf<List<ProductDto>>(emptyList())
    var showBatch by mutableStateOf(false)

    fun openBatch() {
        showBatch = true
        if (products.isEmpty()) {
            viewModelScope.launch {
                try { products = container.repo.products(includeInactive = true) } catch (_: Exception) {}
            }
        }
    }

    fun batchPrice(
        shipperIds: List<Long>,
        productIds: List<Long>,
        mode: String,
        value: String?,
        tierIndex: Int?,
        onDone: (Int) -> Unit,
    ) {
        acting = true
        error = null
        viewModelScope.launch {
            try {
                val res = container.repo.batchPriceRules(shipperIds, productIds, mode, value, tierIndex)
                actionResult = "批量调价成功（" + res.count + " 条）"
                onDone(res.count)
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }
}
