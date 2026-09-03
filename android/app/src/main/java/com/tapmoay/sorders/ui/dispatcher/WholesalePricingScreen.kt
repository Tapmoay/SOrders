package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.util.formatMoney

/**
 * 批发商定价页：为某个批发商逐商品设置专属价格（不同批发商可以不同价）。
 * 信息优先：商品名（第一）→ 默认售价（第二，要改的基准）→ 特价输入（第三）。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WholesalePricingScreen(
    container: AppContainer,
    shipperId: Long,
    shipperName: String = "",
    onBack: () -> Unit,
) {
    val vm: WholesalePricingViewModel = appViewModel { WholesalePricingViewModel(container, shipperId) }
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
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background,
                ),
                title = { Text("批发商定价 · " + shipperName.ifBlank { vm.shipperLabel }.ifBlank { "批发商" }, style = MaterialTheme.typography.titleLarge) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    TextButton(onClick = { vm.showBatch = true; vm.loadMembers() }) {
                        Icon(Icons.Default.Edit, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(4.dp))
                        Text("批量调价", style = MaterialTheme.typography.titleSmall)
                    }
                },
            )
        },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            when {
                vm.loading -> LoadingBox()
                vm.error != null && vm.products.isEmpty() -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
                vm.products.isEmpty() -> EmptyView("暂无商品，请先在商品管理中新增", Modifier.align(Alignment.Center))
                else -> LazyColumn(
                    Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    item {
                        Text(
                            "为每个商品设置该批发商专属价格；留空表示使用默认售价",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    items(vm.products, key = { it.id }) { p ->
                        PricingRow(
                            p = p,
                            value = vm.fieldValue(p),
                            hasRule = vm.rules.containsKey(p.id),
                            acting = vm.acting,
                            onValueChange = { vm.drafts[p.id] = it },
                            onSave = { vm.savePrice(p) },
                            onClear = { vm.clearPrice(p) },
                        )
                    }
                    item { Spacer(Modifier.height(72.dp)) }
                }
            }
        }
    }

    // 批量调价抽屉（锁定当前批发商：仅对其所选商品批量调价）
    if (vm.showBatch) {
        BatchPriceSheet(
            products = vm.products,
            members = emptyList(),
            lockedShipperId = vm.shipperId,
            lockedShipperName = shipperName.ifBlank { vm.shipperLabel },
            acting = vm.acting,
            onExecute = { sids, pids, m, v, ti -> vm.batchPrice(sids, pids, m, v, ti) { vm.showBatch = false } },
            onDismiss = { vm.showBatch = false },
        )
    }
}

@Composable
private fun PricingRow(
    p: ProductDto,
    value: String,
    hasRule: Boolean,
    acting: Boolean,
    onValueChange: (String) -> Unit,
    onSave: () -> Unit,
    onClear: () -> Unit,
) {
    SectionCard {
        Column {
            // ① 商品名（第一信息：最大，按商品名称颜色显示），行首语义色图标
            Row(verticalAlignment = Alignment.CenterVertically) {
                val nameColor = Color(android.graphics.Color.parseColor(p.nameColor ?: "#1565C0"))
                TintedIcon(Icons.Default.Inventory2, nameColor, size = 20.dp, container = 40.dp)
                Spacer(Modifier.width(10.dp))
                Text(
                    p.name,
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Bold,
                    color = nameColor,
                    maxLines = 1,
                    modifier = Modifier.weight(1f),
                )
                if (hasRule) {
                    Surface(color = Color(0xFFD5F5E9), shape = androidx.compose.foundation.shape.CircleShape) {
                        Text("已设特价", style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Medium, color = Color(0xFF00624A), modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp))
                    }
                }
            }
            Spacer(Modifier.height(4.dp))
            // ② 默认售价（第二信息：大数字，橙色=钱）
            Row(verticalAlignment = Alignment.Bottom) {
                Text(
                    "默认售价",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(bottom = 3.dp),
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    "¥" + formatMoney(p.defaultUnitPrice),
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Bold,
                    color = Color(MoneyOrange),
                )
            }
            // ②b 该商品预设批发价档（点击即填入特价输入，可再改；无档位不显示）
            if (p.tierPrices.isNotEmpty()) {
                Spacer(Modifier.height(6.dp))
                Row(
                    Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    p.tierPrices.forEach { t ->
                        Surface(
                            onClick = { onValueChange(t.unitPrice) },
                            shape = MaterialTheme.shapes.small,
                            color = Color(0xFFF5A623).copy(alpha = 0.14f),
                            border = androidx.compose.foundation.BorderStroke(1.dp, Color(0xFFF5A623).copy(alpha = 0.5f)),
                        ) {
                            Text(
                                t.label.ifBlank { "批发价" } + " ¥" + formatMoney(t.unitPrice) + " 点选",
                                style = MaterialTheme.typography.labelSmall,
                                color = Color(0xFFB07700),
                                modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
                            )
                        }
                    }
                }
            }
            Spacer(Modifier.height(12.dp))
            HorizontalDivider(color = MaterialTheme.colorScheme.surfaceVariant)
            Spacer(Modifier.height(12.dp))
            // ③ 批发商特价（第三信息：要写入的值）
            Text(
                "批发商特价（元）",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(6.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                SoTextField(
                    value = value,
                    onValueChange = onValueChange,
                    placeholder = "留空表示使用默认售价",
                    enabled = !acting,
                    keyboardType = KeyboardType.Decimal,
                    modifier = Modifier.weight(1f),
                )
                Spacer(Modifier.width(10.dp))
                Button(
                    onClick = onSave,
                    enabled = !acting && value.isNotBlank(),
                    modifier = Modifier.height(52.dp),
                ) {
                    Text("保存", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                }
            }
            if (hasRule) {
                Spacer(Modifier.height(4.dp))
                TextButton(onClick = onClear, enabled = !acting, modifier = Modifier.align(Alignment.End)) {
                    Text("清除特价", color = MaterialTheme.colorScheme.error)
                }
            }
        }
    }
}