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
import com.tapmoay.sorders.ui.common.rosterPhoneOf
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * 账户管理的**状态档**（2026-10-03 · E2E 报告 P2）。
 *
 * 顺序即下标，[AccountManageViewModel.statusTab] 直接用它；颜色见 `AccountManageScreen`
 * 的 `ACCOUNT_STATUS_COLORS`（按下标取色，⛔ 只能往后面加档）。
 */
val ACCOUNT_STATUS_TABS: List<String> = listOf("全部", "在用", "已停用", "已删除")

/**
 * 某个账号属不属于第 [tab] 档（E2E 报告 P2）。
 *
 * ⚠️ 「已停用」必须**排掉**回收站：后端删号时会顺手把 `is_active` 置 false，
 * 所以回收站账号的 `isActive` 同样是 false —— 不排掉的话「已停用」这一档里
 * 又混进一堆删除账号，等于把 P2 那个"全是被埋掉的旧账号"原样搬了个地方。
 * ⛔ 判据只认后端算好的 [UserDto.isDeleted]（`users.py::_in_recycle_bin`），
 * 界面不许自己拿 `phone.contains("_del")` 猜：恢复撞号的账号带后缀但**不在**回收站里。
 */
fun matchesStatus(u: UserDto, tab: Int): Boolean = when (tab) {
    1 -> u.isActive && !u.isDeleted
    2 -> !u.isActive && !u.isDeleted
    3 -> u.isDeleted
    else -> true
}

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

    // ============================================================ 左栏分类（2026-10-05）
    //
    // 用户原话：「还有我们的账户管理司机管理货主管理批发商管理……在这个位置也加个分类，
    // 默认是显示，全部，同样也是左边侧边栏，然后左边侧边栏同样也是可以新增分类的」。
    //
    // 名册（有哪些分类、什么顺序）在 `user_categories` 这份**全店共用**的名册里，
    // 账号上只存一个名字（`UserDto.category`）。筛选**本地过一遍** ——
    // 名册与列表本来就在手上，不往返后端。

    /** 左栏那几格（名册顺序）。拉不到就退化成只有「全部」——账号照样都在，不拦人。
     *
     * ⛔ 名册里没有的分类名**不是错误**（老数据、别的路径写进去的）：卡片照样画它，
     * 只是左栏里点不到那一格而已，不许因此把账号藏起来。
     */
    var categoryNames by mutableStateOf<List<String>>(emptyList())
        private set

    /** 左栏选中的那一格（`c|分类名`；空串 = 全部）。 */
    var railKey by mutableStateOf("")

    // ============================================================ 状态档（2026-10-03 · E2E 报告 P2）
    //
    // 真机现场（`_tmp/E2E测试报告.md` P2）：账户管理一屏接一屏全是历史停用/删掉的探针账号，
    // 而这一页当时**只有分类那一个口径** —— 「找一个在用的账号」没有任何筛选可点，
    // 只能靠搜索框先知道名字。
    //
    // 四档与判据见 [matchesStatus]。**默认停在「在用」**：这一页的主要用途是找人 / 改人，
    // 默认把回收站与离职账号一起端上来等于没修（它们都在「已停用」「已删除」两档里，
    // 一按就到 —— 档位行常驻在搜索框上面）。筛选**本地过一遍**：与左栏分类同一条路，
    // 名册本来就在手上，不往返后端。
    //
    // ⚠️ 三个筛选的**顺序不能换**：先 [shown]（搜索命中 / 全量名册）→ 再左栏分类 → 最后状态。
    // ⛔ 别把状态并进服务端 `?q=`：后端此刻只认 `q`，多传一个参数不会有任何效果，
    //     却会让人以为"筛过了"（`_check_user_search.py` 钉着服务端搜索的唯一形态）。

    /** 状态档下标：0 全部 / 1 在用 / 2 已停用 / 3 已删除（文案 = [ACCOUNT_STATUS_TABS]）。 */
    var statusTab by mutableStateOf(1)

    /** 这一页真正要画的账号：先按搜索/名册取，再按左栏那一格、最后按状态档过一遍。 */
    val shownInRail: List<UserDto> get() =
        inRail(shown, railKey) { it.category }.filter { matchesStatus(it, statusTab) }

    /** 拉左栏那几格。失败**不吵**（左栏退化成只有「全部」，比弹一页错误好）。 */
    fun loadCategories() {
        viewModelScope.launch {
            try {
                categoryNames = container.repo.userCategories().map { it.name }
                // 选中的那一格没了（被改名/删掉）→ 自己回到「全部」：
                // 不然用户会停在一列空名单前面，以为账号丢了。
                if (railKey.isNotBlank() && categoryNames.none { "c|" + it == railKey }) railKey = ""
            } catch (_: Exception) {
            }
        }
    }

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

    /** 分类草稿（空串 = 未分类）。名册里没有的名字也可以留着（老数据）。 */
    var draftCategory by mutableStateOf("")

    // 必填校验错误（非空 = 抽屉里那一行红字；2026-09-22 之前是"红边 + supportingText"，
    // 而新的表单行是无边框的，没有"边"可红 —— 所以错误必须**自己说出来**，
    // 每一句都得能独立读懂是哪一栏错了）
    var nameError by mutableStateOf<String?>(null)
    var phoneError by mutableStateOf<String?>(null)
    var passwordError by mutableStateOf<String?>(null)

    /**
     * 保存失败时**服务端**回的那一句（如手机号已存在）。
     *
     * ⚠️ 它刻意**不**写进页面级的 [error]：那个状态会把整页换成「一句话 + 重试」（`ErrorView`），
     * 于是"保存被拦下"在用户眼里就成了"**整页账号全没了**"，而真正的红字还画在抽屉背后被盖住
     * （同一个坑 2026-09-21 在「新增地点」上踩过，见 `Components.kt::FormErrorLine` 的注释）。
     * → 表单的错误必须和表单**同生共死**：画在抽屉里、[validate] 一跑就清掉。
     */
    var saveError by mutableStateOf<String?>(null)

    /** 抽屉里那一行红字（字段校验与保存失败合成一句，顺序 = 用户从上往下填的顺序）。 */
    val formError: String? get() = nameError ?: phoneError ?: passwordError ?: saveError

    // 删除确认
    var deleting by mutableStateOf<UserDto?>(null)
    var deletingBusy by mutableStateOf(false)

    init {
        load()
        loadCategories()
    }

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
        draftCategory = ""
        clearSheetErrors()
        showSheet = true
    }

    fun openEdit(u: UserDto) {
        editing = u
        draftName = u.fullName
        draftPhone = u.phone
        draftPassword = ""
        draftRoleKey = AccountRoleKind.fromDto(u).key
        draftCategory = u.category
        clearSheetErrors()
        showSheet = true
    }

    /** 打开抽屉时把上一轮的红字清干净（错误跟着表单走，不留到下一次）。 */
    private fun clearSheetErrors() {
        nameError = null
        phoneError = null
        passwordError = null
        saveError = null
    }

    /** 校验必填项；全过返回 true（红字由 [formError] 承载） */
    fun validate(): Boolean {
        saveError = null
        // 三句话都写成"能独立读懂"的：抽屉里只有**一行**红字，
        // 原来的"必填信息"在这里会变成一句不知道指哪一栏的话。
        nameError = if (draftName.trim().isEmpty()) "请填写姓名" else null
        // 手机号格式走唯一实现（原来这里手抄了一遍"11 位 + 以 1 开头"，
        // 而**同一个 App 的账号管理页**抄的是另一份 —— 两份口径迟早会分叉）
        phoneError = InputRules.mobileError(draftPhone)
        passwordError = when {
            draftPassword.isEmpty() -> if (editing != null) null else "请设置密码（至少 6 位）"
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
            category = draftCategory,
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
                    // 两个数字串**各自成行**（走查 P4）：原来用全角空格并列，Snackbar 窄的时候
                    // 会从账号或密码的数字中间断开，读起来像另一个数。剪贴板拿到的是同一条两行文本。
                    onSaved("账号：" + u.phone + "\n密码：" + draftPassword)
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
                            // 分类：表单里是什么就发什么（空串 = 清成未分类）。
                            // ⛔ 只有派单员能改（后端 `users.py` 里对非派单员 403）——
                            //    这一页本来就只有派单员进得来。
                            category = draftCategory,
                        )
                    )
                    onSaved("已更新账号：" + draftPhone.trim())
                }
                showSheet = false
                load()
            } catch (e: Exception) {
                // 保存失败 → **抽屉里**那一行红字（不是页面级 error：那会把整页列表顶掉）
                saveError = toApiException(e).message
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
                // 提示里的号码走 `rosterPhoneOf`（2026-10-03 · E2E 报告 P1）：「恢复时撞号」
                // 那种账号是**活的**（所以卡上给的是「启用/停用」），而它的 `phone` 仍带着
                // `_del{id}` 后缀 —— 「已启用：13900001234_del160」就是乱码（与 P1 同一件事）。
                // 号码真的已经归别人时（phone_display 为 null）就报姓名，⛔ 不许把后缀端出来。
                val who = rosterPhoneOf(u) ?: u.fullName.ifBlank { u.username }
                actionResult = if (u.isActive) "已停用：" + who else "已启用：" + who
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            }
        }
    }

    /**
     * 把回收站里的账号**放回来**（E2E 报告 P1/P2）。
     *
     * 为什么不能拿「启用」凑合：后端对回收站账号的「启用」直接 400 ——
     * `users.py` 里写着「这个账号在回收站里（删号时手机号已经释放给别的账号用了），
     * 「启用」不会把手机号还回来 —— 请用「恢复」把它放回来」。
     * 界面原来给回收站账号画的是「启用」，点下去只会吃一句后端报错，
     * 所以卡面按 [UserDto.isDeleted] 分成两种动作：回收站 → 「恢复」，停用 → 「启用」。
     *
     * ⚠️ 恢复**不一定**能把号码还回来：删号之后若有人拿同一个号建了新号，
     * 后端只还身份、号码留给新主人（`restore_user` 的冲突分支），
     * 此时 `phone_display` 是 null —— 提示里就报姓名，⛔ 不许把 `_del{id}` 后缀端出来。
     */
    fun restore(u: UserDto) {
        viewModelScope.launch {
            try {
                val back = container.repo.restoreUser(u.id)
                actionResult = "已恢复：" +
                    (rosterPhoneOf(back) ?: back.fullName.ifBlank { back.username })
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
                // 同上：报号的文案一律走 `rosterPhoneOf`，别把 `_del{id}` 端给用户。
                actionResult = "已删除：" + (rosterPhoneOf(u) ?: u.fullName.ifBlank { u.username })
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
