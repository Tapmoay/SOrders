package com.tapmoay.sorders.ui.dispatcher

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.AddAPhoto
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.Inventory2
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.ProductCostHistoryDto
import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.ui.theme.ProductPurple
import com.tapmoay.sorders.ui.theme.QuickPriceGreen
import com.tapmoay.sorders.util.formatDateTime
import com.tapmoay.sorders.util.formatMoney
import com.tapmoay.sorders.util.resolveStaticUrl
import com.tapmoay.sorders.util.trimMoneyZeros
import java.io.File

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProductsScreen(
    container: AppContainer,
    onBack: () -> Unit,
    onOpenCategories: () -> Unit = {},
    /** 打开「各批发商价格」（价格矩阵的"按商品"方向）。 */
    onOpenPricing: (Long) -> Unit = {},
) {
    val vm: ProductsViewModel = appViewModel { ProductsViewModel(container) }
    val snackbar = remember { SnackbarHostState() }
    val context = LocalContext.current
    /**
     * 快捷改价（卡片右侧「改价」）：non-null = 弹窗开着。
     *
     * ⚠️ 必须声明在**函数级**（Scaffold 之外）—— 弹窗渲染在整个 Scaffold 之后，
     *    声明在 content lambda 里的话外面看不见（第一版就是这么写的，编译报 Unresolved）。
     */
    var quickPriceFor by remember { mutableStateOf<ProductDto?>(null) }
    /** 成本价历史弹窗（`⋮ → 成本价历史`）：状态在 VM 里（要拉数据），这里只读它。 */

    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })

    // 失败**必须**看得见：这个页面的错误以前只在"列表为空"时才渲染成整页 ErrorView，
    // 于是列表有数据时的上下架/删除失败**界面上毫无变化**——用户以为点漏了，反复点。
    // ⚠️ 消费的是**动作错误**（vm.error）；加载错误走 vm.loadError（它还要驱动整页 ErrorView）。
    OneShotSnackbar(snackbar, vm.error, onConsumed = { vm.error = null })

    // 相册选图 → 拷贝到缓存 → 交给 VM
    val pickImage = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri != null) {
            try {
                val f = File(context.cacheDir, "product_img_" + System.currentTimeMillis() + ".jpg")
                context.contentResolver.openInputStream(uri)?.use { input ->
                    f.outputStream().use { output -> input.copyTo(output) }
                }
                vm.draftImageLocal = f.absolutePath
            } catch (_: Exception) {
                vm.error = "图片读取失败，请重试"
            }
        }
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = { Text("商品管理") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                // ⛔ 顶栏原来挂着一个「分类管理」按钮、右下角挂着一个「＋」悬浮球。
                //    2026-09-19 用户要求两个动作合并成**底部一条导航栏**
                //    （「给那个商品管理界面的下面加个导航栏，左边分组管理、右边商品新增，
                //     那个 + 把它改成商品新增…两个导航栏做得美观一点」）：
                //    悬浮球压在列表最后一张卡上、顶栏按钮又和返回键挤在一行，
                //    两个动作各在一个角上，视线要跑两趟。
            )
        },
        bottomBar = { ProductsBottomBar(onCategories = onOpenCategories, onAdd = { vm.openCreate() }) },
    ) { padding ->
        // 分类清单与当前选中的分类：**与选品页同一套实现**
        // （`categoryTabs` / `categoryOf` / `CategoryRail` 都在 `ui/common/ProductPicker.kt` 里，
        //  这一页只是把同一根导航条用在自己的列表左边）
        val cats = remember(vm.products, vm.categories) {
            categoryTabs(vm.products, vm.categories.map { it.name })
        }
        var category by remember { mutableStateOf(ALL_CATEGORY) }
        // 选中的分类可能因为改名/改商品分类而消失 —— 那就退回「全部」，
        // 否则用户会停在一个**导航条上已经不存在的分类**上、右边一片空白且无法解释
        LaunchedEffect(cats) {
            if (category !in cats) category = ALL_CATEGORY
        }
        val keyword = vm.query.trim()
        val visible = remember(vm.products, category, keyword) {
            vm.products
                .filter { category == ALL_CATEGORY || categoryOf(it) == category }
                // 名称搜索（用户 2026-09-19：「商品管理的页面要有个搜索的框啊，方便我们找商品」）：
                // 与库存页同一个判据（本地 + 与左边分类 **AND**）。
                .filter { keyword.isEmpty() || it.name.contains(keyword, ignoreCase = true) }
        }

        Column(Modifier.fillMaxSize().padding(padding)) {
            // 搜索框**横跨整页**（在分类条上面）—— 与库存管理页同一版式。
            // 放右栏会被压成半宽，而且分类为空时它会跟着消失；而"找不到某个商品"正是最需要它的时候。
            OutlinedTextField(
                value = vm.query,
                onValueChange = { vm.query = it },
                placeholder = { Text("搜索商品名称", style = MaterialTheme.typography.bodySmall) },
                leadingIcon = { Icon(Icons.Default.Search, contentDescription = null, modifier = Modifier.size(20.dp)) },
                trailingIcon = {
                    if (vm.query.isNotEmpty()) {
                        IconButton(onClick = { vm.query = "" }) {
                            Icon(Icons.Default.Close, contentDescription = "清空搜索", modifier = Modifier.size(18.dp))
                        }
                    }
                },
                singleLine = true,
                textStyle = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
            )
            Box(Modifier.weight(1f)) {
            when {
                vm.loading -> LoadingBox()
                vm.loadError != null && vm.products.isEmpty() -> ErrorView(vm.loadError.orEmpty(), onRetry = { vm.load() })
                vm.products.isEmpty() -> EmptyView("暂无商品，点下方「商品新增」", Modifier.align(Alignment.Center))
                else -> Row(Modifier.fillMaxSize()) {
                    // 左：分类（独立滚动，不会把右边的商品一起带走）—— 与选品页同宽、同观感
                    CategoryRail(
                        tabs = cats,
                        selected = category,
                        onSelect = { category = it },
                        modifier = Modifier.width(92.dp).fillMaxHeight(),
                    )
                    // 右：商品
                    Box(Modifier.weight(1f).fillMaxHeight()) {
                        if (visible.isEmpty()) {
                            // 「搜不到」和「这一类是空的」是两句不同的话 —— 说不清用户会以为商品丢了
                            EmptyView(
                                if (keyword.isNotEmpty()) "没有名称含「$keyword」的商品" else "「$category」下暂无商品",
                                Modifier.align(Alignment.Center),
                            )
                        } else {
                            // ⚠️ 这里原来末尾有一句 `item { Spacer(Modifier.height(72.dp)) }` 给悬浮球让位。
                            //    动作已经搬到底部导航栏、而 Scaffold 的 padding 已经扣掉了那条栏的高度，
                            //    再留 72dp 就是列表底下凭空多一块空白。
                            LazyColumn(
                                Modifier.fillMaxSize(),
                                contentPadding = PaddingValues(start = 10.dp, end = 10.dp, top = 10.dp, bottom = 12.dp),
                                verticalArrangement = Arrangement.spacedBy(8.dp),
                            ) {
                                items(visible, key = { it.id }) { p ->
                                    ProductCard(
                                        p = p,
                                        acting = vm.acting,
                                        onEdit = { vm.openEdit(p) },
                                        onToggle = { vm.toggleActive(p) },
                                        onDelete = { vm.delete(p) },
                                        onOpenPricing = { onOpenPricing(p.id) },
                                        onQuickPrice = { quickPriceFor = p },
                                        onCostHistory = { vm.openCostHistory(p) },
                                    )
                                }
                            }
                        }
                    }
                }
            }
            }
        }
    }

    // 快捷改价（只改默认售价）
    quickPriceFor?.let { p ->
        QuickPriceDialog(
            p = p,
            busy = vm.acting,
            onConfirm = { price -> vm.updateDefaultPrice(p, price) { quickPriceFor = null } },
            onDismiss = { quickPriceFor = null },
        )
    }

    // 成本价历史（只读）：这个商品的价格从什么时候到什么时候是多少
    vm.costHistoryFor?.let { p ->
        CostHistoryDialog(
            p = p,
            rows = vm.costHistory,
            loading = vm.costHistoryLoading,
            onDismiss = { vm.costHistoryFor = null },
        )
    }

    // 新增/编辑 下拉抽屉（基础信息 / 价格 / 库存）
    if (vm.showDialog) {
        ModalBottomSheet(
            onDismissRequest = { vm.showDialog = false },
            sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        ) {
            Column(
                Modifier
                    .fillMaxWidth()
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = 20.dp)
                    .padding(bottom = 32.dp),
            ) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            if (vm.editing == null) "新增商品" else "编辑商品",
                            style = MaterialTheme.typography.titleLarge,
                            modifier = Modifier.weight(1f),
                        )
                        IconButton(onClick = { vm.showDialog = false }) {
                            Icon(Icons.Default.Close, contentDescription = "关闭")
                        }
                    }

                    // ---- 基础信息 ----
                    SectionCard {
                        Text("基础信息", style = MaterialTheme.typography.titleSmall)
                        Spacer(Modifier.height(10.dp))
                        OutlinedTextField(
                            value = vm.draftName, onValueChange = { vm.draftName = it },
                            label = { Text("商品名称（必填）") },
                            singleLine = true, modifier = Modifier.fillMaxWidth(),
                        )
                        Spacer(Modifier.height(10.dp))

                        // 商品图片
                        Text("商品图片（可选）", style = MaterialTheme.typography.bodySmall)
                        Spacer(Modifier.height(6.dp))
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            val local = vm.draftImageLocal
                            val remote = if (vm.editing != null && local == null) vm.editing?.imageUrl else null
                            Box(
                                Modifier
                                    .size(96.dp)
                                    .clip(MaterialTheme.shapes.medium)
                                    .background(MaterialTheme.colorScheme.surfaceVariant)
                                    .clickable { pickImage.launch("image/*") },
                                contentAlignment = Alignment.Center,
                            ) {
                                when {
                                    local != null -> AsyncImage(
                                        model = File(local),
                                        contentDescription = "商品图",
                                        contentScale = ContentScale.Crop,
                                        modifier = Modifier.fillMaxSize().clip(MaterialTheme.shapes.medium),
                                    )
                                    remote != null -> AsyncImage(
                                        model = resolveStaticUrl(remote),
                                        contentDescription = "商品图",
                                        contentScale = ContentScale.Crop,
                                        modifier = Modifier.fillMaxSize().clip(MaterialTheme.shapes.medium),
                                    )
                                    else -> Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                        Icon(Icons.Default.AddAPhoto, contentDescription = null)
                                        Spacer(Modifier.height(2.dp))
                                        Text("选图", style = MaterialTheme.typography.labelSmall)
                                    }
                                }
                            }
                            Spacer(Modifier.width(12.dp))
                            Column(Modifier.weight(1f)) {
                                Text(
                                    "支持相册选图，自动压缩为 jpg 上传",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                                if (local != null || remote != null) {
                                    Spacer(Modifier.height(4.dp))
                                    TextButton(onClick = { vm.draftImageLocal = null }, contentPadding = PaddingValues(0.dp)) {
                                        Text("移除图片")
                                    }
                                }
                            }
                        }
                        Spacer(Modifier.height(10.dp))

                        Text("名称颜色", style = MaterialTheme.typography.bodySmall)
                        Spacer(Modifier.height(6.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            vm.colorOptions.forEach { (hex, _) ->
                                Box(
                                    Modifier
                                        .size(26.dp)
                                        .background(Color(android.graphics.Color.parseColor(hex)), CircleShape)
                                        .clickable { vm.draftColor = hex },
                                    contentAlignment = Alignment.Center,
                                ) {
                                    if (vm.draftColor == hex) {
                                        Icon(
                                            Icons.Default.Check,
                                            contentDescription = null,
                                            tint = Color.White,
                                            modifier = Modifier.size(14.dp),
                                        )
                                    }
                                }
                            }
                        }
                        Spacer(Modifier.height(8.dp))
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text("上架销售", style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
                            Switch(checked = vm.draftActive, onCheckedChange = { vm.draftActive = it })
                        }
                        Text(
                            if (vm.editing != null)
                                "下架后货主下单时不可选，但已有订单不受影响"
                            else
                                "新建默认上架；关闭开关则保存后货主不可见",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.outline,
                        )
                    }

                    Spacer(Modifier.height(10.dp))

                    // ---- 价格与批发价 ----
                    SectionCard {
                        Text("价格", style = MaterialTheme.typography.titleSmall)
                        Spacer(Modifier.height(10.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            OutlinedTextField(
                                value = vm.draftPrice,
                                // 单价规则（唯一实现在 core/InputRules.kt）：只数字 + 至多一个小数点。
                                // ⚠️ 用 priceInput（**4 位小数**）而不是 moneyInput（2 位）：库里
                                //    `products.default_unit_price` 是 `Numeric(14,4)`，用 2 位会把
                                //    "12.3456 元"这种本来定得了的价**悄悄截掉**（用户只会发现第四位打不进去）。
                                //    原来那句 `isDigit() || c == '.'` 能敲出 `1.2.3`，toDoubleOrNull() 得 null。
                                onValueChange = { vm.draftPrice = InputRules.priceInput(it) },
                                label = { Text("默认售价（必填）") },
                                singleLine = true, modifier = Modifier.weight(1f),
                            )
                            OutlinedTextField(
                                value = vm.draftCost,
                                onValueChange = { vm.draftCost = InputRules.priceInput(it) },
                                label = { Text("成本价（选填）") },
                                singleLine = true, modifier = Modifier.weight(1f),
                            )
                        }
                        Spacer(Modifier.height(6.dp))
                        Text(
                            "成本价用于报表计算毛利率，留空按 0 计",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.outline,
                        )

                        Spacer(Modifier.height(8.dp))
                        // ⛔ **这里原来有一段「批发价（可选，可多档）」**（批发价一/二/三 + 添加按钮），
                        //    2026-09-19 用户拍板**整个概念删掉**。
                        //    理由（用户原话）：「同一个商品，这个批发商的价格和那个批发商的价格是不一样的，
                        //    保证操作与逻辑匹配」——而商品上那几个"批发价档位"**下单时谁都不照它走**
                        //    （下单只认按（批发商×商品）存的专属价，或商品默认售价），
                        //    它只在"批量调价"和"定价页下拉"里当预设值。一个看起来像批发价、
                        //    实际不生效的字段，就是最典型的"操作与逻辑不匹配"。
                        //    批发商的价格现在只有一个入口：商品卡「⋮ → 各批发商价格」
                        //    （或批发商管理「定价」），两处都是**真的会生效**的那个价。
                    }

                    Spacer(Modifier.height(10.dp))

                    // ---- 库存 ----
                    SectionCard {
                        Text("库存", style = MaterialTheme.typography.titleSmall)
                        Spacer(Modifier.height(4.dp))
                        SoTextField(
                            value = vm.draftStock,
                            onValueChange = { vm.draftStock = InputRules.intInput(it, 7) },
                            placeholder = if (vm.editing == null) "初始库存（选填）" else "当前库存（由出入库流水维护）",
                            enabled = vm.editing == null,
                            modifier = Modifier.fillMaxWidth(),
                        )
                        Spacer(Modifier.height(10.dp))
                        // 单位：标准紧凑下拉（点击展开常驻列表，点选自动回填）
                        var unitExpanded by remember { mutableStateOf(false) }
                        ExposedDropdownMenuBox(expanded = unitExpanded, onExpandedChange = { unitExpanded = it }) {
                            OutlinedTextField(
                                value = vm.draftUnit,
                                onValueChange = {},
                                readOnly = true,
                                label = { Text("单位") },
                                placeholder = { Text("请选择单位") },
                                trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = unitExpanded) },
                                colors = OutlinedTextFieldDefaults.colors(
                                    focusedBorderColor = MaterialTheme.colorScheme.primary,
                                    unfocusedBorderColor = MaterialTheme.colorScheme.outlineVariant,
                                    focusedLabelColor = MaterialTheme.colorScheme.primary,
                                    unfocusedLabelColor = MaterialTheme.colorScheme.onSurfaceVariant,
                                    cursorColor = MaterialTheme.colorScheme.primary,
                                ),
                                singleLine = true,
                                modifier = Modifier.fillMaxWidth().menuAnchor(),
                            )
                            ExposedDropdownMenu(expanded = unitExpanded, onDismissRequest = { unitExpanded = false }) {
                                listOf("件", "个", "块", "包", "箱", "桶", "袋", "捆", "瓶", "盒", "盘", "斤", "公斤", "吨", "米", "车").forEach { u ->
                                    DropdownMenuItem(
                                        text = { Text(u, maxLines = 1) },
                                        onClick = { vm.draftUnit = u; unitExpanded = false },
                                    )
                                }
                            }
                        }
                        Spacer(Modifier.height(10.dp))
                        // 分类：**从名册里选**（用户 2026-09-19：「他要选择类别的商品分类」）。
                        // 原来这里是"自由填 + 一排可点的小块"，两个毛病：
                        // ① 设计规范 §5 写明了「下拉一律 ExposedDropdownMenuBox 点选回填，
                        //    **不要**用 chips 替代下拉」—— 那是用户早就否决过的做法；
                        // ② 自由填能造出只差一个空格的同名分类，下单页左侧因此多出一格，
                        //    而列表上看不出差别（旧注释也承认这一点，所以才补了那些小块）。
                        // 名册里没有想要的分类时走最后一项「＋ 新建分类…」—— 不把新建这条路堵死。
                        var catExpanded by remember { mutableStateOf(false) }
                        var newCatDialog by remember { mutableStateOf(false) }
                        ExposedDropdownMenuBox(expanded = catExpanded, onExpandedChange = { catExpanded = it }) {
                            OutlinedTextField(
                                value = vm.draftCategory.trim().ifBlank { "未分类" },
                                onValueChange = {},
                                readOnly = true,
                                label = { Text("商品分类（选填）") },
                                trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = catExpanded) },
                                colors = OutlinedTextFieldDefaults.colors(
                                    focusedBorderColor = MaterialTheme.colorScheme.primary,
                                    unfocusedBorderColor = MaterialTheme.colorScheme.outlineVariant,
                                    focusedLabelColor = MaterialTheme.colorScheme.primary,
                                    unfocusedLabelColor = MaterialTheme.colorScheme.onSurfaceVariant,
                                    cursorColor = MaterialTheme.colorScheme.primary,
                                ),
                                singleLine = true,
                                modifier = Modifier.fillMaxWidth().menuAnchor(),
                            )
                            ExposedDropdownMenu(expanded = catExpanded, onDismissRequest = { catExpanded = false }) {
                                DropdownMenuItem(
                                    text = { Text("未分类") },
                                    onClick = { vm.draftCategory = ""; catExpanded = false },
                                )
                                vm.categories.forEach { c ->
                                    DropdownMenuItem(
                                        // 带上"这一类下有几个商品"：改分类时能看出哪个是主力分类
                                        text = {
                                            Text(
                                                c.name + if (c.productCount > 0) "（${c.productCount} 个商品）" else "",
                                                maxLines = 1,
                                            )
                                        },
                                        onClick = { vm.draftCategory = c.name; catExpanded = false },
                                    )
                                }
                                HorizontalDivider()
                                DropdownMenuItem(
                                    text = { Text("＋ 新建分类…") },
                                    onClick = { catExpanded = false; newCatDialog = true },
                                )
                            }
                        }
                        Spacer(Modifier.height(4.dp))
                        Text(
                            "分类决定下单页「选择商品」左侧怎么分组；留空会归到「未分类」。" +
                                "顺序在「分类管理」里排。",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.outline,
                        )
                        if (newCatDialog) {
                            NewCategoryDialog(
                                busy = vm.acting,
                                onConfirm = { name ->
                                    vm.createCategoryAndSelect(name) { newCatDialog = false }
                                },
                                onDismiss = { newCatDialog = false },
                            )
                        }
                        Spacer(Modifier.height(10.dp))
                        SoTextField(
                            value = vm.draftAlert,
                            onValueChange = { vm.draftAlert = InputRules.intInput(it, 7) },
                            placeholder = "库存报警阈值（低于该值提醒，0=不报警）",
                            modifier = Modifier.fillMaxWidth(),
                        )
                        if (vm.editing != null) {
                            Spacer(Modifier.height(4.dp))
                            Text(
                                "初始库存仅在新建时填写；后续请到「库存管理」做出入库",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.outline,
                            )
                        }
                    }

                    vm.error?.let {
                        Spacer(Modifier.height(8.dp))
                        Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                    }

                    Spacer(Modifier.height(14.dp))
                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        OutlinedButton(
                            onClick = { vm.showDialog = false },
                            enabled = !vm.acting,
                            modifier = Modifier.weight(1f),
                        ) { Text("取消") }
                        Button(
                            onClick = { vm.save() },
                            enabled = !vm.acting,
                            modifier = Modifier.weight(1.4f),
                        ) {
                            Text(if (vm.acting) "保存中…" else "保存")
                        }
                    }
                    Spacer(Modifier.height(8.dp))
                }
            }
        }
    }

/**
 * 商品管理的**底部导航栏**：左边「分类管理」、右边「商品新增」（用户 2026-09-19 要求）。
 *
 * 原话：「给那个商品管理界面的下面加个导航栏，左边分别是那个分组管理、右边是商品的
 * 添加按钮，就是那个 + 把它改成商品新增…两个导航栏做得美观一点」。
 *
 * ## 为什么从"两个角"搬到底部一条栏
 * 搬之前是**顶栏一个「分类管理」文字按钮 + 右下角一个「＋」悬浮球**：
 * 两个动作各占一个角，视线在屏幕上要跑两趟；悬浮球还压着列表最后一张卡
 * （所以列表尾巴上被迫留了 72dp 空白）。收到一条栏里之后两个动作并排、
 * 都能写全名（悬浮球只能画一个 +），列表也不再被遮。
 *
 * ## 为什么两个按钮**一实一虚**（"美观"落在这里）
 * 它们不是平级的：新增商品是日常动作、分类管理是偶尔才动一次的设置。
 * 所以右边用实底主按钮（[PrimaryActionButton]，与"提交订单"同一个组件）、
 * 左边用描边次按钮 —— 一眼能看出哪个是主操作。
 * 宽度也按主次分（`weight(1f)` : `weight(1.4f)`），不是两个等宽的方块。
 *
 * 颜色用**商品管理的语义色紫** `ProductPurple`（一色一功能）：这一栏里的两个动作
 * 都属于商品管理，紫是这一块的识别色（卡片上那个「改价」也是它）。
 * ⛔ 不要用钱的橙：同屏「售价」那个数字已经是橙的，会撞色（用户当天刚为这件事改过一次）。
 */
@Composable
private fun ProductsBottomBar(onCategories: () -> Unit, onAdd: () -> Unit) {
    Surface(shadowElevation = 8.dp) {
        Row(
            Modifier
                .fillMaxWidth()
                // 底部系统导航条留白：这一栏不是 M3 的 NavigationBar，不会自己处理 insets
                .navigationBarsPadding()
                .padding(horizontal = 16.dp, vertical = 12.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            OutlinedButton(
                onClick = onCategories,
                modifier = Modifier.weight(1f).height(56.dp),
                shape = MaterialTheme.shapes.medium,
                border = BorderStroke(1.5.dp, Color(ProductPurple)),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = Color(ProductPurple)),
            ) {
                Icon(Icons.Default.Category, contentDescription = null, modifier = Modifier.size(20.dp))
                Spacer(Modifier.width(6.dp))
                Text("分类管理", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
            }
            PrimaryActionButton(
                text = "商品新增",
                onClick = onAdd,
                icon = Icons.Default.Add,
                containerColor = Color(ProductPurple),
                modifier = Modifier.weight(1.4f),
            )
        }
    }
}

/**
 * 商品卡：**一眼看完"卖多少钱、还剩多少"**，动作收进右上角「⋮」、快捷改价在它下面。
 *
 * ## 为什么三个按钮收进菜单（用户 2026-09-19）
 * 原话：「红色框的也就是右边 3 个按钮太占位置了，把在保证按钮性的同时，又让他不占位子」。
 * 三个动作各占一个 `IconButton` 的宽度、横着排，把**商品名和关键数字挤成两行灰字**——
 * 而那正是这一页真正要看的。收进 `DropdownMenu` 之后：动作一个没少
 * （可发现性靠标准的「⋮」），腾出来的整条右边都还给信息。
 *
 * ## 信息为什么用"图标 + 语义色"（用户 2026-09-19）
 * 原话：「那些信息是在商品管理中非常重要的，不一定非要等编辑才能看得到，
 * 我们要用对应的语义色和图标在它的名字的下面进行显示，让人一眼就能看出来」。
 *
 * | 信息 | 颜色 | 图标 | 为什么是这个色 / 为什么在卡上 |
 * |---|---|---|---|
 * | 售价 | 金橙 `MoneyOrange` | `Sell` | 系统里"钱"的语义色（账本/报表/小计同色） |
 * | 库存 | 蓝青 `#00BCD4`（= 库存管理模块色） | `Inventory2` | 跨端同功能同色：这个数字属于库存管理 |
 *
 * ⚠️ **库存还会按状态变色**：0 → 红（没货了）、≤ 报警阈值 → 黄。这两个颜色不是装饰，
 * 是"这一行要你处理"的信号：派单员扫列表时靠它决定先看哪几个。
 *
 * ⛔ **成本价与分类都不在卡上**（都是用户 2026-09-19 明确要求去掉的）：
 * 成本是内部数、不参与对客户报价，只在「⋮ → 编辑」里看和改；
 * 分类已经由**左边那根导航条**表达，同一件事在一屏说两遍只占地方。
 */
@Composable
private fun ProductCard(
    p: ProductDto,
    acting: Boolean,
    onEdit: () -> Unit,
    onToggle: () -> Unit,
    onDelete: () -> Unit,
    onOpenPricing: () -> Unit,
    onQuickPrice: () -> Unit,
    onCostHistory: () -> Unit,
) {
    var menu by remember { mutableStateOf(false) }

    SectionCard {
        Row(verticalAlignment = Alignment.Top) {
            // 商品图
            Box(
                Modifier
                    .size(52.dp)
                    .clip(MaterialTheme.shapes.medium)
                    .background(MaterialTheme.colorScheme.surfaceVariant),
                contentAlignment = Alignment.Center,
            ) {
                if (p.imageUrl != null) {
                    AsyncImage(
                        model = resolveStaticUrl(p.imageUrl),
                        contentDescription = p.name,
                        contentScale = ContentScale.Crop,
                        modifier = Modifier.fillMaxSize(),
                    )
                } else {
                    Icon(
                        Icons.Default.Inventory2,
                        contentDescription = null,
                        tint = Color(android.graphics.Color.parseColor(p.nameColor ?: "#1565C0")),
                    )
                }
            }
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        p.name,
                        style = MaterialTheme.typography.titleSmall,
                        color = Color(android.graphics.Color.parseColor(p.nameColor ?: "#1565C0")),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f, fill = false),
                    )
                    if (!p.isActive) {
                        Spacer(Modifier.width(6.dp))
                        Surface(color = MaterialTheme.colorScheme.surfaceVariant, shape = MaterialTheme.shapes.small) {
                            Text(
                                "已下架",
                                style = MaterialTheme.typography.labelMedium,
                                modifier = Modifier.padding(horizontal = 6.dp, vertical = 1.dp),
                            )
                        }
                    }
                }
                ProductFacts(p)
            }
            // 右侧一列：上面是「⋮」菜单，**下面是空的 —— 放一个「改价」快捷入口**。
            //
            // 用户 2026-09-19 的原话：「商品右上角不是有 3 个点吗？那是我们的正常设置。
            // 我们在它的下面，因为下面比较空嘛，在下面再加一个改价，这个改价就是改默认的售价，
            // 方便嘛、快捷」。
            //
            // 为什么值得单独做：改售价是**最高频的日常操作**（进价一变就要改），
            // 而原来必须先点「⋮ → 编辑」打开整个抽屉、滚到价格那一段、改完再保存。
            // 现在一步到位，而且**只 PATCH 这一个字段**（不会碰到别的字段）。
            // 位置也刚好：这一列本来只有顶部一个 ⋮，下面全是空白，加它不会让卡片变高。
            Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.width(46.dp)) {
                Box {
                    IconButton(onClick = { menu = true }, modifier = Modifier.size(36.dp)) {
                        Icon(Icons.Default.MoreVert, contentDescription = "更多操作", modifier = Modifier.size(20.dp))
                    }
                    DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                        DropdownMenuItem(
                            text = { Text("各批发商价格") },
                            leadingIcon = { Icon(Icons.Default.Sell, contentDescription = null, tint = Color(MoneyOrange)) },
                            onClick = { menu = false; onOpenPricing() },
                        )
                        DropdownMenuItem(
                            text = { Text(if (p.isActive) "下架" else "上架") },
                            leadingIcon = {
                                Icon(
                                    if (p.isActive) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                                    contentDescription = null,
                                    tint = if (p.isActive) MaterialTheme.colorScheme.error else com.tapmoay.sorders.ui.theme.Success,
                                )
                            },
                            onClick = { menu = false; onToggle() },
                        )
                        // 成本价历史（用户 2026-09-19 要的溯源能力）：这个价从什么时候到什么时候是多少。
                        // 只读 —— 改价只有两个入口（这里下面那个快捷改价改售价；成本价在编辑页/进货时改）。
                        DropdownMenuItem(
                            text = { Text("成本价历史") },
                            leadingIcon = {
                                Icon(Icons.Default.History, contentDescription = null, tint = Color(QuickPriceGreen))
                            },
                            onClick = { menu = false; onCostHistory() },
                        )
                        DropdownMenuItem(
                            text = { Text("编辑") },
                            leadingIcon = { Icon(Icons.Default.Edit, contentDescription = null) },
                            onClick = { menu = false; onEdit() },
                    )
                    DropdownMenuItem(
                        text = { Text("删除", color = MaterialTheme.colorScheme.error) },
                        leadingIcon = {
                            Icon(Icons.Default.DeleteOutline, contentDescription = null, tint = MaterialTheme.colorScheme.error)
                        },
                        onClick = { menu = false; onDelete() },
                    )
                }
                }
                // 「改价」：只改默认售价（用户要的快捷入口，见上面那段注释）
                //
                // ⚠️ 颜色用**低饱和绿** `QuickPriceGreen`（用户 2026-09-19 第二次点名这个按钮：
                //    「你商品页面那个改价的那个图标颜色呀，不要用紫色，用绿色，是那种低饱和的绿色」）。
                //    上一版是商品管理的模块紫 —— 而这一页**同屏已经有两处紫**了
                //    （底部导航栏的「商品新增 / 分类管理」），三处紫会让人以为它们是同一类动作。
                //    而钱的橙更不行：旁边「售价」那个数字就是橙的，那是第一版就撞过的色。
                Column(
                    Modifier
                        .clip(MaterialTheme.shapes.small)
                        .clickable(enabled = !acting, onClick = onQuickPrice)
                        .padding(horizontal = 6.dp, vertical = 4.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Icon(
                        Icons.Default.CurrencyYuan,
                        contentDescription = "改价",
                        tint = Color(QuickPriceGreen),
                        modifier = Modifier.size(18.dp),
                    )
                    Text("改价", style = MaterialTheme.typography.labelSmall, color = Color(QuickPriceGreen))
                }
            }
        }
    }
}

/**
 * 成本价历史（只读）：**这个商品的价格从什么时候到什么时候是多少**。
 *
 * 用户 2026-09-19：「我们保留的时候不仅保留成本价，还保留这个成本价存在的时间，
 * 比如说他是从什么时候开始变的、从什么时候结束的，精确到小时和分钟，
 * 这样子的话，我们就能方便且精确地算出来在这段时间的毛利率是多少」。
 *
 * 三件事必须说清楚，少一件这张表就会骗人：
 * 1. **时间要换算到设备时区**（后端发的是 naive UTC）—— 直接用会早 8 小时，
 *    而"这段时间"算错 8 小时正是这个功能要消灭的东西（见 `util/TimeFmt.kt`）；
 * 2. **最后一段写「至今」**，不是一个空白或一个假的结束时间；
 * 3. **来源要标出来**（建商品 / 进货 / 编辑 / 老数据回填）—— 尤其 `BACKFILL`：
 *    那一段的起点是"商品创建时间"，是**推断**出来的，不是真的那一刻改的价，
 *    不标出来用户会拿它去对账。
 */
@Composable
private fun CostHistoryDialog(
    p: ProductDto,
    rows: List<ProductCostHistoryDto>,
    loading: Boolean,
    onDismiss: () -> Unit,
) {
    val unit = p.unit.ifBlank { "件" }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("成本价历史", maxLines = 1, overflow = TextOverflow.Ellipsis) },
        text = {
            Column {
                Text(
                    p.name,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Spacer(Modifier.height(10.dp))
                when {
                    loading -> Row(verticalAlignment = Alignment.CenterVertically) {
                        CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                        Spacer(Modifier.width(8.dp))
                        Text("加载中…", style = MaterialTheme.typography.bodySmall)
                    }
                    rows.isEmpty() -> Text(
                        "这个商品还没有成本价记录。入库时填「进货价」、或在编辑页填成本价，之后每次改动都会记一段。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    else -> Column(
                        Modifier.heightIn(max = 360.dp).verticalScroll(rememberScrollState()),
                        verticalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        rows.forEach { h ->
                            CostHistoryRow(h, unit)
                        }
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("关闭") } },
    )
}

@Composable
private fun CostHistoryRow(h: ProductCostHistoryDto, unit: String) {
    val live = h.effectiveTo == null
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                "¥" + trimMoneyZeros(h.costPrice) + " / " + unit,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Bold,
                color = Color(QuickPriceGreen),
                modifier = Modifier.weight(1f),
            )
            if (live) {
                Surface(color = Color(0xFFE3F1E8), shape = MaterialTheme.shapes.small) {
                    Text(
                        "至今",
                        style = MaterialTheme.typography.labelSmall,
                        color = Color(QuickPriceGreen),
                        modifier = Modifier.padding(horizontal = 6.dp, vertical = 1.dp),
                    )
                }
            }
        }
        Spacer(Modifier.height(2.dp))
        Text(
            formatDateTime(h.effectiveFrom) + " 起" +
                (h.effectiveTo?.let { " ～ " + formatDateTime(it) } ?: "（仍在使用）"),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        val src = when (h.source) {
            "CREATE" -> "建商品时填的"
            "PURCHASE" -> "进货时录的"
            "BACKFILL" -> "老数据回填（起点取商品创建时间，是推断值）"
            else -> "在编辑页改的"
        }
        Text(src, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
    }
}

/**
 * 快捷改价弹窗：**只改默认售价**，不动别的字段。
 *
 * 为什么单独做一个（而不是复用商品编辑抽屉）：用户要的是"方便、快捷" ——
 * 改售价是最高频的动作，而走抽屉要先点开、滚到价格段、再保存。
 * 这里保存走的是 `PATCH /products/{id}` 的**部分更新**（只放 `default_unit_price`），
 * 所以不会顺手改掉别的字段。
 */
@Composable
private fun QuickPriceDialog(
    p: ProductDto,
    busy: Boolean,
    onConfirm: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    // 预填时去掉尾部多余的 0（后端单价是 Numeric(14,4)，直接显示会是 "12.5000"）；
    // ⚠️ 用 trimMoneyZeros 而不是 formatMoney —— 后者只留两位小数，会把 12.3456 显示成 12.35
    var price by remember { mutableStateOf(trimMoneyZeros(p.defaultUnitPrice)) }
    val unit = p.unit.ifBlank { "件" }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("改默认售价", maxLines = 1, overflow = TextOverflow.Ellipsis) },
        text = {
            Column {
                Text(p.name, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = price,
                    // 单价规则唯一实现在 core/InputRules.kt（4 位小数：库里的单价列是 Numeric(14,4)）
                    onValueChange = { price = InputRules.priceInput(it) },
                    label = { Text("售价（元 / $unit）") },
                    singleLine = true,
                    keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(
                        keyboardType = androidx.compose.ui.text.input.KeyboardType.Decimal,
                    ),
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(6.dp))
                Text(
                    "只改这一个价，不动名称、成本、库存、分类。批发商的专属价在「各批发商价格」里单独设。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        },
        confirmButton = {
            TextButton(
                enabled = !busy && price.toDoubleOrNull() != null,
                onClick = { onConfirm(price) },
            ) { Text(if (busy) "保存中…" else "保存") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}

/**
 * 商品卡上那两个数字（图标 + 语义色），**一个一行**。
 *
 * ## 为什么一个一行（用户 2026-09-19）
 * 原话：「那个库存……在成本价的后面，这个不要有，他们全在成本价的下面」——
 * 原来用 `FlowRow` 流式排列，`成本 ¥0.00` 短的时候 `库存` 会被挤到**同一行**、
 * 长的时候又自己换行，于是**每张卡长得都不一样**（列表看起来是毛的）。
 * 现在固定一行一个：既不会出现"这个挤一起、那个换行"，数字也**在竖直方向对齐成一列**，
 * 扫一列价格比扫一片流式文本快得多。
 *
 * ## 为什么没有「成本」（同一天用户要求）
 * 原话：「商品管理界面不要有成本价的显示，成本价是要在编辑里面才会有」。
 * 成本是**内部数**，不参与对客户报价，放在每天扫的列表里只是噪音；
 * 要看/要改都在「⋮ → 编辑」，进货时也能顺手改（见库存页的「进货价」）。
 */
@Composable
private fun ProductFacts(p: ProductDto) {
    val unit = p.unit.ifBlank { "件" }
    Column(Modifier.fillMaxWidth().padding(top = 6.dp), verticalArrangement = Arrangement.spacedBy(3.dp)) {
        Fact(Icons.Default.Sell, "售价", "¥" + formatMoney(p.defaultUnitPrice) + "/" + unit, Color(MoneyOrange))
        Fact(Icons.Default.Inventory2, "库存", "${p.stock} $unit", stockColor(p))
    }
}

@Composable
private fun Fact(icon: androidx.compose.ui.graphics.vector.ImageVector, label: String, value: String, color: Color) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Icon(icon, contentDescription = null, tint = color, modifier = Modifier.size(13.dp))
        Spacer(Modifier.width(3.dp))
        Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.width(3.dp))
        Text(
            value,
            style = MaterialTheme.typography.labelMedium,
            fontWeight = FontWeight.Bold,
            color = color,
            maxLines = 1,
        )
    }
}

/** 库存的颜色 = 状态：0 红（断货）、≤ 报警阈值 黄、其余用库存管理的语义色。 */
private fun stockColor(p: ProductDto): Color = when {
    p.stock <= 0 -> Color(0xFFE53935)
    p.lowStockAlert > 0 && p.stock <= p.lowStockAlert -> Color(0xFFFFB300)
    else -> Color(0xFF00BCD4)
}

/**
 * 商品编辑页里"就地新建分类"的小弹窗。
 *
 * 与「分类管理」页那个 [ProductCategoriesScreen] 里的新建是同一件事，但**不共用**那个弹窗：
 * 那一页还要解释"改名会级联改商品"，这里只要一个名字。重复的是一个 12 行的输入框，
 * 而抽公共组件要给它加三个用不上的参数 —— 不值。
 */
@Composable
private fun NewCategoryDialog(
    busy: Boolean,
    onConfirm: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    var name by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("新建分类") },
        text = {
            Column {
                SoTextField(
                    value = name,
                    onValueChange = { name = it.take(8) },
                    placeholder = "分类名，如 饮料 / 粮油 / 日化",
                )
                Spacer(Modifier.height(8.dp))
                Text(
                    "建好后会自动选中它。顺序到「分类管理」里排。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
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
