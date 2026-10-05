package com.tapmoay.sorders.ui.order

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import coil.compose.AsyncImage
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.HintPrefs
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.core.OrderStatusModel
import com.tapmoay.sorders.data.remote.dto.OrderDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.dispatcher.AssignDriverDialog
import com.tapmoay.sorders.ui.dispatcher.DispatcherPoolViewModel
import com.tapmoay.sorders.ui.nav.Role
import com.tapmoay.sorders.ui.theme.MgrGreen
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.ui.theme.ProductPurple
import com.tapmoay.sorders.ui.theme.ShipperTeal
import com.tapmoay.sorders.util.*
import com.tapmoay.sorders.util.moneyToDouble
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import android.graphics.Bitmap
import java.io.File

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OrderDetailScreen(
    container: AppContainer,
    orderId: Long,
    onBack: () -> Unit,
) {
    val vm: OrderDetailViewModel = appViewModel { OrderDetailViewModel(container, orderId) }
    // 派单弹窗（P12）：订单详情页原来只能看，想派单得退回「派单作业」池子里去翻同一张单。
    // 这里借派单池那份 VM 弹**同一个** `AssignDriverDialog` —— 两个入口一份实现，
    // 档位/运费/收现金/备注的规则不会各写一份。`autoLoadPool = false`：详情页只为弹一个框，
    // 不该顺手把几百条待派单拉下来（名册由 `openAssign` 按需拉）。
    val assignVm: DispatcherPoolViewModel = appViewModel { DispatcherPoolViewModel(container, autoLoadPool = false) }
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val session by container.tokenStore.sessionFlow.collectAsState(initial = null)
    // ⚠️ 会话没就绪**不许猜角色**（2026-09-19 审计）：`sessionFlow` 是 DataStore 冷流，
    //    首帧必然 null，而 `Role.fromKey("")` 会回落成 **SHIPPER**。司机点系统通知冷启动直达
    //    这一页时，首帧就以"货主"渲染：商品行/合计显示 **¥0.00**（后端对司机已把 line_total 置空）、
    //    多出「撤销订单」「删除订单」两个按钮（点了必然 403），而「确认接单」这一帧不存在——
    //    司机打开自己的单看到"这单值 0 元 + 一个点不动的按钮"，会以为系统坏了。
    //    `RoleHomeScreen` 早就为同一件事做了守卫（null → 整页 Loading），这里漏了。
    if (session == null) {
        Box(Modifier.fillMaxSize()) { LoadingBox() }
        return
    }
    val role = Role.fromKey(session?.role ?: "")
    // 大图预览：**用全库唯一那一份**（ui/common/ImagePreview.kt）。这一页 2026-10-06 之前
    // 自己写了一个 Dialog（只有"点开、再点关闭"），与 ImagePreview.kt:44-45 的 ⛔ 约定冲突 ——
    // 于是详情页既没有翻页/计数，也没有双指缩放与保存到相册（用户台账 L-03）。
    val preview = rememberImagePreview()
    // 点开一张大图：`onPhotoClick` 只给得到一个 URL，而弹层要在**这一组**里左右翻页 ——
    // 所以拿这个 URL 回两组里去认领（位置参考图 / 送达照片），认到哪组就在哪组里翻，
    // 认不到就退回"只看这一张"。两组不可能含同一个 URL（一次上传只属于一组）。
    val openPhoto: (String) -> Unit = { url ->
        val order = vm.order
        val place = order?.let { it.imageUrls.ifEmpty { listOfNotNull(it.addressImageUrl) } }.orEmpty()
        val delivery = order?.deliveryPhotoUrls.orEmpty()
        val group = when {
            delivery.contains(url) -> delivery
            place.contains(url) -> place
            else -> listOf(url)
        }
        preview.openStaticPaths(group, group.indexOf(url))
    }

    // 系统相机拍照（成品走 FileProvider）。**不需要 CAMERA 权限**——
    // 这一行以前是错的：清单声明了 `android.permission.CAMERA`，而系统文档写明
    // "declares as using the CAMERA permission which is not granted → ACTION_IMAGE_CAPTURE
    // 抛 SecurityException"；于是司机在权限弹窗点「拒绝」后再点「拍照送达」就是一次
    // **没有任何提示的崩溃**（2026-09-19 报告 P1-9，同源共 4 处：这里 + AI 会话 + 代理下单 + 地址）。
    // 根治不是给 4 处各加一道权限闸，而是**把那个声明删掉**（App 自己一行相机 API 都没调，
    // 4 条链路全部委托系统相机 App）：声明不存在 → 系统不再要求 → 4 处一起好。
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

    // ---- 位置图片（2026-09-20）----
    //
    // 用户原话：「还有一个就是司机他也可以去上交补交照片，如果他到了地方没有照片的话，
    // 他也可以补」「可以进到订单的详情页面然后手动补详细地点和照片」。
    // 所以入口就放在**收货信息卡**里（三个角色都看得到），谁能传由后端判
    // （派单员 / 这单的货主 / **这单的司机**）—— 到过现场的人正是唯一拍得出"这个门口长什么样"的人。
    // 传上去的图会**同时**进这一单对应的「我的地点」（后端 `attach_order_photo`）。
    var showPlacePhotoSheet by remember { mutableStateOf(false) }

    val placePhotoPicker = rememberLauncherForActivityResult(
        ActivityResultContracts.PickMultipleVisualMedia(maxItems = 9)
    ) { uris ->
        uris.forEachIndexed { i, uri ->
            try {
                val f = File(context.cacheDir, "place_" + System.currentTimeMillis() + "_" + i + ".jpg")
                context.contentResolver.openInputStream(uri)?.use { input ->
                    f.outputStream().use { output -> input.copyTo(output) }
                }
                vm.uploadPlacePhoto(f)
            } catch (_: Exception) {
                vm.error = "图片读取失败，请换一张"
            }
        }
    }

    val placePhotoCamera = rememberLauncherForActivityResult(ActivityResultContracts.TakePicturePreview()) { bmp ->
        if (bmp != null) {
            scope.launch(Dispatchers.IO) {
                try {
                    val dir = File(context.cacheDir, "place_imgs").apply { mkdirs() }
                    val f = File(dir, "cam_" + System.currentTimeMillis() + ".jpg")
                    f.outputStream().use { bmp.compress(Bitmap.CompressFormat.JPEG, 88, it) }
                    vm.uploadPlacePhoto(f)
                } catch (_: Exception) {
                    vm.error = "照片处理失败，请重试"
                }
            }
        }
    }

    // ⚠️ 「系统相机拍照不需要 CAMERA 权限」**只在清单没声明它时成立** —— 而清单已经不再声明它
    //    （2026-09-19 报告 P1-9 的根治：删掉 `AndroidManifest.xml` 里的 CAMERA 声明）。
    //    所以这里**不许**再加权限闸：真加了反而会让「拍照送达」永远打不开相机
    //    （`checkSelfPermission` 对一个没声明的权限永远返回 DENIED）。

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
            // ⚠️ 整页错误**只在还没有内容的时候**给（2026-09-23 复核 H5）：
            //    原来是 `vm.error != null ->` 无条件优先，而 `vm.error` 不只是"加载失败"——
            //    "撤销失败""拆单失败""图片读不出来"（本页 :102/:138/:152）都往它里面塞。
            //    后果：用户点一下按钮，整页被换成 ErrorView + 重试按钮，**刚才在看的内容全没了**，
            //    而他真正需要的信息（订单还在、只是这一步没成）被这句"重试"盖住。
            //    现在：没内容 → 整页错误（这时候它确实没什么可显示的）；
            //          有内容 → 走下面那两条横幅（本次刷新没成功 / 这个动作没成功）。
            vm.order == null && vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
            vm.order == null -> EmptyView("订单不存在")
            else -> Column(Modifier.fillMaxSize()) {
                // 「这个动作没成功」：与下面那条刷新提示同一个位置、同一种颜色，都不盖住内容
                vm.error?.let { msg ->
                    Surface(color = MaterialTheme.colorScheme.errorContainer) {
                        Text(
                            msg,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onErrorContainer,
                            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp),
                        )
                    }
                }
                // 「刷新失败但旧数据还在」→ 只提示一行，别把已经看到的内容换成整页错误
                vm.refreshWarning?.let { w ->
                    Surface(color = MaterialTheme.colorScheme.errorContainer) {
                        Text(
                            "这次刷新没成功：$w（下面显示的是上一次的内容）",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onErrorContainer,
                            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp),
                        )
                    }
                }
                // 「这个动作成了」——本页以前**从不显示它**：`actionResult` 早就有
                // （改单/改明细/改运费/拆单/挂账都往里写），但整页要 `Scaffold` 才画得出
                // Snackbar，而这一页没有，于是用户点完只能自己盯着内容看变没变。
                // 正向色画一行、**4 秒后自己消失**（上面那两条红色横幅是"没成"，不会与它同时出现）。
                vm.actionResult?.let { msg ->
                    LaunchedEffect(msg) {
                        delay(4000)
                        vm.actionResult = null
                    }
                    Surface(color = MaterialTheme.colorScheme.primaryContainer) {
                        Text(
                            msg,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onPrimaryContainer,
                            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp),
                        )
                    }
                }
                DetailBody(
                order = vm.order!!,
                edit = vm,
                role = role,
                prefs = container.hintPrefs,
                uploadingPlace = vm.uploadingPlace,
                onAddPlacePhoto = { showPlacePhotoSheet = true },
                acting = vm.acting,
                uploading = vm.uploading,
                onCancelClick = { vm.showCancelDialog = true },
                onDeleteClick = { vm.showDeleteDialog = true },
                onNavigate = {
                    openAmapNavigation(context, vm.order?.addressLng, vm.order?.addressLat, vm.order?.addressDetail)
                },
                onAck = { vm.ack() },
                // 点「拍照送达」= **直接进相机**（用户台账 L-04 第 ① 条）：从前它只开一个底部抽屉，
                // 抽屉里再点一次才是相机 ——「一步能做完的不要拆两步」。
                onCaptureClick = { capture() },
                onPhotoClick = openPhoto,
                // 刚拍还没上传的那张是本地 `File`（不是服务端 URL），所以走 `open(models, at)` 那一支；
                // 本地图不给「保存到相册」那颗按钮（它本来就在这台手机上，再下一次没有意义）。
                onCapturedPhotoClick = { i -> preview.open(vm.capturedPhotos.map { File(it) }, i) },
                onPayClick = { vm.showPayConfirm = true },
                onChargeClick = { vm.openCharge() },
                onEditFreightClick = { vm.openFreightDialog() },
                onSplitClick = { vm.openSplitDialog() },
                onTransferClick = { vm.openTransfer() },
                onAssignClick = { vm.order?.let { assignVm.openAssign(it.id) } },
                onDirectCompleteClick = { p -> vm.completeDirect({ onBack() }, p) },
                canFillNav = vm.canFillNavigation(role.key),
                // 「我是不是批发商」——只给「拨打司机电话」那颗按钮用（判据 `ui/common/DriverCall.kt`）。
                // 会话里没有 `is_member`，只能从 `/users/me` 取（拿不到时是 false ＝ 不给）。
                memberShipper = vm.isMemberShipper,
                onFillNavClick = {
                    // 先预热定位：地图一打开就落在司机当前所在处，少拖一次
                    container.locationManager.requestSingle()
                    vm.showNavPicker = true
                },
            damageByProduct = vm.damageByProduct,
            damageNote = vm.damageNote,
            onDamageQty = { id, q -> vm.damageByProduct[id] = q },
            onDamageNote = { vm.damageNote = it },
            // 拍照送达这条链路的页面内状态（L-04）：已拍几张、送达备注、内部备注（追加一条）。
            photos = vm.capturedPhotos,
            remark = vm.driverRemark,
            onRemarkChange = { vm.driverRemark = it },
            onRemovePhoto = { i -> vm.removeCapturedPhoto(i) },
            onSubmitDelivery = { p -> vm.completeDelivery({ onBack() }, p) },
            noteText = vm.noteText,
            onNoteTextChange = { vm.noteText = it },
            onSaveNote = { vm.saveNote() },
            )
            }
        }
    }

    // 「加一件货」的选品弹层（CHG-0041）：与派单池（CHG-0040 那套）、下单页**同一个组件**
    // （`ui/common/ProductPicker.kt`）—— 挑法、分类签、批发商专属价都不用在这里再写一遍。
    if (vm.showLinePicker) {
        ProductPickerSheet(
            products = vm.linePickerProducts,
            loading = vm.linePickerLoading,
            priceFor = { vm.priceForLinePicker(it) },
            onConfirm = { picked -> vm.addPickedLines(picked) },
            onDismiss = { vm.closeLinePicker() },
            categoryOrder = vm.linePickerCategories,
            error = vm.editError,
            onRetry = { vm.loadEditProducts(force = true) },
        )
    }

    // 司机/派单员：地图选点 → 补导航信息（只有原本没坐标的单能补）
    if (vm.showNavPicker) {
        AmapPickerDialog(
            container = container,
            initialLat = vm.order?.addressLat?.toDoubleOrNull(),
            initialLng = vm.order?.addressLng?.toDoubleOrNull(),
            onPicked = { lat, lng, address -> vm.openNavDialog(lat, lng, address) },
            onDismiss = { vm.showNavPicker = false },
            // 图层：**司机那一侧起步就是标准地图**（用户 2026-09-22：「但是司机的导航是标准地图」）；
            // 派单员那一侧跟着"上次选过的那个"（默认卫星，见 AmapMapHolder.satellite）。
            startSatellite = if (role.key == "driver") false else AmapMapHolder.satellite,
        )
    }
    if (vm.showNavDialog) {
        NavigationFillDialog(
            prefs = container.hintPrefs,
            addressText = vm.navDraftAddress,
            name = vm.navDraftName,
            onNameChange = { vm.navDraftName = it },
            lat = vm.navDraftLat,
            lng = vm.navDraftLng,
            acting = vm.acting,
            onConfirm = { vm.saveNavigation() },
            onDismiss = { vm.showNavDialog = false },
        )
    }

    // 选图用 AlertDialog（设计规范 §5：选择/确认弹窗一律 AlertDialog，如选图"拍照/相册"）
    if (showPlacePhotoSheet) {
        AlertDialog(
            onDismissRequest = { showPlacePhotoSheet = false },
            title = { Text("加位置图片") },
            text = { Text("下一单的人也能看到") },
            confirmButton = {
                TextButton(onClick = {
                    showPlacePhotoSheet = false
                    container.locationManager.requestSingle()
                    placePhotoCamera.launch(null)
                }) { Text("拍照") }
            },
            dismissButton = {
                TextButton(onClick = {
                    showPlacePhotoSheet = false
                    placePhotoPicker.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
                }) { Text("从相册选") }
            },
        )
    }

    // 撤销二次确认
    if (vm.showCancelDialog) {
        AlertDialog(
            onDismissRequest = { vm.showCancelDialog = false },
            title = { Text("确认撤销订单？") },
            text = { Text("撤销后派单员不再处理。") },
            confirmButton = {
                TextButton(
                    onClick = { vm.cancel() },
                    colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error),
                ) { Text("确认撤销") }
            },
            dismissButton = { TextButton(onClick = { vm.showCancelDialog = false }) { Text("再想想") } },
        )
    }

    // 软删除确认（隔离区 30 天，派单员可恢复）
    if (vm.showDeleteDialog) {
        AlertDialog(
            onDismissRequest = { vm.showDeleteDialog = false },
            title = { Text("删除订单？") },
            text = { Text("删除后 30 天内可恢复。确认删除吗？") },
            confirmButton = {
                TextButton(
                    onClick = { vm.delete(onBack) },
                    colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error),
                ) { Text("确认删除") }
            },
            dismissButton = { TextButton(onClick = { vm.showDeleteDialog = false }) { Text("取消") } },
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
                        // 金额规则唯一实现在 core/InputRules.kt（原来这里什么过滤都没有）
                        onValueChange = { vm.draftFreight = InputRules.moneyInput(it) },
                        label = { Text("运费 ¥（留空=待定）") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
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
                        "按份拆分（用 / 分隔，如 150/150）",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = vm.splitPartsText,
                        // 份数只可能是"数字 + 分隔符"（如 150/150）；原来这个框连过滤都没有。
                        // 口味刁的输入（`150/abc`）本来就会在 saveSplit 里被挡成
                        // 「请按份填写比例，如 150/150」—— 但那时候用户已经敲完了，不如敲不进去。
                        onValueChange = { vm.splitPartsText = InputRules.splitPartsInput(it) },
                        label = { Text("各份比例/数量，如 150/150") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "原单撤销，生成多张待派单。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            },
            confirmButton = { TextButton(onClick = { vm.saveSplit() }, enabled = !vm.acting) { Text("拆分") } },
            dismissButton = { TextButton(onClick = { vm.showSplitDialog = false }) { Text("取消") } },
        )
    }
    // 转货：先选「转给谁」（选人抽屉），选完才开那张表单抽屉。
    // ⛔ 两个 ModalBottomSheet 不能同时开（底下的会被压没），所以选人抽屉一关才开表单抽屉
    //    （ViewModel 的 reopenTransferPicker 就是照这个顺序把两个开关拨过来的）。
    if (vm.showTransferPicker) {
        ShipperPickerSheet(
            shippers = vm.transferShippers,
            selectedId = vm.transferTargetId,
            tempName = vm.transferTempName,
            onPick = { vm.onPickTransferShipper(it) },
            onPickTemp = { vm.onPickTransferTemp(it) },
            onDismiss = { vm.showTransferPicker = false },
            title = "转给谁",
        )
    }
    if (vm.showTransferSheet) {
        vm.order?.let { o ->
            OrderTransferSheet(
                order = o,
                targetLabel = vm.transferTargetLabel,
                qtyOf = { vm.transferQty[it] ?: 0 },
                onQtyChange = { id, q -> vm.setTransferQty(id, q) },
                onFillAll = { vm.fillAllTransfer() },
                onPickShipper = { vm.reopenTransferPicker() },
                busy = vm.transferBusy,
                error = vm.transferError,
                onConfirm = { vm.saveTransfer() },
                onDismiss = { vm.showTransferSheet = false },
            )
        }
    }
    // 派单弹窗（与「派单作业」池子共用同一份实现）。派成了 → 让本页重拉一次：
    // 状态从「派单中」翻成「已派单」，底部按钮组也跟着换（`vm.load()`）。
    AssignDriverDialog(assignVm) { vm.load() }
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
            // 就地新建（用户 2026-09-22：「直接点击挂账，这个挂账单位是**自动添加**的」）
            onCreate = { name -> vm.chargeNewUnit(name) },
            acting = vm.acting,
            onDismiss = { vm.showChargeSheet = false },
        )
    }

    // ⛔ 「拍照送达」的底部抽屉（`DeliverySheet`）与内部备注 AlertDialog 已在 2026-10-06 拆掉
    //   （用户台账 L-04）：照片、送达备注、「提交送达」全搬进 `DetailBody` 最底下那两块，
    //   破损卡片只留商品明细下面那一份（抽屉里那份是**第二份**）。
    //   `vm.showDeliverySheet` / `vm.showNoteDialog` 随之退役 —— 状态不再是「开不开弹层」，
    //   而是「已经拍了几张」（`vm.capturedPhotos`）。

    // 照片大图（翻页 / 双指缩放 / 保存到相册）—— 实现在 ui/common/ImagePreview.kt，
    // 全库只此一份：地址页、下单页、订单详情页点开的都是它。
    preview.Show()
}

/**
 * 订单详情「收货信息」卡里的**司机**一行：名字（主角）+ 电话（次要小字）+ 右侧「拨号」按钮。
 *
 * ## 由来（用户 2026-09-22，两轮）
 * 「加一个功能就是在订单详情的界面当中可以拨打司机电话……这个功能显示**只会在派单端里**，
 * 其他人是没有的，也就是点击一个**拨号按钮**，它**自动弹到那个拨号界面**，然后可以拨号打电话给司机」。
 * → 本轮放宽：「派单员……**包括啊或者批发商也是可以拨打司机电话**的……**只有这两个人**能看得到，
 * **司机是没有这个的**」。
 *
 * ## 三个决定
 * 1. **按钮只在 `onDial != null` 时存在**（＝`ui/common/DriverCall.kt::canDialDriver` 放行 + 号码能拨）。
 *    传 null 就整颗不画 —— 调用点负责判，这里不重复判角色（这一层只回答"长什么样"）。
 * 2. **`ACTION_DIAL` 而不是 `ACTION_CALL`**：前者只把号码填进系统拨号盘、由用户自己按最后那一下，
 *    **不需要 `CALL_PHONE` 权限**，也不会误触就拨出去。⛔ 别改成 `ACTION_CALL`：
 *    那要申请权限，而且"点一下就拨出去"正是用户在下单人那一行为什么要求先弹确认的理由。
 * 3. **信息在左、按钮贴最右、同排**（设计规范 §4.16.7）—— 按钮单独占一行会让卡片白白高一行。
 *    图标用 `DriveEta` + `MgrGreen`（司机管理的语义色），与上面「收货人」「下单人」两行的图标同形；
 *    号码是**次要信息**（`bodySmall` 灰），主角是"这单谁在拉"（与线路卡主次同一条口径）。
 */
@Composable
private fun DriverRow(name: String, phone: String, onDial: (() -> Unit)?) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp),
    ) {
        Icon(
            Icons.Default.DriveEta,
            contentDescription = null,
            tint = Color(MgrGreen),
            modifier = Modifier.size(22.dp),
        )
        Spacer(Modifier.width(8.dp))
        Column(Modifier.weight(1f)) {
            Text(
                "司机 " + name,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = androidx.compose.ui.text.font.FontWeight.Bold,
                color = MaterialTheme.colorScheme.onSurface,
            )
            if (phone.isNotBlank()) {
                Text(
                    phone,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        if (onDial != null) {
            FilledTonalButton(
                onClick = onDial,
                contentPadding = PaddingValues(horizontal = 14.dp, vertical = 0.dp),
            ) {
                Icon(Icons.Default.Call, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(6.dp))
                Text("拨号")
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun DetailBody(
    order: OrderDto,
    /**
     * 就地改单的**全部**状态与动作（CHG-0041）。界面这一侧只认得这个接口 ——
     * 六个草稿值加一串动作摊平成参数的话，这张参数表（本来就有 30 个）就没人读得懂了。
     */
    edit: OrderEditHost,
    role: Role,
    prefs: HintPrefs,
    uploadingPlace: Boolean,
    onAddPlacePhoto: () -> Unit,
    acting: Boolean,
    uploading: Boolean,
    onCancelClick: () -> Unit,
    onDeleteClick: () -> Unit,
    onNavigate: () -> Unit,
    onAck: () -> Unit,
    onCaptureClick: () -> Unit,
    onPhotoClick: (String) -> Unit,
    /** 点刚拍还没上传的那张（本地 `File`）→ 大图预览；`i` 是它在 `photos` 里的序号。 */
    onCapturedPhotoClick: (Int) -> Unit = {},
    onPayClick: () -> Unit,
    onChargeClick: () -> Unit,
    onEditFreightClick: () -> Unit,
    onSplitClick: () -> Unit,
    onTransferClick: () -> Unit,
    onAssignClick: () -> Unit,
    onDirectCompleteClick: (String?) -> Unit,
    damageByProduct: Map<Long, Int> = emptyMap(),
    damageNote: String = "",
    onDamageQty: (Long, Int) -> Unit = { _, _ -> },
    onDamageNote: (String) -> Unit = {},
    // ── 拍照送达这条链路的页面内状态与动作（用户台账 L-04：照片、送达备注、内部备注、完成）──
    /** 已经拍了还没上传的照片（本地绝对路径，落在 `context.cacheDir/photos`）。 */
    photos: List<String> = emptyList(),
    /** 送达备注（提交时随照片一起上传）。 */
    remark: String = "",
    onRemarkChange: (String) -> Unit = {},
    onRemovePhoto: (Int) -> Unit = {},
    /** 提交送达：`cash` / `arrears` / `null`（含义与挂车直结那条路的 `onDirectCompleteClick` 相同）。 */
    onSubmitDelivery: (String?) -> Unit = {},
    /**
     * 内部备注（**追加一条**）。
     *
     * ⛔ 后端 `POST /orders/{id}/driver-note` 是 append-only（`orders_delivery.py` 写
     * `[司机 {时间}] ` 前缀**累加**到 `internal_notes`，注释明说写进去就再也改不了），
     * 所以这里**不回填**已有备注 —— 这一格是「再写一条」，历史在上面收货信息卡里只读看。
     */
    noteText: String = "",
    onNoteTextChange: (String) -> Unit = {},
    onSaveNote: () -> Unit = {},
    /** 司机/派单员：这单还没有坐标 → 可以到场补上 */
    canFillNav: Boolean = false,
    onFillNavClick: () -> Unit = {},
    /**
     * 看这一页的人是不是**批发商**（`users.is_member` 的货主）——「谁能拨司机电话」要用它。
     *
     * 传的是**事实**（我是不是批发商），判断留在用它的那一行（`canDialDriver(role, memberShipper)`）：
     * 会话里没有 `is_member`，这一页自己取不到（见 `OrderDetailViewModel.isMemberShipper`）。
     */
    memberShipper: Boolean = false,
) {
    val total = order.orderProducts.sumOf { moneyToDouble(it.lineTotal) }
    // ── 就地改单的两个门（CHG-0041）──
    // ① **谁能改**：只有**派单员** —— 后端 `Permission.ORDER_EDIT` / `ORDER_PRODUCT_EDIT`
    //    只发给 dispatcher（`backend/app/core/rbac.py:95,104`），货主与司机都没有那颗权限。
    // ② **什么状态能改**：判据**只有一处** —— `core/OrderStatusModel.kt` 的 `EDITABLE`
    //    （外围信息：后端 `orders.update_order` 只拒已送达/已撤销/已退货）与 `LINE_EDITABLE`
    //    （商品行：后端 `order_products.LINE_EDITABLE_STATUSES`）。那两个集合由
    //    `_tools/qa/_check_client_contract.py` 与后端源码逐值对账。
    // ⛔ 别在这一页另写一套状态判断：宽一点就是把"点下去必然 400"的按钮摆在用户面前
    //    （本页「挂账」那颗就是这么被修过一次的，见 `OrderStatusModel.canChargeToArrears`）。
    val canEditInfo = role == Role.DISPATCHER && order.status in OrderStatusModel.EDITABLE
    val canEditLines = role == Role.DISPATCHER && order.status in OrderStatusModel.LINE_EDITABLE
    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            SectionCard {
                // 单号那一行（2026-09-22）。
                //
                // ① **单号独占一行，不跟状态徽章挤**：单号是 `SO` + 8 位日期 + 10 位随机数
                //    = **20 个字符**（`backend/app/services/auth_service.py::new_order_no`），
                //    `titleLarge`（22sp）下大约 240dp 宽；同一行再放一个状态徽章就放不下了 ——
                //    单号会被折到第二行，看起来就是"错位"。用户原话：
                //    「那个订单**详情**…那个**订单号**啊出现了**错位**。哎**不要缩小**一点，
                //      这样子就**好看一点**」 → 所以**不动字号**，改的是布局：
                //    单号整行，状态徽章挪到下面那一行（跟「创建于 …」并列）。
                // ② **长按复制**：单号是司机/货主**口头对单**用的标识（后端注释里写着），
                //    不能选中复制就只能手抄 20 个字符。走共用那一份 `copyTextToClipboard`
                //    （它顺带回答"还要不要自己弹提示"：Android 13+ 系统自己会弹，别叠两条）。
                val ctx = LocalContext.current
                var copied by remember { mutableStateOf(false) }
                LaunchedEffect(copied) {
                    if (copied) {
                        delay(2000)
                        copied = false
                    }
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        "#" + order.orderNo,
                        style = MaterialTheme.typography.titleLarge,
                        modifier = Modifier
                            .weight(1f)
                            .combinedClickable(
                                onClick = {},
                                onLongClickLabel = "复制单号",
                                onLongClick = {
                                    if (copyTextToClipboard(ctx, "单号", order.orderNo)) copied = true
                                },
                            ),
                    )
                    if (copied) {
                        Text(
                            "已复制",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.primary,
                        )
                    }
                }
                Spacer(Modifier.height(4.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        "创建于 " + formatDateTime(order.createdAt),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.weight(1f),
                    )
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
                // 下单人那一行点了之后**先确认再拨**（见下面那段注释）
                var confirmCallBoss by remember { mutableStateOf(false) }
                // 就地改（CHG-0041）：点行尾那个「改」，这一块原地变成多行输入框。
                if (edit.editingField == OrderEditField.ADDRESS) {
                    AddressEditBlock(edit)
                } else {
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
                        // 「改」只画给改得动的人（判据见 DetailBody 开头那两个门）
                        if (canEditInfo) EditHint(onClick = { edit.startEdit(OrderEditField.ADDRESS) })
                    }
                }
                // 位置图片：横排缩略图 + 「补地点图」（点缩略图看大图）。
                // 以前这里只画 `addressImageUrl`（首图，150dp 大图）—— 多图上传之后
                // 那张大图会永远只显示第一张，而其它几张谁也看不到；缩略图这一版
                // 三个角色看到的是**同一组图**，也才点得开。
                PlacePhotoStrip(
                    urls = order.imageUrls.ifEmpty { listOfNotNull(order.addressImageUrl) },
                    uploading = uploadingPlace,
                    prefs = prefs,
                    onAdd = onAddPlacePhoto,
                    onPreview = onPhotoClick,
                )
                Spacer(Modifier.height(8.dp))
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                Spacer(Modifier.height(8.dp))
                NavigationBlock(
                    order = order,
                    role = role,
                    canFill = canFillNav,
                    prefs = prefs,
                    onFillClick = onFillNavClick,
                )
                Spacer(Modifier.height(8.dp))
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                Spacer(Modifier.height(8.dp))
                // 收货人（可点击拨打）与下单人（2026-09-20 用户要求：「详情也会显示这 2 个信息，
                // 这边的电话号码都会显示出来」）。名称与电话的拼接规则在 `contactWho`（卡片共用）。
                if (edit.editingField == OrderEditField.DONGJIA) {
                    ContactEditBlock(edit, "收货人", OrderEditField.DONGJIA_NAME, OrderEditField.DONGJIA_PHONE)
                }
                // ⚠️ 姓名/电话都空时**也要画这一行**（只要改得动）：收货人电话正是司机到场要打的
                //    那个号，而以前 `contactWho(...)?.let` 会整行不画 —— 派单员连"补一个号"的入口都没有。
                val dongjiaWho = contactWho(order.contactDongjiaName, order.contactDongjiaPhone)
                if (dongjiaWho != null || canEditInfo) {
                    // 判据要的是字面形态 "收货人 " + who（_check_contact_names.py）：
                    // 空值兜底收在一个变量里，颜色判断仍看 dongjiaWho 本身。
                    val who = dongjiaWho ?: "未填"
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
                            "收货人 " + who,
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = androidx.compose.ui.text.font.FontWeight.Bold,
                            color = if (dongjiaWho != null) androidx.compose.ui.graphics.Color(0xFF0A6CFF)
                                else MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        // ⛔ 这里原来右边还有一句「点击拨打」。用户 2026-09-22：「那个**点击拨打**那个提示
                        //    可以**去掉**，不需要啊，因为他这个已经**蓝色亮起来**了，人家就知道可以拨打」。
                        if (canEditInfo) EditHint(onClick = { edit.startEdit(OrderEditField.DONGJIA) })
                    }
                }
                // 下单人：**也能拨**，但**不直接拨**（用户 2026-09-22：「点击拨打下单人不是点一下就立马
                // 可以拨打，而是他有个**弹窗确认**『是否确认拨打』，可以取消」）—— 下单人常常就在旁边，
                // 误点一下就拨出去不礼貌；收货人是"货要送到的人"，那一行仍然一点就拨。
                // 电话号码那一段是**绿色小字**（用户：「样式不要变，但是颜色变一下，变成（一）点绿色」）。
                if (edit.editingField == OrderEditField.BOSS) {
                    ContactEditBlock(edit, "下单人", OrderEditField.BOSS_NAME, OrderEditField.BOSS_PHONE)
                }
                // 同理：没填时也画这一行（能改的话），否则"补一个下单人电话"无从下手
                val bossWho = contactWho(order.contactBossName, order.contactBossPhone)
                if (bossWho != null || canEditInfo) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable(enabled = order.contactBossPhone.isNotBlank()) { confirmCallBoss = true }
                            .padding(vertical = 6.dp),
                    ) {
                        Icon(
                            Icons.Default.Person,
                            contentDescription = null,
                            tint = androidx.compose.ui.graphics.Color(0xFF00B578),
                            modifier = Modifier.size(22.dp),
                        )
                        Spacer(Modifier.width(8.dp))
                        // 与上面「收货人」那一行**同形**：label 与值拼成一个 Text、左对齐、同一个字号字重
                        // （用户 2026-10-06：「就是**下单人**和后面的那些显示的信息中间出现了空格，
                        //   **有时候有有时候又没有**，跟上面的又不做一个对齐，非常怪」）。
                        // ⛔ 别再给 label 加 `Modifier.weight(1f)` —— 那会把值顶到整行最右，
                        //    中间的空隙 = 整行宽 − label 宽 − 值宽：**值一长空隙就没了、值一短空隙就很大**，
                        //    那正是"有时候有有时候又没有"的来源（不是数据脏）。
                        // 绿色是用户 2026-09-22 点名要的（「样式不要变，但是颜色变一下，变成（一）点绿色」），
                        // 判据要的是字面形态 "下单人 " + who（_check_contact_names.py）；颜色仍看 bossWho 本身。
                        val bossText = bossWho ?: "未填"
                        Text(
                            "下单人 " + bossText,
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = androidx.compose.ui.text.font.FontWeight.Bold,
                            color = if (bossWho != null) androidx.compose.ui.graphics.Color(0xFF00B578)
                                else MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        if (canEditInfo) EditHint(onClick = { edit.startEdit(OrderEditField.BOSS) })
                    }
                    // 确认弹窗（不是一点就拨）：下单人常常就在旁边，误点一下不礼貌
                    if (confirmCallBoss) {
                        AlertDialog(
                            onDismissRequest = { confirmCallBoss = false },
                            title = { Text("确认拨打") },
                            text = {
                                Text(
                                    (order.contactBossName.orEmpty().ifBlank { "下单人" }) +
                                        "：" + order.contactBossPhone,
                                )
                            },
                            confirmButton = {
                                TextButton(onClick = {
                                    confirmCallBoss = false
                                    val uri = android.net.Uri.parse("tel:" + order.contactBossPhone.trim())
                                    ctx.startActivity(android.content.Intent(android.content.Intent.ACTION_DIAL, uri))
                                }) { Text("拨打") }
                            },
                            dismissButton = {
                                TextButton(onClick = { confirmCallBoss = false }) { Text("取消") }
                            },
                        )
                    }
                }
                if (edit.editingField == OrderEditField.REMARK) {
                    RemarkEditBlock(edit)
                } else if (order.remark.isNotBlank() || canEditInfo) {
                    // 备注空着时也画一行（只要改得动）：那是"写一句给司机的话"的入口。
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.weight(1f)) { InfoRow("备注", order.remark.ifBlank { "未填写" }) }
                        if (canEditInfo) EditHint(onClick = { edit.startEdit(OrderEditField.REMARK) })
                    }
                }
                if (role == Role.DRIVER || role == Role.DISPATCHER) {
                    if (order.internalNotes.isNotBlank()) InfoRow("内部备注", order.internalNotes)
                }
                // 司机那一行（2026-09-22 用户两轮口述：「加一个功能就是在订单详情的界面当中
                // **可以拨打司机电话**……这个功能显示**只会在派单端里**，其他人是没有的」
                // → 本轮放宽：「派单员……**包括啊或者批发商也是可以拨打司机电话**的……
                // **只有这两个人**能看得到，**司机是没有这个的**」）。
                //
                // ① **"谁能拨"的判据只有一处**：`ui/common/DriverCall.kt::canDialDriver`
                //    （派单员 + **批发商**）。⛔ 别在这一行里再写一遍角色判断，更别顺手放宽成"所有货主"。
                //    这一行本身（司机是谁 + 电话）三个角色都看得到 —— 它同时是"这单谁在拉"的记账信息，
                //    所以门只落在**动作**（那颗按钮）上，不落在这一行上。
                // ② 号码**不是能拨的形状**时（空号、或司机账号进了回收站之后后端下发的
                //    `13800001234_del160` 这种带软删后缀的值）不给按钮：一个点不动的按钮比
                //    没有按钮更糟，用户会以为是 App 坏了。判据复用 `InputRules`（**不自己写一份
                //    电话规则**）：`phoneError` 管"太短/空"，`PHONE_MAX` 管"多出来的尾巴"。
                // ③ 按钮与信息**同排、贴最右**（设计规范 §4.16.7：`Row { 信息 weight(1f); 按钮们 }`，
                //    别让按钮单独占一行、也别用裸 `IconButton`）。
                if (!order.driverName.isNullOrBlank()) {
                    val driverPhone = order.driverPhone.orEmpty().trim()
                    val dialable = driverPhone.length <= InputRules.PHONE_MAX &&
                        InputRules.phoneError(driverPhone) == null
                    DriverRow(
                        name = order.driverName.orEmpty(),
                        phone = driverPhone,
                        onDial = if (canDialDriver(role, memberShipper) && dialable) {
                            {
                                // `ACTION_DIAL`（不是 `ACTION_CALL`）：只把号码填进系统拨号盘、
                                // 由用户自己按最后那一下 —— 不需要 CALL_PHONE 权限，也不会误触就拨出去
                                // （收货人/下单人那两处同理）。
                                ctx.startActivity(
                                    android.content.Intent(
                                        android.content.Intent.ACTION_DIAL,
                                        android.net.Uri.parse("tel:" + driverPhone),
                                    )
                                )
                            }
                        } else null,
                    )
                }
            }
        }
        item {
            SectionCard {
                SectionTitle(Icons.Default.Inventory2, Color(ProductPurple), "商品明细")
                Spacer(Modifier.height(10.dp))
                // 点一行就能改，这件事得说出来：行本身看不出可点（用户要的形态是
                // 「点击对应的 ui 状态/信息就编辑」，入口的可见性由这句话兜底）。
                if (canEditLines) {
                    Text(
                        "点某一行可以改数量与单价",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(6.dp))
                }
                // 单位换算（一车 = 8 方）：**全 App 一份**（`UnitConv`）。设过换算时数量那一格写
                // 「×10 车 ≈ 80 方」（用户 2026-09-24：「我下的十车，会有 2 个数据」）。
                val conversions by UnitConv.rows.collectAsState()
                // ── 两列（件数 / 金额）的宽度：**本单里最宽的那一条说了算** ──
                // 用户 2026-09-22：「商品明细……后面是有价格的**没有做对齐**啊，就是**件与件数做对齐、
                // 价格与价格做个对齐**，他们都**放在右边的**」（货主那边同一句话）。
                // 做法：每一行都用**同一个宽度** + 右对齐，于是两个数各自成一列；
                // 宽度是量出来的（`Adaptive.kt::rememberTextWidth`，与全 App 同一把尺），不按字数猜。
                // ⚠️ 它只能在组合期、且**不在条件分支里**调；`fold` / `forEach` 是 inline 所以能放进去，
                //    **`map` 不是 inline、别用**（见 Adaptive.kt 的说明）。所以下面全部走 fold。
                val qtyStyle = MaterialTheme.typography.titleMedium.copy(
                    fontWeight = androidx.compose.ui.text.font.FontWeight.Bold,
                )
                val moneyStyle = MaterialTheme.typography.titleSmall.copy(
                    fontWeight = androidx.compose.ui.text.font.FontWeight.Bold,
                )
                val damageStyle = MaterialTheme.typography.labelMedium.copy(
                    fontWeight = androidx.compose.ui.text.font.FontWeight.Bold,
                )
                val qtyW = order.orderProducts.fold(0.dp) { acc, l ->
                    maxOf(acc, rememberTextWidth("×" + qtyWithUnitConverted(l.quantity, l.unit, conversions), qtyStyle))
                }
                val moneyW = order.orderProducts.fold(0.dp) { acc, l ->
                    maxOf(acc, rememberTextWidth("¥" + formatMoney(l.lineTotal), moneyStyle))
                }
                // 货损那一格也**单独占一列**：它一出现就会把这行的金额往左挤 ——
                // 不占列的话，"有货损的那一行"金额就和别的行对不齐了（正是要修的那件事）。
                // ⚠️ 这里对**每一行都量**（哪怕这一行没货损）：`remember` 的槽位数必须与行数一致。
                val damageW = order.orderProducts.fold(0.dp) { acc, l ->
                    maxOf(acc, rememberTextWidth(damageLabel(l.damageQuantity, l.unit), damageStyle))
                }
                val hasDamage = order.orderProducts.any { it.damageQuantity > 0 }
                order.orderProducts.forEachIndexed { i, line ->
                    // 改一行货（CHG-0041）：点这一行 → 原地变成「数量 / 单价 / 删掉这件货」。
                    if (canEditLines && edit.editingLineId == line.id) {
                        ProductLineEditBlock(edit, line)
                    } else {
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .then(
                                // 点整行就能改（比每行右边再挂一颗「改」省地方，动作与派单池那颗一致）
                                if (canEditLines) Modifier.clickable { edit.startLineEdit(line) } else Modifier,
                            )
                            .padding(vertical = 8.dp),
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
                            // 单位是下单时定格的（选品弹窗里能改）；老数据为空 → 只显示件数，
                            // **不编一个"件"出来**（编了就成了"系统说的"，而实际没人填过）。
                            // 拼法只有一处：`Units.kt::qtyWithUnit`（订单卡片走的也是它）。
                            // 2026-09-24 起设过换算时再带后半截（「×10 车 ≈ 80 方」），
                            // 量列宽与渲染用**同一个函数**（不同的话右对齐当场错位）。
                            "×" + qtyWithUnitConverted(line.quantity, line.unit, conversions),
                            style = qtyStyle,
                            color = androidx.compose.ui.graphics.Color(0xFF8455E6),
                            textAlign = TextAlign.End,
                            modifier = Modifier.width(qtyW),
                        )
                        Spacer(Modifier.width(12.dp))
                        if (role != Role.DRIVER) {
                            Text(
                                "¥" + formatMoney(line.lineTotal),
                                style = moneyStyle,
                                color = MaterialTheme.colorScheme.onSurface,
                                textAlign = TextAlign.End,
                                modifier = Modifier.width(moneyW),
                            )
                        }
                        if (hasDamage) {
                            // ⚠️ 用 hasDamage（**整单**判据）而不是 line.damageQuantity > 0：
                            //    这一格得**每一行都占住**，否则没货损的那几行金额会贴到最右边、
                            //    与有货损的那几行错开一列。
                            Spacer(Modifier.width(8.dp))
                            Text(
                                if (line.damageQuantity > 0) damageLabel(line.damageQuantity, line.unit) else "",
                                style = damageStyle,
                                color = Color(MoneyOrange),
                                textAlign = TextAlign.End,
                                modifier = Modifier.width(damageW),
                            )
                        }
                    }
                    if (i != order.orderProducts.lastIndex) {
                        Spacer(Modifier.height(4.dp))
                        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                    }
                    }
                }
                // 这一单还没有货时也说一句：一张空白卡片看起来像"没加载出来"
                if (canEditLines && order.orderProducts.isEmpty()) {
                    Text(
                        "这一单还没有货物 —— 点下面的「加一件货」加。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(4.dp))
                }
                // 「加一件货」：与派单池**同一个动作**（`addPickedLines` 逐行报，失败只丢那一行）；
                // 选品弹层挂在屏级（见 `OrderDetailScreen` 里那段挂载）。
                if (canEditLines) {
                    TextButton(onClick = { edit.openLinePicker() }) { Text("加一件货") }
                }
                Spacer(Modifier.height(10.dp))
                HorizontalDivider()
                Spacer(Modifier.height(10.dp))
                // 司机端详情页**一律不画金额**（2026-09-21 用户定案，与订单卡片同一条规矩）：
                //   原来这里对按单计费(PIECE)且已定价的单显示「运费 ¥…」，现在去掉。
                //   钱只在「我的账单」里看（`ui/driver/DriverFreightScreen`）。
                //   ⛔ 别加回来：判据 `_tools/qa/_check_driver_money.py`（含反向验证）。
                if (role != Role.DRIVER) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
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
                if (order.damageNote.isNotBlank()) {
                    Spacer(Modifier.height(8.dp))
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                    Spacer(Modifier.height(8.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.BrokenImage, contentDescription = null, tint = Color(MoneyOrange), modifier = Modifier.size(16.dp))
                        Spacer(Modifier.width(6.dp))
                        Text(
                            "货损备注：" + order.damageNote,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.weight(1f),
                        )
                    }
                }
            }
        }
        // 司机：已接单可录入商品破损（选填·公司自担），卡片槽紧贴商品明细下方
        if (role == Role.DRIVER && order.status in OrderStatusModel.COMPLETABLE) {
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
                // 退货也是这条单走过的一步（2026-10-03，E2E 走查 P27）：整单退完是 status=RETURNED，
                // 部分退货留在「已送达」但 `returnedAt` 同样有值 —— 只按状态判会漏掉部分退货那一半
                // （走查当时司机端这一页"仍是 已送达、流转记录里没有退货一行"）。
                order.returnedAt?.let { TimeRow("退货", it) }
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
                            if (order.status in OrderStatusModel.FREIGHT_EDITABLE) {
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
                            // ⛔ 已收款的单不许再挂账（后端 `_reject_if_already_collected` 会拒）——
                            //    判据与 AI 侧共用 `OrderStatusModel.canChargeToArrears`，
                            //    理由是"界面给的按钮点了必然失败"（2026-09-23 真机实测抓到）。
                            enabled = !acting &&
                                OrderStatusModel.canChargeToArrears(order.paid, order.settledAmount),
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
                // 派单员：待派单 → 主动作就是「派单」（P12）。原来这一页只有拆分/收款/挂账/删除，
                // 想派单必须记住单号、退回「派单作业」池子里去翻同一张单 —— 报告里就是这么丢的
                // （`_tmp/d_detail2.png`）。闸门与拆分同源（`OrderStatusModel.ASSIGNABLE`），
                // 用主色按钮：这是这一页唯一能把单推走的一步。
                if (role == Role.DISPATCHER && order.status in OrderStatusModel.ASSIGNABLE) {
                    Button(
                        onClick = onAssignClick,
                        enabled = !acting,
                        modifier = Modifier.fillMaxWidth().height(48.dp),
                    ) {
                        Icon(Icons.Default.PersonAddAlt, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("派单")
                    }
                }
                // 派单员：待派单可拆分（大单拆多单分派）
                if (role == Role.DISPATCHER && order.status in OrderStatusModel.ASSIGNABLE) {
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
                // 派单员：这一张单上的货可以转给**别的货主**（拆出去 / 并过去 / 整单转出）。
                // 闸门与「拆分订单」刻意不同源：拆分只对「待派单」开放，转货在途三态都能转
                // （OrderStatusModel.TRANSFERABLE ＝ 后端 transfer_lines 那道挡板的补集）。
                if (role == Role.DISPATCHER && order.status in OrderStatusModel.TRANSFERABLE) {
                    OutlinedButton(
                        onClick = onTransferClick,
                        enabled = !acting,
                        modifier = Modifier.fillMaxWidth().height(48.dp),
                    ) {
                        Icon(Icons.Default.SwapHoriz, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("转货（转给别的货主）")
                    }
                }
                // 货主：派单中/已派单可撤销（后端 `cancel_pending` 同一对取值）
                if (role == Role.SHIPPER && order.status in OrderStatusModel.CANCELLABLE) {
                    OutlinedButton(
                        onClick = onCancelClick,
                        enabled = !acting,
                        modifier = Modifier.fillMaxWidth().height(48.dp),
                        colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error),
                    ) { Text("撤销订单") }
                }
                // 删除订单（软删除→隔离区 30 天：用户不可见，派单员可恢复）
                // ⚠️ 货主侧**只认终态**：「异常」不是通行证（2026-09-19 审计，与后端同一套判据）。
                //    原来这里多了 `|| order.isException`，于是在途单（已接单/待派单）只要被标过异常
                //    就会显示「删除订单」——点了后端会 400（进行中的订单请走撤销或撤回），
                //    而且司机还在路上，删掉会让他的列表里直接少一张单。
                //    「界面给的按钮点了必然失败」这一类，本仓库已经栽过多次，判据必须两端同源。
                //    ⚠️ 2026-09-20：这一对状态提成 `OrderStatusModel.SHIPPER_DELETABLE`
                //       —— AI 侧（`SoftDeleteOrderHandler`）现在也判同一件事，
                //       写两份的下场是"AI 说能删、界面没有按钮"或反过来。
                val canDelete = (role == Role.SHIPPER &&
                    order.status in OrderStatusModel.SHIPPER_DELETABLE) ||
                    (role == Role.DISPATCHER &&
                        (order.status == "CANCELLED" || order.status == "DELIVERED" || order.status == "PENDING_DISPATCH" || order.isException))
                if (canDelete) {
                    OutlinedButton(
                        onClick = onDeleteClick,
                        enabled = !acting,
                        modifier = Modifier.fillMaxWidth().height(48.dp),
                        colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error),
                    ) {
                        Icon(Icons.Default.Delete, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("删除订单")
                    }
                }
                // 司机：已派单（派了单但还没接）→ 唯一主行动：确认接单
                if (role == Role.DRIVER && order.status in OrderStatusModel.ACKABLE) {
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
                if (role == Role.DRIVER && order.status in OrderStatusModel.COMPLETABLE) {
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
                        // 点一下**直接进相机**（L-04 第 ① 条）；拍过之后这颗按钮就是「继续拍照」——
                        // 页面上只留**一个**拍照入口，免得两颗按钮干同一件事。
                        Button(
                            onClick = onCaptureClick,
                            modifier = Modifier.fillMaxWidth().height(56.dp),
                        ) {
                            Icon(Icons.Default.PhotoCamera, contentDescription = null, modifier = Modifier.size(20.dp))
                            Spacer(Modifier.width(8.dp))
                            Text(if (photos.isEmpty()) "拍照送达" else "继续拍照（" + photos.size + " 张）")
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
                    // 「内部备注」那颗按钮（+ AlertDialog）已退役：备注改成页面最底下的输入框
                    // （L-04 第 ⑥ 条「不要弹窗」）。⛔ 角色门一个字没放松 —— 见下面「内部备注」那一块。
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
        // ── 送达凭证（司机 · 拍照送达这条链路）2026-10-06 用户台账 L-04 ────────────────
        // 从前这一整块在底部抽屉里（`ModalBottomSheet`）：点「拍照送达」只开抽屉，照片、
        // 送达备注、货物破损、「提交送达」全都躺在抽屉里；拍完想再拍一张得**先关抽屉**再点入口。
        // 用户原话（m00061）：「点击拍照送达就**直接拍照**」「拍完的照片就在订单界面里出现缩略图，
        // 然后我们可以**再点击继续拍照**」「送达备注就写在内部备注的上面」。
        //
        // ⛔ 挂车直结那条路（`order.freightVisible`）**不走这里**：`has_per_order_pay` 的单
        //    点一下「完成订单 / 收取现金 / 挂账」就走 `completeDirect`（**不带照片**），那颗按钮
        //    留在上面的动作卡里，所以这一块整块不画。
        if (role == Role.DRIVER && order.status in OrderStatusModel.COMPLETABLE && !order.freightVisible) {
            item {
                SectionCard {
                    SectionTitle(
                        Icons.Default.PhotoCamera,
                        Color(ProductPurple),
                        if (photos.isEmpty()) "送达凭证" else "送达照片（已拍 " + photos.size + " 张）",
                    )
                    if (photos.isNotEmpty()) {
                        Spacer(Modifier.height(10.dp))
                        Text(
                            "点一下看大图（可双指放大、可存相册）；右上角的 ⊗ 是删掉这一张",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Spacer(Modifier.height(8.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            photos.forEachIndexed { i, path ->
                                Box {
                                    AsyncImage(
                                        model = File(path),
                                        contentDescription = "已拍照片",
                                        contentScale = ContentScale.Crop,
                                        modifier = Modifier
                                            .size(84.dp)
                                            .clip(MaterialTheme.shapes.medium)
                                            .clickable { onCapturedPhotoClick(i) },
                                    )
                                    IconButton(
                                        onClick = { onRemovePhoto(i) },
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
                    OutlinedTextField(
                        value = remark,
                        onValueChange = onRemarkChange,
                        label = { Text("送达备注（可选）") },
                        minLines = 2,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }
        }

        // ── 内部备注（司机 / 派单员可见）2026-10-06 L-04 第 ⑥ 条 + L-05 的口径 ──────────
        // 从前这里是一颗按钮 + 一个 AlertDialog：写一句话要弹窗、写完再关。用户要的是「就在页面
        // 上写」——弹窗去掉，**角色门一个字都没放松**：后端 `order_response.py` 对货主把
        // `internal_notes` 抹成空串，`orders_delivery.py` 只放 DRIVER/DISPATCHER（司机还
        // 必须是这单的司机）；界面这一侧就是下面这行 `role` 判据 + 收货信息卡里那道只读门。
        //
        // ⛔ 写入口是 **append-only**：后端给每条加 `[司机 {时间}] ` 前缀**累加**到
        //    `internal_notes`（注释明说写进去就再也改不了）。所以这一格**不回填**已有备注 ——
        //    它只能是「再写一条」，历史在上面收货信息卡里只读看。
        if (role == Role.DRIVER && order.status in OrderStatusModel.COMPLETABLE) {
            item {
                SectionCard {
                    SectionTitle(Icons.Default.Notes, Color(0xFF1E6FFF), "内部备注")
                    Spacer(Modifier.height(4.dp))
                    Text(
                        "只有司机和派单员看得到。写进去是追加一条，已有的那条不会被改动。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(10.dp))
                    OutlinedTextField(
                        value = noteText,
                        onValueChange = onNoteTextChange,
                        label = { Text("再写一条备注（与派单员可见）") },
                        minLines = 2,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(Modifier.height(8.dp))
                    OutlinedButton(
                        onClick = onSaveNote,
                        enabled = !acting && noteText.isNotBlank(),
                        modifier = Modifier.fillMaxWidth().height(48.dp),
                    ) {
                        Icon(Icons.Default.Add, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("添加备注")
                    }
                }
            }
        }

        // ── 完成（拍照送达这条链路的最后一步）────────────────────────────────────
        // 用户第 ④ 条：「**只有上传最少一张照片之后才会有这个**（完成入口）」⇒ 一张都没拍时这一
        // 块**整块不存在**（不是置灰：没照片时连按钮都不该出现在页面上）。第 ③ 条：「完成按钮就
        // 移到内部备注的最下面」⇒ 它就是这一页最后一个块。
        // ⛔ `completeDelivery` 里那道 `capturedPhotos.isEmpty()` 是**第二道门**（防界面
        //    之外的调用），别顺手删。挂车直结不走这里（见上面「送达凭证」那块）。
        if (role == Role.DRIVER && order.status in OrderStatusModel.COMPLETABLE &&
            !order.freightVisible && photos.isNotEmpty()
        ) {
            item {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    if (order.collectCash) {
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            Button(
                                onClick = { onSubmitDelivery("cash") },
                                enabled = !uploading,
                                modifier = Modifier.weight(1f).height(56.dp),
                                colors = ButtonDefaults.buttonColors(
                                    containerColor = Color(MoneyOrange),
                                    contentColor = Color.White,
                                ),
                            ) {
                                if (uploading) {
                                    CircularProgressIndicator(Modifier.size(22.dp), color = Color.White, strokeWidth = 2.dp)
                                } else {
                                    Icon(Icons.Default.Payments, contentDescription = null, modifier = Modifier.size(20.dp))
                                    Spacer(Modifier.width(6.dp))
                                    Text("收取现金（" + photos.size + " 张）", style = MaterialTheme.typography.titleSmall)
                                }
                            }
                            OutlinedButton(
                                onClick = { onSubmitDelivery("arrears") },
                                enabled = !uploading,
                                modifier = Modifier.weight(1f).height(56.dp),
                            ) {
                                Icon(Icons.Default.RequestQuote, contentDescription = null, modifier = Modifier.size(20.dp))
                                Spacer(Modifier.width(6.dp))
                                Text("挂账（" + photos.size + " 张）", style = MaterialTheme.typography.titleSmall)
                            }
                        }
                    } else {
                        Button(
                            onClick = { onSubmitDelivery(null) },
                            enabled = !uploading,
                            modifier = Modifier.fillMaxWidth().height(56.dp),
                        ) {
                            if (uploading) {
                                CircularProgressIndicator(Modifier.size(22.dp), color = MaterialTheme.colorScheme.onPrimary, strokeWidth = 2.dp)
                            } else {
                                Icon(Icons.Default.CheckCircle, contentDescription = null, modifier = Modifier.size(20.dp))
                                Spacer(Modifier.width(8.dp))
                                Text("提交送达（" + photos.size + " 张照片）", style = MaterialTheme.typography.titleSmall)
                            }
                        }
                    }
                }
            }
        }
    }
}

/** 商品破损卡片槽（选填·公司自担）：点开可逐商品填破损数量 + 货损备注，默认收起不占空间 */
/**
 * 收货信息里的「导航信息」块。
 *
 * 三句话要看得出区别，所以三种状态各写各的：
 * 1. **有坐标** → 显示「导航可用」，并写明**这个坐标是谁给的**（`nav_source`）：
 *    下单时带的 / 司机到场补的 / 派单员补的。货主看到"司机帮你补的"这件事必须是
 *    真的（后端落库的来源字段），不能靠猜。
 * 2. **没坐标 + 我是司机或派单员** → 高亮提示 + 「我到了，帮补导航」按钮。
 *    这是整个功能的入口：知道坐标的人（到过现场的司机）才有这个按钮。
 * 3. **没坐标 + 我是货主** → 只说事实，不给按钮（货主此刻也不在现场）。
 */
@Composable
private fun NavigationBlock(
    order: OrderDto,
    role: Role,
    canFill: Boolean,
    prefs: HintPrefs,
    onFillClick: () -> Unit,
) {
    val hasCoords = !order.addressLat.isNullOrBlank() && !order.addressLng.isNullOrBlank()
    when {
        hasCoords -> Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                Icons.Default.MyLocation,
                contentDescription = null,
                tint = Color(0xFF00B578),
                modifier = Modifier.size(18.dp),
            )
            Spacer(Modifier.width(6.dp))
            Text("导航可用", style = MaterialTheme.typography.bodyMedium, fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold)
            Spacer(Modifier.width(8.dp))
            Text(
                when (order.navSource) {
                    "driver" -> "司机到场补录"
                    "dispatcher" -> "派单员补录"
                    else -> "下单时已填"
                },
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        canFill -> Column {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    Icons.Default.Warning,
                    contentDescription = null,
                    tint = Color(0xFFE6A23C),
                    modifier = Modifier.size(18.dp),
                )
                Spacer(Modifier.width(6.dp))
                Text(
                    "这单没有导航信息",
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold,
                    modifier = Modifier.weight(1f),
                )
            }
            Spacer(Modifier.height(2.dp))
            // 解释性的话走 HintOnce（出现三次就不再出现）；常驻只留按钮上那 7 个字
            HintOnce(prefs, "order.nav_block", "到地方标一下位置，以后大家都直接能用")
            Spacer(Modifier.height(8.dp))
            Button(
                onClick = onFillClick,
                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF00A2C7), contentColor = Color.White),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Icon(Icons.Default.AddLocationAlt, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(6.dp))
                Text("我到了，补导航")
            }
        }

        else -> Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                Icons.Default.Warning,
                contentDescription = null,
                tint = Color(0xFFE6A23C),
                modifier = Modifier.size(18.dp),
            )
            Spacer(Modifier.width(6.dp))
            Text(
                "没有导航信息 · 司机到场后补上",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/**
 * 收货位置的图片：**横排缩略图 + 一个「补地点图」**（点缩略图看大图）。
 *
 * 为什么三个角色都看得到、也都点得到「补地点图」：这一单的**货主**拍了门口、
 * **司机**到了现场又补了一张"这个路口进来第三家" —— 照片是给**下一单**的人看的，
 * 谁在场谁就该能加。真正拦人的是后端（派单员 / 这单的货主 / 这单的司机），
 * 客户端这边不需要再判一遍"我是谁"（各角色的订单列表本来就只给得到自己的单）。
 *
 * ## 标签为什么是「补地点图」而不是「加图」（2026-09-22 用户要求）
 * 用户原话：「这个订单详情的那个地点的一个下面一个**加图**啊，**他不是加图片，
 * 他是给这个地点补上图片**啊，**要说明一个说明**啊。」
 * 「加图」读起来像"再传一张图上去"（给**订单**加图），而这件事的真实含义是
 * **给这个收货地点补图** —— 图跟着地址走，下次送到这里的人能直接看到。
 * 标签本身就要把这个意思说出来（4 个字，仍在"最多 7~8 字"的尺子里），
 * 补什么、给谁看则由下面那句 [HintOnce] 说（用户 2026-09-20：「有些功能不需要说太多」）。
 */
@Composable
private fun PlacePhotoStrip(
    urls: List<String>,
    uploading: Boolean,
    prefs: HintPrefs,
    onAdd: () -> Unit,
    onPreview: (String) -> Unit,
) {
    Spacer(Modifier.height(8.dp))
    Row(
        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        urls.filter { it.isNotBlank() }.forEach { url ->
            AsyncImage(
                model = resolveStaticUrl(url),
                contentDescription = "位置图片",
                contentScale = ContentScale.Crop,
                modifier = Modifier
                    .size(72.dp)
                    .clip(RoundedCornerShape(12.dp))
                    .clickable { onPreview(url) },
            )
        }
        Surface(
            shape = RoundedCornerShape(12.dp),
            color = MaterialTheme.colorScheme.surfaceVariant,
            modifier = Modifier.size(72.dp).clickable(enabled = !uploading, onClick = onAdd),
        ) {
            Box(contentAlignment = Alignment.Center) {
                if (uploading) {
                    CircularProgressIndicator(Modifier.size(20.dp))
                } else {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Icon(Icons.Default.AddAPhoto, contentDescription = null, modifier = Modifier.size(20.dp))
                        Text("补地点图", style = MaterialTheme.typography.labelSmall)
                    }
                }
            }
        }
    }
    // ⚠️ 这句是**解释句**（走 HintOnce → Hint，总开关关掉就不显示），所以刻意避开
    //    「下次」「下单」这类词：`_hint_inventory.py` 的单位词表里有"次/单"，
    //    命中就会被保守地判成 DATA（**永远显示**）—— 那是已知偏差，不是我们要的行为。
    HintOnce(prefs, "order.place_photo", "补的是这个收货地点的照片（门口、路口、楼栋），以后送到这里的人能直接看到")
}

/**
 * 补导航确认框。**文案只留"几个字"**（用户 2026-09-20：
 * 「有些功能不需要说太多…大概字数最多是 7 到 8 个字」）；
 * 需要解释的（"按下去会写哪三处""坐标相近会怎样"）走 [HintOnce]，出现三次就不再出现。
 */
@Composable
private fun NavigationFillDialog(
    prefs: HintPrefs,
    addressText: String,
    name: String,
    onNameChange: (String) -> Unit,
    lat: String,
    lng: String,
    acting: Boolean,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("补上导航信息") },
        text = {
            Column {
                Text(
                    "坐标 " + lat.take(10) + ", " + lng.take(10),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(10.dp))
                OutlinedTextField(
                    value = name,
                    onValueChange = onNameChange,
                    label = { Text("地点名") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                if (addressText.isNotBlank()) {
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "收货地址：" + addressText,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 3,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                Spacer(Modifier.height(10.dp))
                Text("存三处：这单 / 货主库 / 共享库")
                Spacer(Modifier.height(4.dp))
                HintOnce(prefs, "order.nav_writes", "坐标相近会自动并成一个，不会越攒越多")
            }
        },
        confirmButton = {
            TextButton(onClick = onConfirm, enabled = !acting) {
                Text(if (acting) "提交中…" else "确定")
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}

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
        color = MaterialTheme.colorScheme.surface,
        tonalElevation = 0.dp,
        shadowElevation = 1.dp,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(12.dp)) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth().clickable { expanded = !expanded },
            ) {
                Icon(Icons.Default.BrokenImage, contentDescription = "商品破损", tint = Color(MoneyOrange), modifier = Modifier.size(20.dp))
                Spacer(Modifier.width(8.dp))
                Text("商品破损", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onSurface, modifier = Modifier.weight(1f))
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
                                // 只留数字（原来手写的 `filter { isDigit }.takeLast(3)` 是规则的一份副本）
                                val n = InputRules.intInput(v, 3).toIntOrNull() ?: 0
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
// ⛔ 底部抽屉（DeliverySheet）已删除（用户台账 L-04：「点击拍照送达就直接拍照」）。
//   它原来那四件事现在的去处：
//   ① 已拍照片的缩略图 → 上面 DetailBody 里的「送达照片」区（可点开大图、右上角可删）；
//   ② 「再拍一张」 → 动作卡里那颗**同一个**拍照入口（拍过之后文案变「继续拍照（N 张）」）；
//   ③ 送达备注 / 货物破损 → 备注搬进「送达照片」区；破损这一页商品明细下面本来就有一份
//      （DamageCard），抽屉里那份是**第二份**，随抽屉一起没了；
//   ④ 「提交送达 / 收取现金 / 挂账」 → 页面最底下的「完成」块（**至少一张照片**才画）。


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
    /** 就地新建一个单位并挂上（"自动添加"：名字不在名册里也照样能挂）。 */
    onCreate: (String) -> Unit,
    acting: Boolean,
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
            // ⚠️ 名册里没有那个单位时**不用先退出去建**（用户 2026-09-22：
            //    「直接点击挂账，这个挂账单位是**自动添加**的」）：
            //    在这里写个名字就能建出来并挂上 —— 两个动作（建 + 挂）分开写审计，
            //    所以建成功、挂失败时那句话要说清"单位已建好，再点一次即可"（见 VM）。
            var newName by remember { mutableStateOf("") }
            Row(verticalAlignment = Alignment.CenterVertically) {
                SoTextField(
                    value = newName,
                    onValueChange = { newName = it },
                    placeholder = "名册里没有？写个名字，直接建 + 挂",
                    modifier = Modifier.weight(1f),
                )
                Spacer(Modifier.width(8.dp))
                TextButton(
                    onClick = { onCreate(newName) },
                    enabled = !acting && newName.isNotBlank(),
                ) { Text(if (acting) "处理中…" else "新建并挂账") }
            }
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            Spacer(Modifier.height(6.dp))
            when {
                loading -> LoadingBox()
                units.isEmpty() -> Text(
                    "暂无挂账单位（去工作台加）",
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

/**
 * 送达照片：**单张加载失败只影响那一张**。
 *
 * ⚠️ 原来这里是一个 `var broken by remember { mutableStateOf(false) }`，任何一张的
 * `onError` 把它置真 → 整块 `return`（2026-09-19 审计 L-12）。后果是静默且方向相反的：
 * 司机明明拍了 3 张（提交时也都上传成功了），只要其中一张的 URL 取不到
 * （图片被保留策略压过/服务端刚清理过/那一次上传的响应丢了），界面上**一张都看不到**，
 * 连"这里有送达照片"这件事都看不出来——而送达照片正是"这单真的送到了"的凭据。
 * 所以失败的是**哪一张**，不是"有没有失败"。
 */
@Composable
private fun DeliveryPhotosSection(urls: List<String>, onPhotoClick: (String) -> Unit) {
    val broken = remember { mutableStateListOf<String>() }
    SectionCard {
        SectionTitle(Icons.Default.PhotoLibrary, Color(MgrGreen), "送达照片（" + urls.size + "）")
        Spacer(Modifier.height(10.dp))
        urls.chunked(3).forEach { rowUrls ->
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                rowUrls.forEach { url ->
                    val tile = Modifier
                        .weight(1f)
                        .aspectRatio(1f)
                        .clip(MaterialTheme.shapes.small)
                        .clickable { onPhotoClick(url) }
                    if (url in broken) {
                        // 占位而不是消失：格子留着、点开仍是大图，并如实说是这张没加载出来
                        Box(
                            modifier = tile.background(MaterialTheme.colorScheme.surfaceVariant),
                            contentAlignment = Alignment.Center,
                        ) {
                            Text(
                                "这张没加载出来",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                textAlign = TextAlign.Center,
                            )
                        }
                    } else {
                        AsyncImage(
                            model = resolveStaticUrl(url),
                            contentDescription = "送达照片",
                            contentScale = ContentScale.Crop,
                            onError = { broken.add(url) },
                            modifier = tile,
                        )
                    }
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