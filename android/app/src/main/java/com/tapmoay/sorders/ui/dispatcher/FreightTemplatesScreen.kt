package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import androidx.compose.ui.text.input.KeyboardType
import com.tapmoay.sorders.data.remote.dto.FreightTemplateDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.util.formatMoney

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FreightTemplatesScreen(container: AppContainer, onBack: () -> Unit) {
    val vm: FreightTemplatesViewModel = appViewModel { FreightTemplatesViewModel(container) }
    val snackbar = remember { SnackbarHostState() }

    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })
    OneShotSnackbar(snackbar, vm.error, onConsumed = { vm.error = null })

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            AppTopBar(
                title = "订单模板",
                onBack = onBack,
                actions = {
                    TextButton(onClick = { vm.openCreate() }) {
                        Icon(Icons.Default.Add, null, Modifier.size(20.dp))
                        Spacer(Modifier.width(4.dp))
                        Text("新建")
                    }
                },
            )
        },
    ) { pad ->
        if (vm.templates.isEmpty()) {
            Column(
                Modifier.fillMaxSize().padding(pad),
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text("暂无运费模板", style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(6.dp))
                Text(
                    "模板 = 路线 + 车型 + 一车价，派单选价时一键带出",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(16.dp))
                Button(onClick = { vm.openCreate() }) { Text("创建第一个模板") }
            }
            return@Scaffold
        }
        LazyColumn(
            Modifier.fillMaxSize().padding(pad),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            items(vm.templates, key = { it.id }) { t ->
                SectionCard(modifier = Modifier.fillMaxWidth()) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(t.name, style = MaterialTheme.typography.titleSmall, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold)
                            Spacer(Modifier.height(2.dp))
                            Text(
                                t.fromPlace + " → " + t.toPlace + when (t.vehicleType) {
                                    "small" -> " · 小车"; "large" -> " · 大车"; "trailer" -> " · 挂车"; else -> ""
                                },
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            if (t.remark.isNotBlank()) {
                                Spacer(Modifier.height(2.dp))
                                Text(t.remark, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                        }
                        Text(
                            "¥" + formatMoney(t.fee),
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = androidx.compose.ui.text.font.FontWeight.Bold,
                            color = Color(0xFFFF9500),
                        )
                    }
                    Spacer(Modifier.height(8.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        TextButton(onClick = { vm.openEdit(t) }) {
                            Icon(Icons.Default.Edit, null, Modifier.size(18.dp))
                            Spacer(Modifier.width(2.dp))
                            Text("编辑")
                        }
                        TextButton(onClick = { vm.requestDelete(t) }, colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error)) {
                            Icon(Icons.Default.DeleteOutline, null, Modifier.size(18.dp))
                            Spacer(Modifier.width(2.dp))
                            Text("删除")
                        }
                    }
                }
            }
        }
    }

    // 新建/编辑
    if (vm.showDialog) {
        AlertDialog(
            onDismissRequest = { vm.showDialog = false },
            title = { Text(if (vm.editing == null) "新建运费模板" else "编辑运费模板") },
            text = {
                Column(Modifier.verticalScroll(rememberScrollState())) {
                    SoTextField(vm.draftName, { vm.draftName = it }, placeholder = "模板名称（如：东城→西城 挂车）")
                    Spacer(Modifier.height(8.dp))
                    Row {
                        SoTextField(vm.draftFrom, { vm.draftFrom = it }, Modifier.weight(1f), placeholder = "起点")
                        Spacer(Modifier.width(8.dp))
                        SoTextField(vm.draftTo, { vm.draftTo = it }, Modifier.weight(1f), placeholder = "终点")
                    }
                    Spacer(Modifier.height(8.dp))
                    SoTextField(vm.draftFee, { vm.draftFee = InputRules.moneyInput(it) }, Modifier.fillMaxWidth(), placeholder = "一车价格 ¥", keyboardType = KeyboardType.Decimal)
                    Spacer(Modifier.height(8.dp))
                    Text("适用车型", style = MaterialTheme.typography.labelMedium)
                    Spacer(Modifier.height(4.dp))
                    Row(Modifier.horizontalScroll(rememberScrollState())) {
                        listOf("" to "通用", "small" to "小车", "large" to "大车", "trailer" to "挂车").forEach { (k, label) ->
                            val sel = vm.draftVehicle == k
                            Surface(
                                color = if (sel) MaterialTheme.colorScheme.primary.copy(alpha = 0.12f) else MaterialTheme.colorScheme.surfaceVariant,
                                shape = MaterialTheme.shapes.small,
                                modifier = Modifier.padding(end = 8.dp).clickable { vm.draftVehicle = k },
                            ) {
                                Text(
                                    label,
                                    style = MaterialTheme.typography.labelLarge,
                                    color = if (sel) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp),
                                )
                            }
                        }
                    }
                    Spacer(Modifier.height(8.dp))
                    SoTextField(vm.draftRemark, { vm.draftRemark = it }, Modifier.fillMaxWidth(), placeholder = "备注（选填）")
                }
            },
            confirmButton = { TextButton(onClick = { vm.save() }, enabled = !vm.acting) { Text("保存") } },
            dismissButton = { TextButton(onClick = { vm.showDialog = false }) { Text("取消") } },
        )
    }

    // 删除确认
    vm.deleteTarget?.let { t ->
        AlertDialog(
            onDismissRequest = { vm.deleteTarget = null },
            title = { Text("删除模板") },
            text = { Text("确定删除「" + t.name + "」？历史订单不受影响（已按单快照）。") },
            confirmButton = {
                TextButton(onClick = { vm.confirmDelete() }) { Text("删除", color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = { TextButton(onClick = { vm.deleteTarget = null }) { Text("取消") } },
        )
    }
}
