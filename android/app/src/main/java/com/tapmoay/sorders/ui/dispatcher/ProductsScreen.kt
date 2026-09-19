package com.tapmoay.sorders.ui.dispatcher

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
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
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import coil.compose.AsyncImage
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.util.formatMoney
import com.tapmoay.sorders.util.resolveStaticUrl
import java.io.File

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProductsScreen(
    container: AppContainer,
    onBack: () -> Unit,
    onOpenCategories: () -> Unit = {},
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
        Box(Modifier.fillMaxSize().padding(padding)) {
            when {
                vm.loading -> LoadingBox()
                vm.loadError != null && vm.products.isEmpty() -> ErrorView(vm.loadError.orEmpty(), onRetry = { vm.load() })
                vm.products.isEmpty() -> EmptyView("暂无商品，点击右下角新增", Modifier.align(Alignment.Center))
                else -> LazyColumn(
                    Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(vm.products, key = { it.id }) { p ->
                        ProductCard(
                            p = p,
                            onEdit = { vm.openEdit(p) },
                            onToggle = { vm.toggleActive(p) },
                            onDelete = { vm.delete(p) },
                        )
                    }
                    item { Spacer(Modifier.height(72.dp)) }
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
                                onValueChange = { vm.draftPrice = it.filter { c -> c.isDigit() || c == '.' } },
                                label = { Text("默认售价（必填）") },
                                singleLine = true, modifier = Modifier.weight(1f),
                            )
                            OutlinedTextField(
                                value = vm.draftCost,
                                onValueChange = { vm.draftCost = it.filter { c -> c.isDigit() || c == '.' } },
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

                        Spacer(Modifier.height(12.dp))
                        Text("批发价（可选，可多档）", style = MaterialTheme.typography.bodySmall)
                        Spacer(Modifier.height(6.dp))
                        vm.draftTiers.forEachIndexed { idx, tier ->
                            Row(
                                Modifier.fillMaxWidth().padding(bottom = 8.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(
                                    tier.label.ifBlank { "批发价" },
                                    style = MaterialTheme.typography.bodyLarge,
                                    color = MaterialTheme.colorScheme.onSurface,
                                    modifier = Modifier.width(72.dp),
                                )
                                Spacer(Modifier.width(8.dp))
                                OutlinedTextField(
                                    value = tier.price,
                                    onValueChange = { v -> vm.draftTiers[idx] = tier.copy(price = v.filter { c -> c.isDigit() || c == '.' }) },
                                    label = { Text("价格（元）") },
                                    singleLine = true, modifier = Modifier.weight(1f),
                                )
                                IconButton(onClick = { vm.removeTier(idx) }) {
                                    Icon(Icons.Default.DeleteOutline, contentDescription = "删除档位", modifier = Modifier.size(20.dp))
                                }
                            }
                        }
                        TextButton(onClick = { vm.addTier() }) {
                            Icon(Icons.Default.AddCircleOutline, contentDescription = null, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(4.dp))
                            Text("添加批发价")
                        }
                    }

                    Spacer(Modifier.height(10.dp))

                    // ---- 库存 ----
                    SectionCard {
                        Text("库存", style = MaterialTheme.typography.titleSmall)
                        Spacer(Modifier.height(4.dp))
                        SoTextField(
                            value = vm.draftStock,
                            onValueChange = { vm.draftStock = it.filter { c -> c.isDigit() } },
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
                        // 分类：选品页左侧导航的分组名。自由填（不是枚举）——"饮料/粮油/日化"
                        // 这种分法是店家的业务语言，写死一列选项只会逼着人选一个不对的。
                        SoTextField(
                            value = vm.draftCategory,
                            onValueChange = { vm.draftCategory = it.take(8) },
                            placeholder = "商品分类（选填，如 饮料 / 粮油 / 日化）",
                            modifier = Modifier.fillMaxWidth(),
                        )
                        Spacer(Modifier.height(4.dp))
                        Text(
                            "分类决定下单页「选择商品」左侧怎么分组；留空会归到「未分类」。",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.outline,
                        )
                        // 已有分类做成可点的小块：**防手打错字**。写错一个字（"饮料 " / "饮 料"）
                        // 在下单页就是左侧多一个几乎同名的分类，而列表上看不出差别。
                        // 顺序用**名册**（`vm.categories`，派单员排过的），不是从商品里推的 ——
                        // 从商品推的话这里和下单页左侧会是两种顺序。
                        val existingCats = remember(vm.categories) { vm.categories.map { it.name } }
                        if (existingCats.isNotEmpty()) {
                            Spacer(Modifier.height(6.dp))
                            Row(
                                Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                                horizontalArrangement = Arrangement.spacedBy(6.dp),
                            ) {
                                existingCats.forEach { c ->
                                    val on = vm.draftCategory.trim() == c
                                    Surface(
                                        shape = RoundedCornerShape(8.dp),
                                        color = if (on) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surfaceVariant,
                                        border = androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
                                        modifier = Modifier.clickable { vm.draftCategory = c },
                                    ) {
                                        Text(
                                            c,
                                            style = MaterialTheme.typography.labelMedium,
                                            color = if (on) Color.White else MaterialTheme.colorScheme.onSurfaceVariant,
                                            modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                                        )
                                    }
                                }
                            }
                        }
                        Spacer(Modifier.height(10.dp))
                        SoTextField(
                            value = vm.draftAlert,
                            onValueChange = { vm.draftAlert = it.filter { c -> c.isDigit() } },
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

@Composable
private fun ProductCard(
    p: ProductDto,
    onEdit: () -> Unit,
    onToggle: () -> Unit,
    onDelete: () -> Unit,
) {
    SectionCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
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
                        modifier = Modifier.weight(1f),
                    )
                    if (!p.isActive) {
                        Surface(color = MaterialTheme.colorScheme.surfaceVariant, shape = MaterialTheme.shapes.small) {
                            Text(
                                "已下架",
                                style = MaterialTheme.typography.labelMedium,
                                modifier = Modifier.padding(horizontal = 6.dp, vertical = 1.dp),
                            )
                        }
                    }
                }
                Spacer(Modifier.height(4.dp))
                Text(
                    "售价 ¥" + formatMoney(p.defaultUnitPrice) + "/" + p.unit.ifBlank { "件" } +
                        " · 成本 ¥" + formatMoney(p.costPrice) +
                        " · 库存 " + p.stock + " " + p.unit.ifBlank { "件" } +
                        " · " + p.category.trim().ifBlank { "未分类" },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (p.tierPrices.isNotEmpty()) {
                    Spacer(Modifier.height(2.dp))
                    Text(
                        p.tierPrices.joinToString(" · ") { "${it.label} ¥" + formatMoney(it.unitPrice) },
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.secondary,
                        maxLines = 1,
                    )
                }
            }
            TextButton(onClick = onToggle) {
                Text(
                    if (p.isActive) "下架" else "上架",
                    color = if (p.isActive) MaterialTheme.colorScheme.error else com.tapmoay.sorders.ui.theme.Success,
                    fontWeight = androidx.compose.ui.text.font.FontWeight.Bold,
                )
            }
            IconButton(onClick = onEdit) {
                Icon(Icons.Default.Edit, contentDescription = "编辑", modifier = Modifier.size(18.dp))
            }
            IconButton(onClick = onDelete) {
                Icon(Icons.Default.Delete, contentDescription = "删除", modifier = Modifier.size(18.dp), tint = MaterialTheme.colorScheme.error)
            }
        }
    }
}
