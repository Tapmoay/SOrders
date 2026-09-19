package com.tapmoay.sorders.ui.ai

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.graphics.Bitmap
import android.net.Uri
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.CallSplit
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.AddComment
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.DeleteSweep
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Key
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.NorthEast
import androidx.compose.material.icons.filled.PhotoCamera
import androidx.compose.material.icons.filled.PhotoLibrary
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.Undo
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import com.tapmoay.sorders.ai.AiAttachment
import com.tapmoay.sorders.ai.AiAttachmentLoader
import com.tapmoay.sorders.ai.AiContainer
import com.tapmoay.sorders.ai.AiContext
import com.tapmoay.sorders.ai.AiConversations
import com.tapmoay.sorders.ai.AiPendingWrite
import com.tapmoay.sorders.ai.AiRecentPhotos
import com.tapmoay.sorders.ai.AiRole
import com.tapmoay.sorders.ai.AiVision
import com.tapmoay.sorders.ai.AiWritePreviewStore
import com.tapmoay.sorders.ai.AiWriteRisk
import com.tapmoay.sorders.ai.ThinkingLevel
import com.tapmoay.sorders.ui.common.AppTopBar
import com.tapmoay.sorders.ui.common.DangerConfirmDialog
import com.tapmoay.sorders.ui.common.OneShotSnackbar
import com.tapmoay.sorders.ui.common.SegmentedPicker
import com.tapmoay.sorders.ui.common.appViewModel
import com.tapmoay.sorders.ui.theme.AiBlue
import com.tapmoay.sorders.ui.theme.aiBrandBrush
import kotlinx.coroutines.launch

// ===== 本页自定义尺寸（老人友好：正文 17sp、次要信息 14sp、可点区域 ≥ 48dp）=====
private val MessageTextSize = 17.sp
private val TraceTextSize = 14.sp
private val TapTarget = 48.dp

/**
 * 「这条什么时候来的 / 花了多少 token」那一行的字号：**11sp，比工具痕迹还小一档**。
 *
 * 用户的原话是「对于不重要的信息就把我们稍微退一点，不让他做那么明显」。
 * 这一行的定位就是"要看的时候在"：它既不是内容也不是操作，是**元信息**。
 * 退的方法是**只退字号和颜色**（`outline`），不退可点区域、不删内容——
 * 删掉的话用户想问"这条什么时候发的"就再也找不到答案了。
 */
private val MetaTextSize = 11.sp

/**
 * 模型栏字号：12sp。
 *
 * 刻意比 [TraceTextSize]（14sp）还小一档——用户的原话是「字体可以小一点，那就不占位子了」。
 * 它不是"次要信息"，是"工具条上的状态"：只要看得清、点得到就够了。
 */
private val ModelBarTextSize = 12.sp

/**
 * AI 的单色强调色 = Google AI 蓝（#4285F4，品牌渐变的起点）。
 *
 * 界面里凡是要"表示这是 AI"的单色元素（链接、选中态、图标着色）都用它；
 * 需要更"AI"的地方用品牌渐变（空状态星标徽章），见 [aiBrandBrush]。
 * ⚠️ 发送键**不在**这里（原来在）：用户 2026-09-18 要求它改成蓝色，
 * 于是它和同一行的 ⊕ 一样用 [AiAccent]——一行里两个控件同色，比一个蓝一个渐变更干净。
 */
private val AiAccent = Color(AiBlue)

/**
 * 确认卡明细区的最大高度。
 *
 * 为什么必须有这个上限：明细行数由动作决定（批量调价一次能列十几行），
 * 不封顶的话卡片会长到把「确认/取消」挤出屏幕——**用户根本点不到确认**。
 * 200dp 大致是"能读到 6~8 行"，再多就内部滚动；按钮永远留在可见区。
 */
private val DetailMaxHeight = 200.dp

/** 抽屉宽度：固定 300dp。手机上留出约 1/6 的遮罩够手指侧滑关掉；平板上也不会宽得离谱。 */
private val DrawerWidth = 300.dp

/**
 * 示例问题：点一下＝填入输入框并直接发送。
 *
 * ⚠️ **按角色分开**。v3.13 给货主开了 AI 入口之后，他看到的却是
 * 「哪个司机跑得最多」「把货主账单导成表格」——**那些他既没权限、也不是他要问的**。
 * 空状态是用户对这一页的第一印象，写错等于告诉他"这东西不是给你的"。
 */
private val SAMPLE_QUESTIONS_DISPATCHER = listOf(
    "今天哪些货主的单最多？",
    "哪个司机这个月跑得最多？",
    "有哪些商品库存到红线了？",
    "把这个月的货主账单导成表格",
)

/** 货主的问题示例：他有权限做的事、他真正要问的（下单/地址/账本）。 */
private val SAMPLE_QUESTIONS_SHIPPER = listOf(
    "我最近的订单有哪些？",
    "帮我加一个常用地址",
    "我这个月的账结了吗？",
    "有哪些商品能下单？",
)

/**
 * 输入框里的灰字提示，同样按角色给。
 *
 * 派单端的例子是"库存到红线"——那是**派单员才有的能力**；货主照着敲一句，
 * 得到的只会是一次"你没这个权限"，而他不会再敲第二句。提示语是"教用户怎么用"，
 * 举一个他自己做不到的例子，等于教错。
 */
private const val HINT_DISPATCHER = "例如：哪些商品库存到红线了？"
private const val HINT_SHIPPER = "例如：帮我加一个常用地址"

/**
 * 底部那张白色卡片**上面两个角**的圆角半径。
 *
 * 用户 2026-09-17：「它能将上面的 2 个角做一个圆角的处理吗？显得比较圆滑一点，
 * 就不是那么方方正正的。」原来它是全宽直边，和上面的消息区硬碰硬。
 * 只此一处，要调就调它（`0.dp` 就等于退回直角）。
 */
private val BOTTOM_SHEET_RADIUS = 20.dp

/**
 * 派单员 AI 助手聊天页。
 *
 * 布局要点（都是用户明确提过的）：
 * - **左侧抽屉放历史对话**：顶栏「历史」按钮或从左边缘侧滑都能拉出来；
 * - **顶栏三键**：历史 / 新对话 / 设置。新对话刻意从「更多」里搬到齿轮旁边——
 *   它是高频动作，藏在二级菜单里等于没有；
 * - **发送键在输入框右侧且垂直居中，箭头朝上**：向上 = 「送进上面的聊天记录」，
 *   比原来的纸飞机更直白（纸飞机容易理解成「发到别处」）。
 *
 * @param ai 由 NavGraph 建好并缓存（与 [AiSettingsScreen] 同一个实例，设置页改完 key 本页立刻生效）
 * @param onBack 返回工作台
 * @param onOpenSettings 跳设置页（右上角齿轮，也是「未配置 key」时的出口）
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AiChatScreen(
    ai: AiContainer,
    onBack: () -> Unit,
    onOpenSettings: () -> Unit,
) {
    val vm: AiChatViewModel = appViewModel { AiChatViewModel(ai) }

    val listState = rememberLazyListState()
    val snackbar = remember { SnackbarHostState() }
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val drawerState = rememberDrawerState(DrawerValue.Closed)

    var showClearConfirm by remember { mutableStateOf(false) }
    var confirmDeleteId by remember { mutableStateOf<String?>(null) }
    var showModelSheet by remember { mutableStateOf(false) }
    /** 正在预览的附件（null = 不弹）。挂上之前先让用户核对"我读到的和你那张表是不是一样"。 */
    var previewAttachment by remember { mutableStateOf<AiAttachment?>(null) }

    // 图片走**相册**（系统照片选择器），文件走**文件管理器**。
    //
    // 为什么要分开（而不是一个按钮按 MIME 分流）：用户的原话是
    // 「他这个看照片是直接在照片里选的就是照片文件夹里面选也就是相册里面选」——
    // 找他刚拍的那张单子，人的第一反应是**打开相册**，而不是在文件管理器里翻 Downloads。
    // 一个按钮按类型分流，等于让用户在"我要选的东西在哪个 App 里"这件事上多想一步。
    //
    // PickVisualMedia（Android 13+ 的系统照片选择器；更低版本走系统的图片选择，
    // 再兜底到 ACTION_OPEN_DOCUMENT）：只给图片、只给相册，**不需要相册权限**——
    // 系统把用户选中的那一张交给我们，我们不碰其它照片。
    val pickImage = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.PickVisualMedia(),
    ) { uri ->
        if (uri != null) vm.attachImage(context, uri, onOpenSettings)
    }

    // 文件（Excel / CSV / 文本）用 OpenDocument 而不是 GetContent：
    // 前者给的是**长期可读**的 content:// URI（云盘文件也能拿到），后者在部分 ROM 上
    // 只保证"这一瞬间可读"，而我们要把它读进内存再上传。
    val pickFile = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenDocument(),
    ) { uri ->
        if (uri != null) {
            // 兜底：万一用户的文件管理器里选了张图（有些 ROM 的"最近文件"会混），也按图片走
            val mime = context.contentResolver.getType(uri)
            if (AiAttachmentLoader.isImageMime(mime) || AiAttachmentLoader.looksLikeImage(uri.lastPathSegment)) {
                vm.attachImage(context, uri, onOpenSettings)
            } else {
                vm.attach(context, uri, onOpenSettings)
            }
        }
    }

    // 进入本页时确认一次 key 状态（从设置页返回后由卡片上的「重新检查」兜底）
    LaunchedEffect(Unit) { vm.refreshConfigured() }

    // ------------------------------------------------------------------ 附件面板（v3.34c）
    //
    // 用户拿别的 App 的输入区做参照，原话：
    // 「中间那些图片全是相册的图片已经列出来了，然后在下面再是下面 3 个，我们就又可观又简洁」。
    // 所以输入区从"左边挤两个图标 + 输入框 + 发送键"改成：
    //   [输入框 + ⊕ + ↑]  →  点 ⊕ 展开  →  [最近照片横向排] + [拍照 / 相册 / 文件]
    // 输入框那一行只剩下"打字"和"发出去"两件事，干净；要附件时再展开，不占地方的常态。
    var showAttachPanel by remember { mutableStateOf(false) }

    // 拍照：`TakePicturePreview` 直接回一个 Bitmap（不用 FileProvider、不占第二个权限）。
    // 落成缓存文件再交给 attachImage —— 它那条路收 Uri，`file://` 和相册来的 `content://`
    // 走的是同一段读取代码（见 AiAttachmentLoader.readImage），不用为拍照再写一条支路。
    val cameraLauncher = rememberLauncherForActivityResult(ActivityResultContracts.TakePicturePreview()) { bmp ->
        if (bmp == null) return@rememberLauncherForActivityResult
        try {
            val dir = File(context.cacheDir, "ai_cam").apply { mkdirs() }
            val out = File(dir, "cam_" + System.currentTimeMillis() + ".jpg")
            out.outputStream().use { bmp.compress(Bitmap.CompressFormat.JPEG, 88, it) }
            vm.attachImage(context, Uri.fromFile(out), onOpenSettings)
        } catch (e: Exception) {
            vm.attachError = "这张照片没读出来，请重试一次。"
        }
    }

    // 相册权限**只为把"最近几张"摆出来**。点面板里的「相册」仍然走系统照片选择器（不需要权限），
    // 所以用户拒绝这个权限时功能一个都不少，只是那一排照片是空的——如实说明即可，不反复弹框。
    var hasPhotoAccess by remember { mutableStateOf(AiRecentPhotos.granted(context)) }
    val askPhotoAccess = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        hasPhotoAccess = ok
    }
    var recentPhotos by remember { mutableStateOf<List<Uri>>(emptyList()) }
    LaunchedEffect(showAttachPanel, hasPhotoAccess) {
        recentPhotos = if (showAttachPanel && hasPhotoAccess) {
            withContext(Dispatchers.IO) { AiRecentPhotos.recent(context) }
        } else {
            emptyList()
        }
    }
    // 面板里已挂载的照片由 vm.attachments 推导（见下面 onTogglePhoto 的注释），
    // 这里不再单独存一份勾选集合。

    // 从设置页返回：模型 / 思考强度 / 窗口都可能在那边改过，同步过来
    LaunchedEffect(Unit) { vm.refreshConfig() }

    OneShotSnackbar(snackbar, vm.compactNotice, onConsumed = { vm.compactNotice = null })

    // 新对话 / 切换对话 / 分叉：滚回顶部，给用户一个明确的"换了一段对话"信号
    LaunchedEffect(vm.switchTick) {
        if (vm.switchTick > 0) listState.scrollToItem(0)
    }

    OneShotSnackbar(snackbar, vm.error, onConsumed = { vm.error = null })

    // 挂附件失败（格式不对/太大/云盘没下载完/后端读不出来）：必须说清楚，否则用户
    // 只会看到"点了没反应"，然后反复点同一张坏文件
    OneShotSnackbar(snackbar, vm.attachError, onConsumed = { vm.attachError = null })

    // 抽屉开着时按返回键先关抽屉，而不是直接退出页面
    BackHandler(enabled = drawerState.isOpen) {
        scope.launch { drawerState.close() }
    }

    val leadCount = if (!vm.configured) 1 else 0
    val showGuide = vm.configured && vm.messages.isEmpty()
    val branchCount = if (vm.activeIsBranch) 1 else 0
    val itemCount = leadCount + (if (showGuide) 1 else 0) + branchCount + vm.messages.size +
        (if (vm.totalTokens > 0) 1 else 0)
    val last = vm.messages.lastOrNull()

    // 列表变化就滚到底（含流式文本与工具痕迹增长）
    LaunchedEffect(itemCount, last?.text?.length, last?.toolTrace?.size) {
        if (itemCount > 0) listState.scrollToItem(itemCount - 1)
    }

    /** 复制并提示。Android 13+ 系统自己会弹「已复制」，就不重复弹了。 */
    fun copyText(label: String, text: String) {
        if (text.isBlank()) return
        copyToClipboard(context, label, text)
        if (android.os.Build.VERSION.SDK_INT < 33) {
            scope.launch { snackbar.showSnackbar("已复制$label") }
        }
    }

    ModalNavigationDrawer(
        drawerState = drawerState,
        drawerContent = {
            HistoryDrawer(
                history = vm.history,
                activeId = vm.activeId,
                hasContent = vm.messages.isNotEmpty(),
                onClose = { scope.launch { drawerState.close() } },
                onNew = {
                    vm.newChat()
                    scope.launch { drawerState.close() }
                },
                onOpen = { id ->
                    vm.openConversation(id)
                    scope.launch { drawerState.close() }
                },
                onCopy = { id -> copyText("对话", vm.plainTextOf(id)) },
                onDuplicate = { id ->
                    vm.duplicateConversation(id)
                    scope.launch {
                        drawerState.close()
                        snackbar.showSnackbar("已复制成新对话")
                    }
                },
                onDelete = { id -> confirmDeleteId = id },
                onClearCurrent = { showClearConfirm = true },
            )
        },
    ) {
        Scaffold(
            modifier = Modifier.imePadding(),
            snackbarHost = { SnackbarHost(snackbar) },
            topBar = {
                AppTopBar(
                    title = "AI 助手",
                    // 副标题整条去掉（用户原话「直接去掉那个问数据那个标语」）：
                    // 去掉之后顶栏只剩「AI 助手 + 模型芯片 + 三个按钮」，它们就能在同一行里垂直居中对齐，
                    // 芯片也不必再屈居第二行（原话「模型再往上移一点……所有元件做一个中心对齐」）。
                    // 运行状态（查询中/整理中）改由芯片自己的文案承担，见 AiChatViewModel.modelChipLabel。
                    subtitle = null,
                    onBack = onBack,
                    subtitleTrailing = {
                        ModelChip(
                            label = vm.modelChipLabel,
                            onClick = {
                                vm.refreshModelOptions()
                                showModelSheet = true
                            },
                        )
                    },
                    actions = {
                        // 历史对话：抽屉入口。放在最左，和「返回」相邻，符合"左边能翻历史"的直觉
                        IconButton(
                            onClick = { scope.launch { drawerState.open() } },
                            modifier = Modifier.size(TapTarget),
                        ) {
                            Icon(
                                Icons.Default.History,
                                contentDescription = "历史对话",
                                tint = AiAccent,
                                modifier = Modifier.size(24.dp),
                            )
                        }
                        // 新对话：从「更多」里搬出来的高频动作
                        IconButton(
                            onClick = { vm.newChat() },
                            modifier = Modifier.size(TapTarget),
                        ) {
                            Icon(
                                Icons.Default.AddComment,
                                contentDescription = "新对话",
                                tint = AiAccent,
                                modifier = Modifier.size(24.dp),
                            )
                        }
                        IconButton(onClick = onOpenSettings, modifier = Modifier.size(TapTarget)) {
                            Icon(
                                Icons.Default.Settings,
                                contentDescription = "设置",
                                tint = AiAccent,
                                modifier = Modifier.size(24.dp),
                            )
                        }
                    },
                )
            },
            bottomBar = {
                // 底部这一整块是**一张白色的卡片**（输入栏 + 附件面板 + 确认卡都长在它上面）。
                // 用户 2026-09-17 的要求：「将上面的 2 个角做一个圆角的处理，显得比较圆滑一点，
                // 就不是那么方方正正的」——原来它是全宽直边，顶边一刀切，和上面的消息区
                // 硬碰硬地顶在一起。
                //
                // ⚠️ 圆角只能画在**这一个** Surface 上：里面的 InputBar / AttachPanel 原来各有一个
                //    自己的白底 Surface，各画各的就会把圆角盖成直角（外面圆、里面方，白搭）。
                //    所以那两处改成不带底色的容器，白底与阴影统一由这里出。
                Surface(
                    shape = RoundedCornerShape(topStart = BOTTOM_SHEET_RADIUS, topEnd = BOTTOM_SHEET_RADIUS),
                    color = MaterialTheme.colorScheme.surface,
                    shadowElevation = 8.dp,
                ) {
                Column {
                    // ⚠️ 顺序是刻意的：确认卡在编辑条**下面**、输入框**上面**。
                    // 两个都出现时（很少有），"写数据"这件事优先级更高，离手指更近。
                    WriteConfirmCard(
                        pending = vm.pendingWrites,
                        busyToken = vm.writeBusy,
                        onConfirm = { vm.confirmWrite(it) },
                        onCancel = { vm.cancelWrite(it) },
                    )
                    // 编辑态提示条：**必须显眼**——发送的后果是"撤掉原来的回答"，
                    // 用户不被告知就点发送，会以为对话丢了。
                    if (vm.editingIndex >= 0) {
                        EditingBanner(onCancel = { vm.cancelEdit() })
                    }
                    // 已挂上、还没发出去的附件：一行 chip，点开可以逐格核对
                    if (vm.attachments.isNotEmpty()) {
                        PendingAttachmentStrip(
                            items = vm.attachments,
                            onPreview = { previewAttachment = it },
                            onRemove = { vm.removeAttachment(it) },
                        )
                    }
                    InputBar(
                        value = vm.input,
                        onValueChange = { vm.input = it },
                        sending = vm.sending,
                        attaching = vm.attaching,
                        canSend = vm.input.isNotBlank() || vm.attachments.isNotEmpty(),
                        hint = if (ai.currentRole == AiRole.SHIPPER) HINT_SHIPPER else HINT_DISPATCHER,
                        panelOpen = showAttachPanel,
                        onTogglePanel = {
                            val open = !showAttachPanel
                            showAttachPanel = open
                            // 展开时顺手把相册权限要一次（只在还没给过的时候）。
                            // 不在进页面时就要：那时候用户还不知道这一排照片是干嘛的，
                            // 一进来弹个权限框，拒绝率最高。
                            if (open && !hasPhotoAccess) askPhotoAccess.launch(AiRecentPhotos.permission())
                        },
                        onSend = { vm.send(onOpenSettings) },
                        onStop = { vm.stop() },
                    )
                    if (showAttachPanel) {
                        AttachPanel(
                            photos = recentPhotos,
                            hasPhotoAccess = hasPhotoAccess,
                            canAttachMore = vm.attachments.size < AiAttachment.MAX_FILES &&
                                vm.attachments.count { it.isImage } < AiVision.MAX_IMAGES,
                            // 勾选状态**唯一来源是 vm.attachments**（按 sourceUri 对账），
                            // 不在界面里再存一份 picked 集合——两份状态迟早对不上，
                            // 表现是"取消勾选没反应"或"同一张挂了两遍"。
                            picked = vm.attachments.map { it.sourceUri }.toSet(),
                            attaching = vm.attaching,
                            sending = vm.sending,
                            onTogglePhoto = { uri ->
                                if (vm.isAttached(uri)) vm.removeAttachmentByUri(uri)
                                else vm.attachImage(context, uri, onOpenSettings)
                            },
                            onCamera = { cameraLauncher.launch(null) },
                            onAlbum = {
                                pickImage.launch(
                                    PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly),
                                )
                            },
                            onFile = { pickFile.launch(FILE_PICKER_MIME) },
                        )
                    }
                }
                }
            },
        ) { padding ->
            Column(Modifier.fillMaxSize().padding(padding)) {
                LazyColumn(
                    state = listState,
                    modifier = Modifier.fillMaxWidth().weight(1f),
                    contentPadding = PaddingValues(horizontal = 16.dp, vertical = 12.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                if (!vm.configured) {
                    item(key = "not-configured") {
                        NotConfiguredCard(
                            onOpenSettings = onOpenSettings,
                            onRecheck = { vm.refreshConfigured() },
                        )
                    }
                }
                if (vm.activeIsBranch) {
                    item(key = "branch-bar") {
                        BranchBar()
                    }
                }
                // 角色决定空状态的文案与示例问题（货主看到的不能是"哪个司机跑得最多"）
                val isDispatcher = ai.currentRole == AiRole.DISPATCHER
                val sampleQuestions = if (isDispatcher) SAMPLE_QUESTIONS_DISPATCHER else SAMPLE_QUESTIONS_SHIPPER
                if (showGuide) {
                    item(key = "guide") {
                        Box(Modifier.fillParentMaxSize()) {
                            EmptyGuide(questions = sampleQuestions, isDispatcher = isDispatcher, onPick = { q ->
                                vm.input = q
                                vm.send(onOpenSettings)
                            })
                        }
                    }
                }
                items(count = vm.messages.size, key = { it }) { i ->
                    MessageRow(
                        m = vm.messages[i],
                        index = i,
                        sending = vm.sending,
                        onCopy = { idx -> copyText("这条消息", vm.plainTextAt(idx)) },
                        onBranch = { idx ->
                            vm.branchFromMessage(idx)
                            scope.launch { snackbar.showSnackbar("已从这条开始新开一段对话") }
                        },
                        onEdit = { idx ->
                            vm.beginEdit(idx)
                            scope.launch { snackbar.showSnackbar("已放回输入框，改完点发送即可（原回答会被撤掉）") }
                        },
                        onUndo = { token -> vm.undoWrite(token) },
                    )
                }
                if (vm.totalTokens > 0) {
                    item(key = "tokens") {
                        // 同样的道理：这是**页脚统计**，退到最小最淡（11sp + outline）。
                        // 用户要的是答案，不是账单；但想核对用量时它还在这里。
                        Text(
                            "本对话累计 " + AiConversations.tokenLabel(vm.totalTokens),
                            fontSize = MetaTextSize,
                            color = MaterialTheme.colorScheme.outline,
                            textAlign = TextAlign.Center,
                            modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
                        )
                    }
                }
                }
            }
        }
    }

    if (showClearConfirm) {
        DangerConfirmDialog(
            title = "清空当前对话",
            message = "将清空这段对话的内容，并把它从历史记录里移除，删除后无法恢复。",
            confirmText = "清空",
            onConfirm = {
                vm.clear()
                showClearConfirm = false
            },
            onDismiss = { showClearConfirm = false },
        )
    }

    confirmDeleteId?.let { id ->
        val title = vm.history.firstOrNull { it.id == id }?.title ?: "这段对话"
        DangerConfirmDialog(
            title = "删除对话",
            message = "将删除「$title」，删除后无法恢复。",
            confirmText = "删除",
            onConfirm = {
                vm.deleteConversation(id)
                confirmDeleteId = null
            },
            onDismiss = { confirmDeleteId = null },
        )
    }

    if (showModelSheet) {
        ModelSwitchSheet(
            vm = vm,
            onDismiss = { showModelSheet = false },
            onOpenSettings = {
                showModelSheet = false
                onOpenSettings()
            },
        )
    }

    previewAttachment?.let { att ->
        AttachmentPreviewSheet(att = att, onDismiss = { previewAttachment = null })
    }
}

/**
 * 把 data URL 解成缩略图（**只在界面层做**：base64 解码 + 位图解码都不该进纯逻辑层）。
 *
 * 用 `inSampleSize` 先探尺寸再按需解码——直接用完整位图会有几十 MB，
 * 而我们只要 38dp 的一小块。
 */
private fun AiAttachment.thumbnail(): androidx.compose.ui.graphics.ImageBitmap? {
    val url = imageDataUrl ?: return null
    return try {
        val bytes = android.util.Base64.decode(url.substringAfter("base64,", ""), android.util.Base64.DEFAULT)
        val bounds = android.graphics.BitmapFactory.Options().apply { inJustDecodeBounds = true }
        android.graphics.BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
        var sample = 1
        while (bounds.outWidth / (sample * 2) >= 160 && bounds.outHeight / (sample * 2) >= 160) sample *= 2
        val opts = android.graphics.BitmapFactory.Options().apply { inSampleSize = sample }
        android.graphics.BitmapFactory.decodeByteArray(bytes, 0, bytes.size, opts)
            ?.asImageBitmap()
    } catch (e: Exception) {
        null
    }
}

/** 文件选择器只列这几类：读不了的类型不该出现在选择器里让用户白点一次。 */
private val FILE_PICKER_MIME = arrayOf(
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", // .xlsx
    "application/vnd.ms-excel.sheet.macroEnabled.12",                    // .xlsm
    "text/csv",
    "text/comma-separated-values",
    "text/tab-separated-values",
    "text/plain",
)

/**
 * 已挂载（还没发出去）的附件条。
 *
 * 为什么要有这一条、而不是"选完直接发"：附件是**要花用户 token 的**东西，
 * 而且模型会拿着它去理解一整段对话。让它在发送前看得见、能点开、能删掉，
 * 是这一路上唯一一次"用户能核对"的机会。
 */
@Composable
private fun PendingAttachmentStrip(
    items: List<AiAttachment>,
    onPreview: (AiAttachment) -> Unit,
    onRemove: (Int) -> Unit,
) {
    Surface(tonalElevation = 2.dp) {
        Row(
            Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            items.forEachIndexed { i, att ->
                Surface(
                    onClick = { onPreview(att) },
                    shape = RoundedCornerShape(12.dp),
                    color = MaterialTheme.colorScheme.surfaceContainerHigh,
                ) {
                    Row(
                        Modifier.padding(start = 10.dp, end = 4.dp, top = 6.dp, bottom = 6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        val thumb = remember(att.imageDataUrl) { att.thumbnail() }
                        if (thumb != null) {
                            // 图片附件显示**真缩略图**：用户一眼就知道自己选对没有
                            androidx.compose.foundation.Image(
                                bitmap = thumb,
                                contentDescription = null,
                                contentScale = androidx.compose.ui.layout.ContentScale.Crop,
                                modifier = Modifier
                                    .size(38.dp)
                                    .clip(RoundedCornerShape(6.dp)),
                            )
                        } else {
                            Icon(
                                Icons.Default.Description,
                                contentDescription = null,
                                tint = AiAccent,
                                modifier = Modifier.size(18.dp),
                            )
                        }
                        Spacer(Modifier.width(8.dp))
                        Column {
                            Text(att.title(), fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text(
                                att.summary() + if (att.hasWarnings) " · 有说明" else "",
                                fontSize = 11.sp,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                        IconButton(onClick = { onRemove(i) }, modifier = Modifier.size(30.dp)) {
                            Icon(
                                Icons.Default.Close,
                                contentDescription = "移除这个附件",
                                modifier = Modifier.size(16.dp),
                                tint = MaterialTheme.colorScheme.outline,
                            )
                        }
                    }
                }
            }
        }
    }
}

/**
 * 附件预览：把**读到的东西**原样摆出来。
 *
 * 这一步是"信任"的来源：用户传的是一张 Excel，模型看到的是文本表格——
 * 中间如果有错位（串列、日期变成数字、编码变成乱码），这里是他唯一能发现的地方。
 * 所以这张表**不做任何美化**：格子里是什么就显示什么。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AttachmentPreviewSheet(att: AiAttachment, onDismiss: () -> Unit) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp).padding(bottom = 24.dp)) {
            Text(att.title(), fontSize = 17.sp, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(4.dp))
            Text(
                att.summary(),
                fontSize = 13.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            // 后端给的实话（编码是猜的、有工作表没读、行被截断）：**原样显示**，
            // 不折叠——它们是"你可能要采取行动"的信号。
            att.warnings.forEach { w ->
                Spacer(Modifier.height(6.dp))
                Row(verticalAlignment = Alignment.Top) {
                    Icon(
                        Icons.Default.Info,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.error,
                        modifier = Modifier.size(15.dp),
                    )
                    Spacer(Modifier.width(6.dp))
                    Text(w, fontSize = 12.sp, color = MaterialTheme.colorScheme.error)
                }
            }
            Spacer(Modifier.height(12.dp))
            // 图片：直接把**发给模型的那张图**摆出来。
            // 用户最需要确认的就是"它看到的和我选的是不是同一张"——尤其是拍糊了/选错张的时候。
            val full = remember(att.imageDataUrl) { att.thumbnail() }
            if (full != null) {
                androidx.compose.foundation.Image(
                    bitmap = full,
                    contentDescription = att.title(),
                    contentScale = androidx.compose.ui.layout.ContentScale.Fit,
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(max = 420.dp)
                        .clip(RoundedCornerShape(10.dp)),
                )
                Spacer(Modifier.height(12.dp))
            }
            att.tables.forEach { t ->
                if (att.tables.size > 1) {
                    Text("工作表：${t.name}", fontSize = 13.sp, fontWeight = FontWeight.Medium)
                    Spacer(Modifier.height(4.dp))
                }
                AttachmentTable(t)
                Spacer(Modifier.height(12.dp))
            }
        }
    }
}

/** 预览里的那张表：横向可滚（列多时），最多显示前 30 行。 */
@Composable
private fun AttachmentTable(t: AiAttachment.Table) {
    val shown = t.rows.take(30)
    val colCount = shown.maxOfOrNull { it.size } ?: 0
    Column(Modifier.fillMaxWidth()) {
        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState())) {
            Column {
                shown.forEachIndexed { ri, row ->
                    Row(
                        Modifier
                            .background(
                                if (ri == 0) MaterialTheme.colorScheme.surfaceContainerHigh
                                else Color.Transparent,
                            )
                            .padding(vertical = 4.dp),
                    ) {
                        for (ci in 0 until colCount) {
                            Text(
                                row.getOrNull(ci).orEmpty(),
                                fontSize = 12.sp,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                modifier = Modifier
                                    .width(94.dp)
                                    .padding(horizontal = 6.dp),
                                fontWeight = if (ri == 0) FontWeight.Medium else FontWeight.Normal,
                            )
                        }
                    }
                }
            }
        }
        if (t.rows.size > shown.size) {
            Spacer(Modifier.height(4.dp))
            Text(
                "只显示前 ${shown.size} 行（这张表读回 ${t.rows.size} 行，总共 ${t.rowCount} 行）",
                fontSize = 11.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/**
 * 顶栏中间那枚「当前模型 · 思考强度」：点一下就能换。
 *
 * 形态是用户一条条提出来改成的，别自作聪明改回去：
 * - **不要底色**（原话「不用底色，这样太难看了太突出了」）——没有胶囊、没有填充色；
 * - **字要小**（原话「字体可以小一点，那就不占位子了」）——12sp、次要色，一行而已；
 * - **不显示上下文用量**（原话「不需要显示上下文多少或者已用多少，他只需要知道我这个模型是什么
 *   以及思考强度是怎样」）——所以曾经那个「上下文 2.2k / 128k（1%）」被彻底删掉，
 *   连同 `AiContext.usageLabel` 一起删（留着就会有人再画回来）；
 * - **位置在顶栏中间那块空白**（原话「你这个变小了，是不是可以移到中间去了」）——
 *   字号缩小后它塞得下这块空白，于是不再独占一行。
 *
 * 宽度策略：整块可点，文字过长就省略。省略**从左往右**截尾时，
 * 右半段（`flash` / `v4-pro`）才是区分度最高的部分，所以这里给 `maxLines=1` + 省略号，
 * 并在面板里永远显示完整模型名——顶栏负责"一眼知道大概"，面板负责"确认到底哪个"。
 */
@Composable
private fun ModelChip(
    label: String,
    onClick: () -> Unit,
) {
    Row(
        modifier = Modifier
            .clip(RoundedCornerShape(8.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 6.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            label,
            fontSize = ModelBarTextSize,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Icon(
            Icons.Default.ExpandMore,
            contentDescription = "切换模型与思考强度",
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(15.dp),
        )
    }
}

// ==================== 模型切换面板 ====================

/**
 * 模型 / 思考强度 的切换面板。
 *
 * **改完立刻生效**（不等"保存"）：这是从聊天页顶栏点进来的，用户的心智就是"换完接着问"。
 *
 * ### 这里为什么没有「上下文窗口」
 * 用户口径：**不要让用户选那么多选项，直接按模型支持的最大值用**。
 * 所以窗口改成自动（按模型名推断 + 撞上限自动缩小，见 [AiContext]），面板里只留一句说明，
 * 不留任何旋钮——留一个"选错了会报错"的旋钮，等于把本该我们负责的事推给用户。
 *
 * ### 为什么用分段选择器而不是一排 FilterChip
 * 「思考强度」是**同一维度的程度**（关/低/中/高），分段选择器一眼能看出"这四个是一组、现在在哪一档"；
 * 一排 chip 看起来像四个互不相关的开关。这与 App 其它页的块状导航也是同一套语言。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ModelSwitchSheet(
    vm: AiChatViewModel,
    onDismiss: () -> Unit,
    onOpenSettings: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState) {
        Column(
            Modifier
                .fillMaxWidth()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp)
                .padding(bottom = 28.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            // ---------------- 模型 ----------------
            SheetSectionTitle("模型")
            if (vm.modelCandidates.isEmpty()) {
                Text(
                    "还没有可选的模型清单。到「完整设置」里点一次「拉取模型列表」，之后这里就能直接换。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                // 整块浅底容器：一眼看出"这些是备选，选中的那个在里面"
                Surface(
                    shape = RoundedCornerShape(14.dp),
                    color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.45f),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Column(
                        Modifier
                            .fillMaxWidth()
                            .heightIn(max = 240.dp)
                            .verticalScroll(rememberScrollState())
                            .padding(6.dp),
                    ) {
                        vm.modelCandidates.forEach { name ->
                            val selected = name == vm.currentModel
                            Row(
                                Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(10.dp))
                                    .background(if (selected) AiAccent.copy(alpha = 0.14f) else Color.Transparent)
                                    .clickable { vm.switchModel(name) }
                                    .padding(horizontal = 12.dp, vertical = 12.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(
                                    name,
                                    fontSize = 16.sp,
                                    fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal,
                                    color = if (selected) AiAccent else MaterialTheme.colorScheme.onSurface,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                    modifier = Modifier.weight(1f),
                                )
                                if (selected) {
                                    Icon(
                                        Icons.Default.Check,
                                        contentDescription = "当前使用",
                                        tint = AiAccent,
                                        modifier = Modifier.size(18.dp),
                                    )
                                }
                            }
                        }
                    }
                }
            }

            // ---------------- 思考强度 ----------------
            Spacer(Modifier.height(2.dp))
            SheetSectionTitle("思考强度")
            SegmentedPicker(
                labels = ThinkingLevel.entries.map { it.label },
                selected = ThinkingLevel.entries.indexOf(vm.thinkingLevel).coerceAtLeast(0),
                onSelect = { i -> vm.switchThinkingLevel(ThinkingLevel.entries[i]) },
                accent = AiAccent,
            )
            Text(
                vm.thinkingLevel.hint,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurface,
            )
            // 诚实标注：分级在部分端点上会被静默忽略（本项目实测过），不承诺"选高一定更准更慢"
            NoteLine(
                "部分模型只支持「开/关」、不支持分档（会把强度当没看见）。能确定的是「关」一定更省更快。",
            )

            // ---------------- 上下文（没有旋钮，只有一句说明）----------------
            Spacer(Modifier.height(2.dp))
            SheetSectionTitle("上下文")
            NoteLine(
                "不用设置：自动按模型支持的最大值使用，用到 " +
                    "${(AiContext.COMPACT_AT * 100).toInt()}% 会把较早的对话压成摘要接着答" +
                    "（原对话仍留在「历史」里）。万一模型实际装不下，会自动缩小重试。",
            )

            Spacer(Modifier.height(4.dp))
            OutlinedButton(
                onClick = onOpenSettings,
                shape = RoundedCornerShape(12.dp),
                modifier = Modifier.fillMaxWidth().heightIn(min = TapTarget),
            ) {
                Icon(Icons.Default.Settings, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(8.dp))
                // 按钮里不带括号说明：那串字在手机上必折成两行，按钮会显得很笨重。
                // 说明挪到按钮下面一行小字，反而更好读。
                Text("完整设置", fontSize = 16.sp)
            }
            Text(
                "里面可以填 API Key、开关工具、拉取模型列表。",
                fontSize = 12.5.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth(),
            )
        }
    }
}

/** 面板里的小节标题：比正文重、比大标题轻，用来分段而不是抢焦点。 */
@Composable
private fun SheetSectionTitle(text: String) {
    Text(
        text,
        fontSize = 14.sp,
        fontWeight = FontWeight.SemiBold,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
}

/**
 * 一句说明。带一个小「i」图标，与操作项区分开——
 * 这一段是**解释**不是**按钮**，长得像按钮就会被点。
 */
@Composable
private fun NoteLine(text: String) {
    Row(verticalAlignment = Alignment.Top) {
        Icon(
            Icons.Default.Info,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 1.dp).size(13.dp),
        )
        Spacer(Modifier.width(6.dp))
        Text(
            text,
            fontSize = 12.5.sp,
            lineHeight = 17.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

// ==================== 左侧历史抽屉 ====================

/**
 * 历史对话抽屉。
 *
 * 一行 = 一段对话，显示**标题 + 时间 + 用量**（用户明确要的），右侧「⋮」里是
 * 复制全文 / 复制成新对话 / 删除。行本身点了就切过去。
 *
 * 为什么「复制成新对话」和「从某条分叉」是两个动作：前者是**备份**（原件不动，副本可继续问），
 * 后者是**改主意**（丢掉后半段重来）。两者用途不同，不能互相替代。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun HistoryDrawer(
    history: List<ConversationSummary>,
    activeId: String,
    hasContent: Boolean,
    onClose: () -> Unit,
    onNew: () -> Unit,
    onOpen: (String) -> Unit,
    onCopy: (String) -> Unit,
    onDuplicate: (String) -> Unit,
    onDelete: (String) -> Unit,
    onClearCurrent: () -> Unit,
) {
    ModalDrawerSheet(modifier = Modifier.width(DrawerWidth)) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(start = 16.dp, end = 8.dp, top = 12.dp, bottom = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Icons.Default.History, contentDescription = null, tint = AiAccent, modifier = Modifier.size(22.dp))
            Spacer(Modifier.width(8.dp))
            Text("对话历史", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
            IconButton(onClick = onClose, modifier = Modifier.size(TapTarget)) {
                Icon(Icons.Default.Close, contentDescription = "关闭", modifier = Modifier.size(20.dp))
            }
        }

        Button(
            onClick = onNew,
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp).heightIn(min = TapTarget),
            colors = ButtonDefaults.buttonColors(containerColor = AiAccent, contentColor = Color.White),
        ) {
            Icon(Icons.Default.AddComment, contentDescription = null, modifier = Modifier.size(20.dp))
            Spacer(Modifier.width(8.dp))
            Text("新对话", fontSize = 16.sp)
        }

        Spacer(Modifier.height(8.dp))
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

        if (history.isEmpty()) {
            Column(
                modifier = Modifier.fillMaxWidth().padding(24.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    "还没有历史对话。\n问完第一个问题，这里就会出现记录。",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                )
            }
        } else {
            LazyColumn(modifier = Modifier.weight(1f)) {
                items(items = history, key = { it.id }) { item ->
                    HistoryRow(
                        item = item,
                        active = item.id == activeId,
                        onClick = { onOpen(item.id) },
                        onCopy = { onCopy(item.id) },
                        onDuplicate = { onDuplicate(item.id) },
                        onDelete = { onDelete(item.id) },
                    )
                }
            }
        }

        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        TextButton(
            onClick = onClearCurrent,
            enabled = hasContent,
            modifier = Modifier.fillMaxWidth().heightIn(min = TapTarget),
        ) {
            Icon(Icons.Default.DeleteSweep, contentDescription = null, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(6.dp))
            Text("清空当前对话", fontSize = 15.sp)
        }
    }
}

@Composable
private fun HistoryRow(
    item: ConversationSummary,
    active: Boolean,
    onClick: () -> Unit,
    onCopy: () -> Unit,
    onDuplicate: () -> Unit,
    onDelete: () -> Unit,
) {
    var menu by remember { mutableStateOf(false) }
    Surface(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 10.dp, vertical = 4.dp),
        shape = RoundedCornerShape(12.dp),
        color = if (active) AiAccent.copy(alpha = 0.12f) else Color.Transparent,
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().clickable(onClick = onClick)
                .padding(start = 12.dp, end = 4.dp, top = 8.dp, bottom = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    if (item.isBranch) {
                        Icon(
                            Icons.AutoMirrored.Filled.CallSplit,
                            contentDescription = "分支",
                            tint = AiAccent,
                            modifier = Modifier.size(14.dp),
                        )
                        Spacer(Modifier.width(4.dp))
                    }
                    Text(
                        item.title,
                        style = MaterialTheme.typography.bodyLarge,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        color = if (active) AiAccent else MaterialTheme.colorScheme.onSurface,
                    )
                }
                Spacer(Modifier.height(2.dp))
                Text(
                    buildString {
                        append(item.timeLabel)
                        if (item.tokens > 0) append(" · ").append(item.tokenLabel)
                        // 分支要在列表里就能看出来，不能点进去才知道
                        if (item.isBranch) append(" · 分支")
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                )
            }
            Box {
                IconButton(onClick = { menu = true }, modifier = Modifier.size(TapTarget)) {
                    Icon(
                        Icons.Default.MoreVert,
                        contentDescription = "更多操作",
                        modifier = Modifier.size(20.dp),
                    )
                }
                DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                    DropdownMenuItem(
                        text = { Text("复制全文") },
                        leadingIcon = { Icon(Icons.Default.ContentCopy, contentDescription = null) },
                        onClick = {
                            menu = false
                            onCopy()
                        },
                    )
                    DropdownMenuItem(
                        text = { Text("复制成新对话") },
                        leadingIcon = { Icon(Icons.AutoMirrored.Filled.CallSplit, contentDescription = null) },
                        onClick = {
                            menu = false
                            onDuplicate()
                        },
                    )
                    DropdownMenuItem(
                        text = { Text("删除") },
                        leadingIcon = { Icon(Icons.Default.Delete, contentDescription = null) },
                        onClick = {
                            menu = false
                            onDelete()
                        },
                    )
                }
            }
        }
    }
}

/**
 * 「这是一段分支」的标记。
 *
 * 用**横杠**（两侧粗线 + 中间「分支」二字）而不是一行小字提示：
 * 分支最容易引起的误会是"我上面的消息怎么没了/这段是不是原对话"，
 * 所以标记必须**一眼扫到**。光靠一行灰色小字，用户滑到中间时根本不会注意到头顶那行字。
 *
 * 颜色用中性 outline 灰，不用 AI 语义色（那是"功能标识"的颜色，这里是"分隔/状态"）。
 */
@Composable
private fun BranchBar() {
    Column(Modifier.fillMaxWidth()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            HorizontalDivider(
                modifier = Modifier.weight(1f),
                thickness = 3.dp,
                color = MaterialTheme.colorScheme.outline,
            )
            Text(
                "分支",
                fontSize = TraceTextSize,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onSurface,
                modifier = Modifier.padding(horizontal = 10.dp),
            )
            HorizontalDivider(
                modifier = Modifier.weight(1f),
                thickness = 3.dp,
                color = MaterialTheme.colorScheme.outline,
            )
        }
        Spacer(Modifier.height(4.dp))
        Text(
            "这段对话是从历史里分叉出来的，原对话仍在「历史」里",
            fontSize = TraceTextSize,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.fillMaxWidth(),
            textAlign = TextAlign.Center,
        )
    }
}

// ==================== 单条消息 ====================

/**
 * 一条消息。
 *
 * **长按气泡**可以「复制这条」或「从这里分叉」——这是主流 AI 软件的做法：
 * 复制和分叉都是针对**具体某一轮**的，放在顶栏或抽屉里就指向不明了。
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun MessageRow(
    m: UiMessage,
    index: Int,
    sending: Boolean,
    onCopy: (Int) -> Unit,
    onBranch: (Int) -> Unit,
    onEdit: (Int) -> Unit,
    onUndo: (String) -> Unit,
) {
    val isUser = m.role == Role.USER
    var menu by remember { mutableStateOf(false) }
    Box(Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier
                .fillMaxWidth(0.88f)
                .align(if (isUser) Alignment.CenterEnd else Alignment.CenterStart)
                .combinedClickable(onClick = {}, onLongClick = { menu = true }),
            horizontalAlignment = if (isUser) Alignment.End else Alignment.Start,
        ) {
            // 工具痕迹：系统在查数据，不是聊天内容 → 通栏浅灰底 + 细色条，不做成气泡
            if (m.toolTrace.isNotEmpty()) {
                ToolTraceStrip(m.toolTrace)
                if (m.text.isNotBlank() || sending) Spacer(Modifier.height(6.dp))
            }

            // 思考过程：默认折叠。它是过程不是结论，摊开会把答案淹掉；
            // 但排障时（"它为什么查这个数"）必须能展开看。
            if (!isUser && m.reasoning.isNotBlank()) {
                ReasoningSection(m.reasoning)
                Spacer(Modifier.height(6.dp))
            }

            val bubbleColor = when {
                m.isError -> MaterialTheme.colorScheme.errorContainer
                isUser -> MaterialTheme.colorScheme.primary
                else -> MaterialTheme.colorScheme.surfaceVariant
            }
            val bubbleText = when {
                m.isError -> MaterialTheme.colorScheme.onErrorContainer
                isUser -> Color.White
                else -> MaterialTheme.colorScheme.onSurfaceVariant
            }
            val thinking = m.text.isBlank() && sending

            // 这条用户消息挂着的文件：先在气泡**上方**列出文件名与规模。
            // 为什么不做进气泡里：附件是"这条消息带了什么"，不是"用户说了什么"——
            // 混在一起会让用户以为自己打过那串文件名。
            if (m.attachments.isNotEmpty()) {
                m.attachments.forEach { a ->
                    Surface(
                        shape = RoundedCornerShape(10.dp),
                        color = MaterialTheme.colorScheme.surfaceContainerHigh,
                    ) {
                        Row(
                            Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Icon(
                                Icons.Default.Description,
                                contentDescription = null,
                                tint = AiAccent,
                                modifier = Modifier.size(15.dp),
                            )
                            Spacer(Modifier.width(6.dp))
                            Text(
                                a.filename + " · " + a.summary,
                                fontSize = 12.sp,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.widthIn(max = 240.dp),
                            )
                        }
                    }
                    Spacer(Modifier.height(4.dp))
                }
            }

            if (m.text.isNotBlank() || thinking) {
                Surface(shape = RoundedCornerShape(16.dp), color = bubbleColor, contentColor = bubbleText) {
                    Box(Modifier.padding(horizontal = 14.dp, vertical = 10.dp)) {
                        if (thinking) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                CircularProgressIndicator(
                                    modifier = Modifier.size(16.dp),
                                    strokeWidth = 2.dp,
                                    color = bubbleText,
                                )
                                Spacer(Modifier.width(8.dp))
                                Text("正在思考…", fontSize = MessageTextSize, color = bubbleText)
                            }
                        } else if (m.isError) {
                            // 错误是系统提示，不是模型输出，不做 Markdown 渲染（免得把报错里的符号也解析了）
                            Text(
                                text = "⚠ " + m.text,
                                fontSize = MessageTextSize,
                                lineHeight = 26.sp,
                                color = bubbleText,
                            )
                        } else {
                            // 模型答复走富文本：表格画成真表格、**粗体** 真加粗（原来纯文本时表格是一堆竖线，看不清）
                            AiRichText(
                                text = m.text,
                                fontSize = MessageTextSize,
                                lineHeight = 26.sp,
                                color = bubbleText,
                            )
                        }
                    }
                }
            }

            // 时间 / 用量 / 复制 / 分支：一排放在气泡下方。
            // 复制和分支**做成看得见的图标按钮**，不再只藏在长按菜单里——长按是"知道有这功能才找得到"，
            // 而这两个动作是天天要用的。图标用中性色（onSurfaceVariant），不用 AI 语义色：
            // 这一排是"操作"，跟"这是 AI 功能"是两件事，上色反而会让整屏都是粉的。
            //
            // 撤回按钮排在**最前面**（v3.26）：它是这一排里唯一"有时效"的东西
            // （30 分钟后点了也撤不回来），所以不能让它排在最后被忽略。
            if (m.undoToken != null && !isUser) {
                Spacer(Modifier.height(6.dp))
                Surface(
                    onClick = { onUndo(m.undoToken) },
                    shape = RoundedCornerShape(10.dp),
                    color = MaterialTheme.colorScheme.secondaryContainer,
                    contentColor = MaterialTheme.colorScheme.onSecondaryContainer,
                ) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                    ) {
                        Icon(Icons.Default.Undo, contentDescription = null, modifier = Modifier.size(16.dp))
                        Spacer(Modifier.width(6.dp))
                        Text(
                            m.undoLabel ?: "撤回这一步",
                            fontSize = MessageTextSize,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                }
            }

            if (m.text.isNotBlank()) {
                Spacer(Modifier.height(2.dp))
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(2.dp),
                ) {
                    val meta = if (isUser) {
                        AiConversations.clockLabel(m.at)
                    } else {
                        buildString {
                            append(AiConversations.clockLabel(m.at))
                            if (m.tokens > 0) {
                                if (isNotEmpty()) append(" · ")
                                append("本次 ").append(AiConversations.tokenLabel(m.tokens))
                            }
                        }
                    }
                    if (meta.isNotBlank()) {
                        // 时间/用量是**最不重要**的一行：它只是"这条什么时候来的、花了多少"，
                        // 用户真正的目的是读内容。所以用最小的字号 + 最淡的颜色（outline），
                        // 让它"在，但不抢眼"——这就是用户说的"不重要的信息稍微退一点"。
                        Text(
                            meta,
                            fontSize = MetaTextSize,
                            color = MaterialTheme.colorScheme.outline,
                        )
                        Spacer(Modifier.width(4.dp))
                    }
                    MessageAction("复制", Icons.Default.ContentCopy) { onCopy(index) }
                    if (isUser) {
                        // 用户消息给的是**编辑**而不是「重问」。
                        // 原话：「不要有重问这个选项，因为再充一遍也没有意义，应该改成编辑——
                        // 我这条消息发错了搞错了，可以编辑然后点重新发送，他就会撤回上面那个回答，
                        // 然后就像重新搞一遍一样。」所以这里就是"改写历史"的入口。
                        MessageAction("编辑", Icons.Default.Edit) { onEdit(index) }
                    } else {
                        MessageAction("分支", Icons.AutoMirrored.Filled.CallSplit) { onBranch(index) }
                    }
                }
            }
        }

        DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
            DropdownMenuItem(
                text = { Text("复制这条") },
                leadingIcon = { Icon(Icons.Default.ContentCopy, contentDescription = null) },
                enabled = m.text.isNotBlank(),
                onClick = {
                    menu = false
                    onCopy(index)
                },
            )
            if (isUser) {
                DropdownMenuItem(
                    text = { Text("编辑这条（重新发送）") },
                    leadingIcon = { Icon(Icons.Default.Edit, contentDescription = null) },
                    onClick = {
                        menu = false
                        onEdit(index)
                    },
                )
            } else {
                DropdownMenuItem(
                    text = { Text("从这里分叉") },
                    leadingIcon = { Icon(Icons.AutoMirrored.Filled.CallSplit, contentDescription = null) },
                    onClick = {
                        menu = false
                        onBranch(index)
                    },
                )
            }
        }
    }
}

/**
 * 气泡下方的一个小动作（复制 / 分支）。
 *
 * 图标 + 文字都要：**图标让人一眼认出（用户明确要求"要有对应的图标"），文字让不熟悉图标的人也能用**
 * ——这个 App 面向的是不太玩手机的调度员，只给图标等于没给。
 * 颜色刻意用中性色，不用 AI 语义色：这一排是"对这条消息做什么"，不是"这是 AI 功能"。
 */
@Composable
private fun MessageAction(label: String, icon: ImageVector, onClick: () -> Unit) {
    TextButton(
        onClick = onClick,
        contentPadding = PaddingValues(horizontal = 8.dp, vertical = 0.dp),
        modifier = Modifier.heightIn(min = 40.dp, max = 40.dp),
        colors = ButtonDefaults.textButtonColors(
            // 颜色再退一档（outline 而不是 onSurfaceVariant）：这一排是**次要操作**，
            // 和正文比权重，用户先读到的是答案。字号/图标尺寸保持不变——它们仍然要看得清、点得着。
            contentColor = MaterialTheme.colorScheme.outline,
        ),
    ) {
        Icon(icon, contentDescription = null, modifier = Modifier.size(17.dp))
        Spacer(Modifier.width(4.dp))
        Text(label, fontSize = TraceTextSize)
    }
}

/**
 * 编辑态提示条：告诉用户"这条是改过的、按发送会把原来的回答撤掉"。
 *
 * 为什么必须显眼：编辑的语义是**改写历史**（撤掉这条及其之后的全部内容再重跑）。
 * 不提前说清，用户点完发送看到回答消失，只会以为出了 bug。
 */
@Composable
private fun EditingBanner(onCancel: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(AiAccent.copy(alpha = 0.10f))
            .padding(start = 16.dp, end = 8.dp, top = 4.dp, bottom = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(Icons.Default.Edit, contentDescription = null, tint = AiAccent, modifier = Modifier.size(16.dp))
        Spacer(Modifier.width(6.dp))
        Text(
            "正在编辑这条消息：发送后会重新回答，这条之后的对话会被撤掉",
            fontSize = 12.5.sp,
            color = MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.weight(1f),
        )
        TextButton(onClick = onCancel, contentPadding = PaddingValues(horizontal = 8.dp)) {
            Text("取消", fontSize = 14.sp)
        }
    }
}

/** 工具痕迹条：一行一条小字，浅灰底 + 左侧细色条，一眼看出"这是系统在查数据" */@Composable
private fun ToolTraceStrip(lines: List<String>) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(MaterialTheme.colorScheme.surfaceContainer)
            .padding(horizontal = 10.dp, vertical = 6.dp),
    ) {
        lines.forEach { line ->
            Row(
                modifier = Modifier.padding(vertical = 2.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(Modifier.size(width = 3.dp, height = 16.dp).background(AiAccent, RoundedCornerShape(2.dp)))
                Spacer(Modifier.width(8.dp))
                Text(
                    text = line,
                    fontSize = TraceTextSize,
                    lineHeight = 20.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

// ==================== 思考过程（可折叠） ====================

/**
 * 模型的思考过程。
 *
 * 设计取舍：
 * - **默认折叠**：思考过程往往比答案长好几倍，摊开会把答案挤下去；但它必须**可见可达**，
 *   否则用户无法判断"它是不是理解错了才去查那个数"。
 * - 用虚线感的浅色块 + 灰字，和"工具痕迹"一样属于**过程区**，与答案气泡区分开。
 */
@Composable
private fun ReasoningSection(reasoning: String) {
    var expanded by remember { mutableStateOf(false) }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(MaterialTheme.colorScheme.surfaceContainerLow)
            .clickable { expanded = !expanded }
            .padding(horizontal = 10.dp, vertical = 7.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                if (expanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(16.dp),
            )
            Spacer(Modifier.width(6.dp))
            Text(
                text = if (expanded) "收起思考过程" else "查看思考过程",
                fontSize = TraceTextSize,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        if (expanded) {
            Spacer(Modifier.height(6.dp))
            Text(
                text = reasoning,
                fontSize = TraceTextSize,
                lineHeight = 20.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

// ==================== 空状态引导 ====================

@Composable
private fun EmptyGuide(questions: List<String>, isDispatcher: Boolean, onPick: (String) -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 8.dp, vertical = 16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        // 星标 = Google AI 的做法：**渐变圆角块 + 白色四角星**（不是一根单色线条图标）。
        // 这是整页最像"AI"的一处，也顺手把"这个助手是 Google 那套观感"定住了。
        Box(
            modifier = Modifier
                .size(64.dp)
                .background(aiBrandBrush(), RoundedCornerShape(18.dp)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                Icons.Default.AutoAwesome,
                contentDescription = null,
                tint = Color.White,
                modifier = Modifier.size(34.dp),
            )
        }
        Spacer(Modifier.height(12.dp))
        // 标题与示例都按角色给：空状态是第一印象，写错等于说"这东西不是给你的"。
        // 货主端原先是"我是你的助手"——太虚，等于没说清它是谁的助手；改成"我是货主助手"
        // 与派单端的"我是派单助手"对称（用户 2026-09-15 指出标签要改）。
        Text(if (isDispatcher) "我是派单助手" else "我是货主助手", style = MaterialTheme.typography.titleLarge)
        Spacer(Modifier.height(6.dp))
        Text(
            if (isDispatcher) {
                "用大白话问我：某个数是多少、谁跑得最多、哪些货要补、账单导成表格。\n点下面的问题可以直接试。"
            } else {
                "用大白话跟我说要做什么：下单、加地址、记常用联系人、查订单和账本。\n" +
                    "要动数据的事我都会先给你一张确认卡，你点了才会生效。\n点下面的问题可以直接试。"
            },
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(10.dp))
        Text(
            "左上角「历史」里能看到以前问过的对话",
            style = MaterialTheme.typography.bodyMedium,
            color = AiAccent,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(18.dp))
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            questions.forEach { q ->
                Surface(
                    onClick = { onPick(q) },
                    modifier = Modifier.fillMaxWidth().heightIn(min = TapTarget),
                    shape = RoundedCornerShape(14.dp),
                    color = MaterialTheme.colorScheme.surface,
                    shadowElevation = 1.dp,
                ) {
                    Row(
                        modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            q,
                            style = MaterialTheme.typography.bodyLarge,
                            modifier = Modifier.weight(1f),
                        )
                        Spacer(Modifier.width(8.dp))
                        Icon(
                            Icons.Default.NorthEast,
                            contentDescription = null,
                            tint = AiAccent,
                            modifier = Modifier.size(18.dp),
                        )
                    }
                }
            }
        }
    }
}

// ==================== 未配置 key ====================

@Composable
private fun NotConfiguredCard(onOpenSettings: () -> Unit, onRecheck: () -> Unit) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = MaterialTheme.shapes.medium,
        color = MaterialTheme.colorScheme.surface,
        shadowElevation = 1.dp,
    ) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Default.Key, contentDescription = null, tint = AiAccent, modifier = Modifier.size(22.dp))
                Spacer(Modifier.width(8.dp))
                Text("还没配置模型 API Key", style = MaterialTheme.typography.titleMedium)
            }
            Spacer(Modifier.height(8.dp))
            Text(
                "填好模型地址、Key 和模型名就能开始提问。Key 只保存在这台手机上，不会上传到服务器。",
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(14.dp))
            Button(
                onClick = onOpenSettings,
                modifier = Modifier.fillMaxWidth().heightIn(min = TapTarget),
                colors = ButtonDefaults.buttonColors(
                    containerColor = AiAccent,
                    contentColor = Color.White,
                ),
            ) {
                Icon(Icons.Default.Settings, contentDescription = null, modifier = Modifier.size(20.dp))
                Spacer(Modifier.width(8.dp))
                Text("去设置", fontSize = 17.sp)
            }
            TextButton(
                onClick = onRecheck,
                modifier = Modifier.fillMaxWidth().heightIn(min = 44.dp),
            ) {
                Text("我已配置好，重新检查", fontSize = 16.sp)
            }
        }
    }
}

// ==================== 底部输入区 ====================

/**
 * 输入区。
 *
 * 两处按用户要求改的：
 * 1. **发送键垂直居中**（原来贴底对齐，输入框长到三四行时按钮会跟着掉下去）；
 * 2. **箭头朝上**（`ArrowUpward` 而不是纸飞机）——向上＝"送进上面的聊天记录"，
 *    这比纸飞机更直白：纸飞机容易被理解成"发到别的地方去"。
 */
/**
 * 「AI 申请改数据」的确认卡（可能同时挂多张，正常只有一张）。
 *
 * ### 为什么它钉在输入框正上方，而不是混进消息流里
 * 用户读完 AI 的回答之后，视线落在输入框那一带。卡片如果飘在长对话中间，
 * 会被"再问一句"的冲动直接划过——而卡片超时就没了，用户还以为 AI 已经把事办了。
 * 钉在输入框上方，是"发下一条消息之前必然会看到"的位置。
 */
@Composable
private fun WriteConfirmCard(
    pending: List<AiPendingWrite>,
    busyToken: String?,
    onConfirm: (String) -> Unit,
    onCancel: (String) -> Unit,
) {
    if (pending.isEmpty()) return
    Column(
        Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        pending.forEach { p ->
            WriteCard(
                p = p,
                busy = busyToken == p.token,
                // 有一个在执行时，把所有卡的按钮都禁掉：连点两张卡会连着写两笔，
                // 而用户当时多半以为"我只点了同一个东西两下"。
                anyBusy = busyToken != null,
                onConfirm = onConfirm,
                onCancel = onCancel,
            )
        }
    }
}

@Composable
private fun WriteCard(
    p: AiPendingWrite,
    busy: Boolean,
    anyBusy: Boolean,
    onConfirm: (String) -> Unit,
    onCancel: (String) -> Unit,
) {
    // 档位只影响**视觉重量**，不影响要不要确认——需要确认这件事由 [AiWriteRisk.needsConfirm]
    // 在数据层定死，界面改不了它。低风险动作根本不会走到这里（它们直接执行完了）。
    val high = p.risk == AiWriteRisk.HIGH
    val accent = if (high) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.tertiary

    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(14.dp),
        color = MaterialTheme.colorScheme.surface,
        border = BorderStroke(1.5.dp, accent),
        shadowElevation = 6.dp,
    ) {
        Column(Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Surface(color = accent, shape = RoundedCornerShape(6.dp)) {
                    Text(
                        p.risk.label + "风险",
                        color = Color.White,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
                    )
                }
                Spacer(Modifier.width(8.dp))
                Text(
                    p.title,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
            }

            Spacer(Modifier.height(8.dp))
            // 摘要用正文大小 + 中等字重：它是用户唯一真正要读的一行。
            Text(p.summary, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.Medium)
            Spacer(Modifier.height(4.dp))
            // ⚠️ 明细必须**封顶 + 内部滚动**。
            // 批量调价那种卡片能列出十几行改动，不封顶的话整张卡会长到把「确认/取消」
            // 挤出屏幕——**用户根本点不到确认**，而界面上看不出是为什么（他只会觉得"卡住了"）。
            // 实测踩过：16 行的批量调价卡，按钮直接落在屏幕外。
            Column(
                Modifier
                    .fillMaxWidth()
                    .heightIn(max = DetailMaxHeight)
                    .verticalScroll(rememberScrollState()),
            ) {
                p.detailLines.forEach { line ->
                    Text(
                        line,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }

            Spacer(Modifier.height(8.dp))
            // ⚠️ 这里是普通 Text()，不解析 Markdown：写 `**申请**` 只会显示成星号
            // （v3.7 真机实测踩过）。要突出就用「」。
            Text(
                "${p.risk.blurb}。AI 只是「申请」；写进系统要你点下面的按钮。",
                fontSize = 11.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                "${AiWritePreviewStore.DEFAULT_TTL_MS / 60000} 分钟内有效，过期后重新说一次就行。",
                fontSize = 11.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            Spacer(Modifier.height(10.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                OutlinedButton(
                    onClick = { onCancel(p.token) },
                    enabled = !anyBusy,
                    modifier = Modifier.weight(1f),
                ) { Text("取消") }
                Spacer(Modifier.width(10.dp))
                Button(
                    onClick = { onConfirm(p.token) },
                    enabled = !anyBusy,
                    modifier = Modifier.weight(1.4f),
                    colors = ButtonDefaults.buttonColors(containerColor = accent),
                ) {
                    if (busy) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(16.dp),
                            strokeWidth = 2.dp,
                            color = Color.White,
                        )
                    } else {
                        // 按钮上写**动作本身**而不是「确定」：用户点第十次「确定」时就不再读卡片了，
                        // 而「确认：记一笔支出」这句话他每次都得看一眼。
                        Text(
                            "确认：" + p.title,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun InputBar(
    value: String,
    onValueChange: (String) -> Unit,
    sending: Boolean,
    hint: String,
    onSend: () -> Unit,
    onStop: () -> Unit,
    /** 展开/收起下面的附件面板。 */
    onTogglePanel: () -> Unit,
    /** 面板当前是不是展开的（决定 ⊕ 转不转成 ×）。 */
    panelOpen: Boolean,
    /** 正在上传解析那个文件（不是发送中）。 */
    attaching: Boolean,
    /** 能不能发（有字或有附件）。没字也没附件时发送键是灰的——空消息不该发得出去。 */
    canSend: Boolean,
) {
    // ⚠️ 这里原来自己起了一个 `Surface(shadowElevation = 8.dp)`（白底 + 阴影）。
    // 白底与阴影现在统一由 bottomBar 那张**圆角**卡片出——两层各画各的，
    // 外面圆、里面方，圆角等于白做。
    Row(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 8.dp),
        // 居中：输入框多行时按钮留在视觉中线上，不会滑到底部
        verticalAlignment = Alignment.CenterVertically,
    ) {
            // ⚠️ 这里原来挤着**两个**图标（相册 + 文件）再跟一个输入框，用户评价是
            //    「非常的难看，也不合理」。现在左边只留一个 ⊕：常态下这一行只干两件事
            //    ——打字、发出去；附件是"要的时候才展开"的东西（展开后是下面那个面板）。
            IconButton(onClick = onTogglePanel, enabled = !sending) {
                Icon(
                    if (panelOpen) Icons.Default.Close else Icons.Default.Add,
                    contentDescription = if (panelOpen) "收起附件面板" else "添加附件（照片 / 文件）",
                    tint = if (sending) MaterialTheme.colorScheme.outline else AiAccent,
                )
            }
            // 输入框用**填充式圆角容器**而不是 OutlinedTextField 的描边框：
            // 用户拿参照 App 比过之后说原来的输入区「非常的难看」——描边框在浅色底上像一张表单，
            // 聊天框该是"一个软软的、能装字的块"（参照里的输入区就是填充 + 大圆角）。
            TextField(
                value = value,
                onValueChange = onValueChange,
                modifier = Modifier.weight(1f),
                placeholder = { Text(if (attaching) "正在读文件…" else hint, fontSize = 15.sp) },
                textStyle = MaterialTheme.typography.bodyLarge,
                maxLines = 4,
                shape = RoundedCornerShape(24.dp),
                colors = TextFieldDefaults.colors(
                    // 去掉聚焦/未聚焦那两条指示线——它们是"表单"的语言，不是"聊天框"的
                    focusedIndicatorColor = Color.Transparent,
                    unfocusedIndicatorColor = Color.Transparent,
                    disabledIndicatorColor = Color.Transparent,
                    focusedContainerColor = MaterialTheme.colorScheme.surfaceVariant,
                    unfocusedContainerColor = MaterialTheme.colorScheme.surfaceVariant,
                ),
            )
            Spacer(Modifier.width(8.dp))
            // 发送中 → 变成停止键（停止是"危险动作"，仍用单色红，不跟 AI 渐变混）
            Surface(
                onClick = { if (sending) onStop() else if (canSend) onSend() },
                modifier = Modifier.size(52.dp),
                shape = CircleShape,
                color = Color.Transparent,
            ) {
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .background(
                            brush = when {
                                sending -> SolidColor(MaterialTheme.colorScheme.error)
                                // 用户 2026-09-18：「发送键改成蓝色的，灰色的话不是很明显、很不容易看清。」
                                // 原来空格子用的是 `surfaceVariant`（浅灰），在浅色底上和背景几乎同色，
                                // 一眼看不出那里有个按钮。
                                //
                                // 改法：**始终是蓝的**，只用深浅区分两态——
                                //   空格子 = 淡蓝（看得见"这儿有个发送键"，但仍看得出"还没东西可发"）
                                //   有内容 = 品牌蓝
                                // 不敢两边都用实心深蓝：那会让"可发/不可发"彻底消失，
                                // 用户点了没反应比看不清更困惑（这条是原来那行注释里的顾虑，依然成立）。
                                !canSend -> SolidColor(AiAccent.copy(alpha = 0.45f))
                                else -> SolidColor(AiAccent)
                            },
                            shape = CircleShape,
                        ),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        imageVector = if (sending) Icons.Default.Stop else Icons.Default.ArrowUpward,
                        contentDescription = if (sending) "停止" else "发送",
                        tint = if (!sending && !canSend) MaterialTheme.colorScheme.outline else Color.White,
                        modifier = Modifier.size(26.dp),
                    )
                }
            }
        }
}

/**
 * 附件面板：**最近的照片横着排一行**，下面是「拍照 / 相册 / 文件」三个大按钮。 *
 * ### 为什么是这个形状（用户口径 2026-09-17）
 * 用户拿别的 App 的输入区做参照，原话是：「中间那些图片全是相册的图片已经列出来了，
 * 然后在下面再是下面 3 个，我们就又可观又简洁。」
 * 关键差别是**先看见、再选**：以前必须点「相册」→ 等系统选择器 → 在一堆图里找刚才那张；
 * 现在刚拍的那张就在第一格。
 *
 * ### 三条不能丢的性质
 * 1. **没有相册权限时功能一个都不少**：这一排照片空着，三个按钮照常能干活
 *    （「相册」走的是系统照片选择器，本来就不需要权限）。所以这里只提示一句，不催权限。
 * 2. **勾选状态来自真实附件列表**（`picked`），不是界面自己记的——见调用处的注释。
 * 3. 三个按钮**等宽等高**、图标在上文字在下：手指不用瞄准，也不会因为文字长短歪掉。
 */
@Composable
private fun AttachPanel(
    photos: List<Uri>,
    hasPhotoAccess: Boolean,
    canAttachMore: Boolean,
    picked: Set<String>,
    attaching: Boolean,
    sending: Boolean,
    onTogglePhoto: (Uri) -> Unit,
    onCamera: () -> Unit,
    onAlbum: () -> Unit,
    onFile: () -> Unit,
) {
    // 白底由 bottomBar 那张圆角卡片统一出（这里再画一层会把圆角盖成直角）
    Column(
        modifier = Modifier.fillMaxWidth().padding(start = 12.dp, end = 12.dp, bottom = 12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
            when {
                !hasPhotoAccess -> Text(
                    "允许访问相册后，这里会直接列出最近拍的照片，点一下就挂上。下面的三个入口不受影响。",
                    fontSize = 12.sp,
                    color = MaterialTheme.colorScheme.outline,
                )
                photos.isEmpty() -> Text(
                    "相册里没有读到照片。可以直接拍照，或者点「相册」自己挑。",
                    fontSize = 12.sp,
                    color = MaterialTheme.colorScheme.outline,
                )
                else -> LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(photos, key = { it.toString() }) { uri ->
                        PhotoThumb(
                            uri = uri,
                            selected = uri.toString() in picked,
                            enabled = canAttachMore || uri.toString() in picked,
                            onClick = { onTogglePhoto(uri) },
                        )
                    }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                PanelButton("拍照", Icons.Default.PhotoCamera, enabled = !attaching && !sending, onClick = onCamera)
                PanelButton("相册", Icons.Default.PhotoLibrary, enabled = !attaching && !sending, onClick = onAlbum)
                PanelButton(
                    if (attaching) "读取中…" else "文件",
                    Icons.Default.AttachFile,
                    enabled = !attaching && !sending,
                    onClick = onFile,
                )
            }
        }
}

/** 一张照片：选中时压深 + 右上角打勾；挂满时没选中的那张变灰（能看懂"点不动了"）。 */
@Composable
private fun PhotoThumb(uri: Uri, selected: Boolean, enabled: Boolean, onClick: () -> Unit) {
    Box(modifier = Modifier.size(76.dp)) {
        AsyncImage(
            model = uri,
            contentDescription = if (selected) "已选中" else "相册照片",
            contentScale = ContentScale.Crop,
            modifier = Modifier
                .fillMaxSize()
                .clip(RoundedCornerShape(12.dp))
                .border(
                    width = if (selected) 2.dp else 0.dp,
                    color = if (selected) AiAccent else Color.Transparent,
                    shape = RoundedCornerShape(12.dp),
                )
                .clickable(enabled = enabled, onClick = onClick),
        )
        if (!enabled) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .clip(RoundedCornerShape(12.dp))
                    .background(Color.Black.copy(alpha = 0.45f)),
            )
        }
        // 右上角那个圈：选中 = 实心打勾，没选中 = 空圈（和用户给的那张参照一致）
        Box(
            modifier = Modifier
                .align(Alignment.TopEnd)
                .padding(4.dp)
                .size(20.dp)
                .background(
                    color = if (selected) AiAccent else Color.Black.copy(alpha = 0.35f),
                    shape = CircleShape,
                )
                .border(1.5.dp, Color.White, CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            if (selected) {
                Icon(Icons.Default.Check, contentDescription = null, tint = Color.White, modifier = Modifier.size(14.dp))
            }
        }
    }
}

/** 面板里的大按钮：图标在上、文字在下，三个等宽。 */
@Composable
private fun RowScope.PanelButton(
    label: String,
    icon: ImageVector,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    Surface(
        onClick = onClick,
        enabled = enabled,
        modifier = Modifier.weight(1f).height(64.dp),
        shape = RoundedCornerShape(16.dp),
        color = MaterialTheme.colorScheme.surfaceVariant,
    ) {
        Column(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Icon(
                icon,
                contentDescription = null,
                tint = if (enabled) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.outline,
                modifier = Modifier.size(22.dp),
            )
            Spacer(Modifier.height(4.dp))
            Text(
                label,
                fontSize = 13.sp,
                color = if (enabled) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.outline,
            )
        }
    }
}

/**
 * 写剪贴板。
 *
 * 用系统 `ClipboardManager` 而不是 Compose 的 `LocalClipboardManager`：
 * 后者在 Android 13+ 之后已经被标记为"只在 Compose 内部用"，跨版本行为不一致；
 * 而这里要的行为很明确——把纯文本放进系统剪贴板，让用户能粘到微信里。
 */
private fun copyToClipboard(context: Context, label: String, text: String) {
    val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager ?: return
    cm.setPrimaryClip(ClipData.newPlainText(label, text))
}
