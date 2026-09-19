package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.data.remote.dto.UserDto
import com.tapmoay.sorders.data.remote.dto.VehicleDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.ui.theme.Success
import com.tapmoay.sorders.util.formatMoney

/**
 * 账号管理（司机 / 货主 / 批发商三池共用一个界面）。
 *
 * ## v3.44 的改动：司机池多了一条"车辆"线
 * 用户原话是「给司机管理做一个合理且美观的界面布局」，落点其实是**信息缺了一整块**：
 * 一个司机卡片上原本看不到「他开哪辆车」，而"哪辆车归谁"恰恰是派单时第一个要看的东西。
 * 现在司机卡片上多一行**车辆行**（点一下就配车/换车/解绑），顶部多一条**车队摘要**
 * （共几人、几个已配车、几个没配），列表多一个**搜索框**（姓名/手机号/车牌）——
 * 288 个司机的列表没有搜索是没法用的。
 *
 * ## 三个"丑"的具体来源（这一轮逐条改掉）
 * 1. **没有头像块**：所有卡片都是"几行字"，扫一眼分不出谁是谁。
 *    现在左侧一个**姓氏圆底**（颜色按池分：司机黄绿 / 货主蓝 / 批发商金），
 *    与顶部的角色徽章同色系。
 * 2. **操作按钮挤成一行**：`设为批发商 / 转货主 / 停用` 三个文字键平铺，
 *    误触率高（"停用"和"转货主"挨着）。现在**危险的那个靠右**，且中间留弹性空位。
 * 3. **行尾只有一个铅笔**：看不出"点整张卡"能不能编辑。现在整卡可点 + 行尾图标保持一致。
 *
 * ## 一个刻意的边界
 * **改车辆（车牌/车型/停用/谁没配车）不在这一屏做**，它在「车辆管理」页——
 * 这一屏只做"给这个人配哪辆车"（司机视角）。两个视角改的是同一条接口，
 * 但混在一屏会让"这辆车现在归谁"和"这个人现在开哪辆"两件事互相打架。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun UsersManageScreen(
    container: AppContainer,
    pool: UserPool,
    onBack: () -> Unit,
    onOpenPricing: (UserDto) -> Unit = {},
    onOpenVehicles: () -> Unit = {},
) {
    val vm: UsersManageViewModel = appViewModel { UsersManageViewModel(container, pool) }
    val snackbar = remember { SnackbarHostState() }

    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = { Text(pool.title) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    if (pool == UserPool.MEMBERS) {
                        TextButton(onClick = { vm.openBatch() }) {
                            Icon(Icons.Default.Edit, contentDescription = null, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(4.dp))
                            Text("批量调价", style = MaterialTheme.typography.titleSmall)
                        }
                    }
                    // 司机池：直接跳车辆管理（"谁还没配车"要连着车队一起看才对得上）
                    if (vm.isDriverPool) {
                        TextButton(onClick = onOpenVehicles) {
                            Icon(Icons.Default.LocalShipping, contentDescription = null, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(4.dp))
                            Text("车辆", style = MaterialTheme.typography.titleSmall)
                        }
                    }
                },
            )
        },
        floatingActionButton = {
            FloatingActionButton(onClick = { vm.openCreate() }) {
                Icon(Icons.Default.Add, contentDescription = "新增" + pool.title.removeSuffix("管理"))
            }
        },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            when {
                vm.loading -> LoadingBox()
                vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
                vm.users.isEmpty() -> EmptyView(
                    when (pool) {
                        UserPool.MEMBERS -> "暂无批发商，可在「货主管理」中升级为批发商"
                        UserPool.SHIPPERS -> "暂无货主账号"
                        UserPool.DRIVERS -> "暂无司机账号"
                    },
                    Modifier.align(Alignment.Center),
                )
                else -> LazyColumn(
                    Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    if (vm.isDriverPool) {
                        item { DriverFleetSummary(vm) }
                        item {
                            SoTextField(
                                value = vm.query,
                                onValueChange = { vm.query = it },
                                placeholder = "搜姓名 / 手机号 / 车牌",
                                modifier = Modifier.fillMaxWidth(),
                            )
                        }
                    }
                    if (vm.shown.isEmpty()) {
                        item {
                            EmptyView("没有匹配「${vm.query}」的账号", Modifier.fillMaxWidth().height(140.dp))
                        }
                    }
                    items(vm.shown, key = { it.id }) { u ->
                        UserManageCard(
                            u = u,
                            pool = pool,
                            vehicles = if (vm.isDriverPool) vm.vehiclesOf(u.id) else emptyList(),
                            onEdit = { vm.openEdit(u) },
                            onBindVehicle = { vm.openVehiclePicker(u) },
                            onToggleActive = { vm.toggleActive(u) },
                            onToggleMember = { vm.toggleMember(u) },
                            onSwapRole = { vm.swapRole(u) },
                            onOpenPricing = { onOpenPricing(u) },
                        )
                    }
                    item { Spacer(Modifier.height(72.dp)) }
                }
            }
        }
    }

    // 配车弹层（司机视角：给他挑一辆车；选「不绑车」= 解绑）
    vm.vehiclePickerFor?.let { u ->
        VehiclePickerSheet(
            driverName = u.fullName.ifBlank { u.phone },
            vehicles = vm.vehicles,
            currentIds = vm.vehiclesOf(u.id).map { it.id }.toSet(),
            driverNameOf = { id -> vm.driverNameOf(id) },
            busy = vm.binding,
            onPick = { vid -> vm.pickVehicle(vid) },
            onDismiss = { if (!vm.binding) vm.vehiclePickerFor = null },
        )
    }

    if (vm.showDialog) {
        AlertDialog(
            onDismissRequest = { vm.showDialog = false },
            title = { Text(if (vm.editing == null) "新增" + pool.title.removeSuffix("管理") else "编辑账号") },
            text = {
                // ⚠️ 必须能滚：司机那一套字段（车型/计费方式/计费规则/工资）+ 商品可见范围
                //    叠起来在小屏上会把「保存」顶出屏幕外，而用户只会觉得"这个弹窗坏了"。
                Column(Modifier.verticalScroll(rememberScrollState())) {
                    OutlinedTextField(
                        value = vm.draftPhone, onValueChange = { vm.draftPhone = it },
                        label = { Text("手机号（登录账号）") },
                        singleLine = true, modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = vm.draftName, onValueChange = { vm.draftName = it },
                        label = { Text("姓名") },
                        singleLine = true, modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = vm.draftPassword, onValueChange = { vm.draftPassword = it },
                        label = { Text(if (vm.editing == null) "初始密码（至少 6 位）" else "重置密码（留空不改）") },
                        singleLine = true, modifier = Modifier.fillMaxWidth(),
                    )
                    if (pool == UserPool.DRIVERS && vm.draftVehicleType != "trailer") {
                        Spacer(Modifier.height(8.dp))
                        OutlinedTextField(
                            value = vm.draftSalary,
                            onValueChange = { vm.draftSalary = it },
                            label = { Text("固定工资（元/月，仅派单员可见）") },
                            singleLine = true,
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                    if (pool == UserPool.DRIVERS) {
                        Spacer(Modifier.height(10.dp))
                        // 车辆类型下拉（大车/挂车）
                        var vtExpanded by remember { mutableStateOf(false) }
                        ExposedDropdownMenuBox(expanded = vtExpanded, onExpandedChange = { vtExpanded = it }) {
                            OutlinedTextField(
                                value = driverKindLabel(vm.draftVehicleType),
                                onValueChange = {},
                                readOnly = true,
                                label = { Text("车辆类型") },
                                trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = vtExpanded) },
                                modifier = Modifier.fillMaxWidth().menuAnchor(),
                            )
                            ExposedDropdownMenu(expanded = vtExpanded, onDismissRequest = { vtExpanded = false }) {
                                listOf("large" to "大车司机", "trailer" to "挂车司机").forEach { (k, label) ->
                                    DropdownMenuItem(text = { Text(label) }, onClick = {
                                        vm.draftVehicleType = k
                                        vm.draftBillingMode = if (k == "trailer") "PIECE" else "SALARY"
                                        vtExpanded = false
                                    })
                                }
                            }
                        }
                        Spacer(Modifier.height(8.dp))
                        // 计费方式下拉（固定工资/按单计费）
                        var billExpanded by remember { mutableStateOf(false) }
                        ExposedDropdownMenuBox(expanded = billExpanded, onExpandedChange = { billExpanded = it }) {
                            OutlinedTextField(
                                value = if (vm.draftBillingMode == "PIECE") "按单计费（每单一价）" else "固定工资（月薪，司机不可见）",
                                onValueChange = {},
                                readOnly = true,
                                label = { Text("计费方式") },
                                trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = billExpanded) },
                                modifier = Modifier.fillMaxWidth().menuAnchor(),
                            )
                            ExposedDropdownMenu(expanded = billExpanded, onDismissRequest = { billExpanded = false }) {
                                listOf("SALARY" to "固定工资（月薪，司机不可见）", "PIECE" to "按单计费（每单一价）").forEach { (k, label) ->
                                    DropdownMenuItem(text = { Text(label) }, onClick = {
                                        vm.draftBillingMode = k
                                        billExpanded = false
                                    })
                                }
                            }
                        }

                        // ---- 计费规则（v3.36）----
                        //
                        // 上面那两档（固定工资 / 按单计费）是**老口径**，只能表达"月薪"和"拿全额运费"。
                        // 用户 2026-09-18 要的那几种（每单固定、运费提成、商品提成、工资+提成）
                        // 表达不了，所以走"挂一份命名好的规则"。挂了规则时上面两档就不起作用了，
                        // 这里必须写清楚——否则用户在老字段上改半天，账单一点不变。
                        Spacer(Modifier.height(10.dp))
                        var ruleExpanded by remember { mutableStateOf(false) }
                        val attached = vm.rules.firstOrNull { it.id == vm.draftRuleId }
                        ExposedDropdownMenuBox(expanded = ruleExpanded, onExpandedChange = { ruleExpanded = it }) {
                            OutlinedTextField(
                                value = attached?.name ?: "不挂规则（按上面的车型/计费方式）",
                                onValueChange = {},
                                readOnly = true,
                                label = { Text("计费规则（挂了就以规则为准）") },
                                trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = ruleExpanded) },
                                modifier = Modifier.fillMaxWidth().menuAnchor(),
                            )
                            ExposedDropdownMenu(expanded = ruleExpanded, onDismissRequest = { ruleExpanded = false }) {
                                DropdownMenuItem(
                                    text = { Text("不挂规则（按上面的车型/计费方式）") },
                                    onClick = { vm.draftRuleId = null; ruleExpanded = false },
                                )
                                vm.rules.forEach { r ->
                                    DropdownMenuItem(
                                        // 一句话说明由**后端**给（和服务端算钱的口径同源），界面不自己拼
                                        text = {
                                            Column {
                                                Text(r.name)
                                                Text(
                                                    r.summary,
                                                    style = MaterialTheme.typography.bodySmall,
                                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                                )
                                            }
                                        },
                                        onClick = { vm.draftRuleId = r.id; ruleExpanded = false },
                                    )
                                }
                            }
                        }
                        if (attached != null) {
                            Spacer(Modifier.height(6.dp))
                            Text(
                                "他以后按「${attached.name}」算钱：" + attached.summary +
                                    "（上面的车型/计费方式只在没挂规则时才生效）",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        // 车辆绑定**不在这个弹窗里**：它是另一条写路径（POST /vehicles/{id}/driver），
                        // 单独一个弹层更好报错（后端会因为"这不是司机账号"而拒绝，那句话要原样给用户看）。
                        if (vm.editing != null) {
                            Spacer(Modifier.height(8.dp))
                            Text(
                                "配车请在卡片上的「配车 / 换车」里改 —— 一辆车同时只能归一个司机，" +
                                    "绑错了那边会明确告诉你是谁名下的。",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                    // ---- 商品可见范围（白名单）：只对货主/批发商有意义 ----
                    // 用户 2026-09-18：「派单员可以指定他只只能看到哪些商品」——
                    // 入口就放在**这个人的编辑页**里（和"给谁什么权限"是同一件事，
                    // 单开一页会让人对不上号）。
                    if (vm.editing != null && vm.visibilityApplies) {
                        Spacer(Modifier.height(14.dp))
                        HorizontalDivider()
                        Spacer(Modifier.height(10.dp))
                        ProductVisibilityBlock(
                            scope = vm.draftScope,
                            onScope = { vm.setScope(it) },
                            products = vm.products,
                            selected = vm.draftVisible,
                            onToggle = { vm.toggleVisible(it) },
                            onAll = { vm.selectAllVisible() },
                            onNone = { vm.clearVisible() },
                            loading = vm.visibilityLoading,
                        )
                    }
                }
            },
            confirmButton = { TextButton(onClick = { vm.save() }, enabled = !vm.acting) { Text("保存") } },
            dismissButton = { TextButton(onClick = { vm.showDialog = false }) { Text("取消") } },
        )
    }
    // 商品维度批量调价抽屉（批发商管理页：同一商品可同时修改多个批发商专属价）
    if (vm.showBatch) {
        BatchPriceSheet(
            products = vm.products,
            members = vm.users,
            lockedShipperId = null,
            acting = vm.acting,
            onExecute = { sids, pids, m, v, ti -> vm.batchPrice(sids, pids, m, v, ti) { vm.showBatch = false } },
            onDismiss = { vm.showBatch = false },
        )
    }
}

/**
 * 车型 → 司机的**计费口径**中文。
 *
 * ⚠️ 这一处原来把 `small` 写成了「大车司机」（`"small" -> "大车司机"; "large" -> "大车司机"`），
 * 于是小车司机在列表上和大车司机长得一模一样 —— 而车型决定他的计费口径，
 * 看错了就会在"为什么他的账单是这个数"上白查半天。名单只有这一处，卡片和弹窗共用。
 */
internal fun driverKindLabel(vehicleType: String?): String = when (vehicleType) {
    "trailer" -> "挂车司机"
    "small" -> "小车司机"
    "large" -> "大车司机"
    else -> "未设置车型"
}

/** 司机车队摘要：把"谁还没配车"摆在最上面（这是派单时最容易踩空的一件事）。 */
@Composable
private fun DriverFleetSummary(vm: UsersManageViewModel) {
    val boundDrivers = vm.users.count { u -> vm.vehiclesOf(u.id).isNotEmpty() }
    val unbound = vm.users.size - boundDrivers
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            TintedIcon(Icons.Default.Groups, Color(0xFFCDDC39), size = 20.dp, container = 38.dp)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text("司机团队", style = MaterialTheme.typography.titleMedium)
                Text(
                    "共 " + vm.users.size + " 人 · 已配车 " + boundDrivers + " · 未配车 " + unbound +
                        " · 车队共 " + vm.vehicles.size + " 辆",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        if (unbound > 0) {
            Spacer(Modifier.height(8.dp))
            Text(
                "有 " + unbound + " 位司机还没配车 —— 点卡片上的「配车」就能绑，" +
                    "也可以点右上角「车辆」去管整支车队。",
                style = MaterialTheme.typography.bodySmall,
                color = Color(MoneyOrange),
            )
        }
    }
}

@Composable
private fun UserManageCard(
    u: UserDto,
    pool: UserPool,
    vehicles: List<VehicleDto>,
    onEdit: () -> Unit,
    onBindVehicle: () -> Unit,
    onToggleActive: () -> Unit,
    onToggleMember: () -> Unit,
    onSwapRole: () -> Unit,
    onOpenPricing: () -> Unit,
) {
    val accent = poolAccent(pool)
    SectionCard(Modifier.clickable { onEdit() }) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            // 姓氏圆底：扫一眼就能分人（原来整列都是同样的字，认人靠读）
            Box(
                Modifier.size(40.dp).clip(CircleShape).background(accent.copy(alpha = 0.16f)),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    u.fullName.ifBlank { u.phone }.take(1),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    color = accent,
                )
            }
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        u.fullName.ifBlank { u.username },
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.Bold,
                    )
                    Spacer(Modifier.width(8.dp))
                    if (u.isMember) {
                        Surface(color = Color(0xFFFFF1C6), shape = MaterialTheme.shapes.small) {
                            Text(
                                "批发商",
                                style = MaterialTheme.typography.labelMedium,
                                color = Color(0xFF7A5900),
                                modifier = Modifier.padding(horizontal = 6.dp, vertical = 1.dp),
                            )
                        }
                    }
                    if (!u.isActive) {
                        Spacer(Modifier.width(6.dp))
                        Surface(color = MaterialTheme.colorScheme.surfaceVariant, shape = MaterialTheme.shapes.small) {
                            Text(
                                "已停用",
                                style = MaterialTheme.typography.labelMedium,
                                modifier = Modifier.padding(horizontal = 6.dp, vertical = 1.dp),
                            )
                        }
                    }
                }
                Spacer(Modifier.height(4.dp))
                Text(
                    u.phone,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (pool == UserPool.DRIVERS) {
                    Spacer(Modifier.height(6.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        MiniChip(driverKindLabel(u.vehicleType), Color(0xFF1E6FFF))
                        Spacer(Modifier.width(6.dp))
                        // 计费口径优先显示**后端算好的那句话**（和账单同源）：
                        // 界面自己拼一句"按单 X 元"必然和账单口径分叉。
                        val pay = u.paySummary.ifBlank {
                            when {
                                !u.driverRuleName.isNullOrBlank() -> u.driverRuleName
                                u.salary != null && u.salary != "0" -> "月工资 ¥" + u.salary
                                else -> ""
                            }
                        }
                        if (pay.isNotBlank()) MiniChip(pay, Color(MoneyOrange))
                    }
                }
            }
            if (pool == UserPool.MEMBERS) {
                Button(onClick = onOpenPricing, contentPadding = PaddingValues(horizontal = 12.dp)) {
                    Text("定价")
                }
                Spacer(Modifier.width(4.dp))
            }
            IconButton(onClick = onEdit) {
                Icon(Icons.Default.Edit, contentDescription = "编辑", modifier = Modifier.size(18.dp))
            }
        }

        // ---- 车辆行（只有司机池）：他开哪辆车 ----
        if (pool == UserPool.DRIVERS) {
            Spacer(Modifier.height(10.dp))
            val plates = vehicles.joinToString("、") { it.plateNo }
            Row(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp))
                    .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f))
                    .clickable { onBindVehicle() }
                    .padding(horizontal = 12.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(
                    Icons.Default.LocalShipping,
                    contentDescription = null,
                    tint = if (plates.isEmpty()) MaterialTheme.colorScheme.onSurfaceVariant else Color(0xFFCDDC39),
                    modifier = Modifier.size(18.dp),
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    if (plates.isEmpty()) "未配车" else plates,
                    style = MaterialTheme.typography.bodyMedium,
                    color = if (plates.isEmpty()) MaterialTheme.colorScheme.onSurfaceVariant
                    else MaterialTheme.colorScheme.onSurface,
                    modifier = Modifier.weight(1f),
                )
                Text(
                    if (plates.isEmpty()) "配车" else "换车 / 解绑",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.primary,
                )
            }
        }

        Spacer(Modifier.height(4.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (pool == UserPool.SHIPPERS || pool == UserPool.MEMBERS) {
                TextButton(onClick = onToggleMember, contentPadding = PaddingValues(horizontal = 8.dp)) {
                    Icon(
                        if (u.isMember) Icons.Default.Stars else Icons.Default.StarOutline,
                        contentDescription = null,
                        modifier = Modifier.size(15.dp),
                    )
                    Spacer(Modifier.width(4.dp))
                    Text(if (u.isMember) "取消批发商" else "设为批发商")
                }
            }
            TextButton(onClick = onSwapRole, contentPadding = PaddingValues(horizontal = 8.dp)) {
                Icon(Icons.Default.SwapHoriz, contentDescription = null, modifier = Modifier.size(15.dp))
                Spacer(Modifier.width(4.dp))
                Text(if (u.role == "shipper") "转司机" else "转货主")
            }
            // 危险的那个一律靠右：原来三个文字键平铺，"停用"紧挨着"转货主"，误触代价不对称
            Spacer(Modifier.weight(1f))
            TextButton(onClick = onToggleActive, contentPadding = PaddingValues(horizontal = 8.dp)) {
                Text(if (u.isActive) "停用" else "启用", color = if (u.isActive) MaterialTheme.colorScheme.error else Success)
            }
        }
    }
}

/** 每个池一种强调色（与工作台里该模块的语义色同族；圆底用它 16% 透明、字用它本身）。 */
private fun poolAccent(pool: UserPool): Color = when (pool) {
    UserPool.DRIVERS -> Color(0xFF5A6B00)    // 司机黄绿（与「司机管理」同族）
    UserPool.SHIPPERS -> Color(0xFF0A3168)   // 货主蓝
    UserPool.MEMBERS -> Color(0xFF7A5900)    // 批发商金（与卡上的「批发商」徽章同色）
}

/**
 * **商品可见范围**（白名单）：勾了的才给他看。
 *
 * ## 为什么默认是「全部商品」
 * 这个开关一旦默认成"只给勾选的"，**所有老账号上线那一刻选品页就全空了** ——
 * 而真正的原因藏在一条数据库迁移里，界面上只表现为"商品全没了"。
 * 所以默认不限制，要限制必须由人明确点。
 *
 * ## 为什么"只给勾选的"却一个都没勾时要拦住
 * 那等于让他什么都看不到。用户想这么干的时候，正确路径是先把范围切过去、再逐个勾，
 * 而不是交一份空的上来 —— 交空的只说明他还没勾（或者是误操作），不是他的本意。
 */
@Composable
private fun ProductVisibilityBlock(
    scope: String,
    onScope: (String) -> Unit,
    products: List<ProductDto>,
    selected: Set<Long>,
    onToggle: (Long) -> Unit,
    onAll: () -> Unit,
    onNone: () -> Unit,
    loading: Boolean,
) {
    Column {
        Text("商品可见范围", style = MaterialTheme.typography.titleSmall)
        Spacer(Modifier.height(2.dp))
        Text(
            "决定他在「选择商品」里能看到哪些商品。默认不限制。",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ScopeChip("全部商品", scope != "custom") { onScope("all") }
            ScopeChip("只给勾选的", scope == "custom") { onScope("custom") }
        }
        if (scope == "custom") {
            Spacer(Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    if (selected.isEmpty()) "还没勾任何商品 —— 这样他打开选品页会是空的"
                    else "已勾 ${selected.size} / ${products.size} 个商品",
                    style = MaterialTheme.typography.bodySmall,
                    color = if (selected.isEmpty()) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.weight(1f),
                )
                TextButton(onClick = onAll) { Text("全选") }
                TextButton(onClick = onNone) { Text("全不选") }
            }
            if (loading) {
                LoadingBox(Modifier.height(80.dp))
            } else {
                // 固定高度内滚动：编辑弹窗本身在 AlertDialog 里有高度上限，
                // 商品多了必须自己能滚，否则底下的保存键会被顶出去。
                Column(Modifier.heightIn(max = 220.dp).verticalScroll(rememberScrollState())) {
                    products.forEach { p ->
                        Row(
                            Modifier.fillMaxWidth().clickable { onToggle(p.id) }.padding(vertical = 4.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Checkbox(checked = p.id in selected, onCheckedChange = { onToggle(p.id) })
                            Column(Modifier.weight(1f)) {
                                Text(p.name, style = MaterialTheme.typography.bodyMedium, maxLines = 1)
                                Text(
                                    "¥" + formatMoney(p.defaultUnitPrice) + " / " + p.unit.ifBlank { "件" } +
                                        if (p.isActive) "" else " · 已下架",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun ScopeChip(text: String, selected: Boolean, onClick: () -> Unit) {
    Surface(
        shape = MaterialTheme.shapes.small,
        color = if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surfaceVariant,
        border = androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
        modifier = Modifier.clickable { onClick() },
    ) {
        Text(
            text,
            style = MaterialTheme.typography.bodyMedium,
            color = if (selected) Color.White else MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
        )
    }
}
