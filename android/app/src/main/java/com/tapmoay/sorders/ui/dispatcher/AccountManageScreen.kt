package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.UserDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.*
import kotlinx.coroutines.launch

/** 角色标签配色：浅底 + 深字（与其他页面包章风格一致） */
private fun labelColors(u: UserDto): Pair<Color, Color> = when {
    u.role == "dispatcher" -> Color(0xFFDBE9FF) to Color(0xFF0A4DAF)
    u.role == "driver" && u.vehicleType == "trailer" -> Color(0xFFFFE0B2) to Color(0xFFE65100)
    u.role == "driver" && u.vehicleType == "large" -> Color(0xFFF0F4C3) to Color(0xFF827717)
    u.role == "driver" && u.vehicleType == "small" -> Color(0xFFE0F7FA) to Color(0xFF006064)
    u.role == "driver" -> Color(0xFFF0F4C3) to Color(0xFF827717)
    u.isMember -> Color(0xFFFFF1C6) to Color(0xFF7A5900)
    else -> Color(0xFFD6F3FA) to Color(0xFF005A78)
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AccountManageScreen(
    container: AppContainer,
    onBack: () -> Unit,
) {
    val vm: AccountManageViewModel = appViewModel { AccountManageViewModel(container) }
    val snackbar = remember { SnackbarHostState() }
    val clipboard = LocalClipboardManager.current

    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = { Text("账户管理") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
        floatingActionButton = {
            FloatingActionButton(onClick = { vm.openCreate() }) {
                Icon(Icons.Default.Add, contentDescription = "新增账户")
            }
        },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            when {
                vm.loading -> LoadingBox()
                vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
                vm.users.isEmpty() -> EmptyView("暂无账户，点右下角 + 创建", Modifier.align(Alignment.Center))
                else -> LazyColumn(
                    Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    // 搜索框（用户 2026-09-19：「账户管理…也要添加搜索键」，按**名称 / 手机号 /
                    // 手机号后 4 位**搜）。走**服务端** `?q=` —— 这一页列的是全部角色的账号、
                    // 一页最多 500 条，本地过滤会让第 501 个账号"不存在"。
                    item {
                        SearchField(value = vm.query, onValueChange = { vm.onQueryChange(it) })
                    }
                    if (vm.isSearching) {
                        if (vm.hitsTruncated) {
                            item {
                                TruncationNote(
                                    vm.hitsLimit,
                                    "匹配到的账号不止这些 —— 把关键词写细一点（姓名多打一个字，或手机号多打几位）",
                                )
                            }
                        }
                        if (vm.shown.isEmpty()) {
                            item {
                                EmptyView(
                                    "服务端按姓名/手机号搜过，没有「" + vm.query.trim() + "」这个账号",
                                    Modifier.fillMaxWidth().height(140.dp),
                                )
                            }
                        }
                    } else if (vm.truncated) {
                        // 被服务端截断时**说出来**（判据是响应头 `X-Truncated`，见 AccountManageViewModel）。
                        // 这一页尤其要说：右下角就是「新建账户」，而"列表里没有"最容易被读成
                        // "这个账号不存在"→ 再建一个 → 撞手机号唯一约束。
                        item {
                            TruncationNote(
                                vm.pageLimit,
                                "用上面的搜索框找 —— 那是服务端按姓名/手机号搜的全量结果，" +
                                    "不受这一页限制；直接往下翻找不到不等于没有这个账号，先别急着新建",
                            )
                        }
                    }
                    items(vm.shown, key = { it.id }) { u ->
                        SectionCard {
                            Column(Modifier.fillMaxWidth()) {
                                Row(
                                    Modifier.fillMaxWidth(),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Column(Modifier.weight(1f)) {
                                        Row(verticalAlignment = Alignment.CenterVertically) {
                                            Text(u.fullName.ifBlank { u.phone }, fontWeight = FontWeight.Bold, fontSize = 16.sp)
                                            Spacer(Modifier.width(8.dp))
                                            val (bg, fg) = labelColors(u)
                                        Surface(color = bg, shape = MaterialTheme.shapes.small) {
                                            Text(
                                                AccountRoleKind.labelOf(u),
                                                color = fg,
                                                fontSize = 12.sp,
                                                fontWeight = FontWeight.Medium,
                                                modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                                            )
                                        }
                                        }
                                        Spacer(Modifier.height(4.dp))
                                        Text(u.phone, color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 14.sp)
                                    }
                                    if (!u.isActive) {
                                        Surface(color = MaterialTheme.colorScheme.surfaceVariant, shape = MaterialTheme.shapes.small) {
                                            Text("已停用", color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 12.sp, modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp))
                                        }
                                    }
                                }
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    TextButton(onClick = { vm.openEdit(u) }) {
                                        Icon(Icons.Default.Edit, null, Modifier.size(16.dp), tint = Color(NavBlue))
                                        Spacer(Modifier.width(2.dp))
                                        Text("编辑", fontSize = 13.sp, color = Color(NavBlue))
                                    }
                                    TextButton(onClick = { vm.toggleActive(u) }) {
                                        Icon(
                                            if (u.isActive) Icons.Default.Pause else Icons.Default.PlayArrow,
                                            null, Modifier.size(16.dp),
                                            tint = if (u.isActive) Color(MoneyOrange) else Color(MgrGreen),
                                        )
                                        Spacer(Modifier.width(2.dp))
                                        Text(if (u.isActive) "停用" else "启用", fontSize = 13.sp, color = if (u.isActive) Color(MoneyOrange) else Color(MgrGreen))
                                    }
                                    TextButton(onClick = { vm.deleting = u }) {
                                        Icon(Icons.Default.DeleteOutline, null, Modifier.size(16.dp), tint = Color(MessageRed))
                                        Spacer(Modifier.width(2.dp))
                                        Text("删除", fontSize = 13.sp, color = Color(MessageRed))
                                    }
                                }
                            }
                        }
                    }
                    item { Spacer(Modifier.height(72.dp)) }
                }
            }
        }
    }

    // 删除确认
    vm.deleting?.let { target ->
        AlertDialog(
            onDismissRequest = { vm.dismissDelete() },
            title = { Text("删除账户") },
            text = {
                Text(
                    "确认删除「" + (target.fullName.ifBlank { target.phone }) + " / " + target.phone +
                        "」？删除后该账号不可登录，且手机号可重新建号。"
                )
            },
            confirmButton = {
                TextButton(
                    onClick = { vm.confirmDelete() },
                    enabled = !vm.deletingBusy,
                ) {
                    if (vm.deletingBusy) {
                        CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                    } else {
                        Text("删除", color = Color(MessageRed))
                    }
                }
            },
            dismissButton = {
                TextButton(onClick = { vm.dismissDelete() }) { Text("取消") }
            },
        )
    }

    if (vm.showSheet) {
        ModalBottomSheet(
            onDismissRequest = { vm.showSheet = false },
            sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        ) {
            AccountFormSheet(vm, snackbar, { s -> clipboard.setText(AnnotatedString(s)) })
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AccountFormSheet(
    vm: AccountManageViewModel,
    snackbar: SnackbarHostState,
    copyText: (String) -> Unit,
) {
    val scope = rememberCoroutineScope()
    val isEdit = vm.editing != null
    Column(Modifier.fillMaxWidth().padding(horizontal = 20.dp).padding(bottom = 24.dp)) {
        Text(
            if (isEdit) "编辑账户" else "新增账户",
            style = MaterialTheme.typography.titleLarge,
            fontWeight = FontWeight.Bold,
        )
        Text(
            if (isEdit) "修改后保存即可；密码留空表示不修改"
            else "创建后账号密码自动复制，直接发给对方即可登录",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            fontSize = 13.sp,
        )
        Spacer(Modifier.height(16.dp))

        // 姓名（必填）
        OutlinedTextField(
            value = vm.draftName,
            onValueChange = { vm.draftName = it; vm.nameError = null },
            label = { Text("姓名") },
            singleLine = true,
            isError = vm.nameError != null,
            supportingText = { vm.nameError?.let { Text(it, color = Color(MessageRed)) } },
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(8.dp))

        // 手机号（必填 + 11 位 + 仅数字）；规则唯一实现在 core/InputRules.kt。
        // 过滤写在调用点上（原来的 `vm.onPhoneChange` 也只是转一手），
        // 这样"这个框走的是哪条规则"在同一行就能看见，`_check_input_rules.py` 也是这么认的。
        OutlinedTextField(
            value = vm.draftPhone,
            onValueChange = { v ->
                vm.draftPhone = InputRules.mobileInput(v)
                vm.phoneError = null
            },
            label = { Text("手机号（登录账号）") },
            singleLine = true,
            isError = vm.phoneError != null,
            supportingText = { vm.phoneError?.let { Text(it, color = Color(MessageRed)) } },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone),
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(8.dp))

        // 密码（新增必填；编辑留空不改）
        OutlinedTextField(
            value = vm.draftPassword,
            onValueChange = { vm.draftPassword = it; vm.passwordError = null },
            label = { Text(if (isEdit) "重置密码（留空不修改）" else "密码") },
            singleLine = true,
            isError = vm.passwordError != null,
            supportingText = { vm.passwordError?.let { Text(it, color = Color(MessageRed)) } },
            visualTransformation = PasswordVisualTransformation(),
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(14.dp))

        // 角色（必选，单选 chips）
        Text("角色", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
        FlowRow(
            Modifier.fillMaxWidth().padding(top = 6.dp, bottom = 12.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            AccountRoleKind.entries.forEach { kind ->
                FilterChip(
                    selected = vm.draftRoleKey == kind.key,
                    onClick = { vm.draftRoleKey = kind.key },
                    label = { Text(kind.label) },
                )
            }
        }

        // 保存按钮（点击时触发校验；未过 → 红边提示，不会提交）
        Button(
            onClick = {
                vm.save { msg ->
                    copyText(msg)
                    scope.launch { snackbar.showSnackbar("已保存：$msg") }
                }
            },
            enabled = !vm.acting,
            modifier = Modifier.fillMaxWidth().height(50.dp),
        ) {
            if (vm.acting) CircularProgressIndicator(Modifier.size(22.dp), color = Color.White, strokeWidth = 2.dp)
            else Text("保存", fontSize = 16.sp)
        }
        Spacer(Modifier.height(12.dp))
    }
}