package com.tapmoay.sorders.ui.dispatcher

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.AddAPhoto
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.ProductPurple
import com.tapmoay.sorders.util.resolveStaticUrl
import java.io.File

/**
 * 「新增 / 编辑商品」——**单独一页**（2026-09-21 商品管理改版第 1 期，P7）。
 *
 * ## 用户原话（这一页存在的理由）
 * > 「这是他的新建商品的界面，我们也改一下我们的新建商品的界面——
 * >   **不是很好看，也太乱了**。当然，同样的道理，他有的没必要的东西嘛，不要加，
 * >   我们按照我们的来就行了，**只是照抄他的样式**。」
 *
 * 照抄的是**排版**：整页 + 白卡分段 + **每行"标签在左 / 值在右 / 能进二级的带 `>`"** +
 * 顶部一个大方形的商品图片位 + 底部一对按钮。行本身在 `ui/common/FormRows.kt`（共用）。
 *
 * ⛔ 它那些**没必要的东西一个都没加**：采购单位 / 条形码 / 支持超卖 / 仅套餐售卖 / 金融分组 /
 * 必点商品 / 时价商品 / 库存扣减方式 / 后厨打印机 / 档口 / 供应商 / 产地 / 打印标签 /
 * 销售时段 —— 逐条理由见 `docs/plan-product-management.md` §4。
 *
 * ## 为什么从"底部抽屉"改成"单独一页"
 * ① 参考图就是整页；② 用户**后来**自己定了「新增开销 = 单独一页，「就相当于新增订单一样」」
 * （`ExpenseCreateScreen` 就是"整页 + `TopAppBar` + 白卡 + 底部按钮"，已经是家里表单页的样板）；
 * ③ 这一页要**从二级选择页挑单位与分组**，抽屉里再叠弹层是两层 modal 压着。
 *
 * ## ⛔ 旧页面里两处"会改到钱 / 会撒谎"的地方，这一版都修掉了
 * 见 `ProductFormViewModel` 的类注释（整份回传 → 只发改动的键；预填金额 `formatMoney` → `trimMoneyZeros`）。
 * 另外第三处：原来那个「移除图片」按钮**只清本地草稿**，对已有图片的商品点它再保存，
 * 服务端那张图**原样还在**（界面上像是删掉了）—— 现在它真的会写 `image_url=""`。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProductFormScreen(
    container: AppContainer,
    productId: Long?,
    onBack: () -> Unit,
    /**
     * 打开「各批发商价格」（价格矩阵的"按商品"方向）。
     *
     * ⚠️ 这个入口**原来在商品卡的 `⋮` 菜单里**，用户 2026-09-21 要求把 ⋮ 的功能搬进编辑页，
     * 于是它成了这一页的一行（`NavGraph` 那边也改成把 lambda 传到这里）。
     */
    onOpenPricing: (Long) -> Unit = {},
) {
    val vm: ProductFormViewModel = appViewModel { ProductFormViewModel(container, productId) }
    val snackbar = remember { SnackbarHostState() }
    val context = LocalContext.current

    // 本页提示（"已添加，可以接着录"）与"该退出去了"
    OneShotSnackbar(snackbar, vm.notice, onConsumed = { vm.notice = null })
    LaunchedEffect(vm.closeRequested) { if (vm.closeRequested) onBack() }

    var showUnitPicker by remember { mutableStateOf(false) }
    var showCategoryPicker by remember { mutableStateOf(false) }
    var moreOpen by remember { mutableStateOf(false) }
    var confirmingDelete by remember { mutableStateOf(false) }

    // 相册选图 → 拷贝到缓存 → 交给 VM（与旧页面同一条路径，上传时机也没变）
    val pickImage = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri != null) {
            try {
                val f = File(context.cacheDir, "product_img_" + System.currentTimeMillis() + ".jpg")
                context.contentResolver.openInputStream(uri)?.use { input ->
                    f.outputStream().use { output -> input.copyTo(output) }
                }
                vm.pickImage(f.absolutePath)
            } catch (_: Exception) {
                vm.error = "图片读取失败，请重试"
            }
        }
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
                title = { Text(if (vm.isNew) "新增商品" else "编辑商品", style = MaterialTheme.typography.titleLarge) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
        bottomBar = { ProductFormBottomBar(vm = vm) },
    ) { padding ->
        when {
            vm.loading -> LoadingBox(Modifier.padding(padding))
            vm.loadError != null -> ErrorView(vm.loadError.orEmpty(), onRetry = { vm.load() }, modifier = Modifier.padding(padding))
            else -> Column(
                Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = 16.dp),
            ) {
                Spacer(Modifier.height(6.dp))

                // ---- 商品图片（参考图顶上那一大块）----
                ProductImageBlock(
                    localPath = vm.imageLocal,
                    remoteUrl = vm.currentImageUrl,
                    onPick = { pickImage.launch("image/*") },
                    onRemove = { vm.removeImage() },
                )

                Spacer(Modifier.height(14.dp))

                // ---- 基本信息 ----
                SectionCard {
                    FormInputRow(
                        label = "商品名称",
                        value = vm.name,
                        onValueChange = { vm.name = it },
                        placeholder = "请输入商品名",
                        required = true,
                    )
                    if (vm.isNew) {
                        FormInputRow(
                            label = "库存",
                            value = vm.stock,
                            onValueChange = { vm.stock = InputRules.intInput(it, 7) },
                            placeholder = "初始库存（选填）",
                            required = true,
                            keyboardType = androidx.compose.ui.text.input.KeyboardType.Number,
                        )
                    } else {
                        // 编辑时**不给改**：库存只能走出入库流水（`PATCH /products` 根本不收 stock）。
                        // 写成一行不可点的灰字，而不是一个禁用的输入框 —— 禁用框会让人反复去点。
                        FormRow(label = "库存") {
                            Text(
                                "${vm.stock.ifBlank { "0" }}（由出入库流水维护）",
                                style = MaterialTheme.typography.bodyLarge,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                    FormPickRow(
                        label = "单位",
                        value = vm.unit,
                        onClick = { showUnitPicker = true },
                        placeholder = "请选择单位",
                        required = true,
                    )
                    FormPickRow(
                        label = "商品分组",
                        value = vm.category,
                        onClick = { showCategoryPicker = true },
                        placeholder = "未分类",
                    )
                    FormInputRow(
                        label = "售价",
                        value = vm.price,
                        onValueChange = { vm.price = InputRules.priceInput(it) },
                        placeholder = "请输入",
                        required = true,
                        keyboardType = androidx.compose.ui.text.input.KeyboardType.Decimal,
                    )
                    FormSwitchRow(
                        label = "上架销售",
                        checked = vm.active,
                        onCheckedChange = { vm.active = it },
                    )
                }

                Spacer(Modifier.height(10.dp))
                Hint(
                    if (vm.isNew) "新建默认上架；关闭开关则保存后货主下单时看不到它。"
                    else "下架后货主下单时不可选，但已有订单不受影响。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.outline,
                    modifier = Modifier.padding(horizontal = 4.dp),
                )

                Spacer(Modifier.height(10.dp))

                // ---- 更多设置（参考图里那个可折叠的"更多设置"）----
                SectionCard {
                    FormRow(label = "更多设置", onClick = { moreOpen = !moreOpen }) {
                        Icon(
                            if (moreOpen) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    if (moreOpen) {
                        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                        FormInputRow(
                            label = "成本价",
                            value = vm.cost,
                            onValueChange = { vm.cost = InputRules.priceInput(it) },
                            placeholder = "选填，报表算毛利用",
                            keyboardType = androidx.compose.ui.text.input.KeyboardType.Decimal,
                        )
                        FormInputRow(
                            label = "库存报警",
                            value = vm.alert,
                            onValueChange = { vm.alert = InputRules.intInput(it, 7) },
                            placeholder = "低于该值提醒（0=不报警）",
                            keyboardType = androidx.compose.ui.text.input.KeyboardType.Number,
                        )
                        FormRow(label = "名称颜色") {
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                vm.colorOptions.forEach { (hex, _) ->
                                    Box(
                                        Modifier
                                            .size(26.dp)
                                            .background(productNameColor(hex), CircleShape)
                                            .clickable { vm.color = hex },
                                        contentAlignment = Alignment.Center,
                                    ) {
                                        if (vm.color == hex) {
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
                        }
                    }
                }

                Spacer(Modifier.height(10.dp))

                // ---- 更多操作（**原来是卡片右上角那个「⋮」里的三项**）----
                //
                // 用户 2026-09-21：「那 3 个点啊，就到编辑里面选…那 3 点的这个功能到编辑里面去」。
                // 于是卡片上只留「改价 / 沽清(上架) / 编辑」三个按钮，这三项搬到这里。
                if (!vm.isNew) {
                    SectionCard {
                        FormPickRow(
                            label = "各批发商价格",
                            value = "",
                            placeholder = "查看与设置",
                            onClick = { productId?.let(onOpenPricing) },
                        )
                        FormPickRow(
                            label = "成本价历史",
                            value = "",
                            placeholder = "这个价从什么时候到什么时候",
                            onClick = { vm.openCostHistory() },
                        )
                        FormRow(label = "删除商品", onClick = { confirmingDelete = true }) {
                            Text(
                                "删 除",
                                style = MaterialTheme.typography.titleSmall,
                                fontWeight = FontWeight.Bold,
                                color = MaterialTheme.colorScheme.error,
                            )
                        }
                    }
                    Spacer(Modifier.height(6.dp))
                    Hint(
                        "删除是软删：商品从列表里消失，但数据和账都留着 —— 列表顶端的「回收站」里能把它恢复回来。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.outline,
                        modifier = Modifier.padding(horizontal = 4.dp),
                    )
                    Spacer(Modifier.height(10.dp))
                }

                Spacer(Modifier.height(12.dp))
                FormErrorLine(vm.error)

                // 成本价的口径那句：它是"解释句"，走 Hint（总开关关掉就不显示）
                Spacer(Modifier.height(6.dp))
                Hint(
                    "成本价用于报表计算毛利率，留空按 0 计；改过之后会记一段生效区间，上面那一行「成本价历史」里能查。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.outline,
                    modifier = Modifier.padding(horizontal = 4.dp),
                )
                Spacer(Modifier.height(16.dp))
            }
        }
    }

    if (showUnitPicker) {
        UnitPickerSheet(
            current = vm.unit,
            onPick = { vm.unit = it; showUnitPicker = false },
            onDismiss = { showUnitPicker = false },
        )
    }

    if (showCategoryPicker) {
        CategoryPickerSheet(
            title = "请选择商品分组",
            choices = vm.categories.map { CategoryChoice(it.name, "${it.productCount} 个商品") },
            current = vm.category,
            onPick = { vm.category = it; showCategoryPicker = false },
            onDismiss = { showCategoryPicker = false },
            onCreate = { name -> vm.createCategoryAndSelect(name) },
        )
    }

    // 删除确认：**说清是软删、去哪恢复**（用户 2026-09-20 的硬规矩：删除一律软删 + 界面上要有恢复入口）
    if (confirmingDelete) {
        DangerConfirmDialog(
            title = "删除商品「${vm.name}」？",
            message = "删除是软删：它从商品列表里消失，但库存流水、订单行、账本都原样留着。" +
                "列表顶端的「回收站」里可以把它恢复回来。",
            confirmText = "删除",
            onConfirm = { confirmingDelete = false; vm.delete { onBack() } },
            onDismiss = { confirmingDelete = false },
        )
    }

    // 成本价历史（只读）：**原来是商品卡 ⋮ 里的那一项**，现在挂在编辑页
    val loaded = vm.loaded
    if (loaded != null && vm.showCostHistory) {
        CostHistoryDialog(
            p = loaded,
            rows = vm.costHistory,
            loading = vm.costHistoryLoading,
            onDismiss = { vm.showCostHistory = false },
        )
    }
}

/**
 * 顶上的商品图片位：**有图显示图、没图显示一个浅描边方框 + 相机图标**（参考图顶上那一块）。
 *
 * ⚠️ 参考图那个占位框是**虚线**；我们这里用实线浅描边 —— 虚线要么自己画（红线「自己画的图
 * 只许在 `Charts.kt`」盯着 `Canvas`），要么为一个占位框新增一个 drawable 资源。
 * 两条都不值当，所以形态抄了、线型没抄（这是这一页唯一一处"没照抄"）。
 */
@Composable
private fun ProductImageBlock(
    localPath: String?,
    remoteUrl: String?,
    onPick: () -> Unit,
    onRemove: () -> Unit,
) {
    Column(
        Modifier.fillMaxWidth().padding(vertical = 10.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(
            Modifier
                .size(168.dp)
                .clip(MaterialTheme.shapes.medium)
                .clickable(onClick = onPick),
            contentAlignment = Alignment.Center,
        ) {
            when {
                localPath != null -> AsyncImage(
                    model = File(localPath),
                    contentDescription = "商品图",
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize().clip(MaterialTheme.shapes.medium),
                )
                remoteUrl != null -> AsyncImage(
                    model = resolveStaticUrl(remoteUrl),
                    contentDescription = "商品图",
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize().clip(MaterialTheme.shapes.medium),
                )
                else -> Box(
                    Modifier
                        .fillMaxSize()
                        .border(1.dp, MaterialTheme.colorScheme.outlineVariant, MaterialTheme.shapes.medium),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        Icons.Default.AddAPhoto,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.outline,
                        modifier = Modifier.size(32.dp),
                    )
                }
            }
        }
        Spacer(Modifier.height(6.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("商品图片", style = MaterialTheme.typography.bodyMedium)
            if (localPath != null || remoteUrl != null) {
                Spacer(Modifier.width(10.dp))
                TextButton(onClick = onRemove) { Text("移除", color = MaterialTheme.colorScheme.error) }
            }
        }
    }
}

/**
 * 底部那一对按钮（参考图：左边"完成并继续"、右边"确认"）。
 *
 * 我们这一版：**新增**时左「保存并再添加一个」（描边，次）+ 右「保存」（实底紫，主）；
 * **编辑**时只有右「保存」占满 —— 编辑没有"再来一个"这回事。
 * ⚠️ 用商品管理的**模块色紫**（一色一功能），不要用钱的橙：同屏「售价」那个值已经是橙的。
 */
@Composable
private fun ProductFormBottomBar(vm: ProductFormViewModel) {
    Surface(shadowElevation = 8.dp) {
        Row(
            Modifier
                .fillMaxWidth()
                .navigationBarsPadding()
                .padding(horizontal = 16.dp, vertical = 12.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (vm.isNew) {
                OutlinedButton(
                    onClick = { vm.save(andContinue = true) },
                    enabled = !vm.saving,
                    modifier = Modifier.weight(1f).height(52.dp),
                    shape = MaterialTheme.shapes.medium,
                ) { Text("保存并再添加", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold) }
            }
            Button(
                onClick = { vm.save(andContinue = false) },
                enabled = !vm.saving,
                modifier = Modifier.weight(if (vm.isNew) 1.4f else 1f).height(52.dp),
                shape = MaterialTheme.shapes.medium,
                colors = ButtonDefaults.buttonColors(containerColor = Color(ProductPurple)),
            ) {
                Text(
                    if (vm.saving) "保存中…" else "保存",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Bold,
                )
            }
        }
    }
}
