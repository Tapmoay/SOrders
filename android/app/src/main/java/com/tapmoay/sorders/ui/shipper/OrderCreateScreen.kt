package com.tapmoay.sorders.ui.shipper

import android.graphics.Bitmap
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
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
import com.tapmoay.sorders.core.HintPrefs
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.AddressDto
import com.tapmoay.sorders.data.remote.dto.LocationDto
import com.tapmoay.sorders.data.remote.dto.PlaceCategoryDto
import com.tapmoay.sorders.data.remote.dto.PlaceDto
import com.tapmoay.sorders.ui.dispatcher.PlaceCategoriesPanel
import com.tapmoay.sorders.ui.dispatcher.PlaceCategoriesViewModel
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.MgrGreen
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.ui.theme.ShipperTeal
import coil.compose.AsyncImage
import com.tapmoay.sorders.util.formatMoney
import kotlinx.coroutines.launch
import java.io.File

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OrderCreateScreen(
    container: AppContainer,
    onBack: () -> Unit,
    onCreated: () -> Unit,
    proxyMode: Boolean = false,
    /**
     * 从「预订单」页点「用这张下单」进来时带的那张预设单（0 = 不是从预设单进来的）。
     *
     * ⚠️ 预填**只发生一次**（key = 这个 id）：把用户改过的值再冲回去是最坏的一种"聪明" ——
     *    他改完数量、按提交之前界面又跳一下。
     */
    prefillTemplateId: Long = 0L,
) {
    val vm: OrderCreateViewModel = appViewModel { OrderCreateViewModel(container) }
    LaunchedEffect(prefillTemplateId) {
        if (prefillTemplateId > 0L) {
            vm.prefillFromTemplate(prefillTemplateId) { err -> if (err != null) vm.error = err }
        }
    }
    // 图片预览（位置参考图）：点缩略图看大图，见 ui/common/ImagePreview.kt
    val preview = rememberImagePreview()
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
        // ⚠️ **一次性提示（`vm.toast`）必须在这里也画一遍**（2026-09-22）：它原来只有
        //    「地址抽屉 → 已存进共享库」那一小块里画，于是"已按预设单填好商品与数量""某件商品
        //    已不在商品库""已撤销/已删除"这些话**根本没有机会被看见**（真机 dump 证实：
        //    点了「用这张下单」屏幕上找不到那句提示）。放在页面顶部 + 一个 ✕，用户看得到、也能收掉。
        vm.toast?.let { msg ->
            item {
                Surface(
                    color = Color(0xFFFFF7E6),
                    shape = RoundedCornerShape(12.dp),
                    border = BorderStroke(1.dp, Color(0xFFF0D9A8)),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Row(
                        Modifier.padding(start = 12.dp, top = 8.dp, end = 4.dp, bottom = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            msg,
                            style = MaterialTheme.typography.bodySmall,
                            color = Color(0xFF8A6D1F),
                            modifier = Modifier.weight(1f),
                        )
                        IconButton(onClick = { vm.dismissToast() }) {
                            Icon(Icons.Default.Close, contentDescription = "关掉这条提示", modifier = Modifier.size(18.dp))
                        }
                    }
                }
            }
        }
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
                    // ⚠️ **报价依据要写在这里**（2026-09-22 用户报的错价）：价算错了界面上看不出来
                    //    —— 20 和 10 都只是一个"看起来正常的价"。这句话跟着当前货主与专属价实时变，
                    //    用户在按提交之前就能看出走的是默认价还是谈好的专属价。
                    //    它是**状态**（不是解释），所以用 Text、不走 Hint 总开关。
                    vm.priceBasisText().takeIf { it.isNotBlank() }?.let { basis ->
                        Text(
                            basis,
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
                            // 名称色判据只有一处（`productNameColor`，见 ui/common/ProductCardKit.kt）：
                            // 原来这里是内联的 `parseColor(x ?: "#1565C0")`，**没有 try/catch** ——
                            // 库里一个脏颜色值会让整页下单崩掉。
                            val pc = vm.products.firstOrNull { it.id == line.productId }?.let {
                                productNameColor(it.nameColor)
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
                                // 每次打开都刷一遍抽屉里那三份（分组名册 / 线路 / 我的地点）：
                                // 用户可能刚去「管理分组」改过名，也可能刚去「地址与联系人」
                                // 建过地点，而 VM 是随页面复用的（回来时那份还是进来时拉的）。
                                vm.reloadAddressLibrary()
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
                        // 常驻一句"几个字"，后果交给 HintOnce（说三遍就不说了）
                        Text(
                            "还没选坐标",
                            style = MaterialTheme.typography.bodySmall,
                            color = Color(0xFFE6A23C),
                        )
                        HintOnce(
                            container.hintPrefs,
                            "order.create.no_coord",
                            "司机拿到这单只能靠打电话问路",
                        )
                    } else {
                        // 有坐标 → 给一个**明确的一点**把坐标贡献进共享库。
                        // 为什么必须手动点：共享库是全库共用的一张表，一次误操作
                        // 所有人都看得见（2026-09-19 起能改能删了，但"进来一条"本来就该是人点的）；
                        // 而且"选了地图点"常常只是探索。
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
                                        "已在共享库里",
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
                                        "存进共享地点库",
                                        style = MaterialTheme.typography.bodyMedium,
                                        fontWeight = FontWeight.SemiBold,
                                    )
                                    HintOnce(
                                        container.hintPrefs,
                                        "order.create.save_share",
                                        "以后同样的位置，大家直接能用",
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
                            vm.draftAddressImages.forEachIndexed { i, imgPath ->
                                Box(Modifier.size(72.dp).clip(RoundedCornerShape(12.dp))) {
                                    AsyncImage(
                                        model = File(imgPath),
                                        contentDescription = "位置参考图",
                                        contentScale = ContentScale.Crop,
                                        // 点图 = 看大图（用户 2026-09-22：「他不知道他自己拍的怎么样」）。
                                        // ⚠️ 这里传的是**本地 File**（刚拍还没上传）—— 预览组件收的是
                                        //    Coil 的 model（`Any`），所以本地图和远程图都能看。
                                        modifier = Modifier
                                            .fillMaxSize()
                                            .clip(RoundedCornerShape(12.dp))
                                            .clickable {
                                                preview.open(vm.draftAddressImages.map { File(it) }, i)
                                            },
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

            // 联系与备注（2026-09-22：改成**共用表单行**，白卡里不画边框、值本身就是占位符）
            item {
                FormGroup(icon = Icons.Default.Contacts, title = "联系信息", tint = Color(MgrGreen)) {
                    // 收货人：名称 + 电话。名称从**选中的线路**自动带出来（`applyAddress`），也能手改。
                    FormInputRow(
                        label = "收货人名称",
                        value = vm.dongjiaName,
                        onValueChange = { vm.dongjiaName = it },
                        placeholder = "从线路带出，可改",
                        icon = Icons.Default.Person,
                        iconTint = Color(MgrGreen),
                    )
                    FormInputRow(
                        label = "收货人电话",
                        value = vm.dongjiaPhone,
                        // 只让数字敲得进来（汉字/字母/符号在输入层就被丢掉），最多 12 位，
                        // 并给数字键盘。规则唯一实现在 core/InputRules.kt。
                        onValueChange = { vm.dongjiaPhone = InputRules.phoneInput(it) },
                        placeholder = "请输入手机号",
                        keyboardType = KeyboardType.Phone,
                        icon = Icons.Default.Phone,
                        iconTint = Color(0xFF00B578),
                    )
                    // 下单人：名称 + 电话，进页面就按**当前登录账号**填好（`prefillOrderer`）。
                    FormInputRow(
                        label = "下单人名称",
                        value = vm.bossName,
                        onValueChange = { vm.bossName = it },
                        placeholder = "默认当前账号",
                        icon = Icons.Default.Person,
                        iconTint = Color(0xFF1E6FFF),
                    )
                    FormInputRow(
                        label = "下单人电话",
                        value = vm.bossPhone,
                        onValueChange = { vm.bossPhone = InputRules.phoneInput(it) },
                        placeholder = "选填",
                        keyboardType = KeyboardType.Phone,
                        icon = Icons.Default.Phone,
                        iconTint = Color(0xFF00B578),
                    )
                    FormTextAreaRow(
                        label = "备注",
                        value = vm.remark,
                        onValueChange = { vm.remark = it },
                        placeholder = "选填，例如「到了先打电话」",
                        icon = Icons.Default.Notes,
                        iconTint = Color(0xFF8A8A8E),
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

    // 图片预览（点缩略图之后那个全屏黑底弹层）
    preview.Show()

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
            container = container,
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
            onCategoriesChanged = { vm.reloadAddressLibrary() },
            canManagePlaces = vm.canManageSharedPlaces,
            onUpdatePlace = { id, name, addr -> vm.updatePlace(id, name, addr) },
            onDeletePlace = { vm.deletePlace(it) },
            onDemotePlace = { vm.demotePlace(it) },
            onShareLocation = { vm.shareLocation(it) },
            onRestorePlace = { vm.restorePlace(it) },
            recentlyDeleted = vm.recentlyDeletedPlace,
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
                        "拍照或相册 · 最多 9 张",
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
    container: AppContainer,
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
    /** 第二层抽屉里改过分组之后回来：让上层把分组名册刷一遍。 */
    onCategoriesChanged: () -> Unit,
    /**
     * 共享库的管理（2026-09-19）：**只有派单员**看得到入口，所以连标记带四个动作一起传进来 ——
     * 这一层（抽屉）只画界面，改数据的活全在上层那个 ViewModel 里（它才拿得到 repository）。
     * [canManagePlaces] = false 时行尾连 `⋮` 都不画：不给他看几个点了必然 403 的按钮。
     */
    canManagePlaces: Boolean,
    /** 刚删掉的那条（编号 + 名字）：有值就在列表顶上画一行「已删除 · 撤销」。 */
    recentlyDeleted: Pair<Long, String>?,
    onUpdatePlace: (Long, String?, String?) -> Unit,
    onDeletePlace: (Long) -> Unit,
    onDemotePlace: (Long) -> Unit,
    onRestorePlace: (Long) -> Unit,
    onShareLocation: (LocationDto) -> Unit,
    onDismiss: () -> Unit,
) {
    var keyword by remember { mutableStateOf("") }
    /** 左栏选中的 key：`a`=线路 / `l`=我的地点 / `p`=共享地点 / `c|<分类名>`=我的地点里的某一类。 */
    var sel by remember { mutableStateOf("a") }
    /**
     * 第二层抽屉：点左栏底部那格「管理分组」时，**把这块内容换掉**而不是收起抽屉再开一页。
     *
     * 用户 2026-09-19：「切换的时候突然会闪一下…这样太麻烦了。要干脆就不要弹一个界面，
     * 干脆就直接弹一个 —— 也算一个抽屉吧，**它 2 个抽屉**」。
     */
    var managing by remember { mutableStateOf(false) }

    // 共享库的管理：三个动作各要一次确认/编辑（**只有派单员**看得到入口）。
    // 都放在这一层（抽屉里）而不是各写一个路由：它们都是"改一行数据"，弹一个框就够了。
    var editingPlace by remember { mutableStateOf<PlaceDto?>(null) }
    var demoteTarget by remember { mutableStateOf<PlaceDto?>(null) }
    var deleteTarget by remember { mutableStateOf<PlaceDto?>(null) }
    var publishTarget by remember { mutableStateOf<LocationDto?>(null) }

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
    //
    // ⛔ **一格都不带「N 条」**（用户 2026-09-19 看截图后点名）：「那个分组下面不要显示有多少条啊，
    //    这是多余信息」。左栏回答的是"有哪几类"，条数回答的是"这一类里有多少个"——
    //    后者点进去一眼就数得完；放左栏的代价是整列被撑成两行：`MasterRail` 的**行高是整列统一的**
    //    （`twoLine = items.any { subtitle != null }`），只要有一格带副标题，六格全是 60dp、
    //    五格的第二行空着。真机截图里那五行「8 条 / 9 条 / 3 条 / 0 条 / 0 条」就是这么来的。
    // 同理「管理分组」那格也不再挂「新建 / 排序」：它是**去的地方**不是**数据**，
    // 挂一行小字只会让"整列里独独这一格是两行"。
    val railItems = buildList {
        add(RailItem("a", "线路"))
        add(RailItem("l", "我的地点"))
        add(RailItem("p", "共享地点"))
        categories.forEach { c -> add(RailItem("c|" + c.name, c.name)) }
        add(RailItem("manage", "管理分组"))
    }

    // ⚠️ 分组被**改名/删掉**之后，左栏的选中项可能还指着一个已经不存在的老名字
    //    （`sel` 是本地的，管理分组那一层改的是后端名册）——那时右栏按老名字一条都筛不到，
    //    屏幕上看起来像"**这个分组是空的**"，而地点一条没少。所以名册一变就核对一次选中项。
    LaunchedEffect(categories) {
        if (sel.startsWith("c|") && categories.none { "c|" + it.name == sel }) sel = "l"
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
            if (managing) {
                // 第二层抽屉（同一个 ModalBottomSheet 里换内容 → 不 dismiss、不 push，所以不闪）
                val catVm: PlaceCategoriesViewModel = appViewModel { PlaceCategoriesViewModel(container) }
                PlaceCategoriesPanel(
                    vm = catVm,
                    onBack = {
                        managing = false
                        // 回来时把分组名册刷一遍：建/改名/排序都可能刚发生过，
                        // 不刷的话左栏还是旧的（要退出重进才看得到）。
                        onCategoriesChanged()
                    },
                )
            } else {
                Row(Modifier.fillMaxWidth().weight(1f)) {
                    MasterRail(
                        items = railItems,
                        selectedKey = sel,
                        onSelect = { key ->
                            if (key == "manage") {
                                managing = true
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
                                    isPlace = false,
                                    title = a.receiverName.ifBlank { "未填收货人" },
                                    phone = a.phone,
                                    subtitle = a.detailAddress,
                                    // 「主角是线路」：起点有就画成 A → B（2026-09-22 第三轮）
                                    origin = a.originAddress,
                                    badge = if (a.isDefault) "默认线路" else null,
                                    hasCoords = !a.addressLat.isNullOrBlank(),
                                    onClick = { onPickAddress(a) },
                                )
                            }
                        }
                        sel == "l" || sel.startsWith("c|") -> if (shownLocations.isEmpty()) {
                            item {
                                SheetEmptyHint(
                                    if (kw.isBlank()) {
                                        if (sel == "l") "地点库为空"
                                        else "这个分组下还没有地点"
                                    } else "没有匹配「$kw」的地点",
                                )
                            }
                        } else {
                            itemsIndexed(shownLocations) { _, l ->
                                SheetRow(
                                    isPlace = true,
                                    title = l.name.ifBlank { l.detailAddress.ifBlank { "未命名地点" } },
                                    phone = null,
                                    subtitle = l.detailAddress,
                                    // 分类与仓库都摆在行上：选地点时最需要区分的就是"这是哪一类、是不是我的仓"
                                    badge = listOfNotNull(
                                        l.category.ifBlank { null },
                                        if (l.isWarehouse) "仓库" else null,
                                    ).joinToString(" · ").ifBlank { "未分类" },
                                    hasCoords = !l.addressLat.isNullOrBlank(),
                                    // 位置照片（2026-09-20）：有图就摆一行缩略图 ——
                                    // 选点的时候"这个门口长什么样"比一行地址好认得多
                                    photoUrl = l.imageUrls.firstOrNull() ?: l.imageUrl,
                                    onClick = { onPickLocation(l) },
                                    actions = if (canManagePlaces) {
                                        listOf(RowAction("设为共享地址") { publishTarget = l })
                                    } else {
                                        emptyList()
                                    },
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
                            // 刚删掉的那条：**在列表顶上**给一次撤销的机会（删除是软删，
                            // 用户 2026-09-19：「这些所有功能的删（撤）销操作就是软删」）。
                            // 不塞进"页面底部提示位"：那在 LazyColumn 末尾，长列表里根本不在屏幕上。
                            recentlyDeleted?.let { (id, name) ->
                                item {
                                    Row(
                                        Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 6.dp),
                                        verticalAlignment = Alignment.CenterVertically,
                                    ) {
                                        Text(
                                            "已删除" + if (name.isBlank()) "这条共享地点" else "「$name」",
                                            style = MaterialTheme.typography.bodySmall,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                            modifier = Modifier.weight(1f),
                                        )
                                        TextButton(onClick = { onRestorePlace(id) }) { Text("撤销") }
                                    }
                                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                                }
                            }
                            itemsIndexed(places) { _, p ->
                                SheetRow(
                                    isPlace = true,
                                    title = p.name.ifBlank { p.detailAddress.ifBlank { "未命名地点" } },
                                    phone = null,
                                    subtitle = p.detailAddress,
                                    // ⛔ 这里**原来还挂着**「司机补录 · 用过 2 次」。
                                    // 用户 2026-09-19 点名去掉：「共享地址，它下面不要显示谁是谁使用了、
                                    // 谁是谁用了多少次，这个信息属于多余的」——
                                    // 选地址的时候这两个信息都帮不上忙（用了多少次是别人的使用习惯，
                                    // 来源是谁也不改变这个点能不能用），而它占着行里最醒目的一行小字。
                                    badge = null,
                                    hasCoords = true,
                                    // 共享库的位置照片（2026-09-20 用户：「共享库也加上图片」）——
                                    // 这一行是**全库共用**的，图越多，"下一个送货的人"越不容易找错门
                                    photoUrl = p.imageUrls.firstOrNull() ?: p.imageUrl,
                                    onClick = { onPickPlace(p) },
                                    actions = if (canManagePlaces) {
                                        listOf(
                                            RowAction("改名称或地址") { editingPlace = p },
                                            RowAction("撤销为我的地点") { demoteTarget = p },
                                            RowAction("从共享库删除") { deleteTarget = p },
                                        )
                                    } else {
                                        emptyList()
                                    },
                                )
                            }
                        }
                    }
                }
                }
            }
        }
    }

    // ---- 共享库的管理动作（都只对派单员开放入口）----
    editingPlace?.let { p ->
        EditPlaceDialog(
            place = p,
            busy = false,
            onSave = { name, addr ->
                onUpdatePlace(p.id, name, addr)
                editingPlace = null
            },
            onDismiss = { editingPlace = null },
        )
    }
    publishTarget?.let { l ->
        ConfirmActionDialog(
            hintPrefs = container.hintPrefs,
            title = "设为共享地址",
            // 常驻只留"几个字"（用户 2026-09-20：最多 7~8 字）；解释性的话走 HintOnce，
            // 出现三次就不再出现 —— 见 `ui/common/Components.kt::HintOnce`。
            line = "所有角色都能选到它",
            hintKey = "place.publish",
            hint = "你原来的「我的地点」不会消失，两边各有一份",
            target = l.name.ifBlank { l.detailAddress }.ifBlank { "这个地点" },
            confirmLabel = "设为共享",
            onConfirm = { onShareLocation(l) },
            onDismiss = { publishTarget = null },
        )
    }
    demoteTarget?.let { p ->
        ConfirmActionDialog(
            hintPrefs = container.hintPrefs,
            title = "撤销共享地址",
            line = "别人再也选不到它",
            hintKey = "place.demote",
            hint = "它会存进你自己的「我的地点」，以后只有你能选",
            target = p.name.ifBlank { p.detailAddress },
            confirmLabel = "撤销",
            onConfirm = { onDemotePlace(p.id) },
            onDismiss = { demoteTarget = null },
        )
    }
    deleteTarget?.let { p ->
        ConfirmActionDialog(
            hintPrefs = container.hintPrefs,
            title = "从共享库删除",
            line = "每个人都选不到它了",
            hintKey = "place.delete",
            hint = "删错了可以恢复；只想自己留着，请用「撤销」",
            target = p.name.ifBlank { p.detailAddress },
            confirmLabel = "删除",
            danger = true,
            onConfirm = { onDeletePlace(p.id) },
            onDismiss = { deleteTarget = null },
        )
    }
}

/** 行尾那个 `⋮` 里的一项（共享库的管理动作）。 */
private data class RowAction(val label: String, val onClick: () -> Unit)

/**
 * 一个动作的确认框：**标题 + 一句后果 + 确认**。
 *
 * 为什么要有它（而不是直接执行）：共享库那张表是全库共用的，「撤销」和「删除」在用户嘴里
 * 只差一个字，在库里差的是"别人还能不能选到它" —— 所以确认按钮写的就是动作本身
 * （「撤销」「删除」），不写成含糊的"确定"。
 *
 * 文案口径（用户 2026-09-20）：说清后果只留**一句话**（[line]）；
 * 更细的解释（"原来那条会不会消失""删错了怎么办"）走 [HintOnce] ——
 * 前三遍说清楚，之后不再占位置。以前这里是四行小字，用户的原话是"没必要，直接删掉就可以了"。
 */
@Composable
private fun ConfirmActionDialog(
    hintPrefs: HintPrefs,
    title: String,
    /** 这一动作会改变什么的**一句话**（常驻，≤ 8 字左右）。 */
    line: String,
    /** 解释性补充的**永久身份**（见 `HintOnce` 的注释：改文案不该让用户重看三遍）。 */
    hintKey: String,
    hint: String,
    /** 动的是哪一条（写进标题行，省得用户分不清点的是哪个地点）。 */
    target: String,
    confirmLabel: String,
    danger: Boolean = false,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            Column {
                if (target.isNotBlank()) {
                    Text(
                        "「" + target + "」",
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.SemiBold,
                        modifier = Modifier.padding(bottom = 6.dp),
                    )
                }
                Text(line, style = MaterialTheme.typography.bodyMedium)
                Spacer(Modifier.height(6.dp))
                HintOnce(hintPrefs, hintKey, hint)
            }
        },
        confirmButton = {
            TextButton(onClick = { onConfirm(); onDismiss() }) {
                Text(confirmLabel, color = if (danger) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary)
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}

/**
 * 改共享地点的**名称与地址**（坐标不给改：那是"这个位置在哪儿"的事实，见后端注释）。
 *
 * 两个框都预填当前值、都允许清空其中一个 —— 「名字和地址不能都是空」由后端判并给出一句话，
 * 这里不重复实现那条规则（两处写迟早有两种说法）。
 */
@Composable
private fun EditPlaceDialog(
    place: PlaceDto,
    busy: Boolean,
    onSave: (String?, String?) -> Unit,
    onDismiss: () -> Unit,
) {
    var name by remember(place.id) { mutableStateOf(place.name) }
    var address by remember(place.id) { mutableStateOf(place.detailAddress) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("改共享地点") },
        text = {
            // 弹窗本身就是一张白面，里面照样走共用行（不画第二个框）—— 2026-09-22 规范
            Column {
                FormInputRow(
                    label = "名称",
                    value = name,
                    onValueChange = { name = it },
                    placeholder = "如「一号仓」",
                    icon = Icons.Default.Label,
                    iconTint = Color(ShipperTeal),
                )
                FormTextAreaRow(
                    label = "地址",
                    value = address,
                    onValueChange = { address = it },
                    placeholder = "写清楚门牌 / 园区 / 楼栋",
                    icon = Icons.Default.Place,
                    iconTint = Color(MoneyOrange),
                )
                Spacer(Modifier.height(8.dp))
                Text(
                    "所有角色都会看到新的。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        },
        confirmButton = {
            TextButton(
                enabled = !busy,
                onClick = {
                    onSave(
                        name.trim().takeIf { it != place.name },
                        address.trim().takeIf { it != place.detailAddress },
                    )
                },
            ) { Text(if (busy) "保存中…" else "保存") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
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
/**
 * 弹层里的一行 —— 用**语义色 + 图标**把"人 / 电话 / 地点"分成三样东西。
 *
 * 用户 2026-09-19：「你看那个选择地址…有些信息都不是很明确，字都比较小。
 * 我们看信息的时候要有点明确啊，包括它这个表格，像有些**人物、电话号码、地点**，
 * 我们都可以用对应的**语义色和图标**进行区分。尤其是我们在选择地点的时候要格外注意，
 * **我们选地点可以加粗**，与那个人物和电话号码做一个区分」。
 *
 * 三段各有自己的图标与颜色（一色一功能，与全 App 同一套语义）：
 * | 是什么 | 图标 | 颜色 |
 * |---|---|---|
 * | 人（收货人姓名） | `Person` | 派单蓝 `#1E6FFF` |
 * | 电话 | `Phone` | 完成绿 `#00B578`（绿＝"能打通/可联系"） |
 * | 地点 | `Place` | 地址湖蓝 `#00A2C7`（与「地址与联系人」同色），**加粗** |
 * * 仓库用橙 `#FF9500`、分类用紫 `#8455E6`（与商品分类同色），都做成小标签。
 *
 * ⚠️ 地点名**加粗**是用户点名要的：不加粗时"地点名"和"收货人名"在屏幕上是同一副样子，
 *    而这一段最常见的一眼判断就是"这一条是地点还是人"。
 */
@Composable
private fun SheetRow(
    /** 这一行是"人/线路"还是"地点"——决定图标与标题颜色。 */
    isPlace: Boolean,
    title: String,
    /** 电话（线路才有）。单独一段、绿色 + 电话图标。 */
    phone: String?,
    subtitle: String,
    badge: String?,
    hasCoords: Boolean,
    /** 这个位置的照片；**当前不在卡片上显示**（见下面那条注释），参数留着是为了不动三段调用点。 */
    photoUrl: String? = null,
    /** 线路的**起点**（只有"线路"那一段有）。非空时这一行的主角变成「起点 → 终点」。 */
    origin: String? = null,
    onClick: () -> Unit,
    /** 行尾 `⋮` 里的管理动作（**只有派单员**会给；空 = 不画那个按钮）。 */
    actions: List<RowAction> = emptyList(),
) {
    val headColor = if (isPlace) Color(0xFF00A2C7) else Color(0xFF1E6FFF)
    val headIcon = if (isPlace) Icons.Default.Place else Icons.Default.Person
    // ⛔ 2026-09-22 用户：「那个**共享库**…那个**不要用列表的形式**，也使用**卡片**的形式，
    //    就是**类似商品一样**…而且那个共享库那个卡片形式要改一下，**重要的信息要优先显示**」。
    // 所以这一行不再是一条平铺的行，而是**一张白卡**（圆角 + 极轻阴影，与商品卡同一套观感）；
    // 「重要的信息优先」落在两处：**照片更大**（40 → 56dp，选点时"这个门口长什么样"最省事）、
    // 名称用 `titleMedium` 加粗（比地址重一档）。
    // ⚠️ 这一行是三段（线路 / 我的地点 / 共享地点）**共用**的：只把共享地点改成卡片，
    //    同一个抽屉里三段会长得不一样 —— 那种"半页改了"比没改更像坏了。
    Surface(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
        shape = MaterialTheme.shapes.medium,
        color = MaterialTheme.colorScheme.surface,
        shadowElevation = 1.dp,
    ) {
    Column(
        Modifier
            .fillMaxWidth()
            .clickable { onClick() }
            .padding(horizontal = 12.dp, vertical = 10.dp),
    ) {
        if (!isPlace) {
            // ---- 线路那一段：**主角是"从哪到哪"**（用户 2026-09-22 第三轮，指着这一屏说的：
            //      「这个地点库…这个线路也做个改变啊，这样子不好啊，主要我们的（重要）信息是**线路**，
            //       其次联系人什么的那个信息都可以**在下面放小一点**。而且他这个卡片是**可以做大一点**的」）
            //      ⛔ 上一版这一行的主角是**收货人姓名 + 电话**（大字），地址缩在第二行小字里 ——
            //        和线路卡犯的是同一个错（主次说反了），所以这里跟 `AddressScreen::AddressCard`
            //        同一套版式：起点 →（↓）→ 终点大字，联系人退到下面小字。
            Row(verticalAlignment = Alignment.Top) {
                Column(Modifier.weight(1f)) {
                    // 起点 →（共用连接线）→ 终点：三处用的是同一份 `RouteRail`
                    RouteRail(origin = origin, dest = subtitle)
                }
                SheetRowTrailing(hasCoords = hasCoords, actions = actions)
            }
            // 联系人 = 次要信息，放下面、小一点
            Row(Modifier.padding(top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Default.Person, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.size(12.dp))
                Spacer(Modifier.width(4.dp))
                Text(
                    title,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                )
                if (!phone.isNullOrBlank()) {
                    Spacer(Modifier.width(8.dp))
                    Icon(Icons.Default.Call, contentDescription = null, tint = Color(0xFF00B578), modifier = Modifier.size(11.dp))
                    Spacer(Modifier.width(3.dp))
                    Text(phone, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                }
                if (badge != null) {
                    Spacer(Modifier.width(8.dp))
                    Text(badge, style = MaterialTheme.typography.labelSmall, color = Color(0xFF8455E6))
                }
            }
        } else {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(headIcon, contentDescription = null, tint = headColor, modifier = Modifier.size(16.dp))
            Spacer(Modifier.width(6.dp))
            Text(
                title,
                style = MaterialTheme.typography.titleMedium,
                // 地点加粗（用户点名）；人只用颜色区分，不再加粗，否则两段又一样重
                fontWeight = FontWeight.Bold,
                color = headColor,
                maxLines = 1,
                // ⚠️ 标题**从尾部省略**（`StartEllipsis`），不是从头部。
                //
                // 地点标题常常**本身就是一串地址**（司机补录 / 共享地点进来的记录，
                // name 就是详细地址），而这一屏的地址开头全是「北京市顺义区」——
                // 真正区分彼此的只有**最后那一段**（村 / 小区 / 门牌）。
                // 常规的尾部省略恰好把唯一有用的部分省掉：真机截图里八行全是
                // 「北京市顺义...」，看八行等于没看。
                // 用户 2026-09-19：「省略是可以的，但是你要**从后面往前显示**……
                // 前面的前缀基本上不需要知道，所以那个最明显的那个有颜色的标题
                // 应该是**最后面**的那个地点」。
                overflow = androidx.compose.ui.text.style.TextOverflow.StartEllipsis,
                // ⚠️ 标题**独占**剩下的宽度。原来是 `weight(1f, fill = false)` 后面跟着一个
                //    `Spacer(Modifier.weight(1f))` —— 两个 1 权重把宽度**对半分**，
                //    22 个汉字的地址在右栏里只放得下 7 个字。改成独占后（「有导航」/电话
                //    都是不带权重的固有宽度，仍然贴右），同一行能多显示一倍的字。
                modifier = Modifier.weight(1f),
            )
            if (!phone.isNullOrBlank()) {
                Spacer(Modifier.width(10.dp))
                Icon(Icons.Default.Call, contentDescription = null, tint = Color(0xFF00B578), modifier = Modifier.size(14.dp))
                Spacer(Modifier.width(3.dp))
                Text(
                    phone,
                    style = MaterialTheme.typography.bodyMedium,
                    color = Color(0xFF00B578),
                    maxLines = 1,
                )
            }
            SheetRowTrailing(hasCoords = hasCoords, actions = actions)
        }
        if (subtitle.isNotBlank()) {
            Spacer(Modifier.height(3.dp))
            Text(
                subtitle,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                // ⚠️ 2026-09-22 从 2 行放宽到 **3 行**：地址就是这一行的主体信息，
                //    卡片可以高一点，但**地址不许被省略**（用户：「很多信息由于显示图片
                //    导致了他那个地点的信息被丢失了」—— 根因是图占了 56dp、地址只剩两行）。
                maxLines = 3,
                overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
            )
        }
        if (badge != null) {
            Spacer(Modifier.height(4.dp))
            Text(
                badge,
                style = MaterialTheme.typography.labelSmall,
                color = Color(0xFF8455E6),
            )
        }
        }
    }
    }
}

/**
 * 卡片右侧那一小撮：[有导航] + `⋮` 管理菜单（线路与地点两段共用）。
 *
 * 抽出来是因为 2026-09-22 之后这一行有了**两种主体**（线路 / 地点），
 * 右侧这一撮完全一样 —— 抄两份的话，"⋮ 里的动作"迟早会有一边忘了接。
 */
@Composable
private fun SheetRowTrailing(hasCoords: Boolean, actions: List<RowAction>) {
    if (hasCoords) {
        Spacer(Modifier.width(8.dp))
        Text(
            "有导航",
            style = MaterialTheme.typography.labelSmall,
            color = Color(0xFF00B578),
            fontWeight = FontWeight.Bold,
        )
    }
    // 管理动作收进 `⋮`（设计规范 §4.2：卡片上的动作三个以上就收进 `⋮`）。
    // ⛔ 不要把它们平铺成文字按钮：共享库那一行已经有「改名称/撤销/删除」三个，
    //    平铺会把整行的排版压垮，而"删除"混在里面也更容易被误点。
    if (actions.isNotEmpty()) {
        var open by remember { mutableStateOf(false) }
        Box {
            IconButton(onClick = { open = true }, modifier = Modifier.size(30.dp)) {
                Icon(
                    Icons.Default.MoreVert,
                    contentDescription = "更多操作",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(18.dp),
                )
            }
            DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
                actions.forEach { a ->
                    DropdownMenuItem(
                        text = { Text(a.label) },
                        onClick = { open = false; a.onClick() },
                    )
                }
            }
        }
    }
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
                FormInputRow(
                    label = "商品名称",
                    value = name,
                    onValueChange = { name = it },
                    placeholder = "商品名",
                    icon = Icons.Default.Inventory2,
                    iconTint = Color(0xFF8455E6),
                )
                Spacer(Modifier.height(10.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("数量", style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
                    FilledTonalIconButton(onClick = { qty = (qty - 1).coerceAtLeast(1) }) {
                        Icon(Icons.Default.Remove, contentDescription = "减")
                    }
                    // ⚠️ 数量那个小框**不**走 FormRows：它不是"一行标签 + 值"，
                    //    是步进器中间的紧凑控件（全 App 同一个形态，见 `ProductPicker::QtyDialog`）。
                    //    这类控件**算进**描边输入框的总数、但不算"表单分组里的框"（判据里写明了）。
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
                    "价格由商品定价决定",
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
