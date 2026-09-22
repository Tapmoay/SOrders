package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.util.formatMoney

/**
 * 价格矩阵页：**一个商品 × 一个批发商 = 一个专属价**，两个方向看同一份数据。
 *
 * ## 两个入口（2026-09-19 用户要求"操作与逻辑匹配"）
 * | 入口 | 方向 | 一行长什么样 |
 * |---|---|---|
 * | 批发商管理 → 定价 | [PriceAxis.BY_SHIPPER] | 行 = 商品（这个批发商买每个商品多少钱） |
 * | 商品管理 → 卡片 ⋮ → 各批发商价格 | [PriceAxis.BY_PRODUCT] | 行 = 批发商（这个商品卖给每家多少钱） |
 *
 * 用户的原话是：「同一个商品，这个批发商的价格和那个批发商的价格是不一样的，
 * 关于这个部分的逻辑做一下调整，包括一些操作也做一下调整，保证操作与逻辑匹配，
 * 并且是那种不是很复杂的操作」。
 *
 * 逻辑本来就是按（批发商 × 商品）存的，但**原来只有"按批发商"这一个方向** ——
 * 要给一个商品分别设 A/B/C 三个不同的价，只能进 A 的页面填一次、再进 B、再进 C
 * （批量调价只能给同一口价，或按默认价的百分比）。现在两个方向都在，
 * **操作完全一样**（填价 → 保存 / 清除特价），这就是"不复杂的操作"。
 *
 * ## 这里改的是**真的会生效**的那个价
 * 下单时 `priceFor()` 只认两样：这个（批发商 × 商品）的专属价，或商品默认售价。
 * （商品上原来那套"批发价档位"已于 2026-09-19 整个删除 —— 它看起来像批发价，
 *  但下单时谁都不照它走，正是"操作与逻辑不匹配"的典型。）
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PriceMatrixScreen(
    container: AppContainer,
    axis: PriceAxis,
    focusId: Long,
    onBack: () -> Unit,
) {
    val vm: PriceMatrixViewModel = appViewModel { PriceMatrixViewModel(container, axis, focusId) }
    val snackbar = remember { SnackbarHostState() }

    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })
    OneShotSnackbar(snackbar, vm.error, onConsumed = { vm.error = null })
    OneShotSnackbar(snackbar, vm.loadError, onConsumed = { vm.loadError = null })

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            AppTopBar(
                title = vm.title,
                onBack = onBack,
                actions = {
                    // 批量调价是"多批发商 × 多商品"的工具，只有按批发商看的时候才有意义
                    // （它自己会让你选批发商范围）。按商品看的页面就这一件商品，不必给。
                    if (axis == PriceAxis.BY_SHIPPER) {
                        TextButton(onClick = { vm.showBatch = true; vm.loadMembers() }) {
                            Icon(Icons.Default.Edit, contentDescription = null, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(4.dp))
                            Text("批量调价")
                        }
                    }
                },
            )
        },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            when {
                vm.loading -> LoadingBox()
                vm.loadError != null && vm.targets.isEmpty() ->
                    ErrorView(vm.loadError.orEmpty(), onRetry = { vm.load() })
                vm.targets.isEmpty() ->
                    EmptyView("没有可以定价的对象", Modifier.align(Alignment.Center))
                else -> LazyColumn(
                    Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    item {
                        Column {
                            Text(
                                vm.subtitle,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            if (axis == PriceAxis.BY_PRODUCT && vm.hiddenInactive > 0) {
                                Spacer(Modifier.height(4.dp))
                                Text(
                                    // 说实话，不默默滤掉：给他设价是白设（人已经登不进来、也下不了单）
                                    "另有 " + vm.hiddenInactive + " 个已停用或已删除的批发商没有列出" +
                                        "（给他们设价不会生效）。",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = Color(0xFFFF6B2C),
                                )
                            }
                            // ⚠️ 截断位放在条件**最前面**：`_check_page_truncation_wiring.py`
                            //    要确认"这个提示是被截断时才显示的"（无条件显示等于没判据）。
                            if (vm.truncated && axis == PriceAxis.BY_PRODUCT) {
                                Spacer(Modifier.height(6.dp))
                                TruncationNote(
                                    vm.pageLimit,
                                    // ⚠️ 这一页**没有任何筛选入口**（不撒谎去指一个不存在的按钮）：
                                    //    名册是被服务端截断的，所以连"用搜索框找"都做不到
                                    //    （客户端搜索搜不到根本没取回来的那些行）。
                                    //    只说一句真话：这份名单可能不全。
                                    "这份批发商名单可能不全 —— 没列出来的，不等于没给他设过价。",
                                )
                            }
                            Spacer(Modifier.height(2.dp))
                        }
                    }
                    items(vm.targets, key = { it.id }) { t ->
                        PriceRow(
                            t = t,
                            value = vm.fieldValue(t),
                            shownPrice = vm.effectivePrice(t),
                            hasRule = vm.rules.containsKey(t.id),
                            acting = vm.acting,
                            onValueChange = { v -> vm.drafts[t.id] = v },
                            onSave = { vm.savePrice(t) },
                            onClear = { vm.clearPrice(t) },
                        )
                    }
                    item { Spacer(Modifier.height(24.dp)) }
                }
            }
        }
    }

    if (vm.showBatch) {
        BatchPriceSheet(
            products = emptyList(), // 按批发商看时，范围由抽屉自己选
            members = vm.members,
            lockedShipperId = if (axis == PriceAxis.BY_SHIPPER) focusId else null,
            lockedShipperName = "",
            acting = vm.acting,
            onExecute = { sids, pids, m, v -> vm.batchPrice(sids, pids, m, v) { vm.showBatch = false } },
            onDismiss = { vm.showBatch = false },
        )
    }
}

/**
 * 一行：对手方（商品或批发商）+ 当前生效价 + 价格输入。
 *
 * 两个方向的**结构完全一样**，只有图标与副标题不同 —— 这是有意的：
 * "设这个（批发商 × 商品）的价"在两个方向上本来就是同一件事，
 * 交互不该长得不一样（用户要的"操作与逻辑匹配"）。
 */
@Composable
private fun PriceRow(
    t: PriceTarget,
    value: String,
    shownPrice: String,
    hasRule: Boolean,
    acting: Boolean,
    onValueChange: (String) -> Unit,
    onSave: () -> Unit,
    onClear: () -> Unit,
) {
    SectionCard {
        Column {
            Row(verticalAlignment = Alignment.CenterVertically) {
                // 名称色判据只有一处（`ui/common/ProductCardKit.kt::productNameColor`）：
                // 原来这里是**第二份** `parseColor` 写法。它用 `runCatching` 兜住了异常，
                // 但"坏值退成什么颜色"与商品卡那一套并不一致 —— 同一条脏数据，
                // 在商品卡上是物流蓝、在这一页是主色。批发商本来就没有名称色，仍退主色。
                val c = t.nameColor?.let { productNameColor(it) } ?: MaterialTheme.colorScheme.primary
                TintedIcon(Icons.Default.Inventory2, c, size = 20.dp, container = 40.dp)
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text(
                        t.name,
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                        color = c,
                        maxLines = 1,
                    )
                    if (t.sub.isNotBlank()) {
                        Text(
                            t.sub,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            maxLines = 1,
                        )
                    }
                }
                if (hasRule) {
                    Surface(color = Color(0xFFD5F5E9), shape = MaterialTheme.shapes.small) {
                        Text(
                            "已设专属价",
                            style = MaterialTheme.typography.labelMedium,
                            color = Color(0xFF00624A),
                            modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                        )
                    }
                }
            }
            Spacer(Modifier.height(6.dp))
            // 当前价：**填了就是它、留空就是默认价** —— 一行说清，不用用户自己推
            Row(verticalAlignment = Alignment.Bottom) {
                Text(
                    "¥" + formatMoney(shownPrice),
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold,
                    color = Color(MoneyOrange),
                )
                Spacer(Modifier.width(6.dp))
                Text(
                    if (hasRule || value.isNotBlank()) "这个批发商/商品的实际价" else "按默认价",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(bottom = 4.dp),
                )
            }
            Spacer(Modifier.height(10.dp))
            HorizontalDivider(color = MaterialTheme.colorScheme.surfaceVariant)
            Spacer(Modifier.height(10.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                SoTextField(
                    value = value,
                    // 过滤放在**这个框自己身上**：谁用它都该只收到单价。
                    // 4 位小数（`price_rules.special_unit_price` 是 `Numeric(14,4)`）。
                    // 规则唯一实现在 core/InputRules.kt。
                    onValueChange = { onValueChange(InputRules.priceInput(it)) },
                    placeholder = "留空表示按默认售价",
                    enabled = !acting,
                    keyboardType = KeyboardType.Decimal,
                    modifier = Modifier.weight(1f),
                )
                Spacer(Modifier.width(10.dp))
                Button(
                    onClick = onSave,
                    enabled = !acting && value.isNotBlank(),
                    modifier = Modifier.height(52.dp),
                ) {
                    Text("保存", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                }
            }
            if (hasRule) {
                TextButton(onClick = onClear, enabled = !acting, modifier = Modifier.align(Alignment.End)) {
                    Text("清除专属价（恢复默认价）", color = MaterialTheme.colorScheme.error)
                }
            }
        }
    }
}
