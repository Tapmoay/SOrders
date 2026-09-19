package com.tapmoay.sorders.ui.dispatcher

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.AddAPhoto
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.AddCircleOutline
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
import androidx.compose.ui.window.Dialog
import coil.compose.AsyncImage
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.ui.theme.ProductPurple
import com.tapmoay.sorders.util.formatMoney
import com.tapmoay.sorders.util.resolveStaticUrl
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
                actions = {
                    // 分类管理的入口放在**商品管理页**而不是工作台：分类只服务于选品页的分组，
                    // 它和商品是一件事，多一个工作台格子反而让人找不到。
                    TextButton(onClick = onOpenCategories) {
                        Icon(Icons.Default.Category, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(4.dp))
                        Text("分类管理")
                    }
                },
            )
        },
        floatingActionButton = {
            FloatingActionButton(onClick = { vm.openCreate() }) {
                Icon(Icons.Default.Add, contentDescription = "新增商品")
            }
        },
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
        val visible = remember(vm.products, category) {
            if (category == ALL_CATEGORY) vm.products else vm.products.filter { categoryOf(it) == category }
        }

        Box(Modifier.fillMaxSize().padding(padding)) {
            when {
                vm.loading -> LoadingBox()
                vm.loadError != null && vm.products.isEmpty() -> ErrorView(vm.loadError.orEmpty(), onRetry = { vm.load() })
                vm.products.isEmpty() -> EmptyView("暂无商品，点击右下角新增", Modifier.align(Alignment.Center))
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
                            // 空的是**这一分类**，不是整个商品库 —— 两句话不能混（混了用户会去新建重复商品）
                            EmptyView("「$category」下暂无商品", Modifier.align(Alignment.Center))
                        } else {
                            LazyColumn(
                                Modifier.fillMaxSize(),
                                contentPadding = PaddingValues(start = 10.dp, end = 10.dp, top = 10.dp, bottom = 12.dp),
                                verticalArrangement = Arrangement.spacedBy(8.dp),
                            ) {
                                items(visible, key = { it.id }) { p ->
                                    ProductCard(
                                        p = p,
                                        onEdit = { vm.openEdit(p) },
                                        onToggle = { vm.toggleActive(p) },
                                        onDelete = { vm.delete(p) },
                                        onOpenPricing = { onOpenPricing(p.id) },
                                    )
                                }
                                item { Spacer(Modifier.height(72.dp)) }
                            }
                        }
                    }
                }
            }
        }
    }

    // 新增/编辑 下拉抽屉（基础信息 / 价格与批发价 / 库存）
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
 * 商品卡：**一眼看完"卖多少钱、进价多少、还剩多少、属于哪一类"**，动作收进右上角「⋮」。
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
 * 所以四个数各自带图标与颜色 —— 扫一眼按颜色定位，不必读完整行字：
 *
 * | 信息 | 颜色 | 图标 | 为什么是这个色 |
 * |---|---|---|---|
 * | 售价 | 金橙 `MoneyOrange` | `Sell` | 系统里"钱"的语义色（账本/报表/小计同色） |
 * | 成本 | 中性灰 `#8A8A8E` | `Payments` | 它**也是钱**，但颜色在这里的作用是区分"对外的价"和"对内的成本"：两个都染橙的话，用户得读完字才知道哪个是卖价。成本不参与报价，中性灰最不容易看错 |
 * | 库存 | 蓝青 `#00BCD4`（= 库存管理模块色） | `Inventory2` | 跨端同功能同色：这个数字属于库存管理 |
 * | 分类 | 紫 `ProductPurple` | `Category` | 商品管理的模块色；**未分类**用提醒黄 —— 它是个待办（会让选品页多出一格） |
 *
 * ⚠️ **库存还会按状态变色**：0 → 红（没货了）、≤ 报警阈值 → 黄。这两个颜色不是装饰，
 * 是"这一行要你处理"的信号：派单员扫列表时靠它决定先看哪几个。
 */
@Composable
private fun ProductCard(
    p: ProductDto,
    onEdit: () -> Unit,
    onToggle: () -> Unit,
    onDelete: () -> Unit,
    onOpenPricing: () -> Unit,
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
            // 三个动作全在这里（用户要求"保证按钮性，又不占位子"）
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
        }
    }
}

/** 商品卡上那四个关键数字（图标 + 语义色）。配色依据见 [ProductCard] 的注释。 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ProductFacts(p: ProductDto) {
    val unit = p.unit.ifBlank { "件" }
    val category = p.category.trim()
    FlowRow(
        Modifier.fillMaxWidth().padding(top = 6.dp),
        horizontalArrangement = Arrangement.spacedBy(14.dp),
        verticalArrangement = Arrangement.spacedBy(3.dp),
    ) {
        Fact(Icons.Default.Sell, "售价", "¥" + formatMoney(p.defaultUnitPrice) + "/" + unit, Color(MoneyOrange))
        Fact(Icons.Default.Payments, "成本", "¥" + formatMoney(p.costPrice), Color(0xFF8A8A8E))
        Fact(Icons.Default.Inventory2, "库存", "${p.stock} $unit", stockColor(p))
        Fact(
            Icons.Default.Category,
            "分类",
            category.ifBlank { "未分类" },
            if (category.isBlank()) Color(0xFFFFB300) else Color(ProductPurple),
        )
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
