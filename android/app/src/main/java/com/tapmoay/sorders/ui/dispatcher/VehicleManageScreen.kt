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
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.ui.theme.Success
import kotlinx.coroutines.launch

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

/** 车辆域的语义色：与「司机管理」同色（黄绿）。 */
internal val VehicleAccent = Color(0xFFCDDC39)

internal fun vehicleTypeLabel(t: String?): String = when (t) {
    "small" -> "小货车"
    "large" -> "大货车"
    "trailer" -> "挂车"
    else -> "未设置车型"
}

/** 车型下拉的取值（顺序＝界面顺序：挂车最常见，排第一）。 */
internal val VEHICLE_TYPES = listOf("trailer" to "挂车", "large" to "大货车", "small" to "小货车")

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
    var draftType by mutableStateOf("trailer")
    var draftDriverId by mutableStateOf<Long?>(null)
    var draftActive by mutableStateOf(true)
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

    fun openCreate() {
        editingId = null
        draftPlate = ""
        draftType = "trailer"
        draftDriverId = null
        draftActive = true
        driverQuery = ""
        sheetError = null
        sheetOpen = true
    }

    fun openEdit(v: VehicleDto) {
        editingId = v.id
        draftPlate = v.plateNo
        draftType = v.vehicleType.ifBlank { "trailer" }
        draftDriverId = v.driverId
        draftActive = v.isActive
        driverQuery = ""
        sheetError = null
        sheetOpen = true
    }

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
                    val v = container.repo.createVehicle(VehicleCreateRequest(plate, draftType, draftDriverId))
                    val who = driverNameOf(v.driverId)
                    actionResult = "已添加 " + v.plateNo + if (who.isEmpty()) "" else "，并绑给 $who"
                } else {
                    container.repo.updateVehicle(
                        id,
                        VehicleUpdateRequest(plateNo = plate, vehicleType = draftType, isActive = draftActive),
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
    LaunchedEffect(Unit) { vm.load() }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = { AppTopBar("车辆管理", onBack = onBack) },
        floatingActionButton = {
            ExtendedFloatingActionButton(
                onClick = { vm.openCreate() },
                containerColor = VehicleAccent,
                contentColor = Color(0xFF3A3F00),
                icon = { Icon(Icons.Default.Add, contentDescription = null) },
                text = { Text("新增车辆") },
            )
        },
    ) { padding ->
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
                            SoTextField(
                                value = vm.query,
                                onValueChange = { vm.query = it },
                                placeholder = "搜车牌或司机",
                                modifier = Modifier.fillMaxWidth(),
                            )
                        }
                    }
                    if (vm.vehicles.isEmpty()) {
                        item { EmptyView("还没有登记车辆", Modifier.fillMaxWidth().height(160.dp)) }
                    } else if (vm.shown.isEmpty()) {
                        item { EmptyView("没有匹配「${vm.query}」的车", Modifier.fillMaxWidth().height(160.dp)) }
                    } else {
                        items(vm.shown, key = { it.id }) { v ->
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

    if (vm.sheetOpen) {
        VehicleEditSheet(vm)
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
                color = Color(MoneyOrange),
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
                    if (!v.isActive) {
                        Spacer(Modifier.width(6.dp))
                        MiniChip("停用", MaterialTheme.colorScheme.error)
                    }
                }
            }
            IconButton(onClick = onEdit) {
                Icon(Icons.Default.Edit, contentDescription = "编辑", modifier = Modifier.size(18.dp))
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
                if (driverName.isEmpty()) "点这里绑" else "换 / 解绑",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.primary,
            )
        }
        Spacer(Modifier.height(4.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = onToggleActive, contentPadding = PaddingValues(horizontal = 8.dp)) {
                Text(if (v.isActive) "停用" else "启用", color = if (v.isActive) MaterialTheme.colorScheme.error else Success)
            }
            if (driverName.isNotEmpty()) {
                TextButton(onClick = onUnbind, contentPadding = PaddingValues(horizontal = 8.dp)) {
                    Text("解绑司机")
                }
            }
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
private fun VehicleEditSheet(vm: VehicleManageViewModel) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    var driverOpen by remember { mutableStateOf(false) }
    ModalBottomSheet(onDismissRequest = { vm.closeSheet() }, sheetState = sheetState) {
        Column(
            Modifier.fillMaxWidth().padding(horizontal = 20.dp).padding(bottom = 24.dp)
                .verticalScroll(rememberScrollState()),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    if (vm.editing) "编辑车辆" else "新增车辆",
                    style = MaterialTheme.typography.titleLarge,
                    modifier = Modifier.weight(1f),
                )
                SheetCloseButton(onClick = { vm.closeSheet() })
            }
            Spacer(Modifier.height(12.dp))
            OutlinedTextField(
                value = vm.draftPlate,
                onValueChange = { vm.draftPlate = it },
                label = { Text("车牌号") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(14.dp))
            Text("车型", style = MaterialTheme.typography.labelLarge)
            Spacer(Modifier.height(6.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                VEHICLE_TYPES.forEach { (k, label) ->
                    PickChip(label, vm.draftType == k) { vm.draftType = k }
                }
            }

            Spacer(Modifier.height(16.dp))
            Text("绑的司机", style = MaterialTheme.typography.labelLarge)
            Spacer(Modifier.height(6.dp))
            Row(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp))
                    .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f))
                    .clickable { driverOpen = !driverOpen }
                    .padding(horizontal = 12.dp, vertical = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    vm.driverNameOf(vm.draftDriverId).ifEmpty { "不绑司机" },
                    style = MaterialTheme.typography.bodyMedium,
                    color = if (vm.draftDriverId == null) MaterialTheme.colorScheme.onSurfaceVariant
                    else MaterialTheme.colorScheme.onSurface,
                    modifier = Modifier.weight(1f),
                )
                Icon(
                    if (driverOpen) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
                    contentDescription = null,
                    modifier = Modifier.size(20.dp),
                )
            }
            if (driverOpen) {
                Spacer(Modifier.height(8.dp))
                SoTextField(
                    value = vm.driverQuery,
                    onValueChange = { vm.driverQuery = it },
                    placeholder = com.tapmoay.sorders.core.UserSearch.HINT,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(6.dp))
                DriverPickList(vm)
            }

            if (vm.editing) {
                Spacer(Modifier.height(16.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("启用", style = MaterialTheme.typography.bodyMedium)
                        Text(
                            "停用后这辆车还在台账里（车牌会出现在记账/油耗的历史记录里，所以不提供删除），只是不再派活给它。",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Switch(checked = vm.draftActive, onCheckedChange = { vm.draftActive = it })
                }
            }

            vm.sheetError?.let {
                Spacer(Modifier.height(10.dp))
                Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
            }
            Spacer(Modifier.height(16.dp))
            PrimaryActionButton(
                text = if (vm.saving) "保存中…" else "保存",
                onClick = { vm.save() },
                enabled = !vm.saving,
                containerColor = Color(0xFFCDDC39),
                modifier = Modifier.fillMaxWidth(),
            )
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
    val shown = hits.take(30)
    Column(Modifier.fillMaxWidth().heightIn(max = 240.dp).verticalScroll(rememberScrollState())) {
        PickRow("不绑司机", vm.draftDriverId == null, "解绑（这辆车暂时不归任何人）") { vm.draftDriverId = null }
        shown.forEach { d ->
            val name = d.fullName.ifBlank { d.phone.ifBlank { d.username } }
            val other = vm.vehicles.filter { it.driverId == d.id }
            PickRow(
                name,
                vm.draftDriverId == d.id,
                when {
                    !d.isActive -> "已停用的账号"
                    other.isNotEmpty() -> "他名下已经有 " + other.joinToString("、") { it.plateNo }
                    else -> d.phone
                },
            ) { vm.draftDriverId = d.id }
        }
        if (hits.size > shown.size) {
            Text(
                "还有 " + (hits.size - shown.size) + " 个没显示 —— 输入姓名或手机号缩小范围。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(vertical = 8.dp),
            )
        }
        if (hits.isEmpty()) {
            Text(
                "没有匹配「" + vm.driverQuery.trim() + "」的司机。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(vertical = 8.dp),
            )
        }
    }
}

@Composable
internal fun PickChip(text: String, selected: Boolean, onClick: () -> Unit) {
    Surface(
        shape = MaterialTheme.shapes.small,
        color = if (selected) VehicleAccent else MaterialTheme.colorScheme.surfaceVariant,
        modifier = Modifier.clickable { onClick() },
    ) {
        Text(
            text,
            style = MaterialTheme.typography.bodyMedium,
            color = if (selected) Color(0xFF3A3F00) else MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 8.dp),
        )
    }
}

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
                    Text(
                        "一辆车同时只能归一个司机。选了别人名下的车 = 改挂过来。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                SheetCloseButton(onClick = onDismiss)
            }
            Spacer(Modifier.height(12.dp))
            SoTextField(
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
                    color = if (warn) Color(MoneyOrange) else MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        if (selected) Icon(Icons.Default.Check, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(18.dp))
    }
}
