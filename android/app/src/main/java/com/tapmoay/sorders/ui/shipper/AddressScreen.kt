package com.tapmoay.sorders.ui.shipper

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import coil.compose.AsyncImage
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.core.UserSearch
import com.tapmoay.sorders.util.resolveStaticUrl
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import java.io.File
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.data.remote.dto.AddressDto
import com.tapmoay.sorders.data.remote.dto.ContactDto
import com.tapmoay.sorders.data.remote.dto.LocationDto
import com.tapmoay.sorders.ui.theme.InventoryTeal
import com.tapmoay.sorders.ui.theme.MgrGreen
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.ui.theme.ShipperTeal
import android.graphics.Bitmap
import com.tapmoay.sorders.ui.common.Hint

/** 地址与联系人：三个列表（常用线路=联系人+地点 → 联系人 → 地点），新增入口在各自标题行右侧 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AddressScreen(
    container: AppContainer,
    onBack: () -> Unit,
) {
    val vm: AddressViewModel = appViewModel { AddressViewModel(container) }
    var showContactMenu by remember { mutableStateOf(false) }
    var startLocMenu by remember { mutableStateOf(false) }
    var endLocMenu by remember { mutableStateOf(false) }
    var imageTarget by remember { mutableStateOf("loc") }
    var showImageSource by remember { mutableStateOf(false) }
    var tab by remember { mutableStateOf(0) }  // 0=路线 1=联系人 2=地址
    // 搜索词：三段共用（换段时清空 —— 在"联系人"里搜的名字带到"地点"段只会得到空列表）
    var keyword by remember { mutableStateOf("") }
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    fun savePickedImage(uri: android.net.Uri, target: String, prefix: String) {
        scope.launch(Dispatchers.IO) {
            try {
                val dir = File(context.cacheDir, "loc_images").apply { mkdirs() }
                val f = File(dir, prefix + "_" + System.currentTimeMillis() + "_" + (0..99999).random() + ".jpg")
                context.contentResolver.openInputStream(uri)?.use { inp ->
                    f.outputStream().use { it.write(inp.readBytes()) }
                }
                if (target == "line") vm.uploadLineImage(f) else vm.uploadLocationImage(f)
            } catch (_: Exception) {
                vm.formError = "图片读取失败，请重试"
            }
        }
    }

    // 多选相册（可一次选多张）
    val photoPicker = rememberLauncherForActivityResult(ActivityResultContracts.PickMultipleVisualMedia(maxItems = 9)) { uris ->
        val target = imageTarget
        if (uris.isNotEmpty()) {
            uris.forEach { uri -> savePickedImage(uri, target, "gallery") }
        }
    }

    // 拍照 → 预览位图 → 压缩落盘上传
    val cameraLauncher = rememberLauncherForActivityResult(ActivityResultContracts.TakePicturePreview()) { bmp ->
        val target = imageTarget
        if (bmp != null) {
            scope.launch(Dispatchers.IO) {
                try {
                    val dir = File(context.cacheDir, "loc_images").apply { mkdirs() }
                    val f = File(dir, "cam_" + System.currentTimeMillis() + ".jpg")
                    f.outputStream().use { bmp.compress(Bitmap.CompressFormat.JPEG, 88, it) }
                    if (target == "line") vm.uploadLineImage(f) else vm.uploadLocationImage(f)
                } catch (_: Exception) {
                    vm.formError = "图片处理失败，请重试"
                }
            }
        }
    }

    // 行上的「删除 / 设为默认」这类**没有表单可挂**的动作，失败时用 Snackbar 说一句
    // （与全 App 的做法一致：`OneShotSnackbar` + `vm.notice` 用完置回 null）。
    // ⛔ 不要把它写进 loadError —— 那会把整页换成错误页，而列表其实好好的。
    val snackbar = remember { SnackbarHostState() }
    OneShotSnackbar(snackbar, vm.notice, onConsumed = { vm.notice = null })

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = { Text("地址与联系人") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding)) {
            AddressTabBar(tab = tab, onTab = { tab = it; keyword = "" })
            // 搜索框**三段都有**（用户 2026-09-18：只要是选地点的地方都能搜）。
            // 这里搜的是本地已有的那份列表 —— 数据本来就在手上，即时出结果，
            // 不需要往返后端（共享库那一段在下单页的地址弹层里，那里才需要打后端）。
            Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
                SoTextField(
                    value = keyword,
                    onValueChange = { keyword = it },
                    placeholder = when (tab) {
                        0 -> "搜线路：收货人 / 电话 / 地址"
                        1 -> "搜联系人：姓名 / 电话"
                        else -> "搜地点：名称 / 地址"
                    },
                )
                if (keyword.isNotBlank()) {
                    TextButton(
                        onClick = { keyword = "" },
                        modifier = Modifier.align(Alignment.CenterEnd),
                    ) { Text("清除") }
                }
            }
            val kw = keyword.trim()
            val shownAddresses = remember(vm.addresses, kw) {
                if (kw.isBlank()) vm.addresses
                else vm.addresses.filter {
                    it.receiverName.contains(kw, true) || it.phone.contains(kw) ||
                        it.detailAddress.contains(kw, true) || it.originAddress.orEmpty().contains(kw, true)
                }
            }
            val shownContacts = remember(vm.contacts, kw) {
                if (kw.isBlank()) vm.contacts
                // 「联系人」这一段是**纯按人搜**（姓名 / 手机号，后 4 位也命中）——
                // 走全 App 唯一那份规则（`core/UserSearch`），不在这里再写一遍 contains。
                // ⚠️ 上面「线路」那一段**故意不用它**：它还要按地址文本匹配，
                //    套上只认姓名/手机号的规则会让「按地址找线路」直接失效。
                else vm.contacts.filter { UserSearch.matches(kw, it.displayName, it.phone) }
            }
            val shownLocations = remember(vm.locations, kw) {
                if (kw.isBlank()) vm.locations
                else vm.locations.filter { it.name.contains(kw, true) || it.detailAddress.contains(kw, true) }
            }
            Box(Modifier.weight(1f)) {
                when {
                    vm.loading -> LoadingBox(Modifier.fillMaxSize())
                    // ⚠️ 只看 **loadError**：表单的错误写在抽屉里（见 AddressViewModel 的注释），
                    //    混进来就会让"保存被拦下"变成"整页列表全没了"。
                    vm.loadError != null -> ErrorView(vm.loadError.orEmpty(), onRetry = { vm.load() }, Modifier.fillMaxSize())
                    else -> LazyColumn(
                        Modifier.fillMaxSize(),
                        contentPadding = PaddingValues(16.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        when (tab) {
                            // ---- 2. 联系人 ----
                            1 -> {
                                item {
                                    Row(verticalAlignment = Alignment.CenterVertically) {
                                        Text("联系人", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                                        TextButton(onClick = { vm.openContactDialog() }) {
                                            Icon(Icons.Default.PersonAddAlt, null, Modifier.size(16.dp), tint = Color(MgrGreen))
                                            Spacer(Modifier.width(3.dp))
                                            Text("新增联系人")
                                        }
                                    }
                                }
                                if (shownContacts.isEmpty()) {
                                    item { EmptyView(if (kw.isBlank()) "暂无联系人" else "没有匹配「$kw」的联系人") }
                                } else {
                                    items(shownContacts, key = { "c" + it.id }) { c ->
                                        ContactCard(c = c, onEdit = { vm.openContactDialog(c) }, onDelete = { vm.deleteContact(c) })
                                    }
                                }
                            }

                            // ---- 3. 地点（单独地点）----
                            2 -> {
                                item {
                                    Row(verticalAlignment = Alignment.CenterVertically) {
                                        Text("地点", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                                        TextButton(onClick = { vm.openLocationCreate() }) {
                                            Icon(Icons.Default.Place, null, Modifier.size(16.dp), tint = Color(MoneyOrange))
                                            Spacer(Modifier.width(3.dp))
                                            Text("新增地点")
                                        }
                                    }
                                }
                                if (shownLocations.isEmpty()) {
                                    item { EmptyView(if (kw.isBlank()) "暂无地点" else "没有匹配「$kw」的地点") }
                                } else {
                                    items(shownLocations, key = { "l" + it.id }) { l ->
                                        LocationCard(l = l, onEdit = { vm.openLocationEdit(l) }, onDelete = { vm.deleteLocation(l) })
                                    }
                                }
                            }

                            // ---- 1. 常用线路（联系人 + 地点）----
                            else -> {
                                item {
                                    Row(verticalAlignment = Alignment.CenterVertically) {
                                        Text("常用线路（联系人+地点）", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                                        TextButton(onClick = { vm.openCreate() }) {
                                            Icon(Icons.Default.AddLocationAlt, null, Modifier.size(16.dp), tint = Color(ShipperTeal))
                                            Spacer(Modifier.width(3.dp))
                                            Text("新增线路")
                                        }
                                    }
                                    Spacer(Modifier.height(4.dp))
                                }
                                if (shownAddresses.isEmpty()) {
                                    item { EmptyView(if (kw.isBlank()) "暂无线路，点右侧新增" else "没有匹配「$kw」的线路") }
                                } else {
                                    items(shownAddresses, key = { "a" + it.id }) { a ->
                                        AddressCard(a = a, onEdit = { vm.openEdit(a) }, onDelete = { vm.delete(a) })
                                    }
                                }
                            }
                        }
                        item { Spacer(Modifier.height(24.dp)) }
                    }
                }
            }
        }
    }

    // ---- 新增/编辑线路：底部抽屉（联系人选择 + 起点/终点）----
    if (vm.showCreateDialog) {
        ModalBottomSheet(
            onDismissRequest = { vm.showCreateDialog = false },
            sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        ) {
            Column(
                Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp)
                    .imePadding()
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                Text(if (vm.editing == null) "新增线路" else "编辑线路", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)

                // ---- 四个**白卡分组**（2026-09-22 用户定的全局规范）----
                // 原话：「…只是用**线框**框起来的话太不美观了，而且也不够醒目对比，
                // 所以把他们改进这种**白色的卡片样式**…**这就是个设计规范，包括以后也是这样子啊，
                // 所有都要这样子去改**」。
                // 所以这一页从"一串描边输入框浮在灰底上"改成"**每个分组一张白卡**、
                // 卡里的行不画边框（值本身就是占位符）"——与「新增商品」页同一套行
                // （`ui/common/FormRows.kt`）。
                // ⛔ 判据 `_tools/qa/_check_form_panel_style.py`：这一页的 `OutlinedTextField` 必须是 0。

                // ① 联系人
                FormGroup(icon = Icons.Default.Person, title = "联系人", tint = Color(ShipperTeal)) {
                    ExposedDropdownMenuBox(expanded = showContactMenu, onExpandedChange = { showContactMenu = it }) {
                        FormPickRow(
                            label = "收货联系人",
                            value = if (vm.draftContactId != null) vm.draftName + " " + vm.draftPhone else "",
                            placeholder = "请选择联系人",
                            // 图标与语义色跟着搬（2026-09-22 用户：「图标和语义色不能去掉」）
                            icon = Icons.Default.Person,
                            iconTint = Color(ShipperTeal),
                            onClick = { showContactMenu = true },
                            modifier = Modifier.menuAnchor(),
                        )
                        ExposedDropdownMenu(expanded = showContactMenu, onDismissRequest = { showContactMenu = false }) {
                            DropdownMenuItem(
                                text = { Text("＋ 新增联系人", color = MaterialTheme.colorScheme.primary) },
                                onClick = { showContactMenu = false; vm.openContactDialog(fromLine = true) },
                            )
                            if (vm.contacts.isEmpty()) {
                                DropdownMenuItem(text = { Text("暂无联系人，请先新增联系人") }, onClick = { showContactMenu = false })
                            } else {
                                vm.contacts.forEach { c ->
                                    DropdownMenuItem(
                                        text = { Text(c.displayName.ifBlank { "联系人" } + " " + c.phone) },
                                        onClick = { vm.selectContact(c); showContactMenu = false },
                                    )
                                }
                            }
                        }
                    }
                }

                // ② 起点（可选）
                FormGroup(icon = Icons.Default.Route, title = "起点（可选，从这出发）", tint = Color(InventoryTeal)) {
                    FormTextAreaRow(
                        label = "起点地址",
                        value = vm.draftOrigin,
                        onValueChange = { vm.draftOrigin = it },
                        placeholder = "不填就是「只送到终点」",
                        icon = Icons.Default.Route,
                        iconTint = Color(InventoryTeal),
                    )
                    Box {
                        FormActionRow(
                            label = "从地点库选起点",
                            onClick = { startLocMenu = true },
                            icon = Icons.Default.List,
                            iconTint = Color(InventoryTeal),
                        )
                        DropdownMenu(expanded = startLocMenu, onDismissRequest = { startLocMenu = false }) {
                            DropdownMenuItem(
                                text = { Text("＋ 新增地点", color = MaterialTheme.colorScheme.primary) },
                                onClick = { startLocMenu = false; vm.openLocationCreate("start") },
                            )
                            if (vm.locations.isEmpty()) {
                                DropdownMenuItem(text = { Text("暂无地点，请先新增地点") }, onClick = { startLocMenu = false })
                            } else {
                                vm.locations.forEach { l ->
                                    DropdownMenuItem(
                                        text = { Text(l.name.ifBlank { "地点" } + " · " + l.detailAddress, maxLines = 1) },
                                        onClick = { vm.selectOriginLocation(l); startLocMenu = false },
                                    )
                                }
                            }
                        }
                    }
                    FormActionRow(
                        label = "在地图上选起点",
                        onClick = { vm.openPicker("origin") },
                        icon = Icons.Default.Route,
                        iconTint = Color(InventoryTeal),
                    )
                }

                // ③ 终点（必填）
                FormGroup(icon = Icons.Default.Place, title = "终点（必填）", tint = Color(MoneyOrange)) {
                    FormTextAreaRow(
                        label = "终点地址",
                        value = vm.draftDetail,
                        onValueChange = { vm.draftDetail = it },
                        placeholder = "送到哪里",
                        required = true,
                        icon = Icons.Default.Place,
                        iconTint = Color(MoneyOrange),
                    )
                    Box {
                        FormActionRow(
                            label = "从地点库选终点",
                            onClick = { endLocMenu = true },
                            icon = Icons.Default.List,
                            iconTint = Color(MoneyOrange),
                        )
                        DropdownMenu(expanded = endLocMenu, onDismissRequest = { endLocMenu = false }) {
                            DropdownMenuItem(
                                text = { Text("＋ 新增地点", color = MaterialTheme.colorScheme.primary) },
                                onClick = { endLocMenu = false; vm.openLocationCreate("end") },
                            )
                            if (vm.locations.isEmpty()) {
                                DropdownMenuItem(text = { Text("暂无地点，请先新增地点") }, onClick = { endLocMenu = false })
                            } else {
                                vm.locations.forEach { l ->
                                    DropdownMenuItem(
                                        text = { Text(l.name.ifBlank { "地点" } + " · " + l.detailAddress, maxLines = 1) },
                                        onClick = { vm.selectDestLocation(l); endLocMenu = false },
                                    )
                                }
                            }
                        }
                    }
                    FormActionRow(
                        label = "在地图上选终点",
                        onClick = { vm.openPicker("dest") },
                        icon = Icons.Default.Place,
                        iconTint = Color(MoneyOrange),
                    )
                }

                // ④ 线路图片 + 设为默认（`ImageStrip` 自带标题，所以这一张卡不再加组标题）
                SectionCard {
                    ImageStrip(
                        label = "线路图片",
                        urls = vm.draftImageUrls,
                        uploading = vm.draftImageUploading,
                        tint = Color(MoneyOrange),
                        hint = "支持拍照或从相册选择，可上传多张；从地点库选择会自动带图",
                        onAdd = { imageTarget = "line"; showImageSource = true },
                        onRemove = { vm.removeLineImage(it) },
                    )
                    FormSwitchRow(
                        label = "设为默认线路",
                        checked = vm.draftIsDefault,
                        onCheckedChange = { vm.draftIsDefault = it },
                    )
                }

                // 校验/保存失败的那句话画在**抽屉里面**（见 FormErrorLine 的注释：
                // 写进页面级错误会让"保存被拦下"变成"整页列表全没了"）
                FormErrorLine(vm.formError)
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { vm.showCreateDialog = false }, modifier = Modifier.weight(1f).height(48.dp)) { Text("取消") }
                    Button(onClick = { vm.save() }, enabled = !vm.acting, modifier = Modifier.weight(1f).height(48.dp)) { Text(if (vm.acting) "保存中…" else "保存") }
                }
                Spacer(Modifier.height(24.dp))
            }
        }
    }

    // ---- 新增/编辑地点：底部抽屉 ----
    if (vm.showLocationDialog) {
        ModalBottomSheet(
            onDismissRequest = { vm.showLocationDialog = false },
            sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        ) {
            Column(
                Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp)
                    .imePadding()
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                Text(if (vm.editingLocation == null) "新增地点" else "编辑地点", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                // ---- 白卡 1：这个地点是什么 ----
                FormGroup(icon = Icons.Default.Place, title = "地点", tint = Color(MoneyOrange)) {
                    FormInputRow(
                        label = "地点名称",
                        value = vm.locName,
                        onValueChange = { vm.locName = it },
                        placeholder = "选填，如「一号仓」",
                        icon = Icons.Default.Label,
                        iconTint = Color(ShipperTeal),
                    )
                    FormTextAreaRow(
                        label = "详细地址",
                        value = vm.locDetail,
                        onValueChange = { vm.locDetail = it },
                        placeholder = "写清楚门牌 / 园区 / 楼栋",
                        required = true,
                        icon = Icons.Default.Place,
                        iconTint = Color(MoneyOrange),
                    )
                    // 分组（用户 2026-09-19：「这个分类**不是填名字**啊，是**选择分类**；
                    // 下面不要把它新建的直接写到下面，就相当于点击那个，它下面就有个滑框
                    // 选择对应的分类就可以了」）
                    //
                    // 所以：**下拉选择**（设计规范 §5 写明了「下拉一律 ExposedDropdownMenuBox 点选回填，
                    // **不要**用 chips 替代下拉」）+ 最后一项「＋ 新建分组…」。
                    // 第一版写成"自由填 + 一排可点的小块"，正是规范里否决过的做法。
                    var catExpanded by remember { mutableStateOf(false) }
                    var newCatDialog by remember { mutableStateOf(false) }
                    ExposedDropdownMenuBox(expanded = catExpanded, onExpandedChange = { catExpanded = it }) {
                        FormPickRow(
                            label = "分组",
                            value = vm.locCategory.trim(),
                            placeholder = "未分类",
                            icon = Icons.Default.Folder,
                            iconTint = Color(0xFF8455E6),
                            onClick = { catExpanded = true },
                            modifier = Modifier.menuAnchor(),
                        )
                        ExposedDropdownMenu(expanded = catExpanded, onDismissRequest = { catExpanded = false }) {
                            DropdownMenuItem(
                                text = { Text("未分类") },
                                onClick = { vm.locCategory = ""; catExpanded = false },
                            )
                            vm.placeCategories.forEach { c ->
                                DropdownMenuItem(
                                    // 带上"这一类下有几个地点"：选分组时能看出哪个是主力
                                    text = {
                                        Text(
                                            c.name + if (c.locationCount > 0) "（${c.locationCount} 个地点）" else "",
                                            maxLines = 1,
                                        )
                                    },
                                    onClick = { vm.locCategory = c.name; catExpanded = false },
                                )
                            }
                            HorizontalDivider()
                            DropdownMenuItem(
                                text = { Text("＋ 新建分组…") },
                                onClick = { catExpanded = false; newCatDialog = true },
                            )
                        }
                    }
                    if (newCatDialog) {
                        NewPlaceCategoryDialog(
                            busy = vm.acting,
                            error = vm.formError,
                            onConfirm = { name ->
                                vm.createPlaceCategoryAndSelect(name) { newCatDialog = false }
                            },
                            onDismiss = { newCatDialog = false },
                        )
                    }
                    // 仓库：**只有派单员**能标（后端也拦；这里只是不给他看一个点了会报错的开关）
                    // ⚠️ **不给解释文字**（用户 2026-09-19：「这个设为仓库下面是有解释的，没必要解释」）。
                    if (vm.canMarkWarehouse) {
                        FormSwitchRow(
                            label = "设为仓库",
                            checked = vm.locIsWarehouse,
                            onCheckedChange = { vm.locIsWarehouse = it },
                            icon = Icons.Default.Warehouse,
                            iconTint = Color(MoneyOrange),
                        )
                    }
                    FormActionRow(
                        label = "在地图上选点",
                        onClick = { vm.openPicker("loc") },
                        icon = Icons.Default.Place,
                        iconTint = Color(MoneyOrange),
                    )
                }
                // ---- 白卡 2：图片 + 备注 ----
                SectionCard {
                    ImageStrip(
                        label = "地点图片",
                        urls = vm.locImageUrls,
                        uploading = vm.locImageUploading,
                        tint = Color(MoneyOrange),
                        hint = "支持拍照或从相册选择，可上传多张",
                        onAdd = { imageTarget = "loc"; showImageSource = true },
                        onRemove = { vm.removeLocImage(it) },
                    )
                    FormInputRow(
                        label = "备注",
                        value = vm.locRemark,
                        onValueChange = { vm.locRemark = it },
                        placeholder = "选填",
                        icon = Icons.Default.Notes,
                        iconTint = Color(0xFF8A8A8E),
                    )
                }
                // 同上：新增/编辑地点被拦下时，那句话说在**这张抽屉里**
                FormErrorLine(vm.formError)
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { vm.showLocationDialog = false }, modifier = Modifier.weight(1f).height(48.dp)) { Text("取消") }
                    Button(onClick = { vm.saveLocation() }, enabled = !vm.acting, modifier = Modifier.weight(1f).height(48.dp)) { Text(if (vm.acting) "保存中…" else "保存") }
                }
                Spacer(Modifier.height(24.dp))
            }
        }
    }

    // ---- 地图选点（终点/起点/地点）----
    if (vm.showMapPicker) {
        AmapPickerDialog(
            container = container,
            initialLat = when (vm.mapTarget) {
                "origin" -> vm.draftOriginLat?.toDoubleOrNull()
                "loc" -> vm.locLat?.toDoubleOrNull()
                else -> vm.draftLat?.toDoubleOrNull()
            },
            initialLng = when (vm.mapTarget) {
                "origin" -> vm.draftOriginLng?.toDoubleOrNull()
                "loc" -> vm.locLng?.toDoubleOrNull()
                else -> vm.draftLng?.toDoubleOrNull()
            },
            onPicked = { lat, lng, address -> vm.applyPicked(lat, lng, address) },
            onDismiss = { vm.showMapPicker = false },
        )
    }

    // ---- 添加图片：选择来源（拍照 / 从相册选择）----
    if (showImageSource) {
        AlertDialog(
            onDismissRequest = { showImageSource = false },
            title = { Text("添加图片") },
            text = {
                Column {
                    Row(
                        Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
                            .clickable { showImageSource = false; cameraLauncher.launch(null) }
                            .padding(vertical = 12.dp, horizontal = 4.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(Icons.Default.PhotoCamera, contentDescription = null, tint = Color(ShipperTeal))
                        Spacer(Modifier.width(10.dp))
                        Text("拍照", style = MaterialTheme.typography.bodyLarge)
                    }
                    Row(
                        Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
                            .clickable { showImageSource = false; photoPicker.launch(androidx.activity.result.PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) }
                            .padding(vertical = 12.dp, horizontal = 4.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(Icons.Default.PhotoLibrary, contentDescription = null, tint = Color(MoneyOrange))
                        Spacer(Modifier.width(10.dp))
                        Text("从相册选择（可多选）", style = MaterialTheme.typography.bodyLarge)
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { showImageSource = false }) { Text("取消") }
            },
        )
    }

    // ---- 联系人抽屉 ----
    if (vm.showContactDialog) {
        ModalBottomSheet(
            onDismissRequest = { vm.showContactDialog = false },
            sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        ) {
            Column(
                Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp)
                    .imePadding()
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                Text(if (vm.editingContact == null) "添加联系人" else "编辑联系人", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                // 同样是**白卡 + 共用行**（2026-09-22 的全局规范，见设计系统 §5.0）
                SectionCard {
                    FormInputRow(
                        label = "称呼",
                        value = vm.contactName,
                        onValueChange = { vm.contactName = it },
                        placeholder = "选填，如「张老板」",
                        icon = Icons.Default.Person,
                        iconTint = Color(ShipperTeal),
                    )
                    FormInputRow(
                        label = "电话",
                        value = vm.contactPhone,
                        // 电话只让数字进来（规则唯一实现在 core/InputRules.kt）
                        onValueChange = { vm.contactPhone = InputRules.phoneInput(it) },
                        placeholder = "请输入手机号",
                        required = true,
                        keyboardType = KeyboardType.Phone,
                        icon = Icons.Default.Phone,
                        iconTint = Color(MgrGreen),
                    )
                }
                // 同上：电话不合规（InputRules 那一句）也画在这张抽屉里
                FormErrorLine(vm.formError)
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { vm.showContactDialog = false }, modifier = Modifier.weight(1f).height(48.dp)) { Text("取消") }
                    Button(onClick = { vm.saveContact() }, modifier = Modifier.weight(1f).height(48.dp)) { Text(if (vm.editingContact == null) "添加" else "保存") }
                }
                Spacer(Modifier.height(24.dp))
            }
        }
    }
}

/**
 * 地点表单里那个「＋ 新建分组…」的弹窗（与商品编辑页的 `NewCategoryDialog` 同一形状）。
 *
 * 建好后后端会把它补进名册、界面**自动选中**它 —— 用户点"新建分组"的意图是"归到这一类"，
 * 不该建完还要自己再选一次。
 */
@Composable
private fun NewPlaceCategoryDialog(
    busy: Boolean,
    onConfirm: (String) -> Unit,
    onDismiss: () -> Unit,
    /** 建失败时的一句话（如"已经存在"之外的错误）；画在弹窗里，不写到页面上。 */
    error: String? = null,
) {
    var name by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("新建分组") },
        text = {
            Column {
                SoTextField(
                    value = name,
                    onValueChange = { name = it.take(8) },
                    placeholder = "分组名，如 常送小区 / 工地",
                )
                Spacer(Modifier.height(8.dp))
                Hint(
                    "建好后会自动选中它。顺序到地址库左栏的「管理分组」里排。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                FormErrorLine(error)
            }
        },
        confirmButton = {
            TextButton(enabled = !busy && name.isNotBlank(), onClick = { onConfirm(name) }) {
                Text(if (busy) "提交中…" else "新建并选中")
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}

/**
 * 线路卡：**从 A 点到 B 点**是主角，联系人退到下面，删除/编辑在**左边一上一下**。
 *
 * 用户 2026-09-22 原话：「还有一点就是**线路的这个卡片这个样式不好**，你要知道我们的线路
 * 主要是什么**从 A 点**…那个**联系人啊，可以放在下面**，但是**线必须放在从 A 到 B**，
 * 然后那个**编辑和删除稍微放在左边**…**一上一下**的关系，**上面是删除、下面就是编辑**」
 * ⚠️ 后半句他当场改口了：「**啊说错了，说错了，那个编辑和删除不要在左边是在右边了**」
 * —— 所以动作收在**右边**（还是**一上一下、上删除下编辑**）；左边那一条留给 A→B 轨道。
 *
 * ⚠️ **删除在上、编辑在下**（用户点名两遍）—— ⛔ 不要"顺手"把危险的那个换到下面去。
 *
 * ⚠️ **起点为空时只画终点行**（不画假起点、也不写字占位）：那条线路本来就没填起点，
 * 画一条"（未填）→ 终点"的轨道会让人以为线路坏了。表单里那一栏写的是「不填就是只送到终点」。
 */
@Composable
private fun AddressCard(a: AddressDto, onEdit: () -> Unit, onDelete: () -> Unit) {
    SectionCard {
        Row(verticalAlignment = Alignment.Top) {
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.Top) {
                    // ---- 中：A → B 轨道（这一张卡的主语；连线那一条是共用的 `RouteRail`）
                    Column(Modifier.weight(1f)) {
                        RouteRail(origin = a.originAddress, dest = a.detailAddress)
                    }
                    // ---- 右上：线路图片（有才画）----
                    val img = a.imageUrls.firstOrNull() ?: a.imageUrl
                    if (!img.isNullOrBlank()) {
                        Spacer(Modifier.width(10.dp))
                        AsyncImage(
                            model = resolveStaticUrl(img),
                            contentDescription = "线路图片",
                            contentScale = ContentScale.Crop,
                            modifier = Modifier.size(56.dp).clip(RoundedCornerShape(10.dp)),
                        )
                    }
                }
                Spacer(Modifier.height(10.dp))
                // ---- 下面：联系人（**次要信息，要小**）----
                // 用户 2026-09-22 第二轮：「**线路卡片重要的信息是什么？重要的信息是线路啊**，
                // 像什么**联系人和电话都是次要信息**，都可以**非常小**、都可以小一点，
                // 而且这个线路的卡片**可以拉大一点、拉长也没关系**，因为线路本身信息量有点多」。
                // ⛔ 所以这一行从 `titleMedium` 加粗降成 `bodySmall` 灰字、图标块 30 → 22dp ——
                //    上一版它比"起点/终点"还大，正好把主次说反了。
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TintedIcon(Icons.Default.AccountCircle, Color(ShipperTeal), size = 11.dp, container = 22.dp)
                    Spacer(Modifier.width(8.dp))
                    Text(
                        a.receiverName.ifBlank { "收货人" },
                        style = MaterialTheme.typography.bodySmall,
                        fontWeight = FontWeight.Medium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                    )
                    Spacer(Modifier.width(6.dp))
                    Icon(Icons.Default.Phone, contentDescription = "电话", modifier = Modifier.size(11.dp), tint = Color(0xFF00B578))
                    Spacer(Modifier.width(3.dp))
                    Text(
                        a.phone,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                    )
                    Spacer(Modifier.weight(1f))
                    if (a.isDefault) {
                        Surface(color = MaterialTheme.colorScheme.primaryContainer, shape = MaterialTheme.shapes.small) {
                            Text(
                                "默认",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onPrimaryContainer,
                                modifier = Modifier.padding(horizontal = 6.dp, vertical = 1.dp),
                            )
                        }
                    }
                }
                if (a.remark.isNotBlank()) {
                    Spacer(Modifier.height(4.dp))
                    Text(a.remark, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline, maxLines = 2)
                }
            }
            Spacer(Modifier.width(8.dp))
            // ---- 右：删除（上）/ 编辑（下）—— 一上一下，删除在上（用户点名两遍）----
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                IconButton(onClick = onDelete, modifier = Modifier.size(36.dp)) {
                    Icon(
                        Icons.Default.Delete,
                        contentDescription = "删除",
                        tint = MaterialTheme.colorScheme.error,
                        modifier = Modifier.size(18.dp),
                    )
                }
                IconButton(onClick = onEdit, modifier = Modifier.size(36.dp)) {
                    Icon(Icons.Default.Edit, contentDescription = "编辑", modifier = Modifier.size(18.dp))
                }
            }
        }
    }
}

// ⛔ 这里原来有一个 private 的 `RouteStop`（这一页自己画的"一个停靠点"：图标 + 小标签 + 地址）。
// 2026-09-22 第三轮它被**共用件** `ui/common/RouteRail.kt` 取代了 —— 用户要的是
// 「有个**连接 2 个图标**而且**处于中间**的（线）」，而"起点、终点、中间那条线"必须
// **一处画、三处用**（线路卡 / 地址库线路行 / 订单详情），各画一份就是"参差不齐"的来源。

// ⛔ 这里原来有一个 private 的 `FormGroup`（这一页自己写的"卡外标题 + 白卡"）。
// 2026-09-22 它**搬进了共用零件** `ui/common/FormRows.kt::FormGroup` —— 理由和所有"抄第二份"
// 一样：下单页（`OrderCreateScreen`）也要同一个分组形态，各写一份就会出现
// "两个页面的组标题字号/间距不一样"。判据 `_check_form_panel_style.py` 钉着它只许有一处。

/** 联系人卡 */
@Composable
private fun ContactCard(c: ContactDto, onEdit: () -> Unit, onDelete: () -> Unit) {
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            TintedIcon(Icons.Default.Person, Color(ShipperTeal), size = 16.dp, container = 32.dp)
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(c.displayName.ifBlank { "联系人" }, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Text(c.phone, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            IconButton(onClick = onEdit) { Icon(Icons.Default.Edit, contentDescription = "编辑", modifier = Modifier.size(18.dp)) }
            IconButton(onClick = onDelete) { Icon(Icons.Default.Delete, contentDescription = "删除", tint = MaterialTheme.colorScheme.error, modifier = Modifier.size(18.dp)) }
        }
    }
}

/** 地点卡（纯地点） */
@Composable
private fun LocationCard(l: LocationDto, onEdit: () -> Unit, onDelete: () -> Unit) {
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            val img = l.imageUrls.firstOrNull() ?: l.imageUrl
            if (!img.isNullOrBlank()) {
                AsyncImage(
                    model = resolveStaticUrl(img),
                    contentDescription = "地点图片",
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.size(56.dp).clip(RoundedCornerShape(10.dp)),
                )
                Spacer(Modifier.width(10.dp))
            } else {
                TintedIcon(Icons.Default.Place, Color(MoneyOrange), size = 16.dp, container = 32.dp)
                Spacer(Modifier.width(10.dp))
            }
            Column(Modifier.weight(1f)) {
                Text(l.name.ifBlank { "地点" }, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Text(l.detailAddress, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2)
                if (l.remark.isNotBlank()) {
                    Text(l.remark, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline)
                }
            }
            IconButton(onClick = onEdit) { Icon(Icons.Default.Edit, contentDescription = "编辑", modifier = Modifier.size(18.dp)) }
            IconButton(onClick = onDelete) { Icon(Icons.Default.Delete, contentDescription = "删除", tint = MaterialTheme.colorScheme.error, modifier = Modifier.size(18.dp)) }
        }
    }
}

/** 顶部导航：路线 / 联系人 / 地址（只显示一个模块，点击切换） */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AddressTabBar(tab: Int, onTab: (Int) -> Unit) {
    val tabs = listOf(
        Triple(0, "路线", Icons.Default.Route to Color(ShipperTeal)),
        Triple(1, "联系人", Icons.Default.Person to Color(MgrGreen)),
        Triple(2, "地址", Icons.Default.Place to Color(MoneyOrange)),
    )
    Row(
        Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        tabs.forEach { (idx, label, ic) ->
            val (icon, color) = ic
            val selected = tab == idx
            Surface(
                onClick = { onTab(idx) },
                shape = RoundedCornerShape(12.dp),
                color = if (selected) color.copy(alpha = 0.14f) else MaterialTheme.colorScheme.surface,
                border = BorderStroke(1.dp, if (selected) color.copy(alpha = 0.6f) else MaterialTheme.colorScheme.outlineVariant),
                modifier = Modifier.weight(1f).height(42.dp),
            ) {
                Row(
                    Modifier.fillMaxSize(),
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(icon, contentDescription = label, modifier = Modifier.size(18.dp), tint = if (selected) color else MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.width(5.dp))
                    Text(
                        label,
                        style = MaterialTheme.typography.labelLarge,
                        fontWeight = if (selected) FontWeight.Bold else FontWeight.Medium,
                        color = if (selected) color else MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}

/** 多图选择条：缩略图（可逐个移除 + **点一下看大图**）+ 添加按钮 */
@Composable
private fun ImageStrip(
    label: String,
    urls: List<String>,
    uploading: Boolean,
    tint: Color,
    hint: String,
    onAdd: () -> Unit,
    onRemove: (String) -> Unit,
) {
    // ⚠️ 预览状态在这里**每个 strip 自己记一份**：线路图片与地点图片是两个表单，
    //    共用一份全局状态的话，在 A 表单点开、切到 B 表单还开着（而且图是 A 的）。
    val preview = rememberImagePreview()
    Column(Modifier.fillMaxWidth()) {
        Spacer(Modifier.height(4.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                if (urls.isEmpty()) label else label + "（" + urls.size + " 张）",
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.Medium,
            )
            if (uploading) {
                Spacer(Modifier.width(8.dp))
                CircularProgressIndicator(Modifier.size(14.dp), strokeWidth = 2.dp)
            }
        }
        Spacer(Modifier.height(6.dp))
        Row(
            Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            urls.forEachIndexed { i, u ->
                Box(Modifier.size(72.dp).clip(RoundedCornerShape(12.dp))) {
                    AsyncImage(
                        model = resolveStaticUrl(u),
                        contentDescription = label,
                        contentScale = ContentScale.Crop,
                        // 点图 = 看大图（用户 2026-09-22：「他不知道他自己拍的怎么样」）
                        modifier = Modifier
                            .fillMaxSize()
                            .clip(RoundedCornerShape(12.dp))
                            .clickable { preview.open(urls.map { resolveStaticUrl(it) ?: it }, i) },
                    )
                    Box(
                        Modifier.align(Alignment.TopEnd).padding(3.dp).size(20.dp)
                            .clip(CircleShape)
                            .background(Color.Black.copy(alpha = 0.55f))
                            .clickable { onRemove(u) },
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(Icons.Default.Close, contentDescription = "移除", tint = Color.White, modifier = Modifier.size(13.dp))
                    }
                }
            }
            Box(
                Modifier.size(72.dp)
                    .clip(RoundedCornerShape(12.dp))
                    .background(MaterialTheme.colorScheme.surfaceVariant)
                    .clickable(onClick = onAdd),
                contentAlignment = Alignment.Center,
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(Icons.Default.AddAPhoto, contentDescription = null, tint = tint)
                    Spacer(Modifier.height(2.dp))
                    Text("添加图片", style = MaterialTheme.typography.labelSmall)
                }
            }
        }
        Spacer(Modifier.height(4.dp))
        Text(hint, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
    preview.Show()
}
