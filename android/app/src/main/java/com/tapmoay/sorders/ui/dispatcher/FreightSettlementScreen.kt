package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
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
import kotlinx.coroutines.launch
import java.math.BigDecimal

/**
 * 司机运费结算 —— **侧边抽屉选人 + 顶栏右上角一个月份**（2026-09-22 用户第二轮定稿）。
 *
 * 用户原话：
 * > 那个**司机运费结算**，我们的形式也发生改变……我们也可以按照**右上角一个时间**（栏），
 * > 但是**月份的选择形式跟我们平常的不一样**。然后我们那个司机他那个**不要按照这样子的
 * > 商品的管理**啊 —— 这样子非常不好，我们直接换那个**类似于货主的账本管理**的那种形式，
 * > 是那个**左侧的抽屉栏**在那里选择人物，**也可以在那里搜索**，然后选择之后，
 * > 我们就可以**直接看对应的那个司机那个结账**。
 *
 * ## 页面上只有三件东西（顺序也是用户定的）
 *
 * | 谁 | 形态 |
 * |---|---|
 * | **时间** | 顶栏**右上角**一个药丸（`DatePresetPill`，与账本页同一个零件、同一个位置）；点开是**年月网格** |
 * | **人员** | 页面上**一行入口** → `ModalNavigationDrawer` 的**侧边抽屉**（抽屉里带搜索，选中即关） |
 * | **数据** | 没选人 = 这个月一共要付多少 + 每人一行（点一行进他的结算）；选了人 = 他的统计 + 价格明细 |
 *
 * ## 这一页被否掉过的东西（别再装回来）
 *
 * · **`MasterRail` 那个左栏**（司机列表 + 页面上横跨整页的搜索框）—— 那是"商品管理那套思维"，
 *   用户 2026-09-22 的原话是「**不要按照这样子的商品的管理**啊。这样子，**非常不好**」；
 * · **页内那一行月份药丸**（上上月 / 上月 / 本月 / 自定义）—— 时间挪到顶栏之后，页面上不再铺这一行；
 * · ⛔ **选人不是一排 chip**：人一多就选不过来（这条与账本页同一条规矩，见 `ui/common/PersonPicker.kt`）。
 *
 * ## 右栏（选中某人）为什么是"上统计、下明细"
 * 这是用户 2026-09-19 点名的结构。统计块回答三个问题，且**每个数都写清口径**（这一页有三个容易混的钱）：
 * 1. **司机应得**（`pay_total`，与司机账单/报表**同源** `driver_pay.pay_for_order`）—— 大字；
 * 2. **货主运费**（订单上的 `freight_fee`）—— 完全不同的一个数，混起来就会出现
 *    "明细加起来 ≠ 组头那个数"（老毛病，见下面的注释）；
 * 3. **按件 / 提成**的拆分 —— 司机问"我这钱怎么来的"时照着念。
 * 明细里还留着每单的「应得 + 运费」两栏，与统计**同一个来源**。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FreightSettlementScreen(
    container: AppContainer,
    onBack: () -> Unit,
    /** 点开某一条明细 → 这一单的**原始订单**（订单详情页）。 */
    onOpenOrder: (Long) -> Unit = {},
) {
    val vm: FreightSettlementViewModel = appViewModel { FreightSettlementViewModel(container) }
    // 两个弹层：月份网格（点药丸）与自定义区间（网格里那一行）——都声明在**函数体这一层**
    // （弹层画在 Scaffold 外面，声明在它的 content 里就出了作用域）
    var showMonths by remember { mutableStateOf(false) }
    var showRange by remember { mutableStateOf(false) }
    // 侧边抽屉：选人用（与账本页同一个零件，见 ui/common/PersonPicker.kt）
    val drawer = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()

    val groups = vm.data?.groups ?: emptyList()
    val selected = groups.firstOrNull { driverKey(it) == vm.selectedKey }

    ModalNavigationDrawer(
        drawerState = drawer,
        drawerContent = {
            ModalDrawerSheet {
                PersonDrawer(
                    title = "选择司机",
                    options = vm.drawerDrivers().map { g ->
                        PersonOption(
                            key = driverKey(g),
                            title = g.driverName.ifBlank { "司机 " + g.driverId },
                            // 副标题里放三样：手机号（同名不同人只能靠它分开）· 这个人多少钱 · 几单
                            // ⚠️ 金额放这儿不算"同一份信息写两处"：这里**就是**挑人的地方，
                            //    页面上那一行入口仍然一个数字都不写（见 PersonPicker 的注释）
                            subtitle = listOfNotNull(
                                g.driverPhone?.ifBlank { null },
                                "停用".takeIf { !g.driverActive },
                                "¥" + formatMoney(g.total.toString()) + " · " + g.count + " 单",
                            ).joinToString(" · "),
                        )
                    },
                    selectedKey = vm.selectedKey.ifBlank { null },
                    query = vm.query,
                    onQueryChange = { vm.query = it },
                    onPick = { key ->
                        vm.selectDriver(key.orEmpty())
                        scope.launch { drawer.close() }
                    },
                    emptyText = UserSearch.noMatchText(vm.query) + "司机",
                    allLabel = "全部（" + groups.size + " 位司机）",
                    allSubtitle = "看" + vm.periodWord + "每个人各多少钱",
                )
            }
        },
    ) {
        Scaffold(
            topBar = {
                AppTopBar(
                    title = "司机运费结算",
                    onBack = onBack,
                    actions = {
                        // 时间：顶栏右上角一个紧凑药丸（与账本页同一个零件、同一个位置）。
                        // 口径词永远看得见 —— 这一页最容易搞错的就是"这些数字是哪一段的"。
                        DatePresetPill(label = vm.periodLabel, onClick = { showMonths = true })
                    },
                )
            },
        ) { pad ->
            Column(Modifier.fillMaxSize().padding(pad)) {
                // 人员那一行：**页面上唯一一个"选人"的入口**（点开侧边抽屉）
                PersonTriggerRow(
                    icon = Icons.Default.LocalShipping,
                    color = Color(Accent),
                    label = "司机",
                    value = when {
                        vm.selectedKey.isBlank() -> "全部（" + groups.size + " 位司机）"
                        selected != null -> selected.driverName.ifBlank { "司机 " + selected.driverId }
                        // 换到他没有单的月份时，名字只能从 VM 里那份**记下来的**名字取
                        else -> vm.selectedName.ifBlank { "已选中的司机" }
                    },
                    onOpen = {
                        // 每次打开抽屉都先清搜索词：带着上一次的词打开，名单看起来"少了一半人"
                        vm.query = ""
                        scope.launch { drawer.open() }
                    },
                )
                when {
                    vm.loading && groups.isEmpty() -> LoadingBox()
                    vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })
                    groups.isEmpty() -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        EmptyView(vm.periodWord + "暂无已送达且已计价的运费订单")
                    }
                    // 选了个人，但这一段里没有他 → **如实说**，不许悄悄回落到第一位司机
                    // （那等于"我明明在看的人被换掉了，界面上一句话都没有"）
                    vm.selectedKey.isNotBlank() && selected == null -> Box(
                        Modifier.fillMaxSize(),
                        contentAlignment = Alignment.Center,
                    ) {
                        EmptyView(
                            vm.selectedName.ifBlank { "这位司机" } + "在" + vm.periodWord +
                                "没有已送达且已计价的运费单 —— 点上面那一行可以换一位（或选「全部」）",
                        )
                    }
                    selected == null -> AllDrivers(vm, groups)
                    else -> DriverDetail(selected, vm.periodWord, onOpenOrder)
                }
            }
        }
    }

    // 月份：**年月网格**（年份左右翻 + 12 个月格子），不是我们常用的那列"档位清单"
    if (showMonths) {
        MonthPickerSheet(
            month = vm.month,
            current = vm.currentMonth(),
            onPick = { m ->
                showMonths = false
                vm.pickMonth(m)
            },
            // 「自定义区间」接着开区间弹层（顺序：先关网格、再开弹层）
            onCustom = {
                showMonths = false
                showRange = true
            },
            onDismiss = { showMonths = false },
        )
    }

    // 自定义区间与订单/账本/库存那几页**同一份实现**（`DateRangeDialog`）
    if (showRange) {
        DateRangeDialog(
            initialFrom = vm.rangeFrom,
            initialTo = vm.rangeTo,
            onDismiss = { showRange = false },
            onApply = { f, t -> vm.applyRange(f, t) },
        )
    }
}

/** 这一页的语义色 = 司机运费结算的珊瑚橙（工作台图标同色）。 */
private val Accent = 0xFFFF8A65L

/** 应得那个数用的橙（与报表/账本的金额色同一个）。 */
private val MoneyO = 0xFFFF9500L

/**
 * 月份选择：**年份左右翻 + 12 个月格子** + 底部「自定义区间（按天）」。
 *
 * 为什么是这个形态（用户 2026-09-22）：「我们也可以按照**右上角一个时间**（栏），
 * 但是**月份的选择形式跟我们平常的不一样**」。
 * "我们平常的"= 账本页那列**档位清单**（全部/今天/昨天/…一档一行）——
 * 那是**按天**的筛选；这一页结的是**月**，所以给的是月历式的网格：
 * 一次能看见一整年（"我要看上上上个月"不用在清单里一路翻），跨年也只用点一下"‹"。
 *
 * ⚠️ 选中的那个月高亮；**今天所在的月份**用同一个语义色淡淡标出来（用户对着日历找"这个月"时
 * 靠的就是它）——两者一眼能分开：选中是**实心**的。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun MonthPickerSheet(
    month: String,
    current: String,
    onPick: (String) -> Unit,
    onCustom: () -> Unit,
    onDismiss: () -> Unit,
) {
    // 翻到哪一年：初值 = 当前选中的那一年；**在弹层里翻年不改选中**（点月份才改）
    var year by remember { mutableStateOf(month.take(4).toIntOrNull() ?: current.take(4).toIntOrNull() ?: 2026) }
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(
            Modifier.fillMaxWidth()
                .padding(horizontal = 16.dp)
                .padding(bottom = 22.dp),
        ) {
            Text("选择月份", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(6.dp))
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = { year -= 1 }) {
                    Icon(Icons.Default.ChevronLeft, contentDescription = "上一年")
                }
                Text(
                    year.toString() + " 年",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.weight(1f),
                )
                IconButton(onClick = { year += 1 }) {
                    Icon(Icons.Default.ChevronRight, contentDescription = "下一年")
                }
            }
            Spacer(Modifier.height(4.dp))
            (1..12).chunked(3).forEach { row ->
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    row.forEach { m ->
                        val key = "%04d-%02d".format(year, m)
                        MonthCell(
                            label = m.toString() + " 月",
                            selected = key == month,
                            isCurrent = key == current,
                            onClick = { onPick(key) },
                            modifier = Modifier.weight(1f),
                        )
                    }
                }
                Spacer(Modifier.height(8.dp))
            }
            HorizontalDivider(Modifier.padding(vertical = 4.dp))
            Row(
                Modifier.fillMaxWidth().clickable(onClick = onCustom).padding(vertical = 14.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(
                    Icons.Default.DateRange,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(18.dp),
                )
                Spacer(Modifier.width(8.dp))
                Text("自定义区间（按天选）", style = MaterialTheme.typography.bodyLarge)
                Spacer(Modifier.weight(1f))
                Icon(
                    Icons.Default.ChevronRight,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

/** 月历里的一格（选中 = 实心语义色；"今天所在的月"用同一个色淡淡标出来）。 */
@Composable
private fun MonthCell(
    label: String,
    selected: Boolean,
    isCurrent: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        onClick = onClick,
        color = if (selected) Color(Accent) else MaterialTheme.colorScheme.surface,
        contentColor = when {
            selected -> Color.White
            isCurrent -> Color(Accent)
            else -> MaterialTheme.colorScheme.onSurface
        },
        shape = MaterialTheme.shapes.small,
        modifier = modifier.height(50.dp),
    ) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text(
                label,
                style = MaterialTheme.typography.labelLarge,
                fontWeight = if (selected || isCurrent) FontWeight.Bold else FontWeight.Normal,
            )
        }
    }
}

/**
 * 「全部」那一屏：**这个月一共要付多少**（仪表盘卡）+ **每人一行**（点一行进他的结算）。
 *
 * ⚠️ 顶上那个合计**不是**可有可无的装饰：它是这一页唯一回答"整个月一共要付多少"的地方
 *    （原来在左栏顶上那张卡上，左栏被去掉之后必须有个新的落点）。
 * ⚠️ 每人一行**只用一张白卡**（行与行之间一条分隔线）—— 每人一张卡时，
 *    十几个司机就是一屏的卡片边距，扫"谁多谁少"反而更慢。
 */
@Composable
private fun AllDrivers(vm: FreightSettlementViewModel, groups: List<FreightSettlementGroupDto>) {
    val total = groups.sumOf { it.total }
    val orders = groups.sumOf { it.count }
    val unpriced = groups.sumOf { g -> g.orders.count { it.freightFee == null } }
    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 4.dp, bottom = 16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            SectionCard {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TintedIcon(Icons.Default.LocalShipping, Color(Accent), size = 16.dp, container = 34.dp)
                    Spacer(Modifier.width(10.dp))
                    Column(Modifier.weight(1f)) {
                        Text(
                            vm.periodWord + "司机应得（全部司机）",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Text(
                            "¥" + formatMoney(total.toString()),
                            style = MaterialTheme.typography.headlineSmall,
                            fontWeight = FontWeight.Bold,
                            color = Color(MoneyO),
                        )
                        Text(
                            groups.size.toString() + " 位司机 · 共 " + orders + " 单已完成",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
                if (unpriced > 0) {
                    Spacer(Modifier.height(6.dp))
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
                "每人各多少 · 点一行看他这一个月的价格明细",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(start = 2.dp, top = 2.dp),
            )
        }
        item {
            SectionCard {
                groups.forEachIndexed { i, g ->
                    if (i > 0) {
                        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f))
                    }
                    DriverLine(g = g, onOpen = { vm.selectDriver(driverKey(g)) })
                }
            }
        }
    }
}

/** 「全部」卡里的一行：谁 + 手机号/几单 + 他应得多少（整行可点，进他的结算）。 */
@Composable
private fun DriverLine(g: FreightSettlementGroupDto, onOpen: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onOpen).padding(vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    g.driverName.ifBlank { "司机 " + g.driverId },
                    style = MaterialTheme.typography.titleSmall,
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
                listOf(
                    g.driverPhone?.ifBlank { null } ?: "未登记手机号",
                    g.count.toString() + " 单",
                ).joinToString(" · "),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
            )
        }
        Spacer(Modifier.width(10.dp))
        Text(
            "¥" + formatMoney(g.total.toString()),
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.Bold,
            color = Color(MoneyO),
        )
        Spacer(Modifier.width(4.dp))
        Icon(
            Icons.Default.ChevronRight,
            contentDescription = "看他这一个月的结算",
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/** 选中某人：上面统计、下面明细。 */
@Composable
private fun DriverDetail(
    g: FreightSettlementGroupDto,
    periodWord: String,
    onOpenOrder: (Long) -> Unit,
) {
    // 统计块要的几个数：**全部从同一批明细算出来**，不另开口径。
    // 应得直接取组头的 `total`（后端 `driver_pay.pay_for_order` 逐单累加的结果）。
    val freightTotal = g.orders.mapNotNull { it.freightFee?.toBigDecimalOrNull() }.fold(BigDecimal.ZERO) { a, b -> a + b }
    val unpriced = g.orders.count { it.freightFee == null }
    val piece = g.orders.mapNotNull { it.payPiece.toBigDecimalOrNull() }.fold(BigDecimal.ZERO) { a, b -> a + b }
    val commission = g.orders.mapNotNull { it.payCommission.toBigDecimalOrNull() }.fold(BigDecimal.ZERO) { a, b -> a + b }

    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 4.dp, bottom = 16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
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
                Text(
                    periodWord + "司机应得",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(2.dp))
                Text(
                    "¥" + formatMoney(g.total.toString()),
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold,
                    color = Color(MoneyO),
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
                "价格明细（每单：司机应得 / 货主运费）· 点一行看原始订单",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(start = 2.dp, top = 2.dp),
            )
        }
        itemsIndexed(g.orders, key = { _, o -> o.orderId }) { _, o ->
            // 明细行**可点**（2026-09-20 用户要求：「他的那个下面明细的订单卡片是可以点击的，
            // 点击就是原始的订单信息」）—— 结算时看到一笔对不上，下一件事一定是翻原单。
            SectionCard(Modifier.clickable { onOpenOrder(o.orderId) }) { SettlementOrderRow(o) }
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
        Spacer(Modifier.width(2.dp))
        // 可点的东西要有**看得见**的提示：不然"这一行能点"只有试过的人知道
        Icon(
            Icons.Default.ChevronRight,
            contentDescription = null,
            modifier = Modifier.size(18.dp),
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
