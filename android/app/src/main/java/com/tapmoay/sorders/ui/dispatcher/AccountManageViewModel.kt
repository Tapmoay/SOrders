package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.*
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.api.UserCreateRequest
import com.tapmoay.sorders.data.remote.api.UserUpdateRequest
import com.tapmoay.sorders.data.remote.dto.UserDto
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
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

    /**
     * 账号列表"这一页不是全部"＝账号超过 500 个（后端 `le=500`）。
     *
     * 判据是响应头 `X-Truncated`（走 `AppRepository.pageMeta()`）。这一页**就是这个坑**：
     * 页面右下角就是「新建账户」，而"列表里没有"会被读成"这个账号不存在"→
     * 再建一个 → 撞手机号唯一约束。
     */
    var truncated by mutableStateOf(false)
        private set

    /** 本次服务器上限（`X-Result-Limit`）；null = 老后端没回报，界面不许自己编一个数。 */
    var pageLimit by mutableStateOf<Int?>(null)
        private set

    // ============================================================ 搜索（**服务端**）
    //
    // 用户 2026-09-19：「还有其他的比如说，司机管理啊**账户管理**啊。这些也要添加搜索键。
    // 然后这个搜索键可以根据他们的**名称**还有**电话号码**以及**电话号码的后 4 位**进行搜索」。
    //
    // 这一页原来**一个搜索框都没有**（所以"找不到就先新建"在这里是必然会发生的动作）。
    // 与司机/货主/批发商管理同一套实现、同一个规则：服务端 `?q=`（姓名/手机号，后 4 位也命中）。
    // ⛔ 不许退回本地过滤：这一页列的是**全部角色**的账号，一页最多 500 条，
    //    "列表里没有"在这种页面上最容易被读成"这个账号不存在"。

    /** 搜索词（原样保留；防抖只影响发请求的时机）。 */
    var query by mutableStateOf("")

    /** 服务端命中；**null = 没在搜**（界面要看的是 [users]）。 */
    var hits by mutableStateOf<List<UserDto>?>(null)
        private set

    /** 搜索结果的截断位（与名册那一页各自独立）。 */
    var hitsTruncated by mutableStateOf(false)
        private set
    var hitsLimit by mutableStateOf<Int?>(null)
        private set

    private var searchJob: Job? = null

    /** 界面上要显示的那些账号：在搜就是服务端命中，没在搜就是全部名册。 */
    val shown: List<UserDto> get() = hits ?: users

    val isSearching: Boolean get() = hits != null

    /** 搜索框的唯一入口（防抖 300ms）。 */
    fun onQueryChange(v: String) {
        query = v
        searchJob?.cancel()
        val kw = v.trim()
        if (kw.isEmpty()) {
            hits = null
            hitsTruncated = false
            hitsLimit = null
            return
        }
        searchJob = viewModelScope.launch {
            delay(300)
            try {
                val page = container.repo.usersPage(q = kw)
                hits = page.rows
                hitsTruncated = page.meta.hasMore
                hitsLimit = page.meta.limit
            } catch (e: Exception) {
                error = toApiException(e).message
            }
        }
    }

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
                val page = container.repo.usersPage()
                users = page.rows
                truncated = page.meta.hasMore
                pageLimit = page.meta.limit
                // 建号/改号/停用之后搜索结果也旧了：正在搜就按同一个词再搜一次，
                // 否则"刚建好的账号搜不到"会被当成建号失败。
                if (hits != null) onQueryChange(query)
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

    /** 校验必填项；全过返回 true（红边提示由各 error 状态承载） */
    fun validate(): Boolean {
        nameError = if (draftName.trim().isEmpty()) "必填信息" else null
        // 手机号格式走唯一实现（原来这里手抄了一遍"11 位 + 以 1 开头"，
        // 而**同一个 App 的账号管理页**抄的是另一份 —— 两份口径迟早会分叉）
        phoneError = InputRules.mobileError(draftPhone)
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
                            // 车型只在**角色真的变了**时才发（它唯一的作用就是给新角色定车型）。
                            // 编辑既有司机时车型是独立属性（在「司机管理」里改）：从 kind 反推会把
                            // `vehicle_type = NULL` 静默写成 "large"（2026-09-19 报告 L-9）。
                            vehicleType = if (kind.role == "driver" && kind.role != cur.role) kind.vehicleType else null,
                            // ⛔ 账户管理**不许**发 billing_mode（2026-09-19 报告 P0-5，high）：原来这里按
                            //    车型重算并发送，于是「只改个手机号」也会把司机显式设过的 PIECE 静默翻回
                            //    SALARY → 此后每单快照成 SALARY → 不生成按单账单（不是金额算错，是**账单
                            //    不存在**），而界面只回一句「已更新账号」。`null` 会被 `ApiClient.json` 的
                            //    `explicitNulls = false` 整条丢掉，正好等于"不动"（= 司机管理那条路径的语义）。
                            billingMode = null,
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
