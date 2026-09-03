package com.tapmoay.sorders.ui.order

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.core.content.FileProvider
import coil.compose.AsyncImage
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.nav.Role
import com.tapmoay.sorders.ui.theme.MgrGreen
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.ui.theme.ProductPurple
import com.tapmoay.sorders.ui.theme.ShipperTeal
import com.tapmoay.sorders.util.*
import com.tapmoay.sorders.util.moneyToDouble
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import java.io.File

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OrderDetailScreen(
    container: AppContainer,
    orderId: Long,
    onBack: () -> Unit,
) {
    val vm: OrderDetailViewModel = appViewModel { OrderDetailViewModel(container, orderId) }
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val session by container.tokenStore.sessionFlow.collectAsState(initial = null)
    val role = Role.fromKey(session?.role ?: "")
    var previewUrl by remember { mutableStateOf<String?>(null) }

    // 系统相机拍照（无需 CAMERA 权限；成品走 FileProvider）
    val takePicture = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { ok ->
        val rawPath = vm.pendingRawPhoto
        if (ok && rawPath != null) {
            scope.launch(Dispatchers.IO) {
                try {
                    val dir = File(context.cacheDir, "photos").apply { mkdirs() }
                    val out = File(dir, "done_" + System.currentTimeMillis() + ".jpg")
                    val order = vm.order
                    val loc = container.locationManager.lastPoint
                    // 预留：接入高德后由 GeoResolver 逆地理编码返回具体地点名（村/路/店名）
                    val wmText = if (loc != null)
                        (com.tapmoay.sorders.util.GeoResolver.resolveSync(context, loc.lat, loc.lng)
                            ?: order?.addressDetail ?: "送达地点")
                    else order?.addressDetail ?: "送达地点"
                    Watermark.process(File(rawPath), out, wmText)
                    vm.addCapturedPhoto(out.absolutePath)
                } catch (_: Exception) {
                    vm.error = "照片处理失败，请重试"
                }
            }
        }
    }

    fun capture() {
        // 拍照前预热定位（水印需要实时定位）
        container.locationManager.requestSingle()
        val dir = File(context.cacheDir, "photos").apply { mkdirs() }
        val raw = File(dir, "raw_" + System.currentTimeMillis() + ".jpg")
        vm.pendingRawPhoto = raw.absolutePath
        val uri = FileProvider.getUriForFile(context, context.packageName + ".fileprovider", raw)
        takePicture.launch(uri)
    }

    Column(Modifier.fillMaxSize()) {
        TopAppBar(
            title = { Text("订单详情") },
            navigationIcon = {
                IconButton(onClick = onBack) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                }
            },
        )
        when {
            vm.loading -> LoadingBox()
            vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
            vm.order == null -> EmptyView("订单不存在")
            else -> DetailBody(
                order = vm.order!!,
                role = role,
                acting = vm.acting,
                uploading = vm.uploading,
                onCancelClick = { vm.showCancelDialog = true },
                onNavigate = {
                    openAmapNavigation(context, vm.order?.addressLng, vm.order?.addressLat, vm.order?.addressDetail)
                },
                onAck = { vm.ack() },
                onNoteClick = {
                    vm.noteText = vm.order?.driverRemark ?: ""
                    vm.showNoteDialog = true
                },
                onCaptureClick = { vm.showDeliverySheet = true },
                onPhotoClick = { previewUrl = it },
                onPayClick = { vm.showPayConfirm = true },
                onChargeClick = { vm.openCharge() },
                onEditFreightClick = { vm.openFreightDialog() },
                onSplitClick = { vm.openSplitDialog() },
                onDirectCompleteClick = { p -> vm.completeDirect({ onBack() }, p) },
            damageByProduct = vm.damageByProduct,
            damageNote = vm.damageNote,
            onDamageQty = { id, q -> vm.damageByProduct[id] = q },
            onDamageNote = { vm.damageNote = it },
            )
        }
    }

    // 撤销二次确认
    if (vm.showCancelDialog) {
        AlertDialog(
            onDismissRequest = { vm.showCancelDialog = false },
            title = { Text("确认撤销订单？") },
            text = { Text("撤销后订单进入「已撤销」状态，派单员将不再处理该订单。") },
            confirmButton = {
                TextButton(
                    onClick = { vm.cancel() },
                    colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error),
                ) { Text("确认撤销") }
            },
            dismissButton = { TextButton(onClick = { vm.showCancelDialog = false }) { Text("再想想") } },
        )
    }

    // 派单员：现场收款确认
    if (vm.showFreightDialog) {
        AlertDialog(
            onDismissRequest = { vm.showFreightDialog = false },
            title = { Text("修改司机运费") },
            text = {
                Column {
                    OutlinedTextField(
                        value = vm.draftFreight,
                        onValueChange = { vm.draftFreight = it },
                        label = { Text("运费 ¥（留空=待定）") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            },
            confirmButton = { TextButton(onClick = { vm.saveFreight() }, enabled = !vm.acting) { Text("保存") } },
            dismissButton = { TextButton(onClick = { vm.showFreightDialog = false }) { Text("取消") } },
        )
    }
    if (vm.showSplitDialog) {
        AlertDialog(
            onDismissRequest = { vm.showSplitDialog = false },
            title = { Text("拆分订单") },
            text = {
                Column {
                    Text(
                        "按份拆分数量（用 / 分隔，如 150/150 或 1/1 表示均分）",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = vm.splitPartsText,
                        onValueChange = { vm.splitPartsText = it },
                        label = { Text("各份比例/数量，如 150/150") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "拆分后原单撤销，生成多个待派单，可分别派给不同（或相同）司机。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            },
            confirmButton = { TextButton(onClick = { vm.saveSplit() }, enabled = !vm.acting) { Text("拆分") } },
            dismissButton = { TextButton(onClick = { vm.showSplitDialog = false }) { Text("取消") } },
        )
    }
    if (vm.showPayConfirm) {
        AlertDialog(
            onDismissRequest = { vm.showPayConfirm = false },
            title = { Text("现场收款确认") },
            text = { Text("确认已现场收到货款 ¥" + formatMoney(vm.order?.orderProducts?.sumOf { moneyToDouble(it.lineTotal) }.toString()) + "？确认后订单标记为已收款。") },
            confirmButton = {
                TextButton(onClick = { vm.pay() }, enabled = !vm.acting) { Text("确认收款") }
            },
            dismissButton = { TextButton(onClick = { vm.showPayConfirm = false }) { Text("取消") } },
        )
    }

    // 派单员：挂账（选单位）
    if (vm.showChargeSheet) {
        ChargeSheet(
            loading = vm.loadingUnits,
            units = vm.arrearsUnits,
            onPick = { unit -> vm.charge(unit.id) },
            onDismiss = { vm.showChargeSheet = false },
        )
    }

    // 司机内部备注
    if (vm.showNoteDialog) {
        AlertDialog(
            onDismissRequest = { vm.showNoteDialog = false },
            title = { Text("内部备注") },
            text = {
                OutlinedTextField(
                    value = vm.noteText,
                    onValueChange = { vm.noteText = it },
                    label = { Text("备注（与派单员可见）") },
                    minLines = 3,
                    modifier = Modifier.fillMaxWidth(),
                )
            },
            confirmButton = { TextButton(onClick = { vm.saveNote() }) { Text("保存") } },
            dismissButton = { TextButton(onClick = { vm.showNoteDialog = false }) { Text("取消") } },
        )
    }

    // 拍照送达底部弹窗
    if (vm.showDeliverySheet) {
        DeliverySheet(
            photos = vm.capturedPhotos,
            remark = vm.driverRemark,
            uploading = vm.uploading,
            onRemarkChange = { vm.driverRemark = it },
            onCapture = { capture() },
            onRemove = { i -> vm.removeCapturedPhoto(i) },
            onSubmit = { p -> vm.completeDelivery({ onBack() }, p) },
            onDismiss = { vm.showDeliverySheet = false },
            collectCash = vm.order?.collectCash == true,
            products = vm.order?.orderProducts ?: emptyList(),
            damageByProduct = vm.damageByProduct,
            damageNote = vm.damageNote,
            onDamageQty = { id, q -> vm.damageByProduct[id] = q },
            onDamageNote = { vm.damageNote = it },
        )
    }

    // 照片大图
    previewUrl?.let { url ->
        Dialog(onDismissRequest = { previewUrl = null }) {
            AsyncImage(
                model = resolveStaticUrl(url),
                contentDescription = "送达照片",
                modifier = Modifier.fillMaxSize().clickable { previewUrl = null },
                contentScale = ContentScale.Fit,
            )
        }
    }
}

@Composable
private fun DetailBody(
    order: OrderDto,
    role: Role,
    acting: Boolean,
    uploading: Boolean,
    onCancelClick: () -> Unit,
    onNavigate: () -> Unit,
    onAck: () -> Unit,
    onNoteClick: () -> Unit,
    onCaptureClick: () -> Unit,
    onPhotoClick: (String) -> Unit,
    onPayClick: () -> Unit,
    onChargeClick: () -> Unit,
    onEditFreightClick: () -> Unit,
    onSplitClick: () -> Unit,
    onDirectCompleteClick: (String?) -> Unit,
    damageByProduct: Map<Long, Int> = emptyMap(),
    damageNote: String = "",
    onDamageQty: (Long, Int) -> Unit = { _, _ -> },
    onDamageNote: (String) -> Unit = {},
) {
    val total = order.orderProducts.sumOf { moneyToDouble(it.lineTotal) }
    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            SectionCard {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("#" + order.orderNo, style = MaterialTheme.typography.titleLarge)
                        Spacer(Modifier.height(4.dp))
                        Text(
                            "创建于 " + formatDateTime(order.createdAt),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    OrderStatusChip(order.status)
                }
                if (order.isException) {
                    Spacer(Modifier.height(10.dp))
                    Surface(color = MaterialTheme.colorScheme.errorContainer, shape = MaterialTheme.shapes.small) {
                        Text(
                            "异常订单：" + order.exceptionReason.ifBlank { "未填写原因" },
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onErrorContainer,
                            modifier = Modifier.padding(10.dp),
                        )
                    }
                }
            }
        }

        item {
            SectionCard {
                SectionTitle(Icons.Default.Place, Color(ShipperTeal), "收货信息")
                Spacer(Modifier.height(10.dp))
                val ctx = LocalContext.current
                Row(verticalAlignment = Alignment.Top) {
                    Icon(
                        Icons.Default.Place,
                        contentDescription = "地址",
                        tint = androidx.compose.ui.graphics.Color(0xFF1E6FFF),
                        modifier = Modifier.size(22.dp),
                    )
                    Spacer(Modifier.width(8.dp))
                    Text(
                        order.addressDetail.ifBlank { "未填写收货地址" },
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = androidx.compose.ui.text.font.FontWeight.Bold,
                        color = MaterialTheme.colorScheme.onSurface,
                        modifier = Modifier.weight(1f),
                    )
                }
                if (!order.addressImageUrl.isNullOrBlank()) {
                    Spacer(Modifier.height(8.dp))
                    AsyncImage(
                        model = resolveStaticUrl(order.addressImageUrl),
                        contentDescription = "地址参考图",
                        contentScale = ContentScale.Crop,
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(150.dp)
                            .clip(MaterialTheme.shapes.medium),
                    )
                }
                Spacer(Modifier.height(8.dp))
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                Spacer(Modifier.height(8.dp))
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable {
                            if (order.contactDongjiaPhone.isNotBlank()) {
                                val uri = android.net.Uri.parse("tel:" + order.contactDongjiaPhone.trim())
                                ctx.startActivity(android.content.Intent(android.content.Intent.ACTION_DIAL, uri))
                            }
                        }
                        .padding(vertical = 6.dp),
                ) {
                    Icon(
                        Icons.Default.Call,
                        contentDescription = null,
                        tint = androidx.compose.ui.graphics.Color(0xFF00B578),
                        modifier = Modifier.size(22.dp),
                    )
                    Spacer(Modifier.width(8.dp))
                    Text(
                        "东家电话 " + order.contactDongjiaPhone.ifBlank { "-" },
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = androidx.compose.ui.text.font.FontWeight.Bold,
                        color = androidx.compose.ui.graphics.Color(0xFF0A6CFF),
                    )
                    Spacer(Modifier.weight(1f))
                    Text(
                        "点击拨打",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                if (order.contactBossPhone.isNotBlank()) InfoRow("老板电话", order.contactBossPhone)
                if (order.remark.isNotBlank()) InfoRow("备注", order.remark)
                if (role == Role.DRIVER || role == Role.DISPATCHER) {
                    if (order.internalNotes.isNotBlank()) InfoRow("内部备注", order.internalNotes)
                }
                if (!order.driverName.isNullOrBlank()) {
                    InfoRow("司机", order.driverName + (order.driverPhone?.let { " " + it } ?: ""))
                }
            }
        }
        item {
            SectionCard {
                SectionTitle(Icons.Default.Inventory2, Color(ProductPurple), "商品明细")
                Spacer(Modifier.height(10.dp))
                order.orderProducts.forEachIndexed { i, line ->
                    Row(
                        Modifier.fillMaxWidth().padding(vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            line.productNameSnapshot,
                            style = MaterialTheme.typography.bodyLarge,
                            color = MaterialTheme.colorScheme.onSurface,
                            maxLines = 2,
                            modifier = Modifier.weight(1f),
                        )
                        Text(
                            "×" + line.quantity,
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = androidx.compose.ui.text.font.FontWeight.Bold,
                            color = androidx.compose.ui.graphics.Color(0xFF8455E6),
                        )
                        Spacer(Modifier.width(12.dp))
                        if (role != Role.DRIVER) {
                            Text(
                                "¥" + formatMoney(line.lineTotal),
                                style = MaterialTheme.typography.titleSmall,
                                fontWeight = androidx.compose.ui.text.font.FontWeight.Bold,
                                color = MaterialTheme.colorScheme.onSurface,
                            )
                        }
                    }
                    if (i != order.orderProducts.lastIndex) {
                        Spacer(Modifier.height(4.dp))
                        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                    }
                }
                Spacer(Modifier.height(10.dp))
                HorizontalDivider()
                Spacer(Modifier.height(10.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    if (role == Role.DRIVER) {
                        // 司机：仅按单计费(PIECE)司机且已定价时显示运费；固定工资/未定价/货款一律不显示
                        if (order.driverBillingMode == "PIECE" && order.freightVisible && order.freightFee != null) {
                            Icon(Icons.Default.Payments, contentDescription = null, tint = Color(MoneyOrange), modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(6.dp))
                            Text(
                                "运费",
                                style = MaterialTheme.typography.titleMedium,
                                modifier = Modifier.weight(1f),
                            )
                            Text(
                                "¥" + formatMoney(order.freightFee),
                                style = MaterialTheme.typography.titleLarge,
                                fontWeight = androidx.compose.ui.text.font.FontWeight.Bold,
                                color = Color(MoneyOrange),
                            )
                        }
                    } else {
                        Text(
                            "合计",
                            style = MaterialTheme.typography.titleMedium,
                            modifier = Modifier.weight(1f),
                        )
                        Text(
                            "¥" + formatMoney(total.toString()),
                            style = MaterialTheme.typography.titleLarge,
                            fontWeight = androidx.compose.ui.text.font.FontWeight.Bold,
                            color = androidx.compose.ui.graphics.Color(0xFFFF9500),
                        )
                    }
                }
            }
        }
        // 司机：已接单可录入商品破损（选填·公司自担），卡片槽紧贴商品明细下方
        if (role == Role.DRIVER && order.status == "ACCEPTED") {
            item {
                DamageCard(
                    products = order.orderProducts,
                    damageByProduct = damageByProduct,
                    damageNote = damageNote,
                    onQtyChange = onDamageQty,
                    onNoteChange = onDamageNote,
                )
            }
        }
        item {
            SectionCard {
                SectionTitle(Icons.Default.History, Color(0xFF1E6FFF), "流转记录")
                Spacer(Modifier.height(8.dp))
                TimeRow("下单", order.createdAt)
                order.dispatchedAt?.let { TimeRow("派单", it) }
                order.driverAcknowledgedAt?.let { TimeRow("司机确认", it) }
                order.deliveredAt?.let { TimeRow("送达", it) }
                order.cancelledAt?.let { TimeRow("撤销", it) }
                if (order.driverRemark.isNotBlank()) {
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "司机备注：" + order.driverRemark,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }

        val photos = order.deliveryPhotoUrls.orEmpty()
        if (photos.isNotEmpty()) {
            item {
                // 加载失败（图片已不存在）整块隐藏，不留占位把下方按钮顶下去
                DeliveryPhotosSection(urls = photos, onPhotoClick = onPhotoClick)
            }
        }

        // 派单员收款与挂账（仅派单员可见；货主/司机端不显示）
        if (role == Role.DISPATCHER) {
            item {
                SectionCard {
                    SectionTitle(Icons.Default.AccountBalanceWallet, Color(MoneyOrange), "收款与挂账")
                    Spacer(Modifier.height(10.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column {
                            Text(
                                "订单金额",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            Text(
                                "¥" + formatMoney(total.toString()),
                                style = MaterialTheme.typography.headlineSmall,
                                color = MaterialTheme.colorScheme.primary,
                            )
                        }
                        Spacer(Modifier.weight(1f))
                        PaymentBadge(order)
                    }
                    Spacer(Modifier.height(10.dp))
                    if (order.driverBillingMode == "PIECE") {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Default.Payments, contentDescription = null, tint = Color(MoneyOrange), modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(8.dp))
                            Text(
                                "司机运费",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.weight(1f),
                            )
                            Text(
                                if (order.freightFee != null) "¥" + formatMoney(order.freightFee) else "待定（未定价）",
                                style = MaterialTheme.typography.titleMedium,
                                fontWeight = androidx.compose.ui.text.font.FontWeight.Bold,
                                color = Color(MoneyOrange),
                            )
                            if (order.status != "DELIVERED" && order.status != "CANCELLED") {
                                TextButton(onClick = onEditFreightClick) { Text("修改") }
                            }
                        }
                        Spacer(Modifier.height(12.dp))
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        OutlinedButton(
                            onClick = onPayClick,
                            enabled = !acting && !(order.paid && order.paymentMethod == "cash"),
                            modifier = Modifier.weight(1f),
                        ) {
                            Icon(Icons.Default.Payments, contentDescription = null, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(6.dp))
                            Text(if (order.paid) "已收款" else "现场支付")
                        }
                        Button(
                            onClick = onChargeClick,
                            enabled = !acting,
                            modifier = Modifier.weight(1f),
                        ) {
                            Icon(Icons.Default.RequestQuote, contentDescription = null, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(6.dp))
                            Text("挂账")
                        }
                    }
                }
            }
        }

        item {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                // 派单员：待派单可拆分（大单拆多单分派）
                if (role == Role.DISPATCHER && order.status == "PENDING_DISPATCH") {
                    OutlinedButton(
                        onClick = onSplitClick,
                        enabled = !acting,
                        modifier = Modifier.fillMaxWidth().height(48.dp),
                    ) {
                        Icon(Icons.Default.CallSplit, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("拆分订单（可分派多位司机）")
                    }
                }
                // 货主：派单中可撤销
                if (role == Role.SHIPPER && (order.status == "PENDING_DISPATCH" || order.status == "DISPATCHED")) {
                    OutlinedButton(
                        onClick = onCancelClick,
                        enabled = !acting,
                        modifier = Modifier.fillMaxWidth().height(48.dp),
                        colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error),
                    ) { Text("撤销订单") }
                }
                // 司机：已派单（派了单但还没接）→ 唯一主行动：确认接单
                if (role == Role.DRIVER && order.status == "DISPATCHED") {
                    Button(
                        onClick = onAck,
                        enabled = !acting,
                        modifier = Modifier.fillMaxWidth().height(56.dp),
                        colors = ButtonDefaults.buttonColors(
                            containerColor = androidx.compose.ui.graphics.Color(0xFF00B578),
                            contentColor = androidx.compose.ui.graphics.Color.White,
                        ),
                    ) {
                        Icon(Icons.Default.CheckCircle, contentDescription = null, modifier = Modifier.size(20.dp))
                        Spacer(Modifier.width(8.dp))
                        Text("确认接单", style = MaterialTheme.typography.titleSmall)
                    }
                }
                // 司机：已接单 → 拍照送达 / 导航 / 备注（挂车司机可直接完成，无需拍照）
                if (role == Role.DRIVER && order.status == "ACCEPTED") {
                    if (order.freightVisible) {
                        if (order.collectCash) {
                            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                                Button(
                                    onClick = { onDirectCompleteClick("cash") },
                                    modifier = Modifier.weight(1f).height(56.dp),
                                    colors = ButtonDefaults.buttonColors(containerColor = Color(MoneyOrange), contentColor = Color.White),
                                ) {
                                    Icon(Icons.Default.Payments, contentDescription = null, modifier = Modifier.size(20.dp))
                                    Spacer(Modifier.width(6.dp))
                                    Text("收取现金", style = MaterialTheme.typography.titleSmall)
                                }
                                OutlinedButton(
                                    onClick = { onDirectCompleteClick("arrears") },
                                    modifier = Modifier.weight(1f).height(56.dp),
                                ) {
                                    Icon(Icons.Default.RequestQuote, contentDescription = null, modifier = Modifier.size(20.dp))
                                    Spacer(Modifier.width(6.dp))
                                    Text("挂账", style = MaterialTheme.typography.titleSmall)
                                }
                            }
                        } else {
                            Button(
                                onClick = { onDirectCompleteClick(null) },
                                modifier = Modifier.fillMaxWidth().height(56.dp),
                            ) {
                                Icon(Icons.Default.CheckCircle, contentDescription = null, modifier = Modifier.size(20.dp))
                                Spacer(Modifier.width(8.dp))
                                Text("完成订单", style = MaterialTheme.typography.titleSmall)
                            }
                        }
                    } else {
                        Button(
                            onClick = onCaptureClick,
                            modifier = Modifier.fillMaxWidth().height(56.dp),
                        ) {
                            Icon(Icons.Default.PhotoCamera, contentDescription = null, modifier = Modifier.size(20.dp))
                            Spacer(Modifier.width(8.dp))
                            Text("拍照送达")
                        }
                    }
                    Button(
                        onClick = onNavigate,
                        modifier = Modifier.fillMaxWidth().height(52.dp),
                    ) {
                        Icon(Icons.Default.Navigation, contentDescription = null, modifier = Modifier.size(20.dp))
                        Spacer(Modifier.width(8.dp))
                        Text("高德导航")
                    }
                    OutlinedButton(
                        onClick = onNoteClick,
                        modifier = Modifier.fillMaxWidth().height(48.dp),
                    ) {
                        Icon(Icons.Default.Notes, contentDescription = null, modifier = Modifier.size(20.dp))
                        Spacer(Modifier.width(8.dp))
                        Text("内部备注")
                    }
                }
                // 派单员：已派单/已接单均可导航
                // 派单员：已接单可导航
                if (role == Role.DISPATCHER && (order.status == "DISPATCHED" || order.status == "ACCEPTED")) {
                    Button(
                        onClick = onNavigate,
                        modifier = Modifier.fillMaxWidth().height(48.dp),
                    ) {
                        Icon(Icons.Default.Navigation, contentDescription = null, modifier = Modifier.size(20.dp))
                        Spacer(Modifier.width(8.dp))
                        Text("高德导航")
                    }
                }
            }
        }
        item { Spacer(Modifier.height(8.dp)) }
    }
}

/** 商品破损卡片槽（选填·公司自担）：点开可逐商品填破损数量 + 货损备注，默认收起不占空间 */
@Composable
private fun DamageCard(
    products: List<com.tapmoay.sorders.data.remote.dto.OrderProductDto>,
    damageByProduct: Map<Long, Int>,
    damageNote: String,
    onQtyChange: (Long, Int) -> Unit,
    onNoteChange: (String) -> Unit,
) {
    if (products.isEmpty()) return
    var expanded by remember { mutableStateOf(false) }
    val damaged = damageByProduct.values.filter { it > 0 }.sum()
    Surface(
        shape = MaterialTheme.shapes.medium,
        color = Color(MoneyOrange).copy(alpha = 0.08f),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(12.dp)) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth().clickable { expanded = !expanded },
            ) {
                Icon(Icons.Default.BrokenImage, contentDescription = "商品破损", tint = Color(MoneyOrange), modifier = Modifier.size(22.dp))
                Spacer(Modifier.width(8.dp))
                Text("商品破损", style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
                Text(
                    if (damaged > 0) "已填 " + damaged + " 件" else "未填写",
                    style = MaterialTheme.typography.labelMedium,
                    color = if (damaged > 0) Color(MoneyOrange) else MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.width(4.dp))
                Icon(
                    if (expanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(20.dp),
                )
            }
            if (expanded) {
                Spacer(Modifier.height(10.dp))
                products.forEach { p ->
                    val q = damageByProduct[p.id] ?: 0
                    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                        Text(
                            p.productNameSnapshot,
                            style = MaterialTheme.typography.bodyMedium,
                            modifier = Modifier.weight(1f),
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                        Text("×" + p.quantity, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Spacer(Modifier.width(10.dp))
                        OutlinedTextField(
                            value = if (q <= 0) "" else q.toString(),
                            onValueChange = { v ->
                                val n = v.filter { it.isDigit() }.takeLast(3).toIntOrNull() ?: 0
                                onQtyChange(p.id, if (n > p.quantity) p.quantity else n)
                            },
                            modifier = Modifier.width(76.dp),
                            singleLine = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                            label = { Text("破损", style = MaterialTheme.typography.labelSmall) },
                        )
                    }
                }
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = damageNote,
                    onValueChange = onNoteChange,
                    label = { Text("货损备注（可选）") },
                    minLines = 1,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }
    }
}

/** 拍照送达弹层：多张照片 + 备注 + 提交 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DeliverySheet(
    photos: List<String>,
    remark: String,
    uploading: Boolean,
    onRemarkChange: (String) -> Unit,
    onCapture: () -> Unit,
    onRemove: (Int) -> Unit,
    onSubmit: (String?) -> Unit,
    onDismiss: () -> Unit,
    collectCash: Boolean = false,
    products: List<com.tapmoay.sorders.data.remote.dto.OrderProductDto> = emptyList(),
    damageByProduct: Map<Long, Int> = emptyMap(),
    damageNote: String = "",
    onDamageQty: (Long, Int) -> Unit = { _, _ -> },
    onDamageNote: (String) -> Unit = {},
) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(Modifier.padding(horizontal = 20.dp).padding(bottom = 32.dp)) {
            Text("送达凭证", style = MaterialTheme.typography.titleLarge)
            Spacer(Modifier.height(4.dp))
            Text(
                "拍摄送达照片（自动添加时间与地点水印），至少一张，可拍多张",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(12.dp))

            // 已拍照片缩略图
            if (photos.isNotEmpty()) {
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    photos.forEachIndexed { i, path ->
                        Box {
                            AsyncImage(
                                model = File(path),
                                contentDescription = "待上传照片",
                                contentScale = ContentScale.Crop,
                                modifier = Modifier
                                    .size(84.dp)
                                    .clip(MaterialTheme.shapes.medium),
                            )
                            IconButton(
                                onClick = { onRemove(i) },
                                modifier = Modifier.align(Alignment.TopEnd).size(26.dp),
                            ) {
                                Icon(
                                    Icons.Default.Cancel,
                                    contentDescription = "移除",
                                    tint = MaterialTheme.colorScheme.error,
                                    modifier = Modifier.size(18.dp),
                                )
                            }
                        }
                    }
                }
                Spacer(Modifier.height(12.dp))
            }

            OutlinedButton(
                onClick = onCapture,
                modifier = Modifier.fillMaxWidth().height(48.dp),
            ) {
                Icon(Icons.Default.PhotoCamera, contentDescription = null, modifier = Modifier.size(20.dp))
                Spacer(Modifier.width(8.dp))
                Text(if (photos.isEmpty()) "拍摄第一张照片" else "再拍一张（" + photos.size + "）")
            }
            Spacer(Modifier.height(12.dp))
            OutlinedTextField(
                value = remark,
                onValueChange = onRemarkChange,
                label = { Text("送达备注（可选）") },
                minLines = 2,
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(16.dp))
            DamageCard(
                products = products,
                damageByProduct = damageByProduct,
                damageNote = damageNote,
                onQtyChange = onDamageQty,
                onNoteChange = onDamageNote,
            )
            Spacer(Modifier.height(16.dp))
            if (collectCash) {
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Button(
                        onClick = { onSubmit("cash") },
                        enabled = !uploading && photos.isNotEmpty(),
                        modifier = Modifier.weight(1f).height(50.dp),
                        colors = ButtonDefaults.buttonColors(containerColor = Color(MoneyOrange), contentColor = Color.White),
                    ) {
                        if (uploading) {
                            CircularProgressIndicator(Modifier.size(22.dp), color = Color.White, strokeWidth = 2.dp)
                        } else {
                            Icon(Icons.Default.Payments, contentDescription = null, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(5.dp))
                            Text("收取现金（" + photos.size + " 张）")
                        }
                    }
                    OutlinedButton(
                        onClick = { onSubmit("arrears") },
                        enabled = !uploading && photos.isNotEmpty(),
                        modifier = Modifier.weight(1f).height(50.dp),
                    ) {
                        Icon(Icons.Default.RequestQuote, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(5.dp))
                        Text("挂账（" + photos.size + " 张）")
                    }
                }
            } else {
                Button(
                    onClick = { onSubmit(null) },
                    enabled = !uploading && photos.isNotEmpty(),
                    modifier = Modifier.fillMaxWidth().height(50.dp),
                ) {
                    if (uploading) {
                        CircularProgressIndicator(Modifier.size(22.dp), color = MaterialTheme.colorScheme.onPrimary, strokeWidth = 2.dp)
                    } else {
                        Text("提交送达（" + photos.size + " 张照片）")
                    }
                }
            }
        }
    }
}

/** 支付状态徽章 */
@Composable
private fun PaymentBadge(order: OrderDto) {
    val (label, bg, fg) = when {
        order.paymentMethod == "arrears" ->
            Triple(
                if (!order.arrearsUnitName.isNullOrBlank()) "挂账 · " + order.arrearsUnitName else "挂账",
                MaterialTheme.colorScheme.errorContainer,
                MaterialTheme.colorScheme.onErrorContainer,
            )
        order.paid -> Triple("已收款", Color(0xFFD9F0DA), Color(0xFF1B7A3D))
        else -> Triple("未收款", MaterialTheme.colorScheme.surfaceVariant, MaterialTheme.colorScheme.onSurfaceVariant)
    }
    Surface(color = bg, shape = MaterialTheme.shapes.small) {
        Text(
            label,
            style = MaterialTheme.typography.labelMedium,
            color = fg,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
            maxLines = 1,
        )
    }
}

/** 挂账单位选择弹层 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ChargeSheet(
    loading: Boolean,
    units: List<com.tapmoay.sorders.data.remote.dto.ArrearsUnitDto>,
    onPick: (com.tapmoay.sorders.data.remote.dto.ArrearsUnitDto) -> Unit,
    onDismiss: () -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(Modifier.padding(horizontal = 20.dp).padding(bottom = 32.dp)) {
            Text("挂账到单位", style = MaterialTheme.typography.titleLarge)
            Spacer(Modifier.height(4.dp))
            Text(
                "挂账后订单记入该单位名下，后续与单位统一结算",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(10.dp))
            when {
                loading -> LoadingBox()
                units.isEmpty() -> Text(
                    "暂无挂账单位，请先在「工作台 → 挂账单位」中添加",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.padding(vertical = 20.dp),
                )
                else -> LazyColumn(Modifier.heightIn(max = 360.dp)) {
                    itemsIndexed(units) { _, u ->
                        Row(
                            Modifier
                                .fillMaxWidth()
                                .clickable { onPick(u) }
                                .padding(vertical = 12.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Icon(
                                Icons.Default.Business,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.primary,
                                modifier = Modifier.size(22.dp),
                            )
                            Spacer(Modifier.width(12.dp))
                            Column(Modifier.weight(1f)) {
                                Text(u.name, style = MaterialTheme.typography.bodyLarge)
                                if (u.phone.isNotBlank()) {
                                    Text(
                                        u.phone,
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                            }
                            Icon(Icons.Default.ChevronRight, contentDescription = null)
                        }
                        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                    }
                }
            }
        }
    }
}

/** 送达照片：任一张加载失败 → 整块隐藏（不占位） */
@Composable
private fun DeliveryPhotosSection(urls: List<String>, onPhotoClick: (String) -> Unit) {
    var broken by remember { mutableStateOf(false) }
    if (broken) return
    SectionCard {
        SectionTitle(Icons.Default.PhotoLibrary, Color(MgrGreen), "送达照片（" + urls.size + "）")
        Spacer(Modifier.height(10.dp))
        urls.chunked(3).forEach { rowUrls ->
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                rowUrls.forEach { url ->
                    AsyncImage(
                        model = resolveStaticUrl(url),
                        contentDescription = "送达照片",
                        contentScale = ContentScale.Crop,
                        onError = { broken = true },
                        modifier = Modifier
                            .weight(1f)
                            .aspectRatio(1f)
                            .clip(MaterialTheme.shapes.small)
                            .clickable { onPhotoClick(url) },
                    )
                }
                repeat(3 - rowUrls.size) { Spacer(Modifier.weight(1f)) }
            }
            Spacer(Modifier.height(8.dp))
        }
    }
}

/** 板块标题：图标 + 语义色 + 文字 */
@Composable
private fun SectionTitle(icon: androidx.compose.ui.graphics.vector.ImageVector, color: Color, text: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        TintedIcon(icon, color, size = 16.dp, container = 30.dp)
        Spacer(Modifier.width(8.dp))
        Text(text, style = MaterialTheme.typography.titleMedium)
    }
}

@Composable
private fun TimeRow(label: String, iso: String) {
    Row(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Icon(
            Icons.Default.Schedule,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.outline,
            modifier = Modifier.size(16.dp),
        )
        Spacer(Modifier.width(8.dp))
        Text(label, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.width(72.dp))
        Text(
            formatDateTime(iso),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}