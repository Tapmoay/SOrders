package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.*
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.api.UserCreateRequest
import com.tapmoay.sorders.data.remote.api.UserUpdateRequest
import com.tapmoay.sorders.data.remote.dto.DriverBillingRuleDto
import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.data.remote.dto.UserDto
import com.tapmoay.sorders.data.remote.dto.VehicleDto
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
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

    /**
     * 名册"这一页不是全部"＝账号超过 500 个（后端 `le=500`）。
     *
     * 判据是响应头 `X-Truncated`（走 `AppRepository.pageMeta()`），不再靠"条数等于 500"去猜。
     * 不说出来的后果最重：派单员在名册里找不到某个人，下一步就是"新建一个" ——
     * 而那个账号其实存在（撞手机号唯一约束）。
     */
    var truncated by mutableStateOf(false)
        private set

    /** 本次服务器上限（`X-Result-Limit`）；null = 老后端没回报，界面不许自己编一个数。 */
    var pageLimit by mutableStateOf<Int?>(null)
        private set
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var acting by mutableStateOf(false)
    var actionResult by mutableStateOf<String?>(null)

    // ============================================================ 搜索（**服务端**）
    //
    // 用户 2026-09-19：「还有其他的比如说，**司机管理**啊**账户管理**啊。这些也要添加搜索键。
    // 然后这个搜索键可以根据他们的**名称**还有**电话号码**以及**电话号码的后 4 位**进行搜索」。
    //
    // ⛔ 为什么必须打到服务端，而不是过滤手里这一页：
    //    名册一页最多 500 条，而"这一页不是全部"会被读成"这个账号不存在"→ 再建一个 →
    //    撞手机号唯一约束。第 501 个人在客户端**根本不存在**，本地过滤物理上不可能找到他。
    //    后端 `?q=` 是姓名/手机号子串（`app/core/user_search.py`），**后 4 位天然命中**。
    //
    // 规则的同一条口径在客户端有一份（`core/UserSearch`）给"回全量"的那两处用（账本仪表盘）。
    // 两份实现由 `_check_user_search.py` 钉着，不许分叉。

    /** 搜索词（原样保留，防抖只影响发请求的时机）。 */
    var query by mutableStateOf("")

    /**
     * 服务端搜索命中的账号；**null = 没在搜**（界面要看的是 [roster]）。
     *
     * 单独立一个字段而不是覆盖 [roster]：`driverNameOf` / 车队摘要 / 配车弹层都要
     * **完整名册**才能把名字和车对上，把它们换成"搜索结果"会让这些地方出现
     * 「账号 #5（不在司机名册里）」这种假故障。
     */
    var hits by mutableStateOf<List<UserDto>?>(null)
        private set

    /** 搜索结果的截断位（与名册那一页各自独立：搜索命中的条数是另一件事）。 */
    var hitsTruncated by mutableStateOf(false)
        private set
    var hitsLimit by mutableStateOf<Int?>(null)
        private set

    private var searchJob: Job? = null

    /** 搜索框的唯一入口（防抖 300ms：每敲一个字就打后端既浪费又会让列表闪）。 */
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
                val page = container.repo.usersPage(role = pool.role, memberOnly = pool.memberOnly, q = kw)
                hits = page.rows
                hitsTruncated = page.meta.hasMore
                hitsLimit = page.meta.limit
            } catch (e: Exception) {
                error = toApiException(e).message
            }
        }
    }

    // ---- 车辆（v3.44）：司机池要显示"他开哪辆车"，并支持在这里配车 ----
    var vehicles by mutableStateOf<List<VehicleDto>>(emptyList())

    /** 非空 = 配车弹层开着（当前正在给这个人配车）。 */
    var vehiclePickerFor by mutableStateOf<UserDto?>(null)
    var binding by mutableStateOf(false)

    val isDriverPool: Boolean get() = pool.role == "driver"

    /** 完整名册（**没在搜**时就是它）。名字查找、车队摘要一律用它。 */
    val roster: List<UserDto> get() = users

    /** 界面上要显示的那些账号：在搜就是服务端命中，没在搜就是名册。 */
    val shown: List<UserDto> get() = hits ?: users

    val isSearching: Boolean get() = hits != null

    /** 这个人名下的车（可能不止一辆：一个司机两辆车在现实里是存在的，所以不假设唯一）。 */
    fun vehiclesOf(driverId: Long): List<VehicleDto> = vehicles.filter { it.driverId == driverId }

    /**
     * 车牌 → 车主名（配车弹层要用："现在挂在李四名下"）。
     *
     * ⚠️ 找不到名字时**不能返回空串**：那在弹层里等于"没有司机"，
     * 而真相可能是"绑着一个不在司机名册里的账号"（停用账号 / 老数据）。
     */
    fun driverNameOf(driverId: Long?): String {
        if (driverId == null) return ""
        val d = users.firstOrNull { it.id == driverId }
            ?: hits?.firstOrNull { it.id == driverId }
            ?: return "账号 #$driverId（不在司机名册里）"
        return d.fullName.ifBlank { d.phone.ifBlank { d.username } }
    }

    var showDialog by mutableStateOf(false)
    var editing by mutableStateOf<UserDto?>(null)
    var draftPhone by mutableStateOf("")
    var draftName by mutableStateOf("")
    var draftPassword by mutableStateOf("")
    var draftVehicleType by mutableStateOf("large")

    /**
     * 计费规则（v3.36）：司机可以挂一份**命名好的规则模板**，挂上之后他怎么算钱由规则决定。
     *
     * ⚠️ 2026-09-21 起**不再有** `draftBillingMode` / `draftSalary` 这两个草稿字段：
     *    用户原话「司机管理他现在有固定工资和按单计费，但是后面又加了一个计费规则，
     *    其实**计费规则就已经包括他们上面的这个**」——一份规则里本来就有「固定工资」与「每单/每件/提成」，
     *    再在账号上放两个同类字段就是**同一个数两处写**（改哪一处都可能不生效，而两边都不报错）。
     *    于是：他怎么算钱**只有**这一个入口（[draftRuleId]）；没挂规则时按车型的老口径兜底读，
     *    而那句话由后端算好下发（`pay_summary`），界面不自己拼。
     */
    var rules by mutableStateOf<List<DriverBillingRuleDto>>(emptyList())
    var draftRuleId by mutableStateOf<Long?>(null)

    init {
        load()
        loadRules()
        loadVehicles()
    }

    /** 车辆名册（只有司机池要）。失败静默：读不到车不影响改账号资料。 */
    private fun loadVehicles() {
        if (!isDriverPool) return
        viewModelScope.launch {
            try {
                vehicles = container.repo.vehicles()
            } catch (_: Exception) {
            }
        }
    }

    private fun reloadVehicles() {
        if (!isDriverPool) return
        viewModelScope.launch {
            try {
                vehicles = container.repo.vehicles()
            } catch (e: Exception) {
                error = toApiException(e).message
            }
        }
    }

    fun openVehiclePicker(u: UserDto) {
        vehiclePickerFor = u
        if (vehicles.isEmpty()) reloadVehicles()
    }

    /**
     * 给司机配车 / 解绑（`vehicleId = null` = 解绑他名下**所有**车）。
     *
     * 为什么解绑要一次解掉全部：界面上那一行显示的是"他名下这几辆车"，
     * 用户点的是「不绑车（解绑）」这句话。只解第一辆却显示"已解绑"，
     * 剩下的车会**安静地留着**——而用户以为他已经是无车司机了。
     */
    fun pickVehicle(vehicleId: Long?) {
        val u = vehiclePickerFor ?: return
        binding = true
        viewModelScope.launch {
            try {
                val who = u.fullName.ifBlank { u.phone }
                if (vehicleId == null) {
                    val mine = vehiclesOf(u.id)
                    mine.forEach { container.repo.setVehicleDriver(it.id, null) }
                    actionResult = if (mine.isEmpty()) "他名下本来就没有车" else "已把 " + who + " 名下的车全部解绑"
                } else {
                    val v = container.repo.setVehicleDriver(vehicleId, u.id)
                    actionResult = "已把 " + v.plateNo + " 配给 " + who
                }
                vehiclePickerFor = null
                reloadVehicles()
            } catch (e: Exception) {
                // 错误留在弹层里（`error` 驱动的是整页 ErrorView，会把列表清掉）
                actionResult = "配车失败：" + toApiException(e).message
                vehiclePickerFor = null
            } finally {
                binding = false
            }
        }
    }

    /** 规则名册（只有司机池需要）。失败静默：下拉空着不影响改其它字段。 */
    private fun loadRules() {
        if (pool.role != "driver") return
        viewModelScope.launch {
            try {
                rules = container.repo.driverBillingRules()
            } catch (_: Exception) {
            }
        }
    }

    fun load() {
        loading = users.isEmpty()
        error = null
        viewModelScope.launch {
            try {
                val page = container.repo.usersPage(role = pool.role, memberOnly = pool.memberOnly)
                users = page.rows
                truncated = page.meta.hasMore
                pageLimit = page.meta.limit
                // 名册变了（新建/改名/停用之后）搜索结果也是旧的 —— 正在搜就按同一个词再搜一次，
                // 不然"刚建好的人搜不到"会被当成建号失败。
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
        draftPhone = ""
        draftName = ""
        draftPassword = ""
        draftVehicleType = "large"
        draftRuleId = null
        showDialog = true
    }

    fun openEdit(u: UserDto) {
        editing = u
        draftPhone = u.phone
        draftName = u.fullName
        draftPassword = ""
        draftVehicleType = if (u.vehicleType == "trailer") "trailer" else "large"
        draftRuleId = u.driverRuleId
        showDialog = true
        // 商品可见范围：**只有货主/批发商有这一项**（派单员不受限，司机没有商品目录）
        draftScope = "all"
        draftVisible = emptySet()
        if (visibilityApplies) {
            visibilityLoading = true
            viewModelScope.launch {
                try {
                    val v = container.repo.productVisibility(u.id)
                    draftScope = v.scope
                    draftVisible = v.productIds.toSet()
                } catch (_: Exception) {
                    // 读不到就按"不限制"显示：**不能**默认成 custom ——
                    // 那会在保存时把一个没配过白名单的人改成"什么都看不到"
                } finally {
                    visibilityLoading = false
                }
            }
            // 勾选列表要的商品目录：**含已下架**（他可能被允许看一个下架商品，
            // 只用在售那份去回显会把它显示成"没勾"，一保存就被抹掉）
            if (products.isEmpty()) {
                viewModelScope.launch {
                    try { products = container.repo.products(includeInactive = true) } catch (_: Exception) {}
                }
            }
        }
    }

    // ---- 商品可见范围（白名单）----
    /** 只有货主/批发商有"商品可见范围"这一项。 */
    val visibilityApplies: Boolean
        get() = editing != null && editing?.role == "shipper"

    var draftScope by mutableStateOf("all")
    var draftVisible by mutableStateOf<Set<Long>>(emptySet())
    var visibilityLoading by mutableStateOf(false)

    fun setScope(scope: String) {
        draftScope = scope
    }

    fun toggleVisible(productId: Long) {
        draftVisible = if (productId in draftVisible) draftVisible - productId else draftVisible + productId
    }

    fun selectAllVisible() {
        draftVisible = products.map { it.id }.toSet()
    }

    fun clearVisible() {
        draftVisible = emptySet()
    }

    fun save() {
        // 手机号就是登录账号 —— 格式要求与后端 `UserCreate.phone` 的 `^1\d{10}$` 完全一致。
        // 原来这里只判"长度 ≥5"，于是 10 位、以 2 开头的号能一路走到后端才被 422 挡回来。
        InputRules.mobileError(draftPhone.trim())?.let {
            error = it
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
                            // ⛔ **不再发 `billing_mode` / `salary`**（2026-09-21 用户：
                            //    「司机管理他现在有固定工资和按单计费，但后面又加了一个计费规则，
                            //      其实计费规则**就已经包括**他们上面的这个」）：
                            //    他怎么算钱只有一处——挂的那份「计费规则」（`driver_pay`）。
                            //    建司机时不写这两个字段 = 新账号从此只有一条口径；
                            //    老数据里已有的值仍然按老口径兜底读（没挂规则的司机金额不变）。
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
                        ),
                    )
                }
                actionResult = if (cur == null) "已新增" else "已更新"
                // 商品可见范围**单独一条写路径**（`PUT /users/{id}/product-visibility`）：
                // 它改的是"他能在选品页看到什么"，和改资料不是一件事；单独调也更好报错
                // （后端会因为"选了自定义却一个都没勾"而拒绝，那句话要原样给用户看）。
                if (cur != null && visibilityApplies) {
                    if (draftScope == "custom" && draftVisible.isEmpty()) {
                        // 资料已经改成功了，这里**如实分开说**，不能整体报"更新失败"
                        actionResult = "资料已更新，但可见范围没保存：选了「只给勾选的」却一个都没勾 —— " +
                            "那样他打开选品页会是空的"
                    } else {
                        try {
                            container.repo.setProductVisibility(cur.id, draftScope, draftVisible.toList())
                            if (draftScope == "custom") {
                                actionResult = "已更新，可见商品 ${draftVisible.size} 个"
                            }
                        } catch (e: Exception) {
                            actionResult = "资料已更新，但可见范围没保存：" + toApiException(e).message
                        }
                    }
                }
                // 计费规则**单独一条写路径**（`POST /driver-billing-rules/attach`）：
                // 它是"给这个人定以后怎么算钱"，和改资料不是一件事，后端也刻意没让
                // PATCH /users 能改它（两条写路径必然分叉，见 driver_billing_rules.py 的注释）。
                if (pool.role == "driver" && cur != null && draftRuleId != cur.driverRuleId) {
                    try {
                        container.repo.attachDriverRule(cur.id, draftRuleId)
                        actionResult = if (draftRuleId == null) "已更新，并解除了计费规则" else "已更新，并挂上计费规则"
                    } catch (e: Exception) {
                        // 资料已经改成功了，这里失败要**如实分开说**，不能整体报"更新失败"
                        actionResult = "资料已更新，但计费规则没挂上：" + toApiException(e).message
                    }
                }
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
        onDone: (Int) -> Unit,
    ) {
        acting = true
        error = null
        viewModelScope.launch {
            try {
                val res = container.repo.batchPriceRules(shipperIds, productIds, mode, value)
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
