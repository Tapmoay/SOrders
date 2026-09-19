package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.ArrearsUnitDto
import com.tapmoay.sorders.ui.common.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ArrearsUnitsScreen(
    container: AppContainer,
    onBack: () -> Unit,
) {
    val vm: ArrearsUnitsViewModel = appViewModel { ArrearsUnitsViewModel(container) }
    val snackbar = remember { SnackbarHostState() }

    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = { Text("挂账单位") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
        floatingActionButton = {
            FloatingActionButton(onClick = { vm.openCreate() }) {
                Icon(Icons.Default.Add, contentDescription = "新增挂账单位")
            }
        },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            when {
                vm.loading -> LoadingBox()
                vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
                vm.units.isEmpty() -> EmptyView("暂无挂账单位，点击右下角新增", Modifier.align(Alignment.Center))
                else -> LazyColumn(
                    Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    items(vm.units, key = { it.id }) { u ->
                        UnitCard(
                            u = u,
                            onEdit = { vm.openEdit(u) },
                            onDelete = { vm.delete(u) },
                        )
                    }
                    item { Spacer(Modifier.height(72.dp)) }
                }
            }
        }
    }

    // 新增/编辑弹窗
    if (vm.showDialog) {
        AlertDialog(
            onDismissRequest = { vm.showDialog = false },
            title = { Text(if (vm.editing == null) "新增挂账单位" else "编辑挂账单位") },
            text = {
                Column {
                    SoTextField(
                        vm.draftName, { vm.draftName = it },
                        placeholder = "单位名称（必填）",
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(Modifier.height(8.dp))
                    SoTextField(
                        // 电话只让数字进来（规则唯一实现在 core/InputRules.kt）
                        vm.draftPhone, { vm.draftPhone = InputRules.phoneInput(it) },
                        placeholder = "联系电话",
                        keyboardType = KeyboardType.Phone,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(Modifier.height(8.dp))
                    SoTextField(
                        vm.draftRemark, { vm.draftRemark = it },
                        placeholder = "备注（如结算方式）",
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            },
            confirmButton = { TextButton(onClick = { vm.save() }, enabled = !vm.acting) { Text("保存") } },
            dismissButton = { TextButton(onClick = { vm.showDialog = false }) { Text("取消") } },
        )
    }
}

@Composable
private fun UnitCard(
    u: ArrearsUnitDto,
    onEdit: () -> Unit,
    onDelete: () -> Unit,
) {
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Surface(color = MaterialTheme.colorScheme.primaryContainer, shape = MaterialTheme.shapes.medium) {
                Icon(
                    Icons.Default.Business,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onPrimaryContainer,
                    modifier = Modifier.padding(10.dp).size(22.dp),
                )
            }
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(u.name, style = MaterialTheme.typography.titleSmall)
                if (u.phone.isNotBlank()) {
                    Text(u.phone, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                if (u.remark.isNotBlank()) {
                    Text(u.remark, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline)
                }
            }
            IconButton(onClick = onEdit) {
                Icon(Icons.Default.Edit, contentDescription = "编辑", modifier = Modifier.size(18.dp))
            }
            IconButton(onClick = onDelete) {
                Icon(Icons.Default.Delete, contentDescription = "删除", modifier = Modifier.size(18.dp), tint = MaterialTheme.colorScheme.error)
            }
        }
    }
}
