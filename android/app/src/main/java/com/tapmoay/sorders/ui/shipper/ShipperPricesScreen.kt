package com.tapmoay.sorders.ui.shipper

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.api.ShipperPriceDto
import com.tapmoay.sorders.data.remote.api.ShipperPriceProductDto
import com.tapmoay.sorders.data.remote.dto.ContactDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.ui.theme.ThemeGreen
import com.tapmoay.sorders.util.formatMoney

/**
 * 货主端「下游定价」（台账 L-38 / CHG-0077；2026-10-15 改版走**甲案** CHG-0131）。
 *
 * ## 一段话看懂这一页
 * 批发商货主在这里定「**我卖给下游多少钱**」：一件商品一个**默认价**（给全部下游），
 * 还能给**某一位**下游单独一个价（专人价）。派单员给他的价（「我拿货」）只是参考，
 * 不参与计算 —— 差额归他自己。
 *
 * ## 甲案：一件商品一张卡，默认价就在卡上改
 * 一张卡从上到下：商品名 / 单位 → 大字「卖给下游的价」＋「我拿货（参考）」→ **默认价的输入框 ＋ 保存**
 * → 「按人定价 · N 人」＋「定价」。**默认价不必进抽屉**；
 * 只有要给**某一个人**单独定价时，才点那个人右侧的「定价」进抽屉（见 [DownstreamPersonSheet]）。
 *
 * ## ⛔ 这一页只写不算
 * 单价原样填、原样提交，一分钱的算法全在后端（`order_money` 那一处）。
 * 界面上出现的每个数都是后端给的（含 [MoneyText] 里那句"我拿货"与"我的默认价"）。
 *
 * ## ⛔ 身份不对时**不拉列表**
 * 不是批发商、或他自己在「我的 → 管下游的账」里关掉了这本账 —— 都不是错误，
 * 而是**这一页对他不适用**：照后端 `_require_member` / `_require_downstream` 的
 * 那两句中文原样说清就行（见 [PriceGateCard]），一条列表都不拉。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ShipperPricesScreen(
    container: AppContainer,
    onBack: () -> Unit,
) {
    val vm: ShipperPricesViewModel = appViewModel { ShipperPricesViewModel(container) }
    val snackbar = remember { SnackbarHostState() }

    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            AppTopBar(
                title = "下游定价",
                onBack = onBack,
            )
        },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            when {
                !vm.loaded -> LoadingBox()
                // 拉不出来才占整屏：能拉到东西时错误只当一行提示（见下面那个 item）。
                vm.error != null && vm.products.isEmpty() && vm.canManageDownstream ->
                    ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
                else -> LazyColumn(
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    item { PriceRuleCard() }

                    if (vm.error != null) {
                        item { ErrorView(vm.error.orEmpty(), onRetry = { vm.load() }) }
                    }

                    if (!vm.canManageDownstream) {
                        item { PriceGateCard(isMember = vm.isMember) }
                    } else {
                        if (vm.products.isEmpty()) {
                            item {
                                EmptyView(
                                    "你能定价的商品还一个都没有 —— 先给自己下过单，或等派单员给你设一次专属价",
                                )
                            }
                        }
                        items(vm.products, key = { it.productId }) { product ->
                            DownstreamPriceCard(
                                product = product,
                                vm = vm,
                            )
                        }
                    }
                }
            }
        }
    }

    // 「给谁单独定价」抽屉：只有要动**某一个人**的价时才开（甲案）。
    val pricing = vm.products.firstOrNull { it.productId == vm.pricingProductId }
    if (pricing != null) {
        DownstreamPersonSheet(product = pricing, vm = vm)
    }

    // 删除要二次确认（会改变"以后下的单"怎么算），失败原因画在弹层自己里面。
    val deleting = vm.deleteTarget
    if (deleting != null) {
        DangerConfirmDialog(
            title = "删除这条价？",
            message = priceRowTitle(deleting) + "：" + deleteHint(deleting),
            confirmText = "删除",
            onConfirm = { vm.confirmDelete() },
            onDismiss = { vm.cancelDelete() },
            error = vm.formError,
            enabled = !vm.acting,
        )
    }
}

/** 这一页的规矩（用户 2026-10-06 的三条硬要求之一：先写清"怎么做"）。 */
@Composable
private fun PriceRuleCard() {
    SectionCard {
        Text("这一页定的是「你卖给下游多少钱」", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.height(8.dp))
        RuleLine("派单员给你的价（「我拿货」）只是参考 —— 不参与计算，差额归你自己。")
        RuleLine("不填就是没价：真正的算法只有后端那一处，这一页一个数都不算。")
        RuleLine("改价、删价都不追改已经下的单：老单按下单那一刻的价算。")
        RuleLine("删掉的行进回收站，能恢复；恢复只让它重新生效，不放回已经算过的钱。")
        RuleLine("默认价在这张卡上直接改；要给某一个人单独定价，点右边的「定价」。")
    }
}

@Composable
private fun RuleLine(text: String) {
    Row(Modifier.fillMaxWidth().padding(vertical = 2.dp), verticalAlignment = Alignment.Top) {
        Text("·", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.width(6.dp))
        Text(text, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

/**
 * 身份不对时的那张卡 —— 文案**逐字**是后端 403 里的原话（`api/v1/shipper_prices.py`）。
 *
 * ⛔ 不许自己改写成"你没有权限"这类话：那两句正是用户要认的（他才知道自己该去拨哪个开关）。
 */
@Composable
private fun PriceGateCard(isMember: Boolean) {
    SectionCard {
        Text(
            if (isMember) "这本账你自己关掉了" else "这一项对你不适用",
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.SemiBold,
        )
        Spacer(Modifier.height(8.dp))
        Text(
            if (isMember) {
                "你已经在「我的 → 管下游的账」里关掉了这本账 —— 要记下游的核销，先回去把它打开"
            } else {
                "只有批发商（高级货主）需要给下游货主核销 —— 普通货主是给自己下单、收自己的货，没有这一项"
            },
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/**
 * 一件商品一张卡（甲案）：
 * 上段 = 商品名 / 单位 ＋ 大字「卖给下游的价」＋「我拿货（参考）」—— 两个价放在一起，
 * 「我拿货 ¥17、我卖 ¥18」一眼就能对上；
 * 中段 = **默认价的输入框 ＋ 保存**（不必进抽屉）；
 * 下段 = 「按人定价 · N 人」＋「定价」—— 点它才进抽屉给某一个人单独定价。
 *
 * ⛔ 卡上的默认价取 `product.defaultUnitPrice`（商品列表端点自带），
 *    不在这里读 `vm.prices` —— 那里面只有抽屉开着的那件商品的价。
 */
@Composable
private fun DownstreamPriceCard(product: ShipperPriceProductDto, vm: ShipperPricesViewModel) {
    val fallback = product.defaultUnitPrice
    SectionCard {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(product.productName, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                Text(
                    "单位：" + (product.unit ?: "件"),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(
                if (fallback.isNullOrBlank()) "还没设默认价" else "已设默认价",
                style = MaterialTheme.typography.bodySmall,
                color = if (fallback.isNullOrBlank()) MaterialTheme.colorScheme.outline else Color(MoneyOrange),
            )
        }

        HorizontalDivider(Modifier.padding(vertical = 12.dp), color = MaterialTheme.colorScheme.outlineVariant)

        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Bottom) {
            Column(Modifier.weight(1f)) {
                if (fallback.isNullOrBlank()) {
                    Text(
                        "未设",
                        fontSize = 26.sp,
                        fontWeight = FontWeight.ExtraBold,
                        color = MaterialTheme.colorScheme.outline,
                    )
                } else {
                    Text(
                        "¥" + formatMoney(fallback),
                        fontSize = 26.sp,
                        fontWeight = FontWeight.ExtraBold,
                        color = Color(MoneyOrange),
                    )
                }
                Text(
                    "卖给下游的价",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            PriceFact("我拿货（参考）") {
                // 后端没给这个价时如实说"没记录"，不印 ¥0（那会被读成"不要钱"）。
                if (product.supplyUnitPrice.isNullOrBlank()) {
                    Text("没记录", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.outline)
                } else {
                    MoneyText(product.supplyUnitPrice, style = MaterialTheme.typography.bodyMedium)
                }
            }
        }

        DownstreamPriceInput(
            productId = product.productId,
            contactId = null,
            saveLabel = "保存",
            vm = vm,
            onSave = { vm.save(product, null) },
        )
        if (vm.formErrorProductId == product.productId) {
            FormErrorLine(vm.formError)
        }

        HorizontalDivider(Modifier.padding(vertical = 12.dp), color = MaterialTheme.colorScheme.outlineVariant)

        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(
                "按人定价 · " + product.contactPriceCount + " 人",
                modifier = Modifier.weight(1f),
                style = MaterialTheme.typography.bodyLarge,
            )
            TextButton(onClick = { vm.openPricing(product) }) {
                Text("定价")
            }
        }
    }
}

/** 现状价的标签 + 值（小字标签在上、值在下）。 */
@Composable
private fun PriceFact(label: String, modifier: Modifier = Modifier, value: @Composable () -> Unit) {
    Column(modifier) {
        Text(label, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.height(2.dp))
        value()
    }
}

/**
 * 「给谁单独定价」抽屉（甲案）：顶部两档（在用 / 回收站）＋「全部下游的默认价」一行
 * ＋ 一位下游一行（姓名 ＋ 电话 ＋ 单价输入框 ＋ 保存，在用的那条右边带「删除这条价」）。
 *
 * ⛔ 抽屉体必须 fillMaxHeight + verticalScroll：下游客户多了要能滚，
 *    而且表单错（[FormErrorLine]）必须跟表单在同一屏里 —— 不然用户不知道保存为什么没成。
 * ⛔ 默认价那一行的输入框与列表卡片上那个**共用同一个草稿格**（[draftKeyOf] 按商品 + 人算键），
 *    两处写的是同一个价，不会各写各的。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DownstreamPersonSheet(product: ShipperPriceProductDto, vm: ShipperPricesViewModel) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = { vm.closePricing() }, sheetState = sheetState) {
        Column(
            Modifier.fillMaxWidth()
                .fillMaxHeight(0.9f)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp)
                .padding(bottom = 24.dp),
        ) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text(
                    "给谁单独定价",
                    modifier = Modifier.weight(1f),
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Bold,
                )
                SheetCloseButton(onClick = { vm.closePricing() })
            }
            Text(
                product.productName + "（单位：" + (product.unit ?: "件") + "）",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(12.dp))

            // 两档：默认只看在用的；回收站里躺着的那几条要能看见、要能恢复。
            SegmentedPicker(
                labels = listOf(
                    "在用 · " + activePersonCount(vm.prices) + " 人",
                    "回收站 · " + deletedCount(vm.prices) + " 条",
                ),
                selected = if (vm.includeDeleted) 1 else 0,
                onSelect = { vm.toggleIncludeDeleted(it == 1) },
                accent = Color(ThemeGreen),
            )
            Spacer(Modifier.height(8.dp))

            val fallback = defaultPrice(vm.prices)
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("全部下游的默认价", style = MaterialTheme.typography.bodyLarge)
                    Text(
                        "不填的人按这个价算",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                when {
                    fallback == null -> Text(
                        "未设",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.outline,
                    )
                    fallback.isDeleted -> Text(
                        "已删除 ¥" + money(fallback),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.outline,
                    )
                    else -> MoneyText(fallback.unitPrice, style = MaterialTheme.typography.bodyMedium)
                }
            }
            DownstreamPriceInput(
                productId = product.productId,
                contactId = null,
                saveLabel = "保存",
                vm = vm,
                onSave = { vm.save(product, null) },
            )
            Spacer(Modifier.height(8.dp))
            Text(
                "不填的人按默认价算；没设默认价、也没专人价的人，这一页不管（后端那一处说了算）。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            HorizontalDivider(Modifier.padding(vertical = 12.dp), color = MaterialTheme.colorScheme.outlineVariant)

            if (vm.contacts.isEmpty()) {
                Text(
                    "你的联系人还是空的 —— 先去「地址与联系人」添一位下游客户，再回来给他单独定价",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            // 第二行跟联系人那一页同一个口径：电话 · 备注（备注只有他自己看得见）。
            val contactById = vm.contacts.associateBy { it.id }
            personRows(vm.contacts, vm.prices, vm.includeDeleted).forEach { row ->
                PersonPriceRow(
                    row = row,
                    subtitle = contactById[row.contactId]?.let { contactLine(it) },
                    product = product,
                    vm = vm,
                )
            }

            if (vm.pricesLoading) {
                Spacer(Modifier.height(8.dp))
                LoadingBox()
            }

            FormErrorLine(vm.formError)

            if (vm.formError != null) {
                TextButton(onClick = { vm.dismissFormError() }) { Text("知道了") }
            }
        }
    }
}

/**
 * 抽屉里一位下游一行：姓名 ＋ 电话 ＋ 单价输入框 ＋ 保存。
 *
 * 右边那一格是他**现在这个价**：在用的给价 ＋「删除这条价」；回收站里的给「已删除 ¥…」＋「恢复」；
 * 还没给他单独定过价的，直接告诉他现在按默认价算多少钱（没默认价才说「未设」）。
 */
@Composable
private fun PersonPriceRow(
    row: DownstreamPersonRow,
    subtitle: String?,
    product: ShipperPriceProductDto,
    vm: ShipperPricesViewModel,
) {
    val own = row.price
    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(row.name, style = MaterialTheme.typography.bodyLarge)
                Text(
                    if (subtitle.isNullOrBlank()) "没留电话" else subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            when {
                own == null -> if (row.effectiveUnitPrice != null) {
                    MoneyText(row.effectiveUnitPrice, style = MaterialTheme.typography.bodySmall, prefix = "按默认价 ¥")
                } else {
                    Text("未设", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.outline)
                }
                own.isDeleted -> {
                    Text(
                        "已删除 ¥" + money(own),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.outline,
                    )
                    TextButton(onClick = { vm.restore(own) }, enabled = !vm.acting) { Text("恢复") }
                }
                else -> {
                    MoneyText(own.unitPrice, style = MaterialTheme.typography.bodyMedium)
                    TextButton(onClick = { vm.askDelete(own) }, enabled = !vm.acting) { Text("删除这条价") }
                }
            }
        }
        if (own?.isDeleted != true) {
            DownstreamPriceInput(
                productId = product.productId,
                contactId = row.contactId,
                saveLabel = "保存",
                vm = vm,
                onSave = { vm.save(product, row.contactId) },
            )
        }
    }
}

/**
 * 一行「单价输入框 ＋ 保存」—— 卡片上的默认价、抽屉里的默认价、抽屉里每一位下游，三处都复用它。
 *
 * ⛔ 全页**只有这一处**画单价输入框：过滤规则（[InputRules.priceInput]，单价是 Numeric(14,4)）
 *    与"点进去整串选中"的口径只写一遍 —— 抄成三份的话，迟早有一处漏掉。
 */
@Composable
private fun DownstreamPriceInput(
    productId: Long,
    contactId: Long?,
    saveLabel: String,
    vm: ShipperPricesViewModel,
    onSave: () -> Unit,
) {
    // 草稿格按「商品 + 人」算键：A 商品打了一半的字不许跑到 B 商品的框里。
    val draftKey = draftKeyOf(productId, contactId)
    Row(Modifier.fillMaxWidth().padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        SoTextField(
            value = vm.draftFor(draftKey),
            // 过滤规则唯一实现在 core/InputRules.kt：单价列是 Numeric(14,4) ⇒ priceInput（四位小数）。
            onValueChange = { vm.setDraft(draftKey, InputRules.priceInput(it)) },
            modifier = Modifier.weight(1f),
            placeholder = "单价（元）",
            keyboardType = KeyboardType.Decimal,
            enabled = !vm.submitting,
            // 价框点进去整串选中：用户报过「1」+「15」=「115」那类事故。
            selectAllOnFocus = true,
        )
        Spacer(Modifier.width(8.dp))
        Button(
            onClick = onSave,
            modifier = Modifier.height(52.dp),
            enabled = !vm.submitting,
            // 钱的事用钱的色（焦糖）：跟这一页那个大字价是同一个颜色。
            colors = ButtonDefaults.buttonColors(containerColor = Color(MoneyOrange)),
        ) {
            Text(saveLabel)
        }
    }
}

/** 现状价（弹层里那句"删除这条价？"要复述清楚删的是谁、现在的价是多少）。 */
private fun money(row: ShipperPriceDto): String = com.tapmoay.sorders.util.formatMoney(row.unitPrice)

private fun priceRowTitle(row: ShipperPriceDto): String {
    val name = row.productName.orEmpty().ifBlank { "这件商品" }
    val who = row.contactName.orEmpty().ifBlank { "全部下游（默认价）" }
    return name + " / " + who
}

private fun deleteHint(row: ShipperPriceDto): String =
    "现在 ¥" + money(row) + "。删掉之后，以后下的单不再按这条价算；已经算过的钱一分都不动。"

/** 联系人的第二行：电话＋备注（备注只有他自己看得见，后端字段是 remark）。 */
private fun contactLine(contact: ContactDto): String {
    val parts = mutableListOf<String>()
    if (contact.phone.isNotBlank()) parts.add(contact.phone)
    if (contact.remark.isNotBlank()) parts.add(contact.remark)
    return parts.joinToString(" · ")
}
