package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.UserDto
import com.tapmoay.sorders.data.remote.dto.VehicleCreateRequest
import com.tapmoay.sorders.data.remote.dto.VehicleDto
import com.tapmoay.sorders.data.remote.dto.VehicleUpdateRequest
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.DriverLime
import com.tapmoay.sorders.ui.theme.MessageRed
import com.tapmoay.sorders.ui.theme.NavBlue
import com.tapmoay.sorders.ui.theme.OnDriverLime
import com.tapmoay.sorders.ui.theme.Success
import com.tapmoay.sorders.ui.theme.WarningAmber
import kotlinx.coroutines.launch
import com.tapmoay.sorders.ui.common.Hint

/**
 * 车辆管理（v3.44）——**司机与车辆的绑定在这里落地**。
 *
 * ## 为什么要有这一屏
 * 用户原话：「司机的车辆绑定，App 端做不到」。事实是：后端有 `vehicles.driver_id`，
 * 但 App 只有「新增车辆」一条路（在账本管理的角落里），
 * **没有编辑、没有解绑、没有从司机视角绑车** —— 想把一辆车从张三名下拿下来，
 * 只能去改数据库。而 AI 那边有 `vehicle.update`，于是出现"AI 能做、人做不到"的倒挂。
 *
 * ## 一色一功能
 * 车辆沿用「司机管理」的黄绿（[VehicleAccent]）：它们是同一件事（司机团队与他们的车），
 * 跨屏同功能同色。**车型不再各给一色** —— 那会让这一屏出现四种颜色，
 * 而它们回答的是同一个问题（"这是辆什么车"）。车型用文字标签区分。
 *
 * ## 三个刻意的取舍
 * 1. **绑司机不在这里做**（编辑弹层里做）：`POST /vehicles/{id}/driver` 是唯一落点，
 *    卡片上的「司机」那一行点开就是编辑弹层，不另开一层弹层（嵌套弹层在 Compose 里会闪）。
 * 2. **不做删除，只做停用**：车牌会出现在记账/油耗选车的地方，
 *    删掉之后那些历史记录就再也对不上号了；停用能达到同样效果且可回退。
 *    弹层里写明了这句话，否则用户会一直找那个不存在的删除键。
 * 3. **改车牌/车型与绑司机是两次请求**：前者 `PATCH`，后者专用接口。
 *    所以**部分成功必须如实说**（"车辆信息已保存，但司机没绑上：…"），
 *    不许合并成一句"保存失败"——那会让用户重试一次已经成功的操作。
 */

/**
 * 车辆域的语义色：与「司机管理」同色（黄绿）。
 *
 * ⚠️ 值本身住在 `ui/theme/Color.kt::DriverLime`（就是规范 §2 模块色表里「司机管理」那一格）——
 * 2026-10-04 之前这个值在三个文件里手写了五遍，改色时总会漏一处。这里只回答
 * 「这一页用哪个色」，不再回答「这个色是多少」。
 */
internal val VehicleAccent = Color(DriverLime)

internal fun vehicleTypeLabel(t: String?): String = when (t) {
    "small" -> "小货车"
    "large" -> "大货车"
    "trailer" -> "挂车"
    else -> "未设置车型"
}

/**
 * 车型下拉的取值（顺序＝界面顺序）。
 *
 * **小货车排第一**：它是名册里最多的车型（本机 `vehicles` 表 small 11 / large 3 / trailer 1），
 * 而且下拉第一项就是 [DEFAULT_VEHICLE_TYPE] —— 新建车辆时用户不动这一格也不会建错。
 * 原来默认「挂车」且挂车排第一，不注意就会建错车型（E2E 走查 P11）。
 *
 * ⛔ 取值集**一个字不许扩**：这三档是**计费口径**（司机计费规则 / 运费模板都按它匹配），
 * 顺序可以改，档位不许加（`_tools/qa/_check_vehicle_attrs.py` 钉着）。
 */
internal val VEHICLE_TYPES = listOf("small" to "小货车", "large" to "大货车", "trailer" to "挂车")

/**
 * 新建车辆的默认车型 ＝ 下拉第一项。
 *
 * ⛔ 不要另写字面量：默认值与下拉第一项**必须同源**，否则把顺序换个位置之后，
 * "默认那一个"就会悄悄变成一个不在第一项上的值。
 */
internal val DEFAULT_VEHICLE_TYPE = VEHICLE_TYPES.first().first

class VehicleManageViewModel(private val container: AppContainer) : ViewModel() {

    var vehicles by mutableStateOf<List<VehicleDto>>(emptyList())
    var drivers by mutableStateOf<List<UserDto>>(emptyList())
    var loading by mutableStateOf(false)
    var loadError by mutableStateOf<String?>(null)
    var actionResult by mutableStateOf<String?>(null)
    var query by mutableStateOf("")

    // ---- 新增/编辑弹层 ----
    var sheetOpen by mutableStateOf(false)
    var editingId by mutableStateOf<Long?>(null)
    var draftPlate by mutableStateOf("")
    var draftType by mutableStateOf(DEFAULT_VEHICLE_TYPE)
    var draftDriverId by mutableStateOf<Long?>(null)
    var draftActive by mutableStateOf(true)
    /**
     * **车身型式**（`VehicleAttrs.kt` 里 BODY_CHOICES 的键；空串 = 未设置）。
     *
     * ⚠️ 它与上面的 [draftType]（车型：小货车 / 大货车 / 挂车）**不是一回事**：
     * 那个是**计费口径**（司机计费规则 / 运费模板共用，取值一个字不许扩），
     * 这个只决定**这辆车能填哪些属性**。
     */
    var draftBody by mutableStateOf("")
    /** 分类（左栏分组，2026-10-05）：只影响车辆管理页左栏怎么分组，⛔ 不参与计费。 */
    var draftCategory by mutableStateOf("")
    /** 车辆属性（键 → 用户填的原文）。空串 = 这一项没填，保存前会被剔掉。 */
    var draftAttrs by mutableStateOf<Map<String, String>>(emptyMap())
    /** 换车身型式时"哪几项被去掉了"——⛔ 静默丢掉用户填过的数是最不该发生的一种。 */
    var bodyNote by mutableStateOf<String?>(null)
    var driverQuery by mutableStateOf("")
    var saving by mutableStateOf(false)
    var sheetError by mutableStateOf<String?>(null)

    /** 解绑二次确认（不是日常操作，但按错一次就得重新绑，所以给一次确认）。 */
    var confirmUnbind by mutableStateOf<VehicleDto?>(null)

    val editing: Boolean get() = editingId != null

    fun load() {
        loading = vehicles.isEmpty()
        loadError = null
        viewModelScope.launch {
            try {
                vehicles = container.repo.vehicles()
                drivers = container.repo.drivers()
            } catch (e: Exception) {
                loadError = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    /**
     * 车牌 → 现在挂在谁名下（卡片与选择器都要用；界面**不许自己拼**，只有这一处）。
     *
     * ⚠️ 找不到名字时**不能返回空串**：空串在界面上等于"没有司机"，
     * 而这里的情况恰恰是"有司机、只是他不在我拉到的名册里"（停用的账号 /
     * 老数据里绑了一个非司机账号）。那时卡片会显示「未绑司机」——
     * 用户看到的是"这车没人开"，真相是"绑着一个我认不出的人"，两件事差得很远。
     */
    fun driverNameOf(driverId: Long?): String {
        if (driverId == null) return ""
        val d = drivers.firstOrNull { it.id == driverId } ?: return "账号 #$driverId（不在司机名册里）"
        return d.fullName.ifBlank { d.phone.ifBlank { d.username } }
    }

    /** 搜索命中的车辆（车牌或司机名）。空搜索 = 全部。 */
    val shown: List<VehicleDto>
        get() {
            val q = query.trim()
            if (q.isEmpty()) return vehicles
            return vehicles.filter {
                it.plateNo.contains(q, ignoreCase = true) ||
                    driverNameOf(it.driverId).contains(q, ignoreCase = true)
            }
        }

    // ============================================================ 左栏分类（2026-10-05）
    //
    // 用户原话：「还有我们的账户管理司机管理货主管理批发商管理。车辆管理……在这个位置也加个分类，
    // 默认是显示，全部，同样也是左边侧边栏，然后左边侧边栏同样也是可以新增分类的」。
    //
    // 名册是 `vehicle_categories`（全局一份，挂在 `vehicles.category` 上）——
    // 与账号分类是**两份独立名册**（用户 2026-10-05 要的是两台各自管各自的）。
    // ⛔ 与 `vehicleType`（计费口径）/ `bodyType`（车身型式）三件事，这里只做分组。
    var categoryNames by mutableStateOf<List<String>>(emptyList())
        private set
    var railKey by mutableStateOf("")

    /** 左栏选了一类之后要显示的车（搜索与分类**同时**生效）。 */
    val shownInRail: List<VehicleDto> get() = inRail(shown, railKey) { it.category }

    /** 分类名册（读不到不影响列表：静默，左栏就只有「全部」一格）。 */
    fun loadCategories() {
        viewModelScope.launch {
            try {
                val names = container.repo.vehicleCategories().map { it.name }
                if (railKey.isNotBlank() && names.none { "c|" + it == railKey }) railKey = ""
                categoryNames = names
            } catch (_: Exception) {
            }
        }
    }

    fun openCreate() {
        editingId = null
        draftPlate = ""
        draftType = DEFAULT_VEHICLE_TYPE
        draftDriverId = null
        draftActive = true
        // 新车的车身型式默认「未设置」：⛔ 不替用户认一个（认错了，他就会在一个错误的表单上填一堆数）
        draftBody = ""
        draftCategory = ""
        draftAttrs = emptyMap()
        bodyNote = null
        driverQuery = ""
        sheetError = null
        sheetOpen = true
    }

    fun openEdit(v: VehicleDto) {
        editingId = v.id
        draftPlate = v.plateNo
        // 老数据里车型是空串（`_clean_type(...) or ""` 允许空）时落回默认那一档，
        // 而不是硬写「挂车」：用户一保存就会把空车型写成一个他从没选过的档。
        draftType = v.vehicleType.ifBlank { DEFAULT_VEHICLE_TYPE }
        draftDriverId = v.driverId
        draftActive = v.isActive
        draftBody = v.bodyType
        draftCategory = v.category
        // 后端只回**填过的**属性；这里整份接住，保存时再整份发回去（那正是后端的"整份替换"语义）。
        draftAttrs = v.attrs
        bodyNote = null
        driverQuery = ""
        sheetError = null
        sheetOpen = true
    }

    /** 改一项属性（输入框每次按键都走这里）。 */
    fun setAttr(key: String, value: String) {
        draftAttrs = draftAttrs + (key to value)
    }

    /**
     * 换车身型式：把**新型式不存在的那几项**从草稿里剔掉，并**把剔掉的写出来**。
     *
     * ⛔ 不静默丢：`cargo_height_m` 换到平板车之后连输入框都画不出来了 ——
     * 用户再也看不到那个数，"它还在不在"只能靠猜。所以要么当场说清，要么别动它；
     * 而"别动它"是不行的：后端会以"这不是平板车的属性"整份拒绝（那是**对的**，
     * 它拦的正是"型式与属性对不上"这种最难查的中间态）。
     */
    fun setBody(next: String) {
        if (next == draftBody) return
        val allowed = attrsFor(next).map { it.key }.toSet()
        val dropped = draftAttrs.filter { (k, v) -> k !in allowed && v.trim().isNotEmpty() }
        draftAttrs = draftAttrs.filterKeys { it in allowed }
        draftBody = next
        bodyNote = if (dropped.isEmpty()) {
            null
        } else {
            dropped.entries.joinToString("、") { (k, v) ->
                val f = VEHICLE_ATTR_FIELDS.firstOrNull { it.key == k }
                (if (f == null) k else attrTitle(f, next)) + " 原值 " + v + " 已去掉"
            } + " —— 新的车身型式没有这一项"
        }
    }

    /** 只把**填了的**那几项发给后端（空串 = 没填；后端把空串也当没填，但少传一个键更清楚）。 */
    fun filledAttrs(): Map<String, String> =
        draftAttrs.mapValues { it.value.trim() }.filterValues { it.isNotEmpty() }

    fun closeSheet() {
        if (saving) return
        sheetOpen = false
    }

    fun save() {
        val plate = draftPlate.trim()
        if (plate.isBlank()) {
            sheetError = "请输入车牌号"
            return
        }
        val id = editingId
        val before = if (id != null) vehicles.firstOrNull { it.id == id } else null
        saving = true
        sheetError = null
        viewModelScope.launch {
            try {
                if (id == null) {
                    val v = container.repo.createVehicle(
                        VehicleCreateRequest(
                            plateNo = plate,
                            vehicleType = draftType,
                            driverId = draftDriverId,
                            bodyType = draftBody,
                            category = draftCategory,
                            attrs = filledAttrs(),
                        ),
                    )
                    val who = driverNameOf(v.driverId)
                    actionResult = "已添加 " + v.plateNo + if (who.isEmpty()) "" else "，并绑给 $who"
                } else {
                    container.repo.updateVehicle(
                        id,
                        VehicleUpdateRequest(
                            plateNo = plate,
                            vehicleType = draftType,
                            isActive = draftActive,
                            bodyType = draftBody,
                            category = draftCategory,
                            // ⚠️ **整份**发回去（含空 map）：后端把"传了 attrs"定义成整份替换，
                            //    只发改动的那几个键 = 其余全部被清空。见 VehicleUpdateRequest 的注释。
                            attrs = filledAttrs(),
                        ),
                    )
                    var note = "已保存 " + plate
                    // 只有真的动了司机才发第二个请求（否则每存一次都白写一条绑车日志）
                    if (draftDriverId != before?.driverId) {
                        try {
                            container.repo.setVehicleDriver(id, draftDriverId)
                            note += if (draftDriverId == null) {
                                "，已解绑司机"
                            } else {
                                "，已绑给 " + driverNameOf(draftDriverId)
                            }
                        } catch (e: Exception) {
                            // ⚠️ 车辆信息**已经改成功**了，这里必须分开说。
                            //    合并成"保存失败"的话，用户会重试一次已经生效的改动。
                            note = "车辆信息已保存，但司机没绑上：" + toApiException(e).message
                        }
                    }
                    actionResult = note
                }
                sheetOpen = false
                load()
            } catch (e: Exception) {
                sheetError = toApiException(e).message
            } finally {
                saving = false
            }
        }
    }

    fun unbind(v: VehicleDto) {
        viewModelScope.launch {
            try {
                container.repo.setVehicleDriver(v.id, null)
                actionResult = v.plateNo + " 已解绑司机"
                load()
            } catch (e: Exception) {
                actionResult = "解绑失败：" + toApiException(e).message
            }
        }
    }

    fun toggleActive(v: VehicleDto) {
        viewModelScope.launch {
            try {
                container.repo.updateVehicle(v.id, VehicleUpdateRequest(isActive = !v.isActive))
                actionResult = (if (v.isActive) "已停用 " else "已启用 ") + v.plateNo
                load()
            } catch (e: Exception) {
                actionResult = toApiException(e).message
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun VehicleManageScreen(container: AppContainer, onBack: () -> Unit) {
    val vm: VehicleManageViewModel = appViewModel { VehicleManageViewModel(container) }
    val snackbar = remember { SnackbarHostState() }
    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })
    LaunchedEffect(Unit) {
        vm.load()
        vm.loadCategories()
    }

    // ---- 左栏分类（2026-10-05）----
    //
    // 用户原话：「还有我们的账户管理司机管理货主管理批发商管理。车辆管理……在这个位置也加个分类，
    // 默认是显示，全部，同样也是左边侧边栏，然后左边侧边栏同样也是可以新增分类的」。
    //
    // 形态照「地址与联系人」：**抽屉**（⛔ 不是商品管理那种常驻左栏 —— 用户 2026-09-19 的裁定是
    //「右边的卡片的信息被挤压了不是很好看」）。抽屉底部那格「管理分类」进分类管理面板。
    val drawer = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    val catVm: VehicleCategoriesViewModel = appViewModel { VehicleCategoriesViewModel(container) }
    var managingCategory by remember { mutableStateOf(false) }

    ModalNavigationDrawer(
        drawerState = drawer,
        drawerContent = {
            ModalDrawerSheet(modifier = Modifier.width(CategoryDrawerWidth)) {
                CategoryDrawerSheet(
                    title = "车辆分类",
                    // ⛔ 一格都不显示条数（用户 2026-09-19：「那个分组下面不要显示有多少条啊，
                    //    这是多余信息」）—— 条数只在「管理分类」那个面板里出现。
                    items = listOf(CategoryDrawerItem("", "全部")) +
                        catVm.rows.map { CategoryDrawerItem("c|" + it.name, it.name) },
                    selectedKey = vm.railKey,
                    accent = VehicleAccent,
                    manageLabel = "管理分类",
                    onPick = { key ->
                        vm.railKey = key
                        scope.launch { drawer.close() }
                    },
                    onManage = {
                        managingCategory = true
                        scope.launch { drawer.close() }
                    },
                )
            }
        },
    ) {
    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            AppTopBar(
                "车辆管理",
                onBack = onBack,
                actions = {
                    // 用户画的那个红框位置：标题右边那一格 —— 默认「全部」。
                    // 落位（用户 2026-10-05）：「与下面的卡片做一个右侧对齐」—— 这一页顶栏
                    // 右边只有它，胶囊就贴到右侧。`actions` 自带 4dp 右边距，这里再补 12dp
                    // = 卡片的 16dp 内边距（1080px 截图上量过：卡片右缘 16dp / 胶囊原先 4dp）
                    // —— 用户说「往左移一点」就是这 12dp。
                    CategoryTriggerChip(
                        current = railNameOf(vm.railKey),
                        accent = VehicleAccent,
                        onClick = { scope.launch { drawer.open() } },
                        modifier = Modifier.padding(end = 12.dp),
                    )
                },
            )
        },
        floatingActionButton = {
            ExtendedFloatingActionButton(
                onClick = { vm.openCreate() },
                containerColor = VehicleAccent,
                contentColor = Color(OnDriverLime),
                icon = { Icon(Icons.Default.Add, contentDescription = null) },
                text = { Text("新增车辆") },
            )
        },
    ) { padding ->
        if (managingCategory) {
            // 分类管理在**同一屏的第二层**（不新开路由）：照「地址与联系人」的
            // `CategoryManagePanel` 先例 —— 真机上新开一页会「抽屉先收起再弹整页、中间闪一下」。
            Box(Modifier.fillMaxSize().padding(padding)) {
                VehicleCategoriesPanel(
                    vm = catVm,
                    onBack = {
                        managingCategory = false
                        catVm.load()
                        vm.loadCategories()
                    },
                )
            }
        } else {
        Box(Modifier.fillMaxSize().padding(padding)) {
            when {
                vm.loading -> LoadingBox()
                vm.loadError != null -> ErrorView(vm.loadError.orEmpty(), onRetry = { vm.load() })
                else -> LazyColumn(
                    Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    item { VehicleSummary(vm) }
                    if (vm.vehicles.isNotEmpty()) {
                        item {
                            // 搜索框走全站那一个（规范 §4.4：放大镜 + 入框即出 ✕ 清空）。
                            // 提示语仍是本页自己的：这个框要搜的是**车牌**，不是姓名 / 手机号，
                            // 所以不套 UserSearch.HINT（那是"按人搜"那一份的默认话术）。
                            SearchField(
                                value = vm.query,
                                onValueChange = { vm.query = it },
                                placeholder = "搜车牌或司机",
                                modifier = Modifier.fillMaxWidth(),
                            )
                        }
                    }
                    if (vm.vehicles.isEmpty()) {
                        // ⛔ 别加固定高度（本页三处空态同一条，吃过 160dp 的亏）：EmptyView 肚子里的账是
                        //    「上下各 48dp 内边距 + 56dp 图标 + 12dp + 文案」，固定高度 160 只留 64dp 的内容盒，
                        //    图标就吃掉 56dp，Column 把剩下的额度从后面孩子身上扣光 → 文案被量成 0 高、
                        //    屏幕上只剩图标（2026-10-03 真机复测抓到）。
                        item { EmptyView("还没有登记车辆", Modifier.fillMaxWidth()) }
                    } else if (vm.railKey.isNotBlank() && vm.shownInRail.isEmpty()) {
                        // 这一类下真的没有车时**说出来**（不说的话用户看到一个空页面）
                        item {
                            EmptyView(
                                "「" + railNameOf(vm.railKey) + "」这一类下还没有车 —— " +
                                    "在卡片上编辑、或左栏换一格",
                                Modifier.fillMaxWidth(),
                            )
                        }
                    } else if (vm.shown.isEmpty()) {
                        item { EmptyView("没有匹配「${vm.query}」的车", Modifier.fillMaxWidth()) }
                    } else {
                        items(vm.shownInRail, key = { it.id }) { v ->
                            VehicleCard(
                                v = v,
                                driverName = vm.driverNameOf(v.driverId),
                                onEdit = { vm.openEdit(v) },
                                onUnbind = { vm.confirmUnbind = v },
                                onToggleActive = { vm.toggleActive(v) },
                            )
                        }
                    }
                    item { Spacer(Modifier.height(72.dp)) }
                }
            }
        }
        }
    }
    }

    if (vm.sheetOpen) {
        VehicleEditSheet(vm, catVm)
    }
    vm.confirmUnbind?.let { v ->
        DangerConfirmDialog(
            title = "解绑司机",
            message = "把 " + v.plateNo + " 从「" + vm.driverNameOf(v.driverId) +
                "」名下拿掉？他会变成没有车的司机（派单时可以照常派给他，但车辆台账里对不上号）。",
            confirmText = "解绑",
            onConfirm = {
                vm.confirmUnbind = null
                vm.unbind(v)
            },
            onDismiss = { vm.confirmUnbind = null },
        )
    }
}

@Composable
private fun VehicleSummary(vm: VehicleManageViewModel) {
    val bound = vm.vehicles.count { it.driverId != null }
    val off = vm.vehicles.count { !it.isActive }
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            TintedIcon(Icons.Default.LocalShipping, VehicleAccent, size = 20.dp, container = 38.dp)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text("车队", style = MaterialTheme.typography.titleMedium)
                Text(
                    "共 " + vm.vehicles.size + " 辆 · 已绑司机 " + bound + " · 未绑 " + (vm.vehicles.size - bound) +
                        if (off > 0) " · 停用 " + off else "",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        if (vm.vehicles.isNotEmpty() && bound < vm.vehicles.size) {
            Spacer(Modifier.height(8.dp))
            Text(
                "有 " + (vm.vehicles.size - bound) + " 辆车还没绑司机 —— 点开卡片里「司机」那一行就能绑。",
                style = MaterialTheme.typography.bodySmall,
                color = Color(WarningAmber),
            )
        }
    }
}

@Composable
private fun VehicleCard(
    v: VehicleDto,
    driverName: String,
    onEdit: () -> Unit,
    onUnbind: () -> Unit,
    onToggleActive: () -> Unit,
) {
    SectionCard(Modifier.clickable { onEdit() }) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            TintedIcon(Icons.Default.LocalShipping, VehicleAccent, size = 18.dp, container = 34.dp)
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        v.plateNo,
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                    )
                    Spacer(Modifier.width(8.dp))
                    MiniChip(vehicleTypeLabel(v.vehicleType), MaterialTheme.colorScheme.onSurfaceVariant)
                    // 车身型式（箱式车 / 平板车 / 自卸车 / 挂车）**另起一个 chip**：
                    // 它与左边那个"车型"是两件事 —— 那个决定怎么算钱，这个决定能填哪些属性。
                    // ⚠️ 用后端回的 bodyLabel，不查本地那张表（后端将来多一个取值时不会显示原始码）。
                    if (v.bodyLabel.isNotBlank()) {
                        Spacer(Modifier.width(6.dp))
                        MiniChip(v.bodyLabel, VehicleAccent)
                    }
                    if (!v.isActive) {
                        Spacer(Modifier.width(6.dp))
                        MiniChip("停用", MaterialTheme.colorScheme.error)
                    }
                }
                // 「这车能装多少」—— 只有量过的项才写；一项都没有时**整行不出现**
                // （⛔ 不写"载重 0 吨"：界面上"0 吨"与"没量过"是两件事）。
                val capacity = capacityText(v.attrs)
                if (capacity.isNotEmpty()) {
                    Text(
                        capacity,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
        Spacer(Modifier.height(10.dp))
        // 「司机」那一行本身就是绑车入口：点它 → 编辑弹层（弹层里就是司机选择）。
        Row(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp))
                .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f))
                .clickable { onEdit() }
                .padding(horizontal = 12.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                if (driverName.isEmpty()) Icons.Default.PersonOff else Icons.Default.Person,
                contentDescription = null,
                tint = if (driverName.isEmpty()) MaterialTheme.colorScheme.onSurfaceVariant else Success,
                modifier = Modifier.size(18.dp),
            )
            Spacer(Modifier.width(8.dp))
            Text(
                if (driverName.isEmpty()) "未绑司机" else driverName,
                style = MaterialTheme.typography.bodyMedium,
                color = if (driverName.isEmpty()) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.onSurface,
                modifier = Modifier.weight(1f),
            )
            Text(
                // 这一行只负责"点开编辑弹层"，所以说法也跟着变：解绑现在是卡片左下的
                // 圈底动作（见下面那张动作行），⛔ 别让入口写着解绑、点下去只是开弹层。
                if (driverName.isEmpty()) "点这里绑" else "换司机",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.primary,
            )
        }
        Spacer(Modifier.height(4.dp))

        // ---- 动作行（左＝相反 / 警示 · 右＝编辑）----
        // 规范 §4.2c：卡片上的**图标**动作一律做成"圈底图标"（ui/common/Components.kt::CardActionIcon），
        // 位置是 左＝反向 / 警示（警示放最左）、右＝编辑（惯用手是右手）。
        // 原来那个裸 IconButton 里的 18dp 铅笔正是用户点名「这个不行」的那一种：在信息很满的
        // 卡片上太轻、手指也不好找。
        // 带 label（圈底图标 + 文字）是跟「账户管理」学的：这一页的用户是派单员，
        // 要一眼看清按下去会发生什么，只留一个图标就逼人靠猜。
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            if (driverName.isNotEmpty()) {
                CardActionIcon(
                    icon = Icons.Default.LinkOff,
                    contentDescription = "解绑司机",
                    tint = Color(MessageRed),
                    onClick = onUnbind,
                    label = "解绑",
                    size = 15.dp,
                    container = 30.dp,
                )
            }
            CardActionIcon(
                icon = if (v.isActive) Icons.Default.Pause else Icons.Default.PlayArrow,
                contentDescription = if (v.isActive) "停用" else "启用",
                tint = if (v.isActive) Color(WarningAmber) else Success,
                onClick = onToggleActive,
                label = if (v.isActive) "停用" else "启用",
                size = 15.dp,
                container = 30.dp,
            )
            Spacer(Modifier.weight(1f))
            CardActionIcon(
                icon = Icons.Default.Edit,
                contentDescription = "编辑",
                tint = Color(NavBlue),
                onClick = onEdit,
                label = "编辑",
                size = 15.dp,
                container = 30.dp,
            )
        }
    }
}

@Composable
internal fun MiniChip(text: String, color: Color) {
    Surface(
        shape = MaterialTheme.shapes.small,
        color = color.copy(alpha = 0.12f),
    ) {
        Text(
            text,
            style = MaterialTheme.typography.labelMedium,
            color = color,
            modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun VehicleEditSheet(
    vm: VehicleManageViewModel,
    // 左栏分类名册（2026-10-05）：分类那一格是下拉，候选来自它。
    catVm: VehicleCategoriesViewModel,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    var driverOpen by remember { mutableStateOf(false) }
    // 两个下拉的展开态。车型与车身型式都是"从固定取值里选一个"——
    // 设计规范 §5：「下拉一律 `ExposedDropdownMenuBox` 点选回填，**不要**用点选 chips 替代下拉」。
    // 锚在 `FormPickRow` 上（先例 `ui/shipper/AddressScreen.kt` 的地点分组那两行），不用
    // `OutlinedTextField`：描边输入框会把白卡分组又变回"一堆矩形框浮在灰底上"（那正是这条规范要治的）。
    var typeMenu by remember { mutableStateOf(false) }
    var bodyMenu by remember { mutableStateOf(false) }
    ModalBottomSheet(onDismissRequest = { vm.closeSheet() }, sheetState = sheetState) {
        Column(
            Modifier
                .fillMaxWidth()
                .fillMaxHeight()
                .padding(horizontal = 16.dp)
                .imePadding()
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    if (vm.editing) "编辑车辆" else "新增车辆",
                    style = MaterialTheme.typography.titleLarge,
                    modifier = Modifier.weight(1f),
                )
                SheetCloseButton(onClick = { vm.closeSheet() })
            }
            // ---- 三个**白卡分组**（2026-09-22 用户定的全局规范）----
            // 原话：「…只是用**线框**框起来的话太不美观了…**这就是个设计规范，包括以后也是
            // 这样子啊，所有都要这样子去改**」。所以这一屏从"一串描边输入框浮在灰底上"改成
            // "每个分组一张白卡、卡里的行不画边框（值本身就是占位符）"，与「新增商品」「编辑线路」
            // 同一套行（`ui/common/FormRows.kt`）。
            // ⛔ 判据 `_tools/qa/_check_form_panel_style.py`：这一页的 `OutlinedTextField` 必须是 0。

            // ① 车牌 + 车型
            FormGroup(icon = Icons.Default.LocalShipping, title = "车辆", tint = Color(DriverLime)) {
                FormInputRow(
                    label = "车牌号",
                    value = vm.draftPlate,
                    onValueChange = { vm.draftPlate = it },
                    placeholder = "如 粤LUB6868",
                    // 车牌是这一屏**唯一必填**的（VM 里 save() 第一件事就是拦空车牌），
                    // 所以用 required 画红星，而不是把"必填"写进标签文字。
                    required = true,
                    icon = Icons.Default.LocalShipping,
                    iconTint = Color(DriverLime),
                )
                ExposedDropdownMenuBox(expanded = typeMenu, onExpandedChange = { typeMenu = it }) {
                    FormPickRow(
                        label = "车型",
                        value = vehicleTypeLabel(vm.draftType),
                        placeholder = "请选择",
                        icon = Icons.Default.LocalShipping,
                        iconTint = Color(DriverLime),
                        onClick = { typeMenu = true },
                        modifier = Modifier.menuAnchor(),
                    )
                    ExposedDropdownMenu(expanded = typeMenu, onDismissRequest = { typeMenu = false }) {
                        VEHICLE_TYPES.forEach { (k, label) ->
                            DropdownMenuItem(
                                text = { Text(label) },
                                onClick = { vm.draftType = k; typeMenu = false },
                            )
                        }
                    }
                }
            }
            Hint(
                "车型决定这辆车怎么算钱（司机计费规则与运费模板都按它匹配）。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 4.dp),
            )

            // ---------------- 车身型式 + 车辆属性（2026-09-27） ----------------
            //
            // 用户原话：「给一辆车**固定一个属性**……在**创建车辆的时候就需要填相应的属性**。
            // **不同的车型会需要填的属性是不同的**……别说有可能是个**平板车**、有可能是一个**自卸车**。」
            //
            // ⚠️ 这一块与上面那个"车型"**是两件事**，所以是两个选择器、两行提示语：
            //   车型＝怎么算钱（与司机计费规则共用，取值不许扩）；车身型式＝能填哪些属性（只这张台账用）。
            FormGroup(icon = Icons.Default.Straighten, title = "车身与属性", tint = Color(DriverLime)) {
                ExposedDropdownMenuBox(expanded = bodyMenu, onExpandedChange = { bodyMenu = it }) {
                    FormPickRow(
                        label = "车身型式",
                        // 空串 = 未设置，交给 placeholder 显示「未设置」（`vehicleTypeLabel` 那套只认车型）
                        value = bodyLabelOf(vm.draftBody),
                        placeholder = "未设置",
                        icon = Icons.Default.Straighten,
                        iconTint = Color(DriverLime),
                        onClick = { bodyMenu = true },
                        modifier = Modifier.menuAnchor(),
                    )
                    ExposedDropdownMenu(expanded = bodyMenu, onDismissRequest = { bodyMenu = false }) {
                        BODY_CHOICES.forEach { (k, label) ->
                            DropdownMenuItem(
                                text = { Text(label) },
                                // 走 setBody（不是直接给 draftBody 赋值）：换型式会把**新型式没有的那几项**
                                // 从草稿里剔掉，并把剔掉的写出来 —— 那几项在界面上已经画不出来，
                                // 不说不等于它没被丢掉。
                                onClick = { vm.setBody(k); bodyMenu = false },
                            )
                        }
                    }
                }
                // 这两句必须紧贴它们讲的那些行：第一句说的是"下面这些行为什么是这几行"，
                // 第二句说的是"这些数填来干什么、不填会怎样"。
                Hint(
                    "决定下面能填哪些属性。选错了会填出一批这辆车根本没有的项，所以按行驶证/实车选。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Hint(
                    // ⛔ 界面文案里不许有 Markdown 记号（`_check_ai_guardrails.py` 那一组钉着）：
                    //    这里的字会**原样**画在屏幕上，`**粗体**` 会把星号一起显示出来。
                    "这些是这辆车的固有属性，建车时填一次。载重 / 容积以后要用来算「一车 = 多少方 / 多少吨」；" +
                        "其余是台账信息，不影响任何金额。没量过的留空，别随便填一个数。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                // **一项一行**（原来两列一行）：标签**必须带量纲**（"车高(米)"）—— 不带单位时
                // 4 与 400 在界面上都像是对的；而半栏宽塞不下"净重(吨)"这种标签再加右边一个数，
                // 原来两列那一版在窄屏上正是把标签挤成两行。
                attrsFor(vm.draftBody).forEach { f ->
                    FormInputRow(
                        label = attrTitle(f, vm.draftBody),
                        value = vm.draftAttrs[f.key].orEmpty(),
                        onValueChange = { vm.setAttr(f.key, it) },
                        placeholder = "没量过就留空",
                        keyboardType = if (f.integer) KeyboardType.Number else KeyboardType.Decimal,
                    )
                }
            }
            vm.bodyNote?.let {
                Text(it, style = MaterialTheme.typography.bodySmall, color = Color(WarningAmber))
            }

            // ③ 绑的司机 + 启用
            FormGroup(icon = Icons.Default.Person, title = "司机与状态", tint = Color(NavBlue)) {
                // 司机那一行原来是一整块自绘的圆角灰条（clip + background + clickable）——
                // 那是白卡之前的老画法；现在它就是一个 FormRow（自带内嵌浅色卡 + 可点）。
                FormRow(label = "绑的司机", onClick = { driverOpen = !driverOpen }) {
                    Text(
                        vm.driverNameOf(vm.draftDriverId).ifEmpty { "不绑司机" },
                        style = MaterialTheme.typography.bodyLarge,
                        color = if (vm.draftDriverId == null) MaterialTheme.colorScheme.onSurfaceVariant
                        else MaterialTheme.colorScheme.onSurface,
                    )
                    Spacer(Modifier.width(6.dp))
                    Icon(
                        if (driverOpen) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(20.dp),
                    )
                }
                if (driverOpen) {
                    // 按人搜 = 走共用 SearchField，连提示语都取默认那一份（UserSearch.HINT），
                    // 这样"后 4 位也行"这件事全 App 只有一处说明。
                    SearchField(
                        value = vm.driverQuery,
                        onValueChange = { vm.driverQuery = it },
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(Modifier.height(6.dp))
                    DriverPickList(vm)
                }

                if (vm.editing) {
                    // 启用 / 停用就是一个开关行（原来是自己拼的"文字 + Switch"一行）
                    FormSwitchRow(
                        label = "启用",
                        checked = vm.draftActive,
                        onCheckedChange = { vm.draftActive = it },
                    )
                }
            }
            if (vm.editing) {
                Hint(
                    "停用后不再派活；车牌要留在历史记录里，所以不给删。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = 4.dp),
                )
            }

            // ④ 分类（左栏分组，2026-10-05）：只影响车辆管理页左栏怎么分组，
            //    ⛔ 与上面的车型（计费口径）、车身型式（能填哪些属性）是三件事。
            FormGroup(icon = Icons.Default.Folder, title = "分类", tint = Color(DriverLime)) {
                CategoryPickRow(
                    vm = catVm,
                    selected = vm.draftCategory,
                    onPick = { vm.draftCategory = it },
                    hint = "只影响车辆管理页左栏怎么分组；给车队分组用的，不参与任何计费。",
                )
            }

            // 表单的错画在**表单里**（规范 §4.8 / FormErrorLine）：写成页面级错误的话，
            // "保存被拦下"会变成"整页列表全没了"（这一页的列表在抽屉底下）。
            FormErrorLine(vm.sheetError)

            // 底部一条栏放「取消 / 保存」（与「编辑线路」那个抽屉同一版式）
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    onClick = { vm.closeSheet() },
                    modifier = Modifier.weight(1f).height(48.dp),
                ) { Text("取消") }
                // ⚠️ 黄绿底上的字必须是**深橄榄**（OnDriverLime）：白字对黄绿只有约 1.4:1，
                //    与卡片上那三枚圈底图标、右下那颗 FAB 同一条理由（原来这里走
                //    PrimaryActionButton，它把字色写死成白色 —— 所以那行字在真机上是发灰的）。
                Button(
                    onClick = { vm.save() },
                    enabled = !vm.saving,
                    modifier = Modifier.weight(1f).height(48.dp),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = VehicleAccent,
                        contentColor = Color(OnDriverLime),
                    ),
                ) { Text(if (vm.saving) "保存中…" else "保存") }
            }
            Spacer(Modifier.height(24.dp))
        }
    }
}

/** 司机候选列表（弹层内展开）。**截断必须说出来**，不能安静地少给。 */
@Composable
private fun DriverPickList(vm: VehicleManageViewModel) {
    // 搜索规则走唯一实现（`core/UserSearch`）：姓名 / 手机号 / **手机号后 4 位**。
    // ⚠️ 原来这里是就地写的一遍「姓名 or 手机号 or 用户名」—— 与后端 `?q=`（只认姓名/手机号）
    //    和名册页那个搜索框合起来是**三条口径**；同一件事三个答案，用户只会觉得
    //    "有时搜得到、有时搜不到"，而看不出是规则不一致。
    val hits = com.tapmoay.sorders.core.UserSearch.filter(
        vm.drivers,
        vm.driverQuery,
        // 传的是**界面上显示的那个名字**（空名回落到用户名），保证"看得见的就能搜到"
        { it.fullName.ifBlank { it.username } },
        { it.phone },
    )
    // ⛔ **已停用 / 已删除的账号不进候选**（2026-10-03 · E2E 报告 P10）：原来停用的账号也能绑车，
    //    绑完这辆车就成了「有司机、但派单派不出去」—— 当时界面上只在副标题里写了四个字，拦不住人。
    //    要绑谁先到「账户管理」里把人启用（⛔ 不是在这里悄悄放行）。
    val eligible = hits.filter { it.isActive && !it.isDeleted }
    // 被挡在外面的**数量**要在下面说出来，不能让人看到空列表还以为「搜不到这个司机」。
    val excluded = hits.size - eligible.size
    val shown = eligible.take(30)
    Column(Modifier.fillMaxWidth().heightIn(max = 240.dp).verticalScroll(rememberScrollState())) {
        PickRow("不绑司机", vm.draftDriverId == null, "解绑（这辆车暂时不归任何人）") { vm.draftDriverId = null }
        shown.forEach { d ->
            // 名字回落也不许端出 `_del{id}` 后缀（与 P1 同一件事）。
            val name = d.fullName.ifBlank { rosterPhoneOf(d) ?: ROSTER_PHONE_TAKEN }
            val other = vm.vehicles.filter { it.driverId == d.id }
            PickRow(
                name,
                vm.draftDriverId == d.id,
                when {
                    // 「已停用」那一支不用写了：上面的 eligible 已经把停用/删除的挡在外面（P10）。
                    other.isNotEmpty() -> "他名下已经有 " + other.joinToString("、") { it.plateNo }
                    else -> rosterPhoneOf(d) ?: ROSTER_PHONE_TAKEN
                },
            ) { vm.draftDriverId = d.id }
        }
        if (eligible.size > shown.size) {
            Text(
                "还有 " + (eligible.size - shown.size) + " 个没显示 —— 输入姓名或手机号缩小范围。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(vertical = 8.dp),
            )
        }
        // 搜到了人、却一个能绑的都没有 —— 必须说清是「人被停用了」，
        // ⛔ 不能显示成「没有这个司机」（用户会跑去建重复账号）。
        if (eligible.isEmpty()) {
            Text(
                if (hits.isEmpty()) {
                    "没有匹配「" + vm.driverQuery.trim() + "」的司机。"
                } else {
                    "匹配到 " + hits.size + " 个司机，但他们都是已停用/已删除的账号 —— 先把人在「账户管理」里启用。"
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(vertical = 8.dp),
            )
        }
        // 有能绑的、也有被挡在外面的：挡了几个也要说（P10），否则用户以为「能绑的就这几个人」。
        if (excluded > 0 && eligible.isNotEmpty()) {
            Text(
                "另有 " + excluded + " 个匹配的司机是已停用/已删除的账号，不在这里 —— 先把人在「账户管理」里启用。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(vertical = 8.dp),
            )
        }
    }
}

// ⚠️ 这里原来还有一个 `PickChip`（"选中 = 黄绿底 + 深橄榄字"的小块），
//    车型与车身型式两排都改走下拉（设计规范 §5）之后，它在本仓库一个使用方都没有了 ——
//    留着一个没人用的"第二套选择控件"，下一个人会照着它再写一遍 chips 冒充下拉。

/**
 * **给某个司机选一辆车**（司机管理页用；和车辆管理是同一个动作的另一个视角）。
 *
 * 为什么要有这一面：用户想的是"张三开哪辆车"，而不是"这辆车归谁"。
 * 两个视角都必须能改，但**落点是同一条接口**（`POST /vehicles/{id}/driver`），
 * 所以两边的校验、日志、错误文案完全一致。
 *
 * ⚠️ 选一辆**已经挂在别人名下**的车，含义是"把它改挂过来"——
 * 这件事必须写在那一行上（"现在挂在李四名下"），否则用户以为是在"新增一辆车给他"，
 * 而实际上李四那边会**少一辆车**。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun VehiclePickerSheet(
    driverName: String,
    vehicles: List<VehicleDto>,
    currentIds: Set<Long>,
    driverNameOf: (Long?) -> String,
    busy: Boolean,
    onPick: (Long?) -> Unit,
    onDismiss: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    var q by remember { mutableStateOf("") }
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 20.dp).padding(bottom = 24.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("给「$driverName」配车", style = MaterialTheme.typography.titleLarge)
                    Hint(
                        "一辆车同时只能归一个司机。选了别人名下的车 = 改挂过来。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                SheetCloseButton(onClick = onDismiss)
            }
            Spacer(Modifier.height(12.dp))
            // 与列表页同一个搜索框控件（规范 §4.4）；提示语仍是本页自己的：这个框搜的是车牌。
            SearchField(
                value = q,
                onValueChange = { q = it },
                placeholder = "搜车牌",
                enabled = !busy,
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(8.dp))
            val hits = vehicles.filter { q.isBlank() || it.plateNo.contains(q.trim(), ignoreCase = true) }
            Column(Modifier.fillMaxWidth().heightIn(max = 380.dp).verticalScroll(rememberScrollState())) {
                if (currentIds.isNotEmpty()) {
                    PickRow("不绑车（解绑）", false, "把他名下这 " + currentIds.size + " 辆车都拿掉", enabled = !busy) {
                        onPick(null)
                    }
                }
                hits.forEach { v ->
                    val holder = driverNameOf(v.driverId)
                    val mine = v.id in currentIds
                    PickRow(
                        v.plateNo + "（" + vehicleTypeLabel(v.vehicleType) + "）",
                        mine,
                        when {
                            mine -> "就是他现在这辆"
                            holder.isNotEmpty() -> "现在挂在 " + holder + " 名下 —— 选它会把车改挂过来"
                            !v.isActive -> "已停用 · 目前没有司机"
                            else -> "目前没有司机"
                        },
                        warn = !mine && holder.isNotEmpty(),
                        enabled = !busy,
                    ) { onPick(v.id) }
                }
                if (hits.isEmpty()) {
                    Text(
                        if (vehicles.isEmpty()) "还没有登记任何车辆 —— 去「车辆管理」里先加一辆。"
                        else "没有匹配「$q」的车。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(vertical = 10.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun PickRow(
    title: String,
    selected: Boolean,
    subtitle: String,
    warn: Boolean = false,
    enabled: Boolean = true,
    onClick: () -> Unit,
) {
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp))
            .background(if (selected) MaterialTheme.colorScheme.primary.copy(alpha = 0.10f) else Color.Transparent)
            .clickable(enabled = enabled) { onClick() }
            .padding(horizontal = 10.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyMedium)
            if (subtitle.isNotBlank()) {
                Text(
                    subtitle,
                    style = MaterialTheme.typography.labelMedium,
                    // 「他名下已经有 X 辆车」这类提醒：用提醒色，不借账本的金橙（借色的
                    // 后果是同一个颜色在这一页表示两件事）。
                    color = if (warn) Color(WarningAmber) else MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        if (selected) Icon(Icons.Default.Check, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(18.dp))
    }
}
