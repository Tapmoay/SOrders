package com.tapmoay.sorders.ui.shipper

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
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
import com.tapmoay.sorders.core.AppContainer
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
                vm.error = "图片读取失败，请重试"
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
                    vm.error = "图片处理失败，请重试"
                }
            }
        }
    }

    Scaffold(
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
            AddressTabBar(tab = tab, onTab = { tab = it })
            Box(Modifier.weight(1f)) {
                when {
                    vm.loading -> LoadingBox(Modifier.fillMaxSize())
                    vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() }, Modifier.fillMaxSize())
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
                                if (vm.contacts.isEmpty()) {
                                    item { EmptyView("暂无联系人") }
                                } else {
                                    items(vm.contacts, key = { "c" + it.id }) { c ->
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
                                if (vm.locations.isEmpty()) {
                                    item { EmptyView("暂无地点") }
                                } else {
                                    items(vm.locations, key = { "l" + it.id }) { l ->
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
                                if (vm.addresses.isEmpty()) {
                                    item { EmptyView("暂无线路，点右侧新增") }
                                } else {
                                    items(vm.addresses, key = { "a" + it.id }) { a ->
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
                Modifier.fillMaxWidth().padding(horizontal = 20.dp).imePadding(),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text(if (vm.editing == null) "新增线路" else "编辑线路", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(4.dp))
                // 联系人选择
                ExposedDropdownMenuBox(expanded = showContactMenu, onExpandedChange = { showContactMenu = it }) {
                    OutlinedTextField(
                        value = if (vm.draftContactId != null) vm.draftName + " " + vm.draftPhone else "请选择联系人",
                        onValueChange = {},
                        readOnly = true,
                        label = { Text("联系人") },
                        leadingIcon = { Icon(Icons.Default.Person, null, tint = Color(ShipperTeal)) },
                        trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = showContactMenu) },
                        modifier = Modifier.fillMaxWidth().menuAnchor(),
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
                // 起点（可选）
                OutlinedTextField(
                    vm.draftOrigin, { vm.draftOrigin = it },
                    label = { Text("起点（可选，从这出发）") }, minLines = 2,
                    leadingIcon = { Icon(Icons.Default.Route, null, tint = Color(InventoryTeal)) },
                    modifier = Modifier.fillMaxWidth(),
                )
                Box {
                    OutlinedButton(onClick = { startLocMenu = true }, modifier = Modifier.fillMaxWidth()) {
                        Icon(Icons.Default.List, null, Modifier.size(18.dp), tint = Color(InventoryTeal))
                        Spacer(Modifier.width(6.dp))
                        Text("从地点库选起点")
                    }
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
                OutlinedButton(onClick = { vm.openPicker("origin") }, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Default.Route, null, Modifier.size(18.dp), tint = Color(InventoryTeal))
                    Spacer(Modifier.width(6.dp))
                    Text("起点地图选点")
                }
                // 终点（必填）
                OutlinedTextField(
                    vm.draftDetail, { vm.draftDetail = it },
                    label = { Text("终点（必填）") }, minLines = 2,
                    leadingIcon = { Icon(Icons.Default.Place, null, tint = Color(MoneyOrange)) },
                    modifier = Modifier.fillMaxWidth(),
                )
                Box {
                    OutlinedButton(onClick = { endLocMenu = true }, modifier = Modifier.fillMaxWidth()) {
                        Icon(Icons.Default.List, null, Modifier.size(18.dp), tint = Color(MoneyOrange))
                        Spacer(Modifier.width(6.dp))
                        Text("从地点库选终点")
                    }
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
                OutlinedButton(onClick = { vm.openPicker("dest") }, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Default.Place, null, Modifier.size(18.dp), tint = Color(MoneyOrange))
                    Spacer(Modifier.width(6.dp))
                    Text("终点地图选点")
                }
                // 线路图片（多张：拍照/相册；从地点库选择自动带图）
                ImageStrip(
                    label = "线路图片",
                    urls = vm.draftImageUrls,
                    uploading = vm.draftImageUploading,
                    tint = Color(MoneyOrange),
                    hint = "支持拍照或从相册选择，可上传多张；从地点库选择会自动带图",
                    onAdd = { imageTarget = "line"; showImageSource = true },
                    onRemove = { vm.removeLineImage(it) },
                )
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Default.Star, null, Modifier.size(18.dp), tint = Color(MoneyOrange))
                    Spacer(Modifier.width(8.dp))
                    Text("设为默认线路", style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                    Switch(checked = vm.draftIsDefault, onCheckedChange = { vm.draftIsDefault = it })
                }
                Spacer(Modifier.height(8.dp))
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
                Modifier.fillMaxWidth().padding(horizontal = 20.dp).imePadding(),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text(if (vm.editingLocation == null) "新增地点" else "编辑地点", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(4.dp))
                OutlinedTextField(
                    vm.locName, { vm.locName = it },
                    label = { Text("地点名称（可选）") }, singleLine = true,
                    leadingIcon = { Icon(Icons.Default.Label, null, tint = Color(ShipperTeal)) },
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    vm.locDetail, { vm.locDetail = it },
                    label = { Text("详细地址（必填）") }, minLines = 2,
                    leadingIcon = { Icon(Icons.Default.Place, null, tint = Color(MoneyOrange)) },
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedButton(onClick = { vm.openPicker("loc") }, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Default.Place, null, Modifier.size(18.dp), tint = Color(MoneyOrange))
                    Spacer(Modifier.width(6.dp))
                    Text("地图选点")
                }
                // 地点图片（多张：拍照/相册，创建订单时随地点带入）
                ImageStrip(
                    label = "地点图片",
                    urls = vm.locImageUrls,
                    uploading = vm.locImageUploading,
                    tint = Color(MoneyOrange),
                    hint = "支持拍照或从相册选择，可上传多张",
                    onAdd = { imageTarget = "loc"; showImageSource = true },
                    onRemove = { vm.removeLocImage(it) },
                )
                OutlinedTextField(
                    vm.locRemark, { vm.locRemark = it },
                    label = { Text("备注（可选）") }, singleLine = true,
                    leadingIcon = { Icon(Icons.Default.Notes, null, tint = Color(0xFF8A8A8E)) },
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))
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
                Modifier.fillMaxWidth().padding(horizontal = 20.dp).imePadding(),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text(if (vm.editingContact == null) "添加联系人" else "编辑联系人", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(4.dp))
                OutlinedTextField(
                    vm.contactName, { vm.contactName = it },
                    label = { Text("称呼（可选）") }, singleLine = true,
                    leadingIcon = { Icon(Icons.Default.Person, null, tint = Color(ShipperTeal)) },
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    vm.contactPhone, { vm.contactPhone = it },
                    label = { Text("电话") }, singleLine = true,
                    leadingIcon = { Icon(Icons.Default.Phone, null, tint = Color(MgrGreen)) },
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { vm.showContactDialog = false }, modifier = Modifier.weight(1f).height(48.dp)) { Text("取消") }
                    Button(onClick = { vm.saveContact() }, modifier = Modifier.weight(1f).height(48.dp)) { Text(if (vm.editingContact == null) "添加" else "保存") }
                }
                Spacer(Modifier.height(24.dp))
            }
        }
    }
}

/** 线路卡：联系人（主）+ 小电话图标 + 终点/起点 */
@Composable
private fun AddressCard(a: AddressDto, onEdit: () -> Unit, onDelete: () -> Unit) {
    SectionCard {
        Column {
            Row(verticalAlignment = Alignment.CenterVertically) {
                val img = a.imageUrls.firstOrNull() ?: a.imageUrl
                if (!img.isNullOrBlank()) {
                    AsyncImage(
                        model = resolveStaticUrl(img),
                        contentDescription = "线路图片",
                        contentScale = ContentScale.Crop,
                        modifier = Modifier.size(44.dp).clip(RoundedCornerShape(8.dp)),
                    )
                    Spacer(Modifier.width(10.dp))
                }
                TintedIcon(Icons.Default.AccountCircle, Color(ShipperTeal), size = 15.dp, container = 30.dp)
                Spacer(Modifier.width(10.dp))
                Text(a.receiverName.ifBlank { "收货人" }, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Spacer(Modifier.width(6.dp))
                Icon(Icons.Default.Phone, contentDescription = "电话", modifier = Modifier.size(12.dp), tint = Color(0xFF00B578))
                Spacer(Modifier.width(3.dp))
                Text(a.phone, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.weight(1f))
                if (a.isDefault) {
                    Surface(color = MaterialTheme.colorScheme.primaryContainer, shape = MaterialTheme.shapes.small) {
                        Text("默认", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onPrimaryContainer, modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp))
                    }
                }
                IconButton(onClick = onEdit) { Icon(Icons.Default.Edit, contentDescription = "编辑", modifier = Modifier.size(16.dp)) }
                IconButton(onClick = onDelete) { Icon(Icons.Default.Delete, contentDescription = "删除", modifier = Modifier.size(16.dp), tint = MaterialTheme.colorScheme.error) }
            }
            Spacer(Modifier.height(6.dp))
            Row(verticalAlignment = Alignment.Top) {
                TintedIcon(Icons.Default.Place, Color(MoneyOrange), size = 15.dp, container = 30.dp)
                Spacer(Modifier.width(10.dp))
                Column {
                    Text(a.detailAddress, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium, maxLines = 2)
                    if (!a.originAddress.isNullOrBlank()) {
                        Spacer(Modifier.height(2.dp))
                        Text("从 " + a.originAddress, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2)
                    }
                    if (a.remark.isNotBlank()) {
                        Spacer(Modifier.height(2.dp))
                        Text(a.remark, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline)
                    }
                }
            }
        }
    }
}

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

/** 多图选择条：缩略图（可逐个移除）+ 添加按钮 */
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
            urls.forEach { u ->
                Box(Modifier.size(72.dp).clip(RoundedCornerShape(12.dp))) {
                    AsyncImage(
                        model = resolveStaticUrl(u),
                        contentDescription = label,
                        contentScale = ContentScale.Crop,
                        modifier = Modifier.fillMaxSize().clip(RoundedCornerShape(12.dp)),
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
}
