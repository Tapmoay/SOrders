package com.tapmoay.sorders.ui.dispatcher.report

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccountBalance
import androidx.compose.material.icons.filled.AccountBalanceWallet
import androidx.compose.material.icons.filled.Assessment
import androidx.compose.material.icons.filled.BarChart
import androidx.compose.material.icons.filled.CurrencyYuan
import androidx.compose.material.icons.filled.DirectionsCar
import androidx.compose.material.icons.filled.Insights
import androidx.compose.material.icons.filled.Inventory2
import androidx.compose.material.icons.filled.LocalShipping
import androidx.compose.material.icons.filled.Payments
import androidx.compose.material.icons.filled.Receipt
import androidx.compose.material.icons.filled.ReportProblem
import androidx.compose.material.icons.filled.Storefront
import androidx.compose.material.icons.filled.SwapHoriz
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import com.tapmoay.sorders.data.remote.dto.CustomerBalanceRowDto
import com.tapmoay.sorders.ui.common.EntryCard
import com.tapmoay.sorders.util.formatMoney
import com.tapmoay.sorders.util.moneyToDouble
import java.util.Locale

/**
 * 报表中心 v2（CHG-0034）的**共用色板**。
 *
 * 为什么单独一份：用户 2026-10-05 的要求是「能用图标就用图标、能用语义色就用语义色，
 * 但⚠️不能全是图标全是颜色（全是重点则就是没有重点）」—— 所以语义色必须有**固定含义**，
 * 每页各配一套的下场是"同一个绿在三个页面表示三件事"，用户记不住。
 *
 * 含义（⛔ 不许改，改了所有页面一起变味）：
 * · [good] 绿 = 赚 / 收到 / 正常；· [bad] 红 = **带负号的金额**（亏损 / 净流出 / 留抵 / 负可用额度）
 *   与「欠钱」（别人欠我 / 我欠别人 / 超额度）—— 用户 2026-10-05 改口径：「如果是负的钱的话…
 *   只要是带负号的都是用红色的，其他的用其他颜色或者黑色都没关系」；
 * · [warn] 橙 = 算不出来、待处理（异常单、缺台账、没进货价）与「钱还没到手/该付出去」；
 * · [info] 蓝 = 中性提示（进出、比例如实说出来）；· [violet] 紫 = 资产/存货一类"在手上的东西"；
 * · [gray] 灰 = 说不清的（接口没给的口径）。
 */
internal object Palette {
    val good = Color(0xFF00AC6E)
    val bad = Color(0xFFE07B80)
    val warn = Color(0xFFBC7730)
    val info = Color(0xFF00A4CE)
    val violet = Color(0xFF7B70DE)
    val gray = Color(0xFF477081)
}

/** 语义（不是颜色本身）：颜色随主题走的那一条由 [toneColor] 决定。 */
internal enum class Tone { PLAIN, GOOD, BAD, WARN, INFO, VIOLET, GRAY }

@Composable
internal fun toneColor(t: Tone): Color = when (t) {
    Tone.PLAIN -> MaterialTheme.colorScheme.onSurface
    Tone.GOOD -> Palette.good
    Tone.BAD -> Palette.bad
    Tone.WARN -> Palette.warn
    Tone.INFO -> Palette.info
    Tone.VIOLET -> Palette.violet
    Tone.GRAY -> Palette.gray
}

/**
 * 金额的语义：**带负号的金额一律红** —— 用户 2026-10-05 看过上一版（亏损画橙、只有欠钱才红）之后
 * 改的口径：「如果是负的钱的话，就是欠钱，只要是带负号的都是用红色的，其他的用其他颜色或者
 * 黑色都没关系」「也就是那些金钱显示啊」。所以负数是 [Tone.BAD]；≥ 0 仍然是绿（用户明确说
 * 其他颜色「都没关系」，所以非负这一侧不再细分）。
 *
 * ⚠️ 利润表里的结构减号行（「− 商品成本」「− 司机运费」等）**不**走这个函数：那些值本身是正数，
 * 减号只是公式的运算符，保持中性色（见 ReportV2Nodes.kt 的利润表节点）。
 */
internal fun amountTone(v: Double): Tone = if (v < 0) Tone.BAD else Tone.GOOD

/**
 * 报表中心的一个**节点**（一格屏）。
 *
 * 用户 2026-10-05：「越点越细、树状，甚至到每一张订单」。所以导航不是页签、是**栈**：
 * 首页 → 五张表的某一张 → 它的某一行 → 某个客户的单 → 那张单本身（走订单详情）。
 *
 * [parent] 只用于面包屑；[arg] 给"某一个客户"这类**动态节点**带参数（其余节点恒为 0）。
 */
data class ReportNode(
    val id: String,
    val title: String,
    val parent: String?,
    val icon: ImageVector,
    val color: Color,
    val arg: Long = 0L,
)

/**
 * 节点表 —— 报表中心的**一棵树**（唯一一份）。
 *
 * ⛔ 加节点只许在这里加：面包屑、抽屉高亮、返回上一层都读它。
 * 节点的 id 是稳定字符串（不是序号）—— 序号会在插入新节点时把后面全部挪位。
 */
internal object ReportNodes {

    val home = ReportNode("home", "报表中心", null, Icons.Default.Insights, Palette.violet)

    // 一、利润表这条链（营业额 → 成本/运费/费用/折旧 → 营业利润）
    val profit = ReportNode("pl", "利润表", "home", Icons.Default.CurrencyYuan, Palette.good)
    val revenue = ReportNode("pl.rev", "营业收入", "pl", Icons.Default.Payments, Palette.warn)
    val cost = ReportNode("pl.cost", "商品成本", "pl", Icons.Default.Inventory2, Palette.violet)
    val driverFee = ReportNode("pl.driver", "司机运费", "pl", Icons.Default.LocalShipping, Palette.good)
    val expense = ReportNode("pl.expense", "期间费用", "pl", Icons.Default.Receipt, Palette.info)
    val depreciation = ReportNode("pl.dep", "折旧", "pl", Icons.Default.DirectionsCar, Palette.gray)
    val tax = ReportNode("pl.tax", "税账（价外）", "pl", Icons.Default.Receipt, Palette.gray)

    // 二、资产负债表这条链（时点：别人欠我 / 库存 / 我欠谁）
    val balance = ReportNode("bs", "资产负债表", "home", Icons.Default.AccountBalance, Palette.info)
    val receivable = ReportNode("bs.ar", "别人欠我", "bs", Icons.Default.AccountBalanceWallet, Palette.warn)
    val stock = ReportNode("bs.stock", "库存", "bs", Icons.Default.Inventory2, Palette.violet)
    val driverPayable = ReportNode("bs.driver", "我欠司机", "bs", Icons.Default.LocalShipping, Palette.warn)
    val supplierPayable = ReportNode("bs.supplier", "我欠供应商", "bs", Icons.Default.Storefront, Palette.gray)

    // 三、现金流量表这条链（这一段真进真出）
    val cash = ReportNode("cf", "现金流量表", "home", Icons.Default.SwapHoriz, Palette.good)

    // 四、运营分析表这条链（哪赚哪亏：商品 / 司机 / 车辆 / 异常）
    val ops = ReportNode("ops", "运营分析表", "home", Icons.Default.BarChart, Palette.warn)
    val opsProducts = ReportNode("ops.products", "商品", "ops", Icons.Default.Inventory2, Palette.violet)
    val opsDrivers = ReportNode("ops.drivers", "司机", "ops", Icons.Default.LocalShipping, Palette.good)
    val opsVehicles = ReportNode("ops.vehicles", "车辆", "ops", Icons.Default.DirectionsCar, Palette.gray)
    val opsExceptions = ReportNode("ops.exceptions", "异常单", "ops", Icons.Default.ReportProblem, Palette.warn)

    // 五、关键指标表这条链（比率，全是页面按接口给的两个数相除算的）
    val kpi = ReportNode("kpi", "关键指标表", "home", Icons.Default.Assessment, Palette.good)

    /** 首页那张卡上的五行（顺序＝用户说的"五个标准"的顺序）。 */
    val fiveTables = listOf(profit, balance, cash, ops, kpi)

    /** 某一个客户的单（动态节点）：标题用客户自己的名字，parent 固定指向"别人欠我"。 */
    fun customer(row: CustomerBalanceRowDto, index: Int): ReportNode = ReportNode(
        id = "cust:" + index,
        title = row.name.ifBlank { row.customerNames.firstOrNull().orEmpty().ifBlank { "这个客户" } },
        parent = receivable.id,
        icon = Icons.Default.Storefront,
        color = Palette.warn,
        arg = index.toLong(),
    )
}

/**
 * 报表中心那 11 个**老入口**（原样保留 —— 用户 2026-10-05：「原先的也做一个保存」）。
 *
 * ⛔ key 直接当页签号用（见 `ReportFinance.exportKind`），**新格只许追加在末尾**：
 * 往中间插一个号会让后面每一格都指到别人的页面上（历史上就是这样错的）。
 * ⛔ 这一份是**唯一一份**：老入口页 `ReportHomeScreen` 与 v2 的「详细报表」都读它。
 */
internal val REPORT_ENTRIES: List<EntryCard> = listOf(
    EntryCard("0", "营业纵览", Icons.Default.Payments, Color(0xFFBC7730)),
    EntryCard("1", "商品经营", Icons.Default.Inventory2, Color(0xFFA980F1)),
    EntryCard("2", "司机绩效", Icons.Default.LocalShipping, Color(0xFF00AC6E)),
    EntryCard("3", "客户经营", Icons.Default.Storefront, Color(0xFF00A4CE)),
    EntryCard("4", "资金收支", Icons.Default.SwapHoriz, Color(0xFF7B70DE)),
    // 2026-10-05 CHG-0036：用户定「红色只给欠钱」（别人欠我 / 我欠别人 / 超额度）。异常不是欠账，
    // 所以它从红 #FF4D4F 换成设计系统里已有的琥珀 #F5A623（与「营业纵览」的金橙 #FF9500 同族但更深）。
    EntryCard("5", "异常与审计", Icons.Default.ReportProblem, Color(0xFFC48C1D)),
    EntryCard("6", "经营利润", Icons.Default.CurrencyYuan, Color(0xFF00BAA6)),
    EntryCard("7", "车辆成本", Icons.Default.DirectionsCar, Color(0xFF477081)),
    EntryCard("8", "成本覆盖", Icons.Default.BarChart, Color(0xFF00B622)),
    EntryCard("9", "税账", Icons.Default.Receipt, Color(0xFFE08034)),
    EntryCard("10", "客户欠款", Icons.Default.AccountBalanceWallet, Color(0xFFD60000)),
)

/** 抽屉里每个老入口底下的**一句白话**（用户：「让不懂会计的人也看得懂」）。 */
internal val REPORT_ENTRY_SUBS: Map<String, String> = mapOf(
    "0" to "这一段卖了多少、收回多少、还挂多少",
    "1" to "哪个商品赚钱、哪个货损多",
    "2" to "每个司机跑了多少、还欠他多少运费",
    "3" to "哪些客户在买、买得最多的是谁",
    "4" to "这一段进来多少、出去多少",
    "5" to "哪几张单卡住了、谁改了钱和数据",
    "6" to "营业额减掉各项成本后还剩多少",
    "7" to "每台车这一段花了多少钱",
    "8" to "有多少收入因为没有进货价而算不出成本",
    "9" to "这一段开了多少票、该交多少增值税",
    "10" to "谁欠我钱、欠了多久、有没有超额度",
)

// ---------------------------------------------------------------- 数字格式化
// ⚠️ 金额一律走 util 的 formatMoney：它**已经去掉了尾零**（"87.00" → "87"、"-0" 摆正），
//    所以"数字后面不要那么多零"这条要求对金额本来就成立，这里不再自己写一份。

internal fun num(raw: String?): Double = moneyToDouble(raw)

/** 金额文本（带 ¥，已去尾零）。 */
internal fun money(raw: String?): String = "¥" + formatMoney(raw)

/**
 * 百分比文本：分母为 0（或拿不到数）时回 **"—"**，⛔ 不许回 0% ——
 * 0% 是"算出来是零"，"—" 是"算不出来"，用户对这两句话的反应完全不同。
 */
internal fun percentText(v: Double?): String {
    if (v == null || v.isNaN() || v.isInfinite()) return "—"
    val p = v * 100
    val s = if (kotlin.math.abs(p) < 10.0) String.format(Locale.US, "%.1f", p) else String.format(Locale.US, "%.0f", p)
    // 小数位那一档也去尾零：0.0% → 0%（用户要的「不要那么多零」同样适用于比率）。
    // ⚠️ 只去掉整档的 ".0"：0.9% 一个字都不少，"0" 与 "-0" 都写成 0%。
    val clean = s.removeSuffix(".0")
    return if (clean == "-0" || clean == "0") "0%" else clean + "%"
}

/** 两个数相除（分母 0 → null，显示成"—"）。 */
internal fun ratio(numerator: Double, denominator: Double): Double? =
    if (denominator == 0.0) null else numerator / denominator

internal fun ratioOf(numeratorRaw: String?, denominatorRaw: String?): Double? =
    ratio(num(numeratorRaw), num(denominatorRaw))

/** 迷你条的长度（相对同组最大值；值为 0 时留一点点，否则那一行看着像没画）。 */
internal fun fractionOf(value: Double, max: Double): Float {
    if (max <= 0.0) return 0.02f
    return (kotlin.math.abs(value) / max).toFloat().coerceIn(0.02f, 1f)
}

/** 日期文本截短（"2026-09-30T…" → "09-30"）。 */
internal fun shortDate(raw: String?): String {
    val s = raw?.trim().orEmpty()
    if (s.length >= 10) return s.substring(5, 10)
    return s
}
