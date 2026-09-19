package com.tapmoay.sorders.ui.shipper

import android.graphics.Bitmap
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
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
import com.tapmoay.sorders.data.remote.dto.LocationDto
import com.tapmoay.sorders.data.remote.dto.PlaceDto
import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.MoneyOrange
import coil.compose.AsyncImage
import com.tapmoay.sorders.util.formatMoney
import kotlin.math.roundToInt
import kotlinx.coroutines.launch
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
    var showImageSheet by remember { mutableStateOf(false) }
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    // 相册多选（一次最多 9 张）
    val photoPicker = rememberLauncherForActivityResult(ActivityResultContracts.PickMultipleVisualMedia(maxItems = 9)) { uris ->
        uris.forEach { uri ->
            try {
                val f = File(context.cacheDir, "order_img_" + System.currentTimeMillis() + "_" + uris.indexOf(uri) + ".jpg")
                context.contentResolver.openInputStream(uri)?.use { input ->
                    f.outputStream().use { output -> input.copyTo(output) }
                }
                vm.addDraftImage(f.absolutePath)
            } catch (_: Exception) {
            }
        }
    }

    // 拍照（单张，可连续拍累积）
    val cameraLauncher = rememberLauncherForActivityResult(ActivityResultContracts.TakePicturePreview()) { bmp ->
        if (bmp != null) {
            scope.launch(kotlinx.coroutines.Dispatchers.IO) {
                try {
                    val dir = File(context.cacheDir, "order_imgs").apply { mkdirs() }
                    val f = File(dir, "cam_" + System.currentTimeMillis() + ".jpg")
                    f.outputStream().use { bmp.compress(Bitmap.CompressFormat.JPEG, 88, it) }
                    vm.addDraftImage(f.absolutePath)
                } catch (_: Exception) {
                }
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
                            val pc = vm.products.firstOrNull { it.id == line.productId }?.let {
                                androidx.compose.ui.graphics.Color(android.graphics.Color.parseColor(it.nameColor ?: "#1565C0"))
                            } ?: MaterialTheme.colorScheme.onSurface
                            TintedIcon(Icons.Default.Inventory2, pc, size = 16.dp, container = 36.dp)
                            Spacer(Modifier.width(10.dp))
                            Column(Modifier.weight(1f)) {
                                Text(
                                    line.name.ifBlank { "未命名商品" },
                                    style = MaterialTheme.typography.bodyLarge,
                                    fontWeight = FontWeight.SemiBold,
                                    color = pc,
                                    maxLines = 1,
                                )
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Text("单价 ", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                    Text("¥" + formatMoney(line.price), style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.SemiBold, color = Color(MoneyOrange))
                                    Text("  ·  数量 ", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                    Text(line.quantity.toString() + " " + line.unit, style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.SemiBold, color = Color(0xFF1E6FFF))
                                }
                            }
                            Column(horizontalAlignment = Alignment.End) {
                                Text(
                                    "¥" + formatMoney(line.lineTotal.toString()),
                                    style = MaterialTheme.typography.titleMedium,
                                    fontWeight = FontWeight.Bold,
                                    color = Color(MoneyOrange),
                                )
                                Row {
                                    IconButton(onClick = { vm.editingLineIndex = i }, modifier = Modifier.size(32.dp)) {
                                        Icon(Icons.Default.Edit, contentDescription = "编辑", modifier = Modifier.size(15.dp), tint = Color(0xFF1E6FFF))
                                    }
                                    IconButton(onClick = { vm.removeLine(i) }, modifier = Modifier.size(32.dp)) {
                                        Icon(Icons.Default.Delete, contentDescription = "删除", modifier = Modifier.size(15.dp), tint = MaterialTheme.colorScheme.error)
                                    }
                                }
                            }
                        }
                        if (i != vm.lines.lastIndex) HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                    }
                    Spacer(Modifier.height(6.dp))
                    OutlinedButton(
                        onClick = { vm.showProductPicker = true },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Icon(Icons.Default.Add, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text(if (vm.lines.isEmpty()) "添加商品" else "继续添加商品")
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
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        OutlinedButton(onClick = { vm.showMapPicker = true }, modifier = Modifier.weight(1f)) {
                            Icon(Icons.Default.Place, contentDescription = null, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(6.dp))
                            Text("地图选点")
                        }
                        OutlinedButton(onClick = { vm.showAddressSheet = true }, modifier = Modifier.weight(1f)) {
                            Icon(Icons.Default.List, contentDescription = null, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(6.dp))
                            Text("地址库")
                        }
                    }
                    if (vm.addressLat.isNullOrBlank()) {
                        Spacer(Modifier.height(8.dp))
                        Text(
                            "还没选地图坐标：司机拿到这单只能靠打电话问路。" +
                                "点「地图选点」定位一下，或者从「地址库 → 共享地点」里挑一个别人标过的。",
                            style = MaterialTheme.typography.bodySmall,
                            color = Color(0xFFE6A23C),
                        )
                    } else {
                        // 有坐标 → 给一个**明确的一点**把坐标贡献进共享库。
                        // 为什么必须手动点：共享库是全库共用、**没有删除接口**的表，
                        // 一次误操作是永久的；而且"选了地图点"常常只是探索。
                        Spacer(Modifier.height(8.dp))
                        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                        Spacer(Modifier.height(8.dp))
                        if (vm.placeSaved) {
                            Column {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Icon(
                                        Icons.Default.CheckCircle,
                                        contentDescription = null,
                                        tint = Color(0xFF00B578),
                                        modifier = Modifier.size(18.dp),
                                    )
                                    Spacer(Modifier.width(6.dp))
                                    Text(
                                        "这个位置已在共享地点库里",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = Color(0xFF00B578),
                                    )
                                }
                                // ⚠️ 提示必须放在**用户刚点的那一行下面**，不能塞到页面底部的
                                //    通用提示位：那在 LazyColumn 末尾，长表单里根本不在屏幕上
                                //    （真机 dump 验证过 —— 等于没有反馈）。而"新建还是并入"
                                //    恰恰是用户最需要知道的一句话。
                                vm.toast?.let {
                                    Spacer(Modifier.height(4.dp))
                                    Text(
                                        it,
                                        style = MaterialTheme.typography.bodySmall,
                                        color = Color(0xFF00B578),
                                    )
                                }
                            }
                        } else {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Column(Modifier.weight(1f)) {
                                    Text(
                                        "把这个位置存进共享地点库",
                                        style = MaterialTheme.typography.bodyMedium,
                                        fontWeight = FontWeight.SemiBold,
                                    )
                                    Text(
                                        "下次同样的位置（包括别人送的单）直接拉坐标，不用各自再传一次",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                                Spacer(Modifier.width(8.dp))
                                OutlinedButton(
                                    onClick = { vm.saveCurrentPlaceToSharedLibrary() },
                                    enabled = !vm.savingPlace,
                                ) {
                                    Text(if (vm.savingPlace) "存入中…" else "存入")
                                }
                            }
                        }
                    }
                    Spacer(Modifier.height(10.dp))
                    OutlinedButton(onClick = { showImageSheet = true }, modifier = Modifier.fillMaxWidth()) {
                        Icon(Icons.Default.PhotoCamera, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("位置图片")
                    }
                    if (vm.draftAddressImages.isNotEmpty()) {
                        Spacer(Modifier.height(8.dp))
                        Row(
                            Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            vm.draftAddressImages.forEach { imgPath ->
                                Box(Modifier.size(72.dp).clip(RoundedCornerShape(12.dp))) {
                                    AsyncImage(
                                        model = File(imgPath),
                                        contentDescription = "位置参考图",
                                        contentScale = ContentScale.Crop,
                                        modifier = Modifier.fillMaxSize().clip(RoundedCornerShape(12.dp)),
                                    )
                                    Box(
                                        Modifier.align(Alignment.TopEnd).padding(3.dp).size(20.dp)
                                            .clip(CircleShape)
                                            .background(Color.Black.copy(alpha = 0.55f))
                                            .clickable { vm.removeDraftImage(imgPath) },
                                        contentAlignment = Alignment.Center,
                                    ) {
                                        Icon(Icons.Default.Close, contentDescription = "移除", tint = Color.White, modifier = Modifier.size(13.dp))
                                    }
                                }
                            }
                        }
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
                        label = { Text("收货人电话") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(Modifier.height(10.dp))
                    OutlinedTextField(
                        value = vm.bossPhone,
                        onValueChange = { vm.bossPhone = it },
                        label = { Text("下单人电话（可选）") },
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

    // 外卖式全屏选品页（货主下单 / 代理下单共用同一个组件）
    if (vm.showProductPicker) {
        ProductPickerSheet(
            products = vm.products,
            loading = vm.loadingProducts,
            priceFor = { vm.priceFor(it) },
            categoryOrder = vm.categoryOrder,
            onConfirm = { picked ->
                if (vm.addPickedLines(picked)) vm.showProductPicker = false
            },
            onDismiss = { vm.showProductPicker = false },
        )
    }

    // 选收货地址：线路 / 我的地点 / 共享地点 三段
    if (vm.showAddressSheet) {
        AddressPickerSheet(
            addresses = vm.addresses,
            locations = vm.locations,
            places = vm.places,
            onPickAddress = { vm.applyAddress(it) },
            onPickLocation = { vm.applyLocation(it) },
            onPickPlace = { vm.applyPlace(it) },
            onSearchPlaces = { vm.loadPlaces(it) },
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
                if (isNew) vm.addLine(updated.name, updated.price, null, updated.unit, updated.quantity)
                else vm.updateLine(idx, updated)
                vm.editingLineIndex = null
            },
            onDismiss = { vm.editingLineIndex = null },
        )
    }

    // 位置图片：弹窗选择（拍摄 / 图片上传·多张）
    if (showImageSheet) {
        AlertDialog(
            onDismissRequest = { showImageSheet = false },
            title = { Text("位置图片") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text(
                        "拍摄现场位置照片或从相册选择，可多张（最多 9 张）",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    OutlinedButton(
                        onClick = { showImageSheet = false; cameraLauncher.launch(null) },
                        modifier = Modifier.fillMaxWidth().height(48.dp),
                    ) {
                        Icon(Icons.Default.PhotoCamera, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("拍照")
                    }
                    OutlinedButton(
                        onClick = {
                            showImageSheet = false
                            photoPicker.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
                        },
                        modifier = Modifier.fillMaxWidth().height(48.dp),
                    ) {
                        Icon(Icons.Default.PhotoLibrary, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("图片上传（多张）")
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { showImageSheet = false }) { Text("取消") }
            },
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


/**
 * 选收货地址：**线路 / 我的地点 / 共享地点** 三段。
 *
 * ## 为什么要把三张表放在一个弹层里
 * 它们回答的是同一个问题"这单送到哪"，只是来源不同：
 * - **线路**（`shipper_addresses`）：带收货人电话的完整线路，最常用；
 * - **我的地点**（`shipper_locations`）：纯地点（含坐标）。**司机到场补录的坐标会进这里** ——
 *   用户要的"下次他下这个单的时候就会自动添加"就落在这一段；
 * - **共享地点**（`places`）：全库共用，别人/司机标过的坐标直接拉过来
 *   （"省的每个人都要手动上传一次"）。
 *
 * 三个来源分开列而不是混成一列，是因为**来源决定了可信度**：自己的地点是确认过的，
 * 共享地点可能只有坐标没有名字。混在一起用户没法判断该信哪个。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AddressPickerSheet(
    addresses: List<AddressDto>,
    locations: List<LocationDto>,
    places: List<PlaceDto>,
    onPickAddress: (AddressDto) -> Unit,
    onPickLocation: (LocationDto) -> Unit,
    onPickPlace: (PlaceDto) -> Unit,
    onSearchPlaces: (String?) -> Unit,
    onDismiss: () -> Unit,
) {
    val tabs = listOf("线路", "我的地点", "共享地点")
    var tab by remember { mutableStateOf(0) }
    var keyword by remember { mutableStateOf("") }

    // 搜索**三段都有**（用户 2026-09-18：只要是选地点的地方都能搜）。
    // 前两段在本地过滤（数据本来就在手上，即时出结果）；共享地点段还要**同时**打后端 ——
    // 后端那份是全库的，本地这份只是"最近常用的一页"，只筛本地会漏掉远处的地点。
    val kw = keyword.trim()
    val shownAddresses = remember(addresses, kw) {
        if (kw.isBlank()) addresses
        else addresses.filter {
            it.receiverName.contains(kw, true) || it.phone.contains(kw) || it.detailAddress.contains(kw, true)
        }
    }
    val shownLocations = remember(locations, kw) {
        if (kw.isBlank()) locations
        else locations.filter { it.name.contains(kw, true) || it.detailAddress.contains(kw, true) }
    }

    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(Modifier.padding(bottom = 20.dp)) {
            Text(
                "选择收货地址",
                style = MaterialTheme.typography.titleLarge,
                modifier = Modifier.padding(horizontal = 20.dp),
            )
            Spacer(Modifier.height(10.dp))
            SegmentedStatusTabs(
                labels = tabs.map { it + " " + countOf(it, addresses, locations, places) },
                colors = listOf(
                    Color(0xFF1E6FFF),
                    Color(0xFF00A2C7),
                    Color(0xFF00B578),
                ),
                selected = tab,
                onSelect = {
                    tab = it
                    keyword = ""
                    onSearchPlaces(null)
                },
            )
            Spacer(Modifier.height(10.dp))
            Box(Modifier.fillMaxWidth().padding(horizontal = 20.dp)) {
                SoTextField(
                    value = keyword,
                    onValueChange = {
                        keyword = it
                        // 共享地点段顺带搜后端（全库那部分本地没有）
                        if (tab == 2) onSearchPlaces(it.ifBlank { null })
                    },
                    placeholder = when (tab) {
                        0 -> "搜收货人、电话或地址"
                        1 -> "搜地点名或地址"
                        else -> "搜地点名或地址（全库）"
                    },
                )
                if (keyword.isNotBlank()) {
                    TextButton(
                        onClick = { keyword = ""; onSearchPlaces(null) },
                        modifier = Modifier.align(Alignment.CenterEnd),
                    ) { Text("清除") }
                }
            }
            Spacer(Modifier.height(8.dp))
            LazyColumn(Modifier.heightIn(max = 400.dp)) {
                when (tab) {
                    0 -> if (shownAddresses.isEmpty()) {
                        item {
                            SheetEmptyHint(
                                if (kw.isBlank()) "线路库为空，可先去「地址与联系人」添加"
                                else "没有匹配「$kw」的线路",
                            )
                        }
                    } else {
                        itemsIndexed(shownAddresses) { _, a ->
                            SheetRow(
                                title = a.receiverName.ifBlank { "收货人" } + "  " + a.phone,
                                subtitle = a.detailAddress,
                                badge = if (a.isDefault) "默认" else null,
                                hasCoords = !a.addressLat.isNullOrBlank(),
                                onClick = { onPickAddress(a) },
                            )
                        }
                    }
                    1 -> if (shownLocations.isEmpty()) {
                        item {
                            SheetEmptyHint(
                                if (kw.isBlank()) "地点库为空。司机到场帮你补的导航位置会出现在这里"
                                else "没有匹配「$kw」的地点",
                            )
                        }
                    } else {
                        itemsIndexed(shownLocations) { _, l ->
                            SheetRow(
                                title = l.name.ifBlank { l.detailAddress.ifBlank { "未命名地点" } },
                                subtitle = l.detailAddress,
                                badge = "我的",
                                hasCoords = !l.addressLat.isNullOrBlank(),
                                onClick = { onPickLocation(l) },
                            )
                        }
                    }
                    else -> if (places.isEmpty()) {
                        item {
                            SheetEmptyHint(
                                if (keyword.isBlank()) "共享地点库还是空的"
                                else "没有匹配「$keyword」的地点",
                            )
                        }
                    } else {
                        itemsIndexed(places) { _, p ->
                            SheetRow(
                                title = p.name.ifBlank { p.detailAddress.ifBlank { "未命名地点" } },
                                subtitle = p.detailAddress,
                                badge = sourceLabel(p.source) + " · 用过 " + p.useCount + " 次",
                                hasCoords = true,
                                onClick = { onPickPlace(p) },
                            )
                        }
                    }
                }
            }
        }
    }
}

private fun countOf(
    tab: String,
    addresses: List<AddressDto>,
    locations: List<LocationDto>,
    places: List<PlaceDto>,
): Int = when (tab) {
    "线路" -> addresses.size
    "我的地点" -> locations.size
    else -> places.size
}

private fun sourceLabel(source: String): String = when (source) {
    "driver" -> "司机补录"
    "dispatcher" -> "派单员"
    "shipper" -> "货主"
    else -> "共享"
}

@Composable
private fun SheetEmptyHint(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.bodyMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(horizontal = 20.dp, vertical = 18.dp),
    )
}

/** 弹层里的一行：标题 + 副标题 + 角标 + 「有导航」标记（有没有坐标一眼可辨）。 */
@Composable
private fun SheetRow(
    title: String,
    subtitle: String,
    badge: String?,
    hasCoords: Boolean,
    onClick: () -> Unit,
) {
    Column(
        Modifier
            .fillMaxWidth()
            .clickable { onClick() }
            .padding(horizontal = 20.dp, vertical = 14.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(title, style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f), maxLines = 1)
            if (hasCoords) {
                Text(
                    "有导航",
                    style = MaterialTheme.typography.labelSmall,
                    color = Color(0xFF00B578),
                    fontWeight = FontWeight.Bold,
                )
                Spacer(Modifier.width(8.dp))
            }
            badge?.let {
                Text(
                    it,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        if (subtitle.isNotBlank()) {
            Spacer(Modifier.height(2.dp))
            Text(
                subtitle,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 2,
                overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
            )
        }
    }
    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
}


/** 行编辑弹窗：数量步进 + 单价 */
@Composable
fun LineEditDialog(
    initial: LineDraft,
    onConfirm: (LineDraft) -> Unit,
    onDismiss: () -> Unit,
    title: String = "商品信息",
) {
    var name by remember { mutableStateOf(initial.name) }
    var price by remember { mutableStateOf(initial.price) }
    var qty by remember { mutableStateOf(initial.quantity.coerceAtLeast(1)) }
    var unit by remember { mutableStateOf(initial.unit.ifBlank { "件" }) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title, maxLines = 1, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis) },
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
                    OutlinedTextField(
                        value = qty.toString(),
                        onValueChange = { v -> qty = v.filter { c -> c.isDigit() }.take(4).toIntOrNull()?.coerceIn(1, 9999) ?: 1 },
                        singleLine = true,
                        textStyle = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Bold, color = Color(0xFF1E6FFF)),
                        keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(keyboardType = androidx.compose.ui.text.input.KeyboardType.Number),
                        modifier = Modifier.width(96.dp),
                    )
                    FilledTonalIconButton(onClick = { qty = (qty + 1).coerceAtMost(9999) }) {
                        Icon(Icons.Default.Add, contentDescription = "加")
                    }
                }
                Spacer(Modifier.height(10.dp))
                // 单位与选品弹窗同一套口径：下单和送货单上显示的就是它
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("单位", style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
                    SoTextField(
                        value = unit,
                        onValueChange = { unit = it.take(8) },
                        placeholder = "件/箱/斤",
                        modifier = Modifier.width(140.dp),
                    )
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
                        onConfirm(LineDraft(initial.productId, name.trim(), qty, price, unit.trim().ifBlank { "件" }))
                    }
                },
            ) { Text("确定") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}