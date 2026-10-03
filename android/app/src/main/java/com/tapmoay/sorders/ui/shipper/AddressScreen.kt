package com.tapmoay.sorders.ui.shipper

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
import androidx.compose.ui.text.style.TextOverflow
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
import com.tapmoay.sorders.ui.theme.DestOrange
import com.tapmoay.sorders.ui.theme.MgrGreen
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.ui.theme.OriginTeal
import com.tapmoay.sorders.ui.theme.ShipperTeal
import com.tapmoay.sorders.ui.dispatcher.ContactCategoriesPanel
import com.tapmoay.sorders.ui.dispatcher.ContactCategoriesViewModel
import com.tapmoay.sorders.ui.dispatcher.PlaceCategoriesPanel
import com.tapmoay.sorders.ui.dispatcher.PlaceCategoriesViewModel
import com.tapmoay.sorders.ui.dispatcher.RouteCategoriesPanel
import com.tapmoay.sorders.ui.dispatcher.RouteCategoriesViewModel
import android.graphics.Bitmap
import com.tapmoay.sorders.ui.common.Hint

/**
 * 顶部三档的标签与语义色：与「地址与联系人」这一页的三个概念一一对应
 * （路线 = 起点那族的蓝青、联系人 = 人 / 本页模块色的湖蓝、地址 = 橙；色值走 `ui/theme/Color.kt` 的命名 token，⛔ 不写裸色值）。
 * 交给共用件 `SegmentedStatusTabs` 去画 —— 它自己负责"放不下就整条滑动"那条契约。
 */
private val ADDRESS_TABS = listOf("路线", "联系人", "地址")
private val ADDRESS_TAB_COLORS = listOf(Color(OriginTeal), Color(ShipperTeal), Color(MoneyOrange))

/** 抽屉选中格 → 分类名：`""` = 全部、`"c|分类名"` = 某一类（三档共用同一套 key 约定，见 `AddressViewModel`）。 */
private fun railCategoryName(key: String): String =
    if (key.startsWith("c|")) key.removePrefix("c|") else ""
/** 地址与联系人：三个列表（常用线路=联系人+地点 → 联系人 → 地点），新增入口在各自标题行右侧 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AddressScreen(
    container: AppContainer,
    onBack: () -> Unit,
) {
    val vm: AddressViewModel = appViewModel { AddressViewModel(container) }
    var startLocMenu by remember { mutableStateOf(false) }
    var endLocMenu by remember { mutableStateOf(false) }
    var imageTarget by remember { mutableStateOf("loc") }
    var showImageSource by remember { mutableStateOf(false) }
    var tab by remember { mutableStateOf(0) }  // 0=路线 1=联系人 2=地址
    // 搜索词：三段共用（换段时清空 —— 在"联系人"里搜的名字带到"地点"段只会得到空列表）
    var keyword by remember { mutableStateOf("") }
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    // ---- 分类：三个页签共用同一个**左侧抽屉**（`ModalNavigationDrawer`）----
    // 形态照「账本管理」，⛔ 不是商品管理那种常驻左栏：用户原话「商品管理的话，那样子的界面
    // 导致了右边的卡片的信息被挤压了不是很好看」。
    val drawer = rememberDrawerState(DrawerValue.Closed)
    /** 分类管理面板（同屏第二层）：抽屉里点「管理分类」就换成它；返回时回读名册。 */
    var managingCategory by remember { mutableStateOf(false) }
    // 抽屉里的那一列：一趟「全部」+ 每个分类。三档共用同一套 key 约定
    // （`""` = 全部 / `"c|分类名"` = 某一类），与 `AddressViewModel` 的 `*RailKey` 一一对应。
    // ⛔ 一格都不显示条数 —— 用户 2026-09-19 的裁定：「那个分组下面不要显示有多少条啊，这是多余信息」。
    val routeDrawerItems = remember(vm.routeCategories) {
        listOf(CategoryDrawerItem("", "全部")) + vm.routeCategories.map { CategoryDrawerItem("c|" + it.name, it.name) }
    }
    val contactDrawerItems = remember(vm.contactCategories) {
        listOf(CategoryDrawerItem("", "全部")) + vm.contactCategories.map { CategoryDrawerItem("c|" + it.name, it.name) }
    }
    val placeDrawerItems = remember(vm.placeCategories) {
        listOf(CategoryDrawerItem("", "全部")) + vm.placeCategories.map { CategoryDrawerItem("c|" + it.name, it.name) }
    }

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

    ModalNavigationDrawer(
        drawerState = drawer,
        drawerContent = {
            ModalDrawerSheet(modifier = Modifier.width(CategoryDrawerWidth)) {
                // 抽屉里那一列随页签换（三档各有一份自己那份名册），但**形态与 key 约定完全一样**。
                CategoryDrawerSheet(
                    title = when (tab) {
                        1 -> "联系人分类"
                        2 -> "地点分类"
                        else -> "线路分类"
                    },
                    items = when (tab) {
                        1 -> contactDrawerItems
                        2 -> placeDrawerItems
                        else -> routeDrawerItems
                    },
                    selectedKey = when (tab) {
                        1 -> vm.contactRailKey
                        2 -> vm.locRailKey
                        else -> vm.routeRailKey
                    },
                    accent = ADDRESS_TAB_COLORS[tab],
                    manageLabel = "管理分类",
                    onPick = { key ->
                        when (tab) {
                            1 -> vm.contactRailKey = key
                            2 -> vm.locRailKey = key
                            else -> vm.routeRailKey = key
                        }
                        scope.launch { drawer.close() }
                    },
                    onManage = {
                        managingCategory = true
                        scope.launch { drawer.close() }
                    },
                )
            }
        },
    ) {
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
            // 分类管理（同屏第二层）：抽屉里点「管理分类」就换成它 —— 用户要的是"同一个抽屉里的第二层"，
            // 不是再弹一个界面（也塞不进 360dp 宽的抽屉里）。
            // 返回时回读名册：用户可能在面板里改名 / 删掉一整类，抽屉里那一格得跟着变。
            if (managingCategory) {
                Box(Modifier.fillMaxSize().padding(padding)) {
                    CategoryManagePanel(
                        container = container,
                        tab = tab,
                        onBack = {
                            managingCategory = false
                            when (tab) {
                                1 -> vm.reloadContactCategories()
                                2 -> vm.reloadPlaceCategories()
                                else -> vm.reloadRouteCategories()
                            }
                        },
                    )
                }
            } else {
                Column(Modifier.fillMaxSize().padding(padding)) {
                    // 顶部三档走全 App 唯一那份 `SegmentedStatusTabs`（§3 组件速查）。
                    // ⛔ 别再退回自己画的描边胶囊：导航形态在每一页必须一样，用户才不会每次重新认。
                    SegmentedStatusTabs(
                        labels = ADDRESS_TABS,
                        colors = ADDRESS_TAB_COLORS,
                        selected = tab,
                        onSelect = { tab = it; keyword = "" },
                    )
                    // 搜索框**三段都有**（用户 2026-09-18：只要是选地点的地方都能搜）。
                    // 这里搜的是本地已有的那份列表 —— 数据本来就在手上，即时出结果，
                    // 不需要往返后端（共享库那一段在下单页的地址弹层里，那里才需要打后端）。
                    // ⚠️ 联系人那一档是**按人搜索**，必须走全 App 唯一那份 `SearchField`
                    //    （放大镜 + ✕ 一键清空 + 提示语同源 `core/UserSearch.HINT`）——
                    //    自己拿 `SoTextField` 顶一份，用户在两页看到的形状就不一样，
                    //    而且会丢掉"能按手机号后 4 位搜"那句提示。
                    // 线路 / 地点两档搜的是地址型文本，继续用 `SoTextField` + 地址占位语。
                    Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
                        if (tab == 1) {
                            SearchField(value = keyword, onValueChange = { keyword = it })
                        } else {
                            SoTextField(
                                value = keyword,
                                onValueChange = { keyword = it },
                                placeholder = when (tab) {
                                    0 -> "搜线路：收货人 / 电话 / 地址"
                                    else -> "搜地点：名称 / 地址"
                                },
                            )
                        }
                        // 清空统一成 ✕（与 `SearchField` 里的那个同形）。联系人档自带 ✕，这里不重复画。
                        if (tab != 1 && keyword.isNotBlank()) {
                            IconButton(
                                onClick = { keyword = "" },
                                modifier = Modifier.align(Alignment.CenterEnd),
                            ) {
                                Icon(Icons.Default.Close, contentDescription = "清空搜索", modifier = Modifier.size(18.dp))
                            }
                        }
                    }
                    val kw = keyword.trim()
                    // 三档各自的分类筛选：抽屉里选了某一类就只留那一类（空串 = 全部）。
                    // ⚠️ 分类是**本地过一遍**（名册与列表本来就在手上），不往返后端。
                    val routeRailName = railCategoryName(vm.routeRailKey)
                    val locRailName = railCategoryName(vm.locRailKey)
                    val shownAddresses = remember(vm.addresses, kw, vm.routeRailKey) {
                        val base = if (kw.isBlank()) vm.addresses
                        else vm.addresses.filter {
                            it.receiverName.contains(kw, true) || it.phone.contains(kw) ||
                                it.detailAddress.contains(kw, true) || it.originAddress.orEmpty().contains(kw, true)
                        }
                        if (routeRailName.isBlank()) base else base.filter { it.category == routeRailName }
                    }
                    val shownContacts = remember(vm.contacts, kw) {
                        if (kw.isBlank()) vm.contacts
                        // 「联系人」这一段是**纯按人搜**（姓名 / 手机号，后 4 位也命中）——
                        // 走全 App 唯一那份规则（`core/UserSearch`），不在这里再写一遍 contains。
                        // ⚠️ 上面「线路」那一段**故意不用它**：它还要按地址文本匹配，
                        //    套上只认姓名/手机号的规则会让「按地址找线路」直接失效。
                        else vm.contacts.filter { UserSearch.matches(kw, it.displayName, it.phone) }
                    }
                    val shownLocations = remember(vm.locations, kw, vm.locRailKey) {
                        val base = if (kw.isBlank()) vm.locations
                        else vm.locations.filter { it.name.contains(kw, true) || it.detailAddress.contains(kw, true) }
                        if (locRailName.isBlank()) base else base.filter { it.category == locRailName }
                    }
                    // 删除是软删，但「软」是数据库的事，用户要的是**当场能救回来**（规范 06:1371：
                    // 删除一律软删 + **手边**要有撤回）。这一行就摆在列表**顶上**：它跟着内容走、
                    // 永远在第一屏；⛔ 不塞进页面底部提示位 —— 那在长列表的末尾，根本不在屏幕上。
                    vm.recentlyDeleted?.let { rd ->
                        val what = if (rd.name.isBlank()) "这条" + rd.label else "「" + rd.name + "」"
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier.fillMaxWidth().padding(start = 4.dp, end = 4.dp),
                        ) {
                            Text(
                                "已删除" + what,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.weight(1f),
                            )
                            TextButton(onClick = { vm.undoDelete() }, enabled = !vm.acting) { Text("撤销") }
                        }
                        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                    }
                    Box(Modifier.weight(1f)) {
                        when {
                            vm.loading -> LoadingBox(Modifier.fillMaxSize())
                            // ⚠️ 只看 **loadError**：表单的错误写在抽屉里（见 AddressViewModel 的注释），
                            //    混进来就会让"保存被拦下"变成"整页列表全没了"。
                            vm.loadError != null -> ErrorView(vm.loadError.orEmpty(), onRetry = { vm.load() }, Modifier.fillMaxSize())
                            // ---- 2. 联系人：单独一支（它自己就是一整块 LazyColumn）----
                            // 分类那一列已经挪进左侧抽屉（`ModalNavigationDrawer`），列表占整幅宽度。
                            // ⚠️ 外层是**无主语 when**，所以这一支必须写成条件（`tab == 1`），
                            //    直接写 `1 ->` 会被当成"条件类型不匹配"编译不过。
                            tab == 1 -> ContactCategoryPane(vm = vm, keyword = kw, contacts = shownContacts, onOpenDrawer = { scope.launch { drawer.open() } })
                            else -> LazyColumn(
                                Modifier.fillMaxSize(),
                                contentPadding = PaddingValues(16.dp),
                                verticalArrangement = Arrangement.spacedBy(10.dp),
                            ) {
                                when (tab) {
                                    // ---- 2. 联系人 ----：已由外面的 ContactCategoryPane 接管（标题行胶囊 + 左侧抽屉）

                                    // ---- 3. 地点（单独地点）----
                                    2 -> {
                                        item {
                                            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                                                // 标题 + 分类胶囊占左边一组（用户框的就是这个位置），右边留给「新增地点」。
                                                Row(Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically) {
                                                    Text("地点", style = MaterialTheme.typography.titleMedium, maxLines = 1)
                                                    Spacer(Modifier.width(8.dp))
                                                    CategoryTriggerChip(
                                                        current = locRailName,
                                                        accent = Color(MoneyOrange),
                                                        onClick = { scope.launch { drawer.open() } },
                                                    )
                                                }
                                                TextButton(onClick = { vm.openLocationCreate() }) {
                                                    Icon(Icons.Default.Place, null, Modifier.size(16.dp), tint = Color(MoneyOrange))
                                                    Spacer(Modifier.width(3.dp))
                                                    Text("新增地点")
                                                }
                                            }
                                        }
                                        if (shownLocations.isEmpty()) {
                                            item {
                                                EmptyView(
                                                    when {
                                                        kw.isNotBlank() -> "没有匹配「$kw」的地点"
                                                        locRailName.isNotBlank() -> "「" + locRailName + "」下还没有地点"
                                                        else -> "暂无地点"
                                                    },
                                                )
                                            }
                                        } else {
                                            items(shownLocations, key = { "l" + it.id }) { l ->
                                                LocationCard(l = l, onEdit = { vm.openLocationEdit(l) }, onDelete = { vm.deleteLocation(l) })
                                            }
                                        }
                                    }

                                    // ---- 1. 常用线路（联系人 + 地点）----
                                    else -> {
                                        item {
                                            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                                                Row(Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically) {
                                                    Text("常用线路", style = MaterialTheme.typography.titleMedium, maxLines = 1)
                                                    Spacer(Modifier.width(8.dp))
                                                    CategoryTriggerChip(
                                                        current = routeRailName,
                                                        accent = Color(ShipperTeal),
                                                        onClick = { scope.launch { drawer.open() } },
                                                    )
                                                }
                                                TextButton(onClick = { vm.openCreate() }) {
                                                    Icon(Icons.Default.AddLocationAlt, null, Modifier.size(16.dp), tint = Color(ShipperTeal))
                                                    Spacer(Modifier.width(3.dp))
                                                    Text("新增线路")
                                                }
                                            }
                                            Spacer(Modifier.height(4.dp))
                                        }
                                        if (shownAddresses.isEmpty()) {
                                            item {
                                                EmptyView(
                                                    when {
                                                        kw.isNotBlank() -> "没有匹配「$kw」的线路"
                                                        routeRailName.isNotBlank() -> "「" + routeRailName + "」下还没有线路"
                                                        else -> "暂无线路，点右侧新增"
                                                    },
                                                )
                                            }
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
                    .fillMaxHeight()
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
                // 2026-09-24 改：挑选入口从这里的**下拉菜单**换成全 App 同一个「选择联系人」弹层
                // （`ui/common/ContactPickerSheet.kt`）—— 下拉在人一多时滚不完、也搜不了，
                // 而下单页刚加的正是那个弹层；两处必须是同一份实现，否则同一个联系人
                // 在一处挑得到、在另一处挑不到。
                // 同时把名称/电话两栏**显式摊出来**：老做法只能"从名册挑一个"，
                // 线路里本来就存着的那位（名册里没有他）在编辑时既看不见、也保不住。
                FormGroup(icon = Icons.Default.Person, title = "联系人", tint = Color(ShipperTeal)) {
                    FormPickRow(
                        label = "收货联系人",
                        value = boundContactLabel(vm.draftName, vm.draftPhone),
                        placeholder = "请选择联系人",
                        // 图标与语义色跟着搬（2026-09-22 用户：「图标和语义色不能去掉」）
                        icon = Icons.Default.Person,
                        iconTint = Color(ShipperTeal),
                        onClick = { vm.openContactPickerFor("line") },
                    )
                    FormInputRow(
                        label = "收货人名称",
                        value = vm.draftName,
                        onValueChange = { vm.draftName = it },
                        placeholder = "从联系人带出，可改",
                        icon = Icons.Default.Person,
                        iconTint = Color(ShipperTeal),
                    )
                    FormInputRow(
                        label = "收货人电话",
                        value = vm.draftPhone,
                        // 规则唯一实现在 core/InputRules.kt（与下单页那两个电话框同一条）
                        onValueChange = { vm.draftPhone = InputRules.phoneInput(it) },
                        placeholder = "请输入手机号",
                        keyboardType = KeyboardType.Phone,
                        icon = Icons.Default.Phone,
                        iconTint = Color(MgrGreen),
                    )
                }

                // ② 起点（可选）
                FormGroup(icon = Icons.Default.Route, title = "起点（可选）", tint = Color(OriginTeal)) {
                    FormTextAreaRow(
                        label = "起点地址",
                        value = vm.draftOrigin,
                        onValueChange = { vm.draftOrigin = it },
                        placeholder = "不填就是「只送到终点」",
                        icon = Icons.Default.Route,
                        iconTint = Color(OriginTeal),
                    )
                    Box {
                        FormActionRow(
                            label = "从地点库选起点",
                            onClick = { startLocMenu = true },
                            icon = Icons.Default.List,
                            iconTint = Color(OriginTeal),
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
                        iconTint = Color(OriginTeal),
                    )
                }

                // ③ 终点（必填）
                FormGroup(icon = Icons.Default.Place, title = "终点（必填）", tint = Color(DestOrange)) {
                    FormTextAreaRow(
                        label = "终点地址",
                        value = vm.draftDetail,
                        onValueChange = { vm.draftDetail = it },
                        placeholder = "送到哪里",
                        required = true,
                        icon = Icons.Default.Place,
                        iconTint = Color(DestOrange),
                    )
                    Box {
                        FormActionRow(
                            label = "从地点库选终点",
                            onClick = { endLocMenu = true },
                            icon = Icons.Default.List,
                            iconTint = Color(DestOrange),
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
                        iconTint = Color(DestOrange),
                    )
                    // 分类（与地点表单同一套做法：名册管顺序、字符串管归属）。
                    // ⚠️ 下拉点选 + 最后一项「＋ 新建分类…」，⛔ 不用 chips 替代下拉（设计规范 §5），
                    // 也不在这里自由填名字 —— 填出来的名字会绕过名册、顺序乱掉。
                    var routeCatExpanded by remember { mutableStateOf(false) }
                    var newRouteCatDialog by remember { mutableStateOf(false) }
                    ExposedDropdownMenuBox(
                        expanded = routeCatExpanded,
                        onExpandedChange = { routeCatExpanded = it },
                    ) {
                        FormPickRow(
                            label = "分类",
                            value = vm.routeCategory.trim(),
                            placeholder = "未分类",
                            icon = Icons.Default.Folder,
                            iconTint = Color(ShipperTeal),
                            onClick = { routeCatExpanded = true },
                            modifier = Modifier.menuAnchor(),
                        )
                        ExposedDropdownMenu(
                            expanded = routeCatExpanded,
                            onDismissRequest = { routeCatExpanded = false },
                        ) {
                            DropdownMenuItem(
                                text = { Text("未分类") },
                                onClick = { vm.routeCategory = ""; routeCatExpanded = false },
                            )
                            vm.routeCategories.forEach { c ->
                                DropdownMenuItem(
                                    // 带上"这一类下有几条线路"：选分类时能看出哪个是主力
                                    text = {
                                        Text(
                                            c.name + if (c.addressCount > 0) "（${c.addressCount} 条线路）" else "",
                                            maxLines = 1,
                                        )
                                    },
                                    onClick = { vm.routeCategory = c.name; routeCatExpanded = false },
                                )
                            }
                            HorizontalDivider()
                            DropdownMenuItem(
                                text = { Text("＋ 新建分类…") },
                                onClick = { routeCatExpanded = false; newRouteCatDialog = true },
                            )
                        }
                    }
                    if (newRouteCatDialog) {
                        NewPlaceCategoryDialog(
                            busy = vm.acting,
                            error = vm.formError,
                            title = "新建分类",
                            placeholder = "分类名，如 常送工地 / 城东片区",
                            onConfirm = { name ->
                                vm.createRouteCategoryAndSelect(name) { newRouteCatDialog = false }
                            },
                            onDismiss = { newRouteCatDialog = false },
                        )
                    }
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
                    // 备注：这条线路原来**存得下、列表卡上也画得出，只有这个抽屉里看不见**
                    //（保存时一直在传 remark = draftRemark.trim()）。第 4 批补上这一栏，形状直接照抄
                    // 地点抽屉那张「图片 + 备注」的白卡 —— 同一件事在两个抽屉里必须长一样。
                    FormInputRow(
                        label = "备注",
                        value = vm.draftRemark,
                        onValueChange = { vm.draftRemark = it },
                        placeholder = "选填",
                        icon = Icons.Default.Notes,
                        iconTint = MaterialTheme.colorScheme.outline,
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
                    .fillMaxHeight()
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
                            iconTint = Color(ShipperTeal),
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
                // ---- 白卡 1b：这个地点默认谁收货 ----
                // 用户 2026-09-24：「可以通过地点来绑定联系人，就大家选择地点之后，
                // 自动填入对应的联系人」。⛔ 只有「我的地点」能绑 —— 共享地点库（`places`）
                // 是全库共用的，往它上面绑电话等于给所有人换了默认收货人。
                FormGroup(icon = Icons.Default.Contacts, title = "这个地点的联系人", tint = Color(ShipperTeal)) {
                    FormPickRow(
                        label = "从联系人里选",
                        value = boundContactLabel(vm.locContactName, vm.locContactPhone),
                        placeholder = "未绑定",
                        icon = Icons.Default.Person,
                        iconTint = Color(ShipperTeal),
                        onClick = { vm.openContactPickerFor("loc") },
                    )
                    FormInputRow(
                        label = "联系人名称",
                        value = vm.locContactName,
                        onValueChange = { vm.locContactName = it },
                        placeholder = "选填",
                        icon = Icons.Default.Person,
                        iconTint = Color(ShipperTeal),
                    )
                    FormInputRow(
                        label = "联系人电话",
                        value = vm.locContactPhone,
                        onValueChange = { vm.locContactPhone = InputRules.phoneInput(it) },
                        placeholder = "选填",
                        keyboardType = KeyboardType.Phone,
                        icon = Icons.Default.Phone,
                        iconTint = Color(MgrGreen),
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
                        iconTint = MaterialTheme.colorScheme.outline,
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

    // ---- 选择联系人（线路表单 / 地点表单**共用这一份**弹层）----
    vm.contactPickTarget?.let { target ->
        ContactPickerSheet(
            contacts = vm.contacts,
            title = if (target == "loc") "选择这个地点的联系人" else "选择收货联系人",
            creating = vm.creatingContact,
            // ⚠️ `error` 留空：这一页的取数失败由整页的 `loadError` 说（`vm.load()` 里），
            //    弹层里再报一次就会把"列表好好的、只是新建没成"变成"联系人全没了"。
            createError = vm.pickerError,
            onCreate = { name, phone -> vm.createContactAndPick(name, phone) },
            onPick = { vm.applyPickedContact(it) },
            onDismiss = { vm.contactPickTarget = null; vm.pickerError = null },
        )
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
                    .fillMaxHeight()
                    .padding(horizontal = 16.dp)
                    .imePadding()
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                Text(if (vm.editingContact == null) "添加联系人" else "编辑联系人", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                // 分类（FEAT-0007）与地点表单那排「分组」**同一个形状**：
                // 下拉点选（设计规范 §5：下拉一律 ExposedDropdownMenuBox，别用 chips 替代）+ 末尾「＋ 新建分类…」。
                var catExpanded by remember { mutableStateOf(false) }
                var newCatDialog by remember { mutableStateOf(false) }
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
                        // CHG-0010：这一栏**不再必填**（用户原话「新建联系人的时候不需要必填手机号」）——
                        // ⛔ 别再挂 required = true：校验早就放开了，标记却还写着必填，
                        //    用户会以为「只填称呼存不下来」（模拟器上就是这么被抓到的）。
                        keyboardType = KeyboardType.Phone,
                        icon = Icons.Default.Phone,
                        iconTint = Color(MgrGreen),
                    )
                    // 分类：**选填**（不建分类的人照样能用联系人；后端把空串当"未分类"）。
                    ExposedDropdownMenuBox(expanded = catExpanded, onExpandedChange = { catExpanded = it }) {
                        FormPickRow(
                            label = "分类",
                            value = vm.contactCategory.trim(),
                            placeholder = "未分类",
                            icon = Icons.Default.Folder,
                            iconTint = Color(ShipperTeal),
                            onClick = { catExpanded = true },
                            modifier = Modifier.menuAnchor(),
                        )
                        ExposedDropdownMenu(expanded = catExpanded, onDismissRequest = { catExpanded = false }) {
                            DropdownMenuItem(
                                text = { Text("未分类") },
                                onClick = { vm.contactCategory = ""; catExpanded = false },
                            )
                            vm.contactCategories.forEach { c ->
                                DropdownMenuItem(
                                    // 带上"这一类里有几位"：挑分类时能看出哪个是主力（与地点那排同口径）
                                    text = {
                                        Text(
                                            c.name + if (c.contactCount > 0) "（${c.contactCount} 位联系人）" else "",
                                            maxLines = 1,
                                        )
                                    },
                                    onClick = { vm.contactCategory = c.name; catExpanded = false },
                                )
                            }
                            HorizontalDivider()
                            DropdownMenuItem(
                                text = { Text("＋ 新建分类…") },
                                onClick = { catExpanded = false; newCatDialog = true },
                            )
                        }
                    }
                }
                if (newCatDialog) {
                    NewPlaceCategoryDialog(
                        busy = vm.acting,
                        error = vm.formError,
                        title = "新建分类",
                        placeholder = "分类名，如 供货商 / 老客户",
                        hint = "建好后会自动选中它。顺序到联系人左栏的「管理分类」里排。",
                        onConfirm = { name ->
                            vm.createContactCategoryAndSelect(name) { newCatDialog = false }
                        },
                        onDismiss = { newCatDialog = false },
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
 * 「分类管理」面板：抽屉里点「管理分类」→ 关抽屉 → 该页签整块换成它（**同一屏的第二层**，⛔ 不新开页面）。
 *
 * 三个页签各有一份自己的名册（线路 / 联系人 / 地点），面板本身长得一模一样 —— 这里只做「按页签挑一个 VM」。
 * 返回时上层会回读名册（`reloadXxxCategories`），抽屉里那一格才跟着改名 / 删除走。
 *
 * ⚠️ `appViewModel` 是 Activity 级缓存，VM 的 `init { load() }` 只跑第一次 ⇒ 每次进来补一次 `load()`，
 * 否则面板显示的是上一次的条数（2026-10-03 模拟器实测：库里已经是 1 位，面板显示「0 位联系人」）。
 */
@Composable
private fun CategoryManagePanel(container: AppContainer, tab: Int, onBack: () -> Unit) {
    when (tab) {
        1 -> {
            val catVm: ContactCategoriesViewModel = appViewModel { ContactCategoriesViewModel(container) }
            LaunchedEffect(Unit) { catVm.load() }
            ContactCategoriesPanel(vm = catVm, onBack = onBack)
        }
        2 -> {
            val catVm: PlaceCategoriesViewModel = appViewModel { PlaceCategoriesViewModel(container) }
            LaunchedEffect(Unit) { catVm.load() }
            PlaceCategoriesPanel(vm = catVm, onBack = onBack)
        }
        else -> {
            val catVm: RouteCategoriesViewModel = appViewModel { RouteCategoriesViewModel(container) }
            LaunchedEffect(Unit) { catVm.load() }
            RouteCategoriesPanel(vm = catVm, onBack = onBack)
        }
    }
}

/**
 * 「联系人」这一段：**标题行上一个分类胶囊 + 点开左侧抽屉**（三档同一形态）。
 *
 * 用户 2026-10-04 的原话：「干脆给线路联系人以及地点，这3个的界面玩个框了框的位置加一个分类显示……
 * 点击这个按钮的时候，它就会弹出一个在左侧来，它这个左侧抽屉就是我们的那个分类显示，可以去参考
 * 账本管理的那些代码**就不要使用那个商品管理的界面了**，商品管理的话，那样子的界面导致了右边的
 * 卡片的信息被挤压了不是很好看」。
 *
 * 所以这里**不再**常驻一条 `MasterRail` —— 那正是被否掉的商品管理式左栏（112dp 宽的固定左栏把右边
 * 的卡片挤窄了）。抽屉是 `ModalNavigationDrawer`（形态照「账本管理」`DispatcherLedgerScreen.kt`），
 * 不点开时右边就是整幅宽度的列表。
 *
 * 三条纪律照旧：
 * · key 约定 `""` = 全部 / `"c|分类名"` = 某一类 / `"manage"` = 分类管理（抽屉里最后一行，由零件自己加）；
 * · **抽屉里一格都不带「N 位」**（用户 2026-09-19：「那个分组下面不要显示有多少条啊，这是多余信息」）；
 * · 管理是**同屏第二层**（`CategoryManagePanel`），不是新页面。
 *
 * ⚠️ 别把分类做成"下拉筛选"：用户要的是看得见的分组（抽屉里一整列），下拉只做表单里选一个值。
 */
@Composable
private fun ContactCategoryPane(
    vm: AddressViewModel,
    keyword: String,
    /** 已经被搜索框筛过一遍的联系人（姓名 / 手机号）。这一层只再叠一次"分类"筛选。 */
    contacts: List<ContactDto>,
    /** 点分类胶囊 → 上层开抽屉（抽屉挂在 `AddressScreen` 上，三档共用同一个）。 */
    onOpenDrawer: () -> Unit,
) {
    val railName = railCategoryName(vm.contactRailKey)
    val inCategory = remember(contacts, vm.contactRailKey) {
        if (railName.isBlank()) contacts else contacts.filter { it.category == railName }
    }
    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                // 标题 + 分类胶囊占左边一组，右边留给「新增联系人」（胶囊把「新增」挤走就等于没做）。
                Row(Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically) {
                    Text("联系人", style = MaterialTheme.typography.titleMedium, maxLines = 1)
                    Spacer(Modifier.width(8.dp))
                    CategoryTriggerChip(
                        current = railName,
                        accent = Color(ShipperTeal),
                        onClick = onOpenDrawer,
                    )
                }
                TextButton(onClick = { vm.openContactDialog() }) {
                    Icon(Icons.Default.PersonAddAlt, null, Modifier.size(16.dp), tint = Color(ShipperTeal))
                    Spacer(Modifier.width(3.dp))
                    Text("新增联系人")
                }
            }
        }
        if (inCategory.isEmpty()) {
            item {
                EmptyView(
                    when {
                        keyword.isNotBlank() -> "没有匹配「$keyword」的联系人"
                        railName.isNotBlank() -> "「" + railName + "」下还没有联系人"
                        else -> "暂无联系人"
                    },
                )
            }
        } else {
            items(inCategory, key = { "c" + it.id }) { c ->
                ContactCard(c = c, onEdit = { vm.openContactDialog(c) }, onDelete = { vm.deleteContact(c) })
            }
        }
        item { Spacer(Modifier.height(24.dp)) }
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
    // 下面三个默认值 =「地点分组」那一处的原文案。联系人分类（FEAT-0007）复用同一个弹窗，
    // 只换名字 —— 两处各写一份的话，将来改一处就会留下另一处的不一致。
    title: String = "新建分组",
    placeholder: String = "分组名，如 常送小区 / 工地",
    // ⛔ 说明句**不许**写成这里的默认值：判据 _check_hints.py 靠「字面量挂在 Hint 调用里」
    //    来盯住「有人把它改回裸 Text」，挪到参数默认值上那句话就**从提示目录里消失**、
    //    _tools/qa/_reverse_verify_hints.py 的用例①（一处解释句改回裸 Text）也就失灵了
    //    —— 2026-10-03 实测踩到，所以地点那一句留在下面的 Hint 调用里内联，
    //    联系人分类（FEAT-0007 复用同一个弹窗）只在调用处换一句。
    hint: String = "",
) {
    var name by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            Column {
                SoTextField(
                    value = name,
                    onValueChange = { name = it.take(8) },
                    placeholder = placeholder,
                )
                Spacer(Modifier.height(8.dp))
                Hint(
                    hint.ifBlank { "建好后会自动选中它。顺序到地址库左栏的「管理分组」里排。" },
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
                    Icon(Icons.Default.Phone, contentDescription = "电话", modifier = Modifier.size(11.dp), tint = Color(MgrGreen))
                    Spacer(Modifier.width(3.dp))
                    Text(
                        a.phone,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                    )
                    Spacer(Modifier.weight(1f))
                    if (a.isDefault) {
                        // 与地点卡的「仓库」是同一个标签件（形状只有一处实现，见 CardTag）
                        CardTag(
                            text = "默认",
                            container = MaterialTheme.colorScheme.primaryContainer,
                            content = MaterialTheme.colorScheme.onPrimaryContainer,
                        )
                    }
                }
                if (a.remark.isNotBlank()) {
                    Spacer(Modifier.height(4.dp))
                    Text(a.remark, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline, maxLines = 2)
                }
            }
            Spacer(Modifier.width(8.dp))
            // ---- 右：删除（上）/ 编辑（下）—— 一上一下，删除在上（用户点名两遍）----
            // ⚠️ **竖排不吃 §4.2c 的"左＝反向、右＝编辑"位置条**：那一页位置条管的是**横排**
            //    两个动作用户，这里上下排布本身就是位置信息（上＝危险）。所以只把形态对齐
            //    （裸 18dp 图标 → `CardActionIcon` 圈底），顺序一个字不动。
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                CardActionIcon(
                    icon = Icons.Default.Delete,
                    contentDescription = "删除",
                    tint = MaterialTheme.colorScheme.error,
                    onClick = onDelete,
                )
                CardActionIcon(
                    icon = Icons.Default.Edit,
                    contentDescription = "编辑",
                    tint = MaterialTheme.colorScheme.primary,
                    onClick = onEdit,
                )
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

/**
 * 卡片上的一个小标签（「默认」「仓库」同形状；颜色由调用处给）。
 *
 * 为什么做成共用件：两张卡各画一份，圆角 / 字号 / 内边距一定会慢慢分叉，
 * 而这一页一共也就这两种标签 —— 一处实现、两处调用是唯一划算的写法。
 * ⛔ 它不是动作按钮：动作一律走 CardActionIcon（圈底 36dp、可点、有语义）。
 */
@Composable
private fun CardTag(text: String, container: Color, content: Color) {
    Surface(color = container, shape = MaterialTheme.shapes.small) {
        Text(
            text,
            style = MaterialTheme.typography.labelSmall,
            color = content,
            maxLines = 1,
            modifier = Modifier.padding(horizontal = 6.dp, vertical = 1.dp),
        )
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
                // 分类（FEAT-0007）也要在卡上看得见：左栏那道筛选就是按它过滤的，卡片上一个字都不写，
                // 用户在「全部」里只能逐个点开编辑去看这个人归在哪一类。没归类就整行不画，不留空标签。
                if (c.category.isNotBlank()) {
                    Spacer(Modifier.height(4.dp))
                    CardTag(
                        text = c.category,
                        container = Color(ShipperTeal).copy(alpha = 0.14f),
                        content = Color(ShipperTeal),
                    )
                }
            }
            // 卡片动作分区（见 `CardActionIcon` 的 KDoc）：**左＝反向/警示（删除），右＝编辑**
            // —— 用户 2026-09-22：「编辑一定在右边，因为我们的惯用手是右手」。原来这两张卡
            //    把**删除放在了最右边**（右手最容易点到的地方放着最危险的那个），且都是裸图标。
            CardActionIcon(
                icon = Icons.Default.Delete,
                contentDescription = "删除",
                tint = MaterialTheme.colorScheme.error,
                onClick = onDelete,
            )
            CardActionIcon(
                icon = Icons.Default.Edit,
                contentDescription = "编辑",
                tint = MaterialTheme.colorScheme.primary,
                onClick = onEdit,
            )
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
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        l.name.ifBlank { "地点" },
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                        maxLines = 1,
                        modifier = Modifier.weight(1f, fill = false),
                    )
                    // 「这是我的仓」是**身份**，摆在名字这一行（不在名字里加字、也不藏进备注）：
                    // 入库 / 下单带不带出仓库那一套全靠它，卡片上不写，用户只能靠记忆。
                    if (l.isWarehouse) {
                        Spacer(Modifier.width(6.dp))
                        CardTag(
                            text = "仓库",
                            container = Color(MoneyOrange).copy(alpha = 0.14f),
                            content = Color(MoneyOrange),
                        )
                    }
                }
                Text(
                    l.detailAddress,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                    // 长地址保**尾部**：门牌号 / 几栋几室在最后，默认的 Clip 正好把那几个字切掉，
                    // 而那几个字才是「到底送到哪」的落点。
                    overflow = TextOverflow.StartEllipsis,
                )
                // 绑了联系人的地点要在地点卡上**看得见**：不写这一行，用户只能靠"下单时会不会带出来"猜
                // （而卡片上没有任何线索）。没绑就整行不画，不留一个空标签。
                if (hasBoundContact(l.contactName, l.contactPhone)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.Person, null, Modifier.size(13.dp), tint = Color(ShipperTeal))
                        Spacer(Modifier.width(4.dp))
                        Text(
                            boundContactLabel(l.contactName, l.contactPhone),
                            style = MaterialTheme.typography.bodySmall,
                            color = Color(ShipperTeal),
                            maxLines = 1,
                        )
                    }
                }
                if (l.remark.isNotBlank()) {
                    Text(l.remark, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline)
                }
            }
            // 卡片动作分区（见 `CardActionIcon` 的 KDoc）：**左＝反向/警示（删除），右＝编辑**
            // —— 用户 2026-09-22：「编辑一定在右边，因为我们的惯用手是右手」。原来这两张卡
            //    把**删除放在了最右边**（右手最容易点到的地方放着最危险的那个），且都是裸图标。
            CardActionIcon(
                icon = Icons.Default.Delete,
                contentDescription = "删除",
                tint = MaterialTheme.colorScheme.error,
                onClick = onDelete,
            )
            CardActionIcon(
                icon = Icons.Default.Edit,
                contentDescription = "编辑",
                tint = MaterialTheme.colorScheme.primary,
                onClick = onEdit,
            )
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
        Hint(hint, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
    preview.Show()
}