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
import androidx.compose.foundation.text.KeyboardOptions
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
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.AddressDto
import com.tapmoay.sorders.data.remote.dto.LocationDto
import com.tapmoay.sorders.data.remote.dto.PlaceCategoryDto
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
    /** 地址库左栏那格「管理分组」→ 地点分类管理页（新建 / 排序）。 */
    onOpenPlaceCategories: () -> Unit = {},
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
                        OutlinedButton(
                            onClick = {
                                // 每次打开都刷一次分组名册：用户可能刚去「管理分组」建/改过，
                                // 而 VM 是随页面复用的（回来时那份还是进来时拉的）。
                                vm.reloadPlaceCategories()
                                vm.showAddressSheet = true
                            },
                            modifier = Modifier.weight(1f),
                        ) {
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
                        // 只让数字敲得进来（汉字/字母/符号在输入层就被丢掉），最多 12 位，
                        // 并给数字键盘。规则唯一实现在 core/InputRules.kt。
                        onValueChange = { vm.dongjiaPhone = InputRules.phoneInput(it) },
                        label = { Text("收货人电话") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone),
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(Modifier.height(10.dp))
                    OutlinedTextField(
                        value = vm.bossPhone,
                        onValueChange = { vm.bossPhone = InputRules.phoneInput(it) },
                        label = { Text("下单人电话（可选）") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone),
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
            error = vm.productsError,
            onRetry = { vm.loadProducts() },
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
            categories = vm.placeCategories,
            placesTruncated = vm.placesTruncated,
            placesLimit = vm.placesLimit,
            onPickAddress = { vm.applyAddress(it) },
            onPickLocation = { vm.applyLocation(it) },
            onPickPlace = { vm.applyPlace(it) },
            onSearchPlaces = { vm.loadPlaces(it) },
            onManageCategories = {
                vm.showAddressSheet = false
                onOpenPlaceCategories()
            },
            onDismiss = { vm.showAddressSheet = false },
        )
    }

    // 行编辑弹窗。
    // ⚠️ 只有**清单里已有的行**能编辑（idx 由列表行上的编辑按钮给出）。
    //    这里原本还有一条"新增手输的自定义商品行"的分支（`idx` 越界即新增），
    //    但 `editingLineIndex` 的唯一赋值点就是 `vm.editingLineIndex = i`，
    //    那条分支**从来没有被走到过**；而且 2026-09-19 起行编辑弹窗不再收单价，
    //    真走进去也只会产出一行没有价格的行（手输的自定义商品没有商品库给它定价，
    //    后端会按空单价收下 = 0 元）。死分支 + 会产废行的分支，一起删掉。
    //    后端仍然支持 product_id 为空的行（AI 的手输行用得上），只是下单页不再开这个口子。
    val editIdx = vm.editingLineIndex
    val editLine = editIdx?.let { vm.lines.getOrNull(it) }
    if (editLine != null) {
        LineEditDialog(
            initial = editLine,
            onConfirm = { updated ->
                vm.updateLine(editIdx!!, updated)
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
 *
 * ## 2026-09-19：改成"左边一栏、右边内容"，左栏底部多一格「管理分组」
 * 用户先要「3 个分组就放在左侧，右边就是对应的地点」，又改口要"三个漂亮按钮"，
 * 最后拿着一张**左栏版**的截图圈住左栏底部说：
 * 「在这个界面当中管理分组的话，就在这个红框的位置。它跟左边那一个一个分组类别是一个
 *   对齐的状态。然后管理分组是一个**新的界面**吧…同样是可以创建分组然后进行排序都可以。
 *   所以我们在下单的时候是**可以**勾选分组的，但也不会强迫去勾选；如果不去选分组的话，
 *   我们就默认按照我们的 3 个分组进行选择」。
 *
 * 于是：左栏 = 固定三段（线路 / 我的地点 / 共享地点）+ 自定义分组（有才出现）+
 * **底部那格「管理分组」**（点了去 `PlaceCategoriesScreen` 新界面，与商品分类同一套做法）。
 * 「默认按 3 个分组」= 一进来选中的就是「线路」，不选分组也照样能用。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AddressPickerSheet(
    addresses: List<AddressDto>,
    locations: List<LocationDto>,
    places: List<PlaceDto>,
    /** 自定义分组名册（**自己那一份**）：左栏在固定三段后面把它们列出来。 */
    categories: List<PlaceCategoryDto>,
    /** 共享地点这一页被服务端截断了没有 + 本次上限（判据是响应头 `X-Truncated`/`X-Result-Limit`）。 */
    placesTruncated: Boolean,
    placesLimit: Int?,
    onPickAddress: (AddressDto) -> Unit,
    onPickLocation: (LocationDto) -> Unit,
    onPickPlace: (PlaceDto) -> Unit,
    onSearchPlaces: (String?) -> Unit,
    /** 左栏底部那格「管理分组」→ 新界面（建分组 / 排序）。 */
    onManageCategories: () -> Unit,
    onDismiss: () -> Unit,
) {
    var keyword by remember { mutableStateOf("") }
    /** 左栏选中的 key：`a`=线路 / `l`=我的地点 / `p`=共享地点 / `c|<分类名>`=我的地点里的某一类。 */
    var sel by remember { mutableStateOf("a") }

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
    val shownLocations = remember(locations, sel, kw) {
        val byCat = if (sel.startsWith("c|")) locations.filter { it.category == sel.removePrefix("c|") } else locations
        if (kw.isBlank()) byCat
        else byCat.filter { it.name.contains(kw, true) || it.detailAddress.contains(kw, true) }
    }
    // 左栏 = 固定三段 + 自定义分类（有才显示）+ 底部「管理分组」。
    //
    // 用户 2026-09-19：截图里画了个框指着左栏**底部**那一格 ——
    // 「在这个界面当中管理分组的话，就在这个**红框**的位置。它跟左边那一个一个分组类别
    //   是一个**对齐**的状态。然后管理分组是一个**新的界面**吧」。
    // 所以「管理分组」是左栏里的一格（不是按钮、不是浮层），点它去新界面（与商品分类同一个做法）。
    val catCounts = locations.groupingBy { it.category }.eachCount()
    val railItems = buildList {
        add(RailItem("a", "线路", addresses.size.toString() + " 条"))
        add(RailItem("l", "我的地点", locations.size.toString() + " 条"))
        add(RailItem("p", "共享地点", places.size.toString() + " 条"))
        categories.forEach { c ->
            add(RailItem("c|" + c.name, c.name, (catCounts[c.name] ?: 0).toString() + " 条"))
        }
        add(RailItem("manage", "管理分组", "新建 / 排序"))
    }

    // 提示语在**调用之前**算好（不写成 `placeholder = when {...}`）：
    // `_check_input_rules.py` 会把 `placeholder =` 后面那一段里的字符串字面量当"框的标题"，
    // 而 `when { sel == "a" -> ... }` 里的 `"a"` 会被它当成标题 → 误判成"电话输入框"。
    // 挪出来之后这一段里一个字符串都没有，判据不再误报（那条 EXCLUDED 也随之作废）。
    val searchHint = when {
        sel == "a" -> "搜收货人、电话或地址"
        sel == "p" -> "搜地点名或地址（全库）"
        else -> "搜地点名或地址"
    }

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        // **抽屉直接拉到最高**（用户 2026-09-19：「把底部抽屉拉到最高」）
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
    ) {
        Column(Modifier.fillMaxWidth().fillMaxHeight(0.92f).padding(bottom = 12.dp)) {
            Text(
                "选择收货地址",
                style = MaterialTheme.typography.titleLarge,
                modifier = Modifier.padding(horizontal = 20.dp),
            )
            Spacer(Modifier.height(10.dp))
            // 搜索框横跨整页（在左栏**上面**）：左栏是"有哪几类"、搜索是"那个地点在哪"，
            // 两个维度；放进左栏会被压成半宽，而且左栏为空时它跟着消失。
            Box(Modifier.fillMaxWidth().padding(horizontal = 20.dp)) {
                SoTextField(
                    value = keyword,
                    onValueChange = {
                        keyword = it
                        // 共享地点段顺带搜后端（全库那部分本地没有）
                        if (sel == "p") onSearchPlaces(it.ifBlank { null })
                    },
                    placeholder = searchHint,
                )
                if (keyword.isNotBlank()) {
                    TextButton(
                        onClick = { keyword = ""; onSearchPlaces(null) },
                        modifier = Modifier.align(Alignment.CenterEnd),
                    ) { Text("清除") }
                }
            }
            Spacer(Modifier.height(10.dp))
            Row(Modifier.fillMaxWidth().weight(1f)) {
                MasterRail(
                    items = railItems,
                    selectedKey = sel,
                    onSelect = { key ->
                        if (key == "manage") {
                            onManageCategories()
                        } else {
                            sel = key
                            keyword = ""
                            onSearchPlaces(null)
                        }
                    },
                    modifier = Modifier.width(112.dp).fillMaxHeight(),
                )
                LazyColumn(Modifier.weight(1f).fillMaxHeight()) {
                    when {
                        sel == "a" -> if (shownAddresses.isEmpty()) {
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
                        sel == "l" || sel.startsWith("c|") -> if (shownLocations.isEmpty()) {
                            item {
                                SheetEmptyHint(
                                    if (kw.isBlank()) {
                                        if (sel == "l") "地点库为空。司机到场帮你补的导航位置会出现在这里"
                                        else "这个分组下还没有地点（在「地址与联系人」里给地点选个分组）"
                                    } else "没有匹配「$kw」的地点",
                                )
                            }
                        } else {
                            itemsIndexed(shownLocations) { _, l ->
                                SheetRow(
                                    title = l.name.ifBlank { l.detailAddress.ifBlank { "未命名地点" } },
                                    subtitle = l.detailAddress,
                                    // 分类与仓库都摆在行上：选地点时最需要区分的就是"这是哪一类、是不是我的仓"
                                    badge = listOfNotNull(
                                        l.category.ifBlank { null },
                                        if (l.isWarehouse) "仓库" else null,
                                    ).joinToString(" · ").ifBlank { "未分类" },
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
                            // 共享地点被服务端截断时**说出来**：这张表只增不减又全库共用，
                            // "一页"迟早不是"全部"。出路就是上面那个搜索框——共享地点段的搜索
                            // 会**打后端** `q`（见 onValueChange），所以它是真能翻出旧记录的。
                            // ⚠️ 不许写"更早的"：这里是按"用过多少次"倒序，被截掉的是**用得少的**。
                            if (placesTruncated) {
                                item {
                                    TruncationNote(
                                        placesLimit,
                                        "要找的地点不在列表里就用上面的搜索框搜名字或地址",
                                    )
                                }
                            }
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


/**
 * 行编辑弹窗：**只能改商品名与数量** —— 单价与单位都不给改。
 *
 * ## 为什么不给改单价（2026-09-19 用户要求）
 * 用户原话：「它这个选的商品页面它是不能改订单价的不然那货主他想改多少就改多少」。
 * 单价只有一个来源：**商品定价**（`products.default_unit_price`，批发商走
 * `price_rules.special_unit_price`），由派单员在「商品管理 / 批发商定价」里维护。
 * 下单的人（货主、代理下单的派单员）手上不该有一个能改它的框：
 * 能改的字段就是会被改错的字段，而这里改错的是**钱**（且不会有任何提示）。
 * 弹窗里保留「小计」（数量 × 单价，跟着数量实时变）—— 不给改，但钱要看得见。
 *
 * ## 为什么不给改单位（2026-09-19 用户要求）
 * 见 `ui/common/ProductPicker.kt` 文件头：单位由派单员在商品上设好，
 * 改它会产生"这次记 3 箱、下次记 3 件"这种两边都不报错的口径分裂。
 */
@Composable
fun LineEditDialog(
    initial: LineDraft,
    onConfirm: (LineDraft) -> Unit,
    onDismiss: () -> Unit,
    title: String = "商品信息",
) {
    var name by remember { mutableStateOf(initial.name) }
    var qty by remember { mutableStateOf(initial.quantity.coerceAtLeast(1)) }

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
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("数量", style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
                    FilledTonalIconButton(onClick = { qty = (qty - 1).coerceAtLeast(1) }) {
                        Icon(Icons.Default.Remove, contentDescription = "减")
                    }
                    OutlinedTextField(
                        value = qty.toString(),
                        onValueChange = { v -> qty = InputRules.intInput(v, 4).toIntOrNull()?.coerceIn(1, 9999) ?: 1 },
                        singleLine = true,
                        textStyle = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Bold, color = Color(0xFF1E6FFF)),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.width(96.dp),
                    )
                    FilledTonalIconButton(onClick = { qty = (qty + 1).coerceAtMost(9999) }) {
                        Icon(Icons.Default.Add, contentDescription = "加")
                    }
                }
                Spacer(Modifier.height(10.dp))
                Text(
                    "小计 ¥" + formatMoney((initial.price.toDoubleOrNull()?.times(qty) ?: 0.0).toString()),
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.primary,
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    "单价由商品定价决定，下单时不能改；要改价请让派单员在「商品管理 / 批发商定价」里调整。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        },
        confirmButton = {
            TextButton(
                onClick = {
                    if (name.isNotBlank()) {
                        // 单价与单位都沿用原值（商品定价 / 商品库单位），这里不给改 —— 见函数头注释
                        onConfirm(LineDraft(initial.productId, name.trim(), qty, initial.price, initial.unit.ifBlank { "件" }))
                    }
                },
            ) { Text("确定") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}
