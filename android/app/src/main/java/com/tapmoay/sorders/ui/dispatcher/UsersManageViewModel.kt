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
import com.tapmoay.sorders.ui.common.ALL_CATEGORY
import com.tapmoay.sorders.ui.common.categoryOf
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

    /**
     * **抽屉里**的校验失败与保存失败（2026-10-03 · CHG-0018）。
     *
     * ⚠️ 这两类错误原来写的是上面那个**页面级** `error`：抽屉（原来是弹窗）是另一个窗口，
     *    那句话被画在它**背后**的页面主体里 —— 用户看到的是"点「保存」没有任何反应"，
     *    而抽屉一关，整页还会被 `ErrorView` 顶掉（一条数据都没丢，但页面没了）。
     *    现在：**表单里的错**走这里 → `FormErrorLine` 画在「保存」正上方；
     *    页面级 `error` 从此只留给"名单读不出来 / 点卡片上的动作失败"这一类**页面级**的事。
     */
    var formError by mutableStateOf<String?>(null)
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

    // ============================================================ 左栏分类（2026-10-05）
    //
    // 用户原话：「还有我们的账户管理司机管理货主管理批发商管理。车辆管理……在这个位置也加个分类，
    // 默认是显示，全部，同样也是左边侧边栏，然后左边侧边栏同样也是可以新增分类的」。
    //
    // 一份名册喂**四个**页面（账户 / 司机 / 货主 / 批发商）—— 它挂在 `users.category` 上，
    // 后端名册是 `user_categories`（全局一份，不是按人分区那一类）。
    // 筛选**在本地过一遍**：名册与列表本来就在手上，不往返后端（与地址页同一条）。
    var categoryNames by mutableStateOf<List<String>>(emptyList())
        private set
    var railKey by mutableStateOf("")

    /** 左栏选了一类之后要显示的那些账号（没选 = 全部）。 */
    val shownInRail: List<UserDto> get() = inRail(shown, railKey) { it.category }

    /** 分类名册（读不到不影响列表：静默，左栏就只有「全部」一格）。 */
    fun loadCategories() {
        viewModelScope.launch {
            try {
                val names = container.repo.userCategories().map { it.name }
                // 选中的那一格没了（分类被删/改名）→ 回到「全部」，别把列表锁死在一个不存在的类别上
                if (railKey.isNotBlank() && names.none { "c|" + it == railKey }) railKey = ""
                categoryNames = names
            } catch (_: Exception) {
            }
        }
    }

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

    // 抽屉开关（2026-10-03 · CHG-0018 之前叫 `showDialog`：它当时真的是个 AlertDialog）。
    var showSheet by mutableStateOf(false)
    var editing by mutableStateOf<UserDto?>(null)
    var draftPhone by mutableStateOf("")
    var draftName by mutableStateOf("")
    var draftPassword by mutableStateOf("")
    var draftVehicleType by mutableStateOf("large")
    /** 分类（左栏分组，2026-10-05）：四个名册页共用这一份名册。 */
    var draftCategory by mutableStateOf("")

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
        loadCategories()
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
        draftCategory = ""
        draftRuleId = null
        formError = null
        showSheet = true
    }

    fun openEdit(u: UserDto) {
        editing = u
        draftPhone = u.phone
        draftName = u.fullName
        draftPassword = ""
        draftVehicleType = if (u.vehicleType == "trailer") "trailer" else "large"
        draftCategory = u.category
        draftRuleId = u.driverRuleId
        formError = null
        showSheet = true
        // 商品可见范围：**只有货主/批发商有这一项**（派单员不受限，司机没有商品目录）
        draftScope = "all"
        draftVisible = emptySet()
        draftAllowCategories = emptySet()
        draftHidden = emptySet()
        draftHiddenCategories = emptySet()
        visibilityQuery = ""
        if (visibilityApplies) {
            visibilityLoading = true
            viewModelScope.launch {
                try {
                    val v = container.repo.productVisibility(u.id)
                    draftScope = v.scope
                    draftVisible = v.productIds.toSet()
                    // 四维一起回显：少回显一维 = 一保存就把它抹掉（排除项被抹掉更糟：
                    // 用户以为某个商品是关着的，它其实又出现了）
                    draftAllowCategories = v.categoryNames.toSet()
                    draftHidden = v.hiddenProductIds.toSet()
                    draftHiddenCategories = v.hiddenCategoryNames.toSet()
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

    // ---- 商品可见范围（分类 + 单品，授权 + 排除；CHG-0062）----
    /** 只有货主/批发商有"商品可见范围"这一项。 */
    val visibilityApplies: Boolean
        get() = editing != null && editing?.role == "shipper"

    var draftScope by mutableStateOf("all")

    /** 单品**授权**（只有「只给勾选的」那一档看它）。 */
    var draftVisible by mutableStateOf<Set<Long>>(emptySet())

    /** 分类**授权**（按名字算；空串代表「未分类」那一类。只有 custom 档算数）。 */
    var draftAllowCategories by mutableStateOf<Set<String>>(emptySet())

    /** 单品**排除**（两档都生效，且**优先于授权**）。 */
    var draftHidden by mutableStateOf<Set<Long>>(emptySet())

    /** 分类**排除**（两档都生效，且优先于授权）。 */
    var draftHiddenCategories by mutableStateOf<Set<String>>(emptySet())

    var visibilityLoading by mutableStateOf(false)

    /**
     * 可见范围第二层里的搜索词。
     *
     * 留在 VM 而不是第二层里 `remember`：退出去看一眼上一层的档位汇总、再进来接着挑，
     * 词不该被清掉（和批量页的 `query` 同一个道理）。
     */
    var visibilityQuery by mutableStateOf("")

    fun setScope(scope: String) {
        // 只换档位，**不清**那四维：勾过的东西留着，切回来还在。
        // 哪一维在哪一档算数是后端定的（`replace_visibility` 在 scope != custom 时不写授权行），
        // 界面按同一套口径显示就行。
        draftScope = scope
    }

    /**
     * 他**最终看得见**的商品 id —— 与后端 `resolve_visible_product_ids` 同一套规则：
     * 先按档位算授权，再减排除，**排除优先**（分类排除压单品授权、单品排除压分类授权）。
     */
    fun visibleProductIds(): Set<Long> {
        val allowed = if (draftScope == "custom") {
            products.filter { categoryOf(it) in draftAllowCategories || it.id in draftVisible }
        } else {
            products
        }
        val denied = products.filter { categoryOf(it) in draftHiddenCategories }.map { it.id }.toSet()
        return allowed.map { it.id }.toSet() - draftHidden - denied
    }

    /** 点一个商品行：现在"看得见"就关掉它，看不见就放开它。 */
    fun toggleVisibleProduct(p: ProductDto) {
        val id = p.id
        if (id in visibleProductIds()) {
            // 靠分类授权看见的也要用单品排除压住它 —— 只撤单品授权会"点了没反应"
            draftHidden = draftHidden + id
            draftVisible = draftVisible - id
        } else {
            draftHidden = draftHidden - id
            // custom 档里"这一类没整类授权"：得单独把这件加进单品授权，否则放开还是不显示
            if (draftScope == "custom" && categoryOf(p) !in draftAllowCategories) {
                draftVisible = draftVisible + id
            }
        }
    }

    /**
     * 点分类头（和"全选筛选出的 N 个"那一行）。
     *
     * [ALL_CATEGORY] 不是分类、只是一档筛选（还可能被搜索词收窄过），所以它只能**逐件**关，
     * 不能记成"这一类不给"。
     */
    fun toggleVisibleCategory(name: String, targetOn: Boolean, ids: List<Long>) {
        val picked = ids.toSet()
        val named = name != ALL_CATEGORY
        if (targetOn) {
            draftHidden = draftHidden - picked
            if (named) {
                draftHiddenCategories = draftHiddenCategories - name
                if (draftScope == "custom") draftAllowCategories = draftAllowCategories + name
            }
        } else if (named && draftScope == "custom") {
            // custom 档"这一类不给" = 撤掉整类授权；已经单件授权进来的也要撤 ——
            // 用户点的是"这一类全不给"，留一件开着是打脸
            draftAllowCategories = draftAllowCategories - name
            draftVisible = draftVisible - picked
            draftHidden = draftHidden - picked
        } else if (named) {
            // all 档"这一类不给"记成分类排除：以后新建到这个分类的商品**自动**也看不见
            //（只逐件关的话，明天新加的商品又会冒出来）
            draftHiddenCategories = draftHiddenCategories + name
            draftHidden = draftHidden - picked
        } else {
            draftHidden = draftHidden + picked
        }
    }

    /** 关掉抽屉（右上角的 × 与底部「取消」都走这里）。保存途中不许关：闸门是 [acting]。 */
    fun closeSheet() {
        if (!acting) showSheet = false
    }

    fun save() {
        // 手机号就是登录账号 —— 格式要求与后端 `UserCreate.phone` 的 `^1\d{10}$` 完全一致。
        // 原来这里只判"长度 ≥5"，于是 10 位、以 2 开头的号能一路走到后端才被 422 挡回来。
        InputRules.mobileError(draftPhone.trim())?.let {
            formError = it
            return
        }
        val cur = editing
        if (cur == null && draftPassword.length < 6) {
            formError = "初始密码至少 6 位"
            return
        }
        acting = true
        // 只清**表单里**那条错；页面级的 error 留着（它说的是另一件事：名单读不出来）
        formError = null
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
                            // 分类（左栏分组）：只有派单员能改这一格（后端 `PATCH /users` 里判的）
                            category = draftCategory,
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
                            category = draftCategory,
                        ),
                    )
                }
                actionResult = if (cur == null) "已新增" else "已更新"
                // 商品可见范围**单独一条写路径**（`PUT /users/{id}/product-visibility`）：
                // 它改的是"他能在选品页看到什么"，和改资料不是一件事；单独调也更好报错
                // （后端会因为"配完他一个商品都看不到"而拒绝，那句话要原样给用户看）。
                if (cur != null && visibilityApplies) {
                    val seen = visibleProductIds()
                    if (seen.isEmpty() && products.isNotEmpty()) {
                        // 本地先拦一道，省一次注定失败的往返。判据与后端**一模一样**：
                        // 不看"勾了几个"，看"他到底能看见几个"（只勾分类、一件单品都不勾是完全合法的）。
                        // 商品目录空的时候不拦 —— 那说明目录还没建，不是配错了。
                        // 资料已经改成功了，这里**如实分开说**，不能整体报"更新失败"。
                        actionResult = "资料已更新，但可见范围没保存：这么配他一个商品都看不到 —— " +
                            "那样他打开选品页会是空的"
                    } else {
                        try {
                            // 五样全发：哪一维在哪一档生效由后端判（授权只在 custom 档写、排除两档都写）
                            container.repo.setProductVisibility(
                                cur.id, draftScope,
                                draftVisible.toList(),
                                draftAllowCategories.toList(),
                                draftHidden.toList(),
                                draftHiddenCategories.toList(),
                            )
                            if (draftScope == "custom") {
                                val off = draftHidden.size + draftHiddenCategories.size
                                actionResult = "已更新，可见商品 ${seen.size} 个" +
                                    if (off > 0) "（另关掉 $off 个）" else ""
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
                showSheet = false
                load()
            } catch (e: Exception) {
                // 保存失败画在**抽屉里**（FormErrorLine），别画到抽屉背后去
                formError = toApiException(e).message
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
