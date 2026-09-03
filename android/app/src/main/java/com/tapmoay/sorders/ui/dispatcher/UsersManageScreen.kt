package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.clickable
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.UserDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.Success

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun UsersManageScreen(
    container: AppContainer,
    pool: UserPool,
    onBack: () -> Unit,
    onOpenPricing: (UserDto) -> Unit = {},
) {
    val vm: UsersManageViewModel = appViewModel { UsersManageViewModel(container, pool) }
    val snackbar = remember { SnackbarHostState() }

    LaunchedEffect(vm.actionResult) {
        vm.actionResult?.let {
            snackbar.showSnackbar(it)
            vm.actionResult = null
        }
    }

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
                    items(vm.users, key = { it.id }) { u ->
                        UserManageCard(
                            u = u,
                            pool = pool,
                            onEdit = { vm.openEdit(u) },
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

    if (vm.showDialog) {
        AlertDialog(
            onDismissRequest = { vm.showDialog = false },
            title = { Text(if (vm.editing == null) "新增" + pool.title.removeSuffix("管理") else "编辑账号") },
            text = {
                Column {
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
                                value = when (vm.draftVehicleType) {
                                    "trailer" -> "挂车司机"
                                    else -> "大车司机"
                                },
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

@Composable
private fun UserManageCard(
    u: UserDto,
    pool: UserPool,
    onEdit: () -> Unit,
    onToggleActive: () -> Unit,
    onToggleMember: () -> Unit,
    onSwapRole: () -> Unit,
    onOpenPricing: () -> Unit,
) {
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        u.fullName.ifBlank { u.username },
                        style = MaterialTheme.typography.titleSmall,
                    )
                    Spacer(Modifier.width(8.dp))
                    if (u.isMember) {
                        Surface(
                            color = androidx.compose.ui.graphics.Color(0xFFFFF1C6),
                            shape = MaterialTheme.shapes.small,
                        ) {
                            Text(
                                "批发商",
                                style = MaterialTheme.typography.labelMedium,
                                color = androidx.compose.ui.graphics.Color(0xFF7A5900),
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
                if (pool == UserPool.DRIVERS && !u.vehicleType.isNullOrBlank()) {
                    Spacer(Modifier.height(2.dp))
                    Text(
                        when (u.vehicleType) { "small" -> "大车司机"; "large" -> "大车司机"; "trailer" -> "挂车司机"; else -> "大车司机" },
                        style = MaterialTheme.typography.labelMedium,
                        color = androidx.compose.ui.graphics.Color(0xFF1E6FFF),
                    )
                }
                if (pool == UserPool.DRIVERS && !u.salary.isNullOrBlank() && u.salary != "0") {
                    Spacer(Modifier.height(2.dp))
                    Text(
                        "月工资 ¥" + u.salary,
                        style = MaterialTheme.typography.labelMedium,
                        color = androidx.compose.ui.graphics.Color(0xFFFF9500),
                    )
                }
            }
            // 批发商：每个商品可设特价
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
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
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
            Spacer(Modifier.weight(1f))
            TextButton(onClick = onToggleActive, contentPadding = PaddingValues(horizontal = 8.dp)) {
                Text(if (u.isActive) "停用" else "启用", color = if (u.isActive) MaterialTheme.colorScheme.error else Success)
            }
        }
    }
}