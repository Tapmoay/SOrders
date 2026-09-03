package com.tapmoay.sorders.ui.shipper

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.AddressDto
import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.ui.common.*
import coil.compose.AsyncImage
import com.tapmoay.sorders.util.formatMoney
import kotlin.math.roundToInt
import java.io.File

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OrderCreateScreen(
    container: AppContainer,
    onBack: () -> Unit,
    onCreated: () -> Unit,
    proxyMode: Boolean = false,
) {
    val vm: OrderCreateViewModel = appViewModel { OrderCreateViewModel(container) }
    var showShipperPicker by remember { mutableStateOf(false) }
    val context = LocalContext.current
    val pickAddressImage = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri != null) {
            try {
                val f = File(context.cacheDir, "addr_img_" + System.currentTimeMillis() + ".jpg")
                context.contentResolver.openInputStream(uri)?.use { input ->
                    f.outputStream().use { output -> input.copyTo(output) }
                }
                vm.draftAddressImage = f.absolutePath
            } catch (_: Exception) {
            }
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(if (proxyMode) "代理下单" else "下单") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
        bottomBar = {
            Surface(shadowElevation = 8.dp) {
                Row(
                    Modifier.fillMaxWidth().padding(16.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column {
                        Text("合计", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Text(
                            "¥" + formatMoney(vm.totalAmount().toString()),
                            style = MaterialTheme.typography.titleLarge,
                            color = MaterialTheme.colorScheme.primary,
                        )
                    }
                    Spacer(Modifier.weight(1f))
                    PrimaryActionButton(
                        text = if (vm.submitting) "提交中…"
                        else "提交订单 ¥" + formatMoney(vm.totalAmount().toString()),
                        onClick = { vm.submit { onCreated() } },
                        enabled = !vm.submitting,
                        containerColor = Color(0xFF00A56E),
                        icon = Icons.Default.Send,
                        modifier = Modifier.width(200.dp),
                    )
                }
            }
        },
    ) { padding ->
        LazyColumn(
            Modifier.fillMaxSize().padding(padding),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
        if (proxyMode) {
            item {
                SectionCard {
                    Text("为谁下单", style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.height(8.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            val picked = vm.tempShipperName?.ifBlank { null } ?: vm.shippers.firstOrNull { it.id == vm.shipperId }?.fullName
                            Text(picked ?: "请选择货主", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                            Spacer(Modifier.height(2.dp))
                            Text(
                                if (vm.tempShipperName != null) "临时货主（未注册）" else if (vm.shipperId != null) "已注册货主" else "点击选择货主",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        TextButton(onClick = { showShipperPicker = true }) { Text("选择") }
                    }
                }
            }
        }
            // 商品行
            item {
                SectionCard {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("商品明细", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                        Text(
                            vm.lines.size.toString() + "/10 组",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Spacer(Modifier.height(10.dp))
                    vm.lines.forEachIndexed { i, line ->
                        Row(
                            Modifier.fillMaxWidth().padding(vertical = 8.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Column(Modifier.weight(1f)) {
                                Text(line.name.ifBlank { "未命名商品" }, style = MaterialTheme.typography.bodyLarge, maxLines = 1)
                                Text(
                                    "单价 ¥" + formatMoney(line.price) + " × " + line.quantity + " " + line.unit,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                            Text(
                                "¥" + formatMoney(line.lineTotal.toString()),
                                style = MaterialTheme.typography.titleSmall,
                            )
                            IconButton(onClick = { vm.editingLineIndex = i }) {
                                Icon(Icons.Default.Edit, contentDescription = "编辑", modifier = Modifier.size(18.dp))
                            }
                            IconButton(onClick = { vm.removeLine(i) }) {
                                Icon(Icons.Default.Delete, contentDescription = "删除", modifier = Modifier.size(18.dp), tint = MaterialTheme.colorScheme.error)
                            }
                        }
                        if (i != vm.lines.lastIndex) HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                    }
                    Spacer(Modifier.height(6.dp))
                    OutlinedButton(
                        onClick = { vm.showProductSheet = true },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Icon(Icons.Default.Add, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("添加商品")
                    }
                }
            }

            // 收货地址
            item {
                SectionCard {
                    Text("收货地址", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(10.dp))
                    Text(
                        vm.addressDetail.ifBlank { "未选择收货地址" },
                        style = MaterialTheme.typography.bodyMedium,
                        color = if (vm.addressDetail.isBlank()) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.onSurface,
                    )
                    Spacer(Modifier.height(10.dp))
                    Row {
                        OutlinedButton(onClick = { vm.showMapPicker = true }) {
                            Icon(Icons.Default.Place, contentDescription = null, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(6.dp))
                            Text("地图选点")
                        }
                        Spacer(Modifier.width(10.dp))
                        OutlinedButton(onClick = { vm.showAddressSheet = true }) {
                            Icon(Icons.Default.List, contentDescription = null, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(6.dp))
                            Text("地址库")
                        }
                        Spacer(Modifier.width(10.dp))
                        OutlinedButton(onClick = { pickAddressImage.launch("image/*") }) {
                            Icon(Icons.Default.AddAPhoto, contentDescription = null, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(6.dp))
                            Text("位置图片")
                        }
                    }
                    vm.draftAddressImage?.let { imgPath ->
                        Spacer(Modifier.height(8.dp))
                        AsyncImage(
                            model = File(imgPath),
                            contentDescription = "位置参考图",
                            contentScale = ContentScale.Crop,
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(150.dp)
                                .clip(MaterialTheme.shapes.medium),
                        )
                    }
                }
            }

            // 联系与备注
            item {
                SectionCard {
                    Text("联系信息", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(10.dp))
                    OutlinedTextField(
                        value = vm.dongjiaPhone,
                        onValueChange = { vm.dongjiaPhone = it },
                        label = { Text("东家（收货人）电话") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(Modifier.height(10.dp))
                    OutlinedTextField(
                        value = vm.bossPhone,
                        onValueChange = { vm.bossPhone = it },
                        label = { Text("老板电话（可选）") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(Modifier.height(10.dp))
                    OutlinedTextField(
                        value = vm.remark,
                        onValueChange = { vm.remark = it },
                        label = { Text("备注（可选）") },
                        minLines = 2,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }

            item {
                vm.error?.let {
                    Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
                }
            }
            item { Spacer(Modifier.height(8.dp)) }
        }
    }

    // 商品选择底部弹窗
    if (vm.showProductSheet) {
        ProductSheet(
            products = vm.products,
            loading = vm.loadingProducts,
            onPick = { p -> vm.addLine(p.name, p.defaultUnitPrice, p.id, p.unit); vm.showProductSheet = false },
            onDismiss = { vm.showProductSheet = false },
        )
    }

    // 地址库选择
    if (vm.showAddressSheet) {
        AddressSheet(
            addresses = vm.addresses,
            onPick = { a -> vm.applyAddress(a) },
            onDismiss = { vm.showAddressSheet = false },
        )
    }

    // 行编辑弹窗
    vm.editingLineIndex?.let { idx ->
        val isNew = idx < 0 || idx >= vm.lines.size
        val draft = if (isNew) LineDraft() else vm.lines[idx]
        LineEditDialog(
            initial = draft,
            onConfirm = { updated ->
                if (isNew) vm.addLine(updated.name, updated.price, null)
                else vm.updateLine(idx, updated)
                vm.editingLineIndex = null
            },
            onDismiss = { vm.editingLineIndex = null },
        )
    }

    // 高德选点
    if (vm.showMapPicker) {
        AmapPickerDialog(
            container = container,
            initialLat = vm.addressLat?.toDoubleOrNull(),
            initialLng = vm.addressLng?.toDoubleOrNull(),
            onPicked = { lat, lng, address -> vm.applyPicked(lat, lng, address) },
            onDismiss = { vm.showMapPicker = false },
        )
    }
    // 代理下单：选择货主弹窗
    if (showShipperPicker) {
        AlertDialog(
            onDismissRequest = { showShipperPicker = false },
            title = { Text("为谁下单") },
            text = {
                Column(Modifier.verticalScroll(rememberScrollState()).heightIn(max = 420.dp)) {
                    Text("临时货主（未注册，可直接填名字）", style = MaterialTheme.typography.labelLarge)
                    Spacer(Modifier.height(4.dp))
                    SoTextField(vm.tempShipperName ?: "", { vm.setShipper(null, it) }, placeholder = "临时货主姓名")
                    Spacer(Modifier.height(12.dp))
                    Text("已注册货主", style = MaterialTheme.typography.labelLarge)
                    if (vm.shippers.isEmpty()) {
                        Text("暂无货主", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    vm.shippers.forEach { s ->
                        Row(
                            Modifier.fillMaxWidth().clickable { vm.setShipper(s.id, null); showShipperPicker = false }.padding(vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            RadioButton(selected = vm.shipperId == s.id, onClick = { vm.setShipper(s.id, null); showShipperPicker = false })
                            Spacer(Modifier.width(8.dp))
                            Column {
                                Text(s.fullName.ifBlank { s.username }, style = MaterialTheme.typography.bodyLarge)
                                Text(s.phone.ifBlank { "-" }, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                        }
                    }
                }
            },
            confirmButton = { TextButton(onClick = { showShipperPicker = false }) { Text("确定") } },
            dismissButton = { TextButton(onClick = { showShipperPicker = false }) { Text("取消") } },
        )
    }
    if (proxyMode) {
        LaunchedEffect(Unit) { vm.loadShippers() }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ProductSheet(
    products: List<ProductDto>,
    loading: Boolean,
    onPick: (ProductDto) -> Unit,
    onDismiss: () -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(Modifier.padding(bottom = 24.dp)) {
            Text("选择商品", style = MaterialTheme.typography.titleLarge, modifier = Modifier.padding(horizontal = 20.dp))
            Spacer(Modifier.height(8.dp))
            if (loading) {
                LoadingBox()
            } else if (products.isEmpty()) {
                Text(
                    "暂无可用商品\n请联系派单员先在「商品管理」中添加商品后再下单",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = 20.dp, vertical = 16.dp),
                )
            } else {
                LazyColumn(Modifier.heightIn(max = 360.dp)) {
                    itemsIndexed(products) { _, p ->
                        Row(
                            Modifier
                                .fillMaxWidth()
                                .clickable { onPick(p) }
                                .padding(horizontal = 20.dp, vertical = 16.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            if (p.imageUrl != null) {
                                AsyncImage(
                                    model = com.tapmoay.sorders.util.resolveStaticUrl(p.imageUrl),
                                    contentDescription = p.name,
                                    contentScale = ContentScale.Crop,
                                    modifier = Modifier
                                        .size(44.dp)
                                        .clip(MaterialTheme.shapes.small),
                                )
                            } else {
                                Box(
                                    Modifier
                                        .size(44.dp)
                                        .clip(MaterialTheme.shapes.small)
                                        .background(
                                            androidx.compose.ui.graphics.Color(android.graphics.Color.parseColor(p.nameColor ?: "#1565C0")),
                                        ),
                                    contentAlignment = Alignment.Center,
                                ) {
                                    Icon(
                                        Icons.Default.Inventory2,
                                        contentDescription = null,
                                        tint = androidx.compose.ui.graphics.Color.White,
                                        modifier = Modifier.size(22.dp),
                                    )
                                }
                            }
                            Spacer(Modifier.width(12.dp))
                            Column(Modifier.weight(1f)) {
                                Text(p.name, style = MaterialTheme.typography.bodyLarge)
                                Text(
                                    "默认价 ¥" + formatMoney(p.defaultUnitPrice),
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                            Button(onClick = { onPick(p) }, contentPadding = PaddingValues(horizontal = 14.dp, vertical = 6.dp)) {
                                Text("添加")
                            }
                        }
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AddressSheet(
    addresses: List<AddressDto>,
    onPick: (AddressDto) -> Unit,
    onDismiss: () -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(Modifier.padding(bottom = 24.dp)) {
            Text("从地址库选择", style = MaterialTheme.typography.titleLarge, modifier = Modifier.padding(horizontal = 20.dp))
            Spacer(Modifier.height(8.dp))
            if (addresses.isEmpty()) {
                Text(
                    "地址库为空，可先去地址管理添加",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = 20.dp, vertical = 16.dp),
                )
            } else {
                LazyColumn(Modifier.heightIn(max = 360.dp)) {
                    itemsIndexed(addresses) { _, a ->
                        Column(
                            Modifier
                                .fillMaxWidth()
                                .clickable { onPick(a) }
                                .padding(horizontal = 20.dp, vertical = 16.dp),
                        ) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(
                                    a.receiverName.ifBlank { "收货人" } + " " + a.phone,
                                    style = MaterialTheme.typography.titleSmall,
                                    modifier = Modifier.weight(1f),
                                )
                                if (a.isDefault) {
                                    Text(
                                        "默认",
                                        style = MaterialTheme.typography.labelMedium,
                                        color = MaterialTheme.colorScheme.primary,
                                    )
                                }
                            }
                            Text(
                                a.detailAddress,
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 2,
                            )
                        }
                        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                    }
                }
            }
        }
    }
}

/** 行编辑弹窗：数量步进 + 单价 */
@Composable
fun LineEditDialog(
    initial: LineDraft,
    onConfirm: (LineDraft) -> Unit,
    onDismiss: () -> Unit,
) {
    var name by remember { mutableStateOf(initial.name) }
    var price by remember { mutableStateOf(initial.price) }
    var qty by remember { mutableStateOf(initial.quantity.coerceAtLeast(1)) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("商品信息") },
        text = {
            Column {
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    label = { Text("商品名称") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(10.dp))
                OutlinedTextField(
                    value = price,
                    onValueChange = { price = it.filter { c -> c.isDigit() || c == '.' } },
                    label = { Text("单价（元）") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(10.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("数量", style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
                    FilledTonalIconButton(onClick = { qty = (qty - 1).coerceAtLeast(1) }) {
                        Icon(Icons.Default.Remove, contentDescription = "减")
                    }
                    Text(qty.toString(), style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(horizontal = 16.dp))
                    FilledTonalIconButton(onClick = { qty = (qty + 1).coerceAtMost(9999) }) {
                        Icon(Icons.Default.Add, contentDescription = "加")
                    }
                }
                Spacer(Modifier.height(10.dp))
                Text(
                    "小计 ¥" + formatMoney((price.toDoubleOrNull()?.times(qty) ?: 0.0).toString()),
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.primary,
                )
            }
        },
        confirmButton = {
            TextButton(
                onClick = {
                    if (name.isNotBlank()) {
                        onConfirm(LineDraft(initial.productId, name.trim(), qty, price))
                    }
                },
            ) { Text("确定") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}

