package com.tapmoay.sorders.ui.shipper

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.api.ShipperPriceDto
import com.tapmoay.sorders.data.remote.api.ShipperPriceProductDto
import com.tapmoay.sorders.data.remote.dto.ContactDto
import com.tapmoay.sorders.ui.common.*

/**
 * 货主端「下游定价」（台账 L-38 / CHG-0077）。
 *
 * ## 一段话看懂这一页
 * 批发商货主在这里定「**我卖给下游多少钱**」：一件商品一个**默认价**（给全部下游），
 * 还能给**某一位**下游单独一个价（专人价）。派单员给他的价（「我拿货」）只是参考，
 * 不参与计算 —— 差额归他自己。
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
                            ProductPriceCard(
                                product = product,
                                vm = vm,
                            )
                        }
                    }
                }
            }
        }
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

/** 一件商品：先给三条现状（我拿货 / 我的默认价 / 几个专人价），点「定价」展开这一件。 */
@Composable
private fun ProductPriceCard(product: ShipperPriceProductDto, vm: ShipperPricesViewModel) {
    val open = vm.openProductId == product.productId
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
            TextButton(onClick = { vm.toggleProduct(product.productId) }) {
                Text(if (open) "收起" else "定价")
            }
        }
        Spacer(Modifier.height(4.dp))
        Row(Modifier.fillMaxWidth()) {
            PriceFact("我拿货（参考）", Modifier.weight(1f)) {
                // 后端没给这个价时如实说"没记录"，不印 ¥0（那会被读成"不要钱"）。
                if (product.supplyUnitPrice.isNullOrBlank()) {
                    Text("没记录", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.outline)
                } else {
                    MoneyText(product.supplyUnitPrice, style = MaterialTheme.typography.bodyMedium)
                }
            }
            PriceFact("我的默认价", Modifier.weight(1f)) {
                if (product.defaultUnitPrice.isNullOrBlank()) {
                    Text("未设", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.outline)
                } else {
                    MoneyText(product.defaultUnitPrice, style = MaterialTheme.typography.bodyMedium)
                }
            }
            PriceFact("专人价", Modifier.weight(1f)) {
                Text(product.contactPriceCount.toString() + " 个", style = MaterialTheme.typography.bodyMedium)
            }
        }

        if (open) {
            HorizontalDivider(Modifier.padding(vertical = 12.dp), color = MaterialTheme.colorScheme.outlineVariant)
            PriceEditor(product = product, vm = vm)
        }
    }
}

@Composable
private fun PriceFact(label: String, modifier: Modifier = Modifier, value: @Composable () -> Unit) {
    Column(modifier) {
        Text(label, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.height(2.dp))
        value()
    }
}

/**
 * 展开后的编辑器：**默认价**一格（给全部下游）＋ 每位联系人一格（专人价）。
 *
 * 每格都是"输入框 + 保存"，保存成功时后端会**复活＋覆盖**命中的那一行（不插新行），
 * 所以这里不需要"先删再改"那种两步操作。
 */
@Composable
private fun PriceEditor(product: ShipperPriceProductDto, vm: ShipperPricesViewModel) {
    val productId = product.productId
    Text("给不同的人不同的价", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
    Spacer(Modifier.height(4.dp))
    Text(
        "不填的人按默认价算；没设默认价、也没专人价的人，这一页不管（后端那一处说了算）。",
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    Spacer(Modifier.height(12.dp))

    // ① 默认价
    PriceEditRow(
        title = "全部下游的默认价",
        subtitle = null,
        row = vm.priceOf(productId, null),
        draftKey = SHIPPER_PRICE_DEFAULT_KEY,
        vm = vm,
        onSave = { key -> vm.save(product, null, key) },
    )

    HorizontalDivider(Modifier.padding(vertical = 12.dp), color = MaterialTheme.colorScheme.outlineVariant)

    // ② 每位联系人
    if (vm.contacts.isEmpty()) {
        Text(
            "你的联系人还是空的 —— 先去「地址与联系人」添一位下游客户，再回来给他单独定价",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    } else {
        vm.contacts.forEach { contact ->
            PriceEditRow(
                title = contact.displayName.ifBlank { contact.phone.ifBlank { "联系人 " + contact.id } },
                subtitle = contactLine(contact),
                row = vm.priceOf(productId, contact.id),
                draftKey = contact.id,
                vm = vm,
                onSave = { key -> vm.save(product, contact.id, key) },
            )
            Spacer(Modifier.height(4.dp))
        }
    }

    if (vm.pricesLoading) {
        Spacer(Modifier.height(8.dp))
        LoadingBox()
    }

    FormErrorLine(vm.formError)

    // 回收站开关：默认只看在用的（多了这一档，列表会长出一截"已删除"的行）。
    TextButton(onClick = { vm.toggleIncludeDeleted(!vm.includeDeleted) }) {
        Text(if (vm.includeDeleted) "只看在用的价" else "显示已删除的价（回收站）")
    }

    if (vm.formError != null) {
        TextButton(onClick = { vm.dismissFormError() }) { Text("知道了") }
    }
}

/** 一行"某人 / 默认价"：现状 + 输入框 + 保存（已删除的行给"恢复"）。 */
@Composable
private fun PriceEditRow(
    title: String,
    subtitle: String?,
    row: ShipperPriceDto?,
    draftKey: Long,
    vm: ShipperPricesViewModel,
    onSave: (Long) -> Unit,
) {
    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.bodyLarge)
                if (!subtitle.isNullOrBlank()) {
                    Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            // 现状：在用的给价 + 删除；回收站里的给"已删除" + 恢复。
            when {
                row == null -> Text("未设", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.outline)
                row.isDeleted -> {
                    Text("已删除 ¥" + money(row), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.outline)
                    TextButton(onClick = { vm.restore(row) }, enabled = !vm.acting) { Text("恢复") }
                }
                else -> {
                    MoneyText(row.unitPrice, style = MaterialTheme.typography.bodyMedium)
                    TextButton(onClick = { vm.askDelete(row) }) { Text("删除") }
                }
            }
        }
        if (row?.isDeleted != true) {
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
                Button(onClick = { onSave(draftKey) }, enabled = !vm.submitting) {
                    Text(if (row == null) "设价" else "改价")
                }
            }
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
