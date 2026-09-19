package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.UserSearch
import com.tapmoay.sorders.data.remote.dto.FreightSettlementGroupDto
import com.tapmoay.sorders.data.remote.dto.FreightSettlementOrderDto
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.util.formatDateTime
import com.tapmoay.sorders.util.formatMoney
import com.tapmoay.sorders.util.trimMoneyZeros
import java.math.BigDecimal

/**
 * 司机运费结算 —— **左边一篮司机、右边那位司机的详情**（用户 2026-09-19）。
 *
 * 原话：「我们那个司机计费啊那个运费计费那个图标啊，他那个功能，那个界面不是很好啊，
 * 我们采用一个**商品管理的一个界面的思维**啊，就是左边它有个篮子嘛，那个篮子全是对应的司机，
 * 我们点击司机就能看，然后右边就是他们的详情。然后详情的那个最上面是有一个**统计**啊
 * 大致的一些信息内容，然后后面这下面的就是**明细**，比如说，关于一些订单啊的**价格明细**」。
 *
 * ## 为什么原来那版不行
 * 原来是一列**卡片**：每个司机一张，卡上写"谁、几单、多少钱"，下面的订单默认露 2 单。
 * 293 个司机（本机实测）时，想核**某一个**司机的账得滚很久，而滚的过程中
 * 别人的钱一直在眼前晃。两栏之后：左边只回答"有哪几个人"（一屏能扫十几个），
 * 右边只回答"这个人这一个月怎么回事"。
 *
 * ## 右栏为什么是"上统计、下明细"
 * 这是用户点名的结构。统计块回答三个问题，且**每个数都写清口径**（这一页有三个容易混的钱）：
 * 1. **司机应得**（`pay_total`，与司机账单/报表**同源** `driver_pay.pay_for_order`）—— 大字；
 * 2. **货主运费**（订单上的 `freight_fee`）—— 完全不同的一个数，混起来就会出现
 *    "明细加起来 ≠ 组头那个数"（老毛病，见下面的注释）；
 * 3. **按件 / 提成**的拆分 —— 司机问"我这钱怎么来的"时照着念。
 * 明细里还留着每单的「应得 + 运费」两栏，与统计**同一个来源**。
 *
 * ⚠️ 左边篮子的搜索走 `core/UserSearch`（姓名 / 手机号 / 后 4 位）——
 *    与账本、名册页**同一条规则**：293 个司机没有搜索就是一列找不到人的名单。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FreightSettlementScreen(container: AppContainer, onBack: () -> Unit) {
    val vm: FreightSettlementViewModel = appViewModel { FreightSettlementViewModel(container) }

    Scaffold(
        topBar = { AppTopBar(title = "司机运费结算 · " + vm.month, onBack = onBack) },
    ) { pad ->
        Column(Modifier.fillMaxSize().padding(pad)) {
            MonthPills(vm)
            val groups = vm.data?.groups ?: emptyList()
            when {
                vm.loading && groups.isEmpty() ->
                    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
                vm.error != null ->
                    ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
                groups.isEmpty() ->
                    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        Text(
                            "本月暂无已送达且已计价的运费订单",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                else -> SettlementBody(vm, groups)
            }
        }
    }
}

/** 上上月 / 上月 / 本月。 */
@Composable
private fun MonthPills(vm: FreightSettlementViewModel) {
    Row(
        Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        listOf(-2 to "上上月", -1 to "上月", 0 to "本月").forEach { (delta, label) ->
            val target = java.time.LocalDate.now().plusMonths(delta.toLong())
                .format(java.time.format.DateTimeFormatter.ofPattern("yyyy-MM"))
            val sel = vm.month == target
            Surface(
                color = if (sel) Color(Accent).copy(alpha = 0.14f) else MaterialTheme.colorScheme.surface,
                shape = MaterialTheme.shapes.small,
                modifier = Modifier.clickable { vm.shiftMonth(delta) },
            ) {
                Text(
                    label,
                    style = MaterialTheme.typography.labelLarge,
                    color = if (sel) Color(Accent) else MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = 14.dp, vertical = 7.dp),
                )
            }
        }
    }
}

/** 这一页的语义色 = 司机运费结算的珊瑚橙（工作台图标同色）。 */
private val Accent = 0xFFFF8A65L

/**
 * 两栏主体：左篮子 + 右详情。
 *
 * ⚠️ 顶部那行"本月共 N 位司机 · 应得合计 ¥X"**不是**可有可无的装饰：
 *    两栏之后"整个月一共要付多少"这件事没有别的地方能看到了（原来它在列表顶上那张卡上）。
 */
@Composable
private fun SettlementBody(vm: FreightSettlementViewModel, groups: List<FreightSettlementGroupDto>) {
    val visible = UserSearch.filter(groups, vm.query, { it.driverName }, { it.driverPhone })
    // 选中的那位：换月份/搜索之后原来选的人可能不在了 → 回落到第一行，
    // 否则右边会停在一个左栏里根本没高亮的司机上（"我明明点了李四，右边是空的"）
    val selected = groups.firstOrNull { driverKey(it) == vm.selectedKey } ?: visible.firstOrNull()

    Column(Modifier.fillMaxSize()) {
        // 月度仪表盘 + 搜索（全宽，与商品管理/库存管理同一版式：
        // 搜索和左栏是两个维度，塞进左栏会被压成半宽）
        Column(Modifier.padding(horizontal = 16.dp, vertical = 4.dp)) {
            Row(verticalAlignment = Alignment.Bottom) {
                Text(
                    "本月共 " + groups.size + " 位司机 · 应得合计",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.width(6.dp))
                Text(
                    "¥" + formatMoney(groups.sumOf { it.total }.toString()),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    color = Color(0xFFFF9500),
                )
            }
            Spacer(Modifier.height(6.dp))
            // 按人搜索的唯一实现（姓名 / 手机号 / 后 4 位）——293 个司机必须有它
            SearchField(value = vm.query, onValueChange = { vm.query = it })
        }
        Spacer(Modifier.height(6.dp))
        Row(Modifier.weight(1f)) {
            MasterRail(
                items = visible.map {
                    RailItem(
                        key = driverKey(it),
                        label = it.driverName.ifBlank { "司机 " + it.driverId },
                        // 钱排在前面：这一页是结算，扫一眼先看钱；单数跟在后面够用就行
                        subtitle = "¥" + trimMoneyZeros(it.total.toString()) + " · " + it.count + " 单",
                    )
                },
                selectedKey = selected?.let { driverKey(it) }.orEmpty(),
                onSelect = { vm.selectDriver(it) },
                accent = Color(Accent),
                modifier = Modifier.width(118.dp).fillMaxHeight(),
            )
            Box(Modifier.weight(1f).fillMaxHeight()) {
                if (visible.isEmpty()) {
                    EmptyView(
                        UserSearch.noMatchText(vm.query) + "司机",
                        Modifier.align(Alignment.Center),
                    )
                } else if (selected == null) {
                    EmptyView("左边点一位司机看他的明细", Modifier.align(Alignment.Center))
                } else {
                    DriverDetail(selected)
                }
            }
        }
    }
}

/** 一位司机的 key（左栏选中、VM 里存的都是它，**不许两处各拼一份**）。 */
internal fun driverKey(g: FreightSettlementGroupDto): String = "d|" + g.driverId

/** 右栏：上面统计、下面明细。 */
@Composable
private fun DriverDetail(g: FreightSettlementGroupDto) {
    // 统计块要的几个数：**全部从同一批明细算出来**，不另开口径。
    // 应得直接取组头的 `total`（后端 `driver_pay.pay_for_order` 逐单累加的结果）。
    val freightTotal = g.orders.mapNotNull { it.freightFee?.toBigDecimalOrNull() }.fold(BigDecimal.ZERO) { a, b -> a + b }
    val unpriced = g.orders.count { it.freightFee == null }
    val piece = g.orders.mapNotNull { it.payPiece.toBigDecimalOrNull() }.fold(BigDecimal.ZERO) { a, b -> a + b }
    val commission = g.orders.mapNotNull { it.payCommission.toBigDecimalOrNull() }.fold(BigDecimal.ZERO) { a, b -> a + b }

    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = 10.dp, end = 10.dp, top = 10.dp, bottom = 16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        item {
            SectionCard {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TintedIcon(Icons.Default.LocalShipping, Color(Accent), size = 16.dp, container = 34.dp)
                    Spacer(Modifier.width(10.dp))
                    Column(Modifier.weight(1f)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                g.driverName.ifBlank { "司机 " + g.driverId },
                                style = MaterialTheme.typography.titleMedium,
                                fontWeight = FontWeight.Bold,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                            if (!g.driverActive) {
                                Spacer(Modifier.width(6.dp))
                                Surface(color = MaterialTheme.colorScheme.surfaceVariant, shape = MaterialTheme.shapes.small) {
                                    Text(
                                        "已停用",
                                        style = MaterialTheme.typography.labelSmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        modifier = Modifier.padding(horizontal = 6.dp, vertical = 1.dp),
                                    )
                                }
                            }
                        }
                        Text(
                            g.driverPhone?.ifBlank { null } ?: "未登记手机号",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
                Spacer(Modifier.height(10.dp))
                // ⚠️ 「应得」和「货主运费」是**两个不同的数**，标签必须各写各的：
                //    混起来就会出现"明细加起来 ≠ 上面那个数"（这一页的老毛病）。
                Text("本月司机应得", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.height(2.dp))
                Text(
                    "¥" + formatMoney(g.total.toString()),
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold,
                    color = Color(0xFFFF9500),
                )
                Spacer(Modifier.height(2.dp))
                Text(
                    g.count.toString() + " 单已完成 · 货主运费合计 ¥" + formatMoney(freightTotal.toString()),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                // 拆分只在这一项真的非零时才说 —— 写一行「按件 ¥0.00」是纯噪音
                val parts = buildList {
                    if (piece.signum() != 0) add("按件 ¥" + formatMoney(piece.toString()))
                    if (commission.signum() != 0) add("提成 ¥" + formatMoney(commission.toString()))
                }
                if (parts.isNotEmpty()) {
                    Text(
                        "其中 " + parts.joinToString(" · "),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                if (unpriced > 0) {
                    Spacer(Modifier.height(2.dp))
                    Text(
                        "有 " + unpriced + " 单还没定价（运费待补），它现在的应得按 0 计 —— 补价后这里会自动变",
                        style = MaterialTheme.typography.bodySmall,
                        color = Color(0xFFFF6B2C),
                    )
                }
            }
        }
        item {
            Text(
                "价格明细（每单：司机应得 / 货主运费）",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(start = 2.dp, top = 2.dp),
            )
        }
        itemsIndexed(g.orders, key = { _, o -> o.orderId }) { _, o ->
            SectionCard { SettlementOrderRow(o) }
        }
    }
}

/** 一条结算明细（**一行**：左边单号+时间+地址，右边应得+运费）。 */
@Composable
private fun SettlementOrderRow(o: FreightSettlementOrderDto) {
    Row(
        Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(o.orderNo, style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
            // ⚠️ 时间是**结算**要看的（哪天送的），所以排在地址前面；
            //    地址长，让它占剩下的位置并截断 —— 原来顺序反过来，时间被挤没了。
            val where = listOfNotNull(
                o.deliveredAt?.let { formatDateTime(it) },
                o.addressDetail.takeIf { it.isNotBlank() },
            ).joinToString(" · ")
            Text(
                where.ifBlank { o.deliveryDescription },
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Spacer(Modifier.width(8.dp))
        // 明细行显示**司机应得**（pay_total，与组头同一个来源），运费另标注：
        // 以前这里取 `freightFee`（货主运费）→ 明细加起来 ≠ 组头那个数。
        Column(horizontalAlignment = Alignment.End) {
            Text(
                "¥" + formatMoney(o.payTotal),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Bold,
                textAlign = TextAlign.End,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                if (o.freightFee != null) "运费 ¥" + formatMoney(o.freightFee) else "运费 待定价",
                style = MaterialTheme.typography.labelSmall,
                color = if (o.freightFee != null) MaterialTheme.colorScheme.onSurfaceVariant else Color(0xFFFF6B2C),
            )
        }
    }
}
