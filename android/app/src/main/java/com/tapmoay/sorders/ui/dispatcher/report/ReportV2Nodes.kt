package com.tapmoay.sorders.ui.dispatcher.report

import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.ui.common.EmptyView
import com.tapmoay.sorders.ui.common.LoadingBox
import com.tapmoay.sorders.ui.common.SectionCard
import com.tapmoay.sorders.ui.dispatcher.ReportFinance
import java.util.Locale

/**
 * 报表中心 v2 的**下钻层**（CHG-0034）：从首页那五张表点进来之后的每一层。
 *
 * 三条规矩（与首页同一套，写在 `ReportV2ViewModel` 顶部）：
 * - 每个金额都是接口字段本身，页面不做钱的加减；唯二的例外（司机待结、应付供应商）在那一行上写明「这一行是页面相加的」。
 * - 比率是页面算的（接口没给），分母为 0 写「—」不是 0%。
 * - 「别人欠我」是**时点**账（到 [ReportV2ViewModel.asOfText] 那一天为止），与「这一段」的区间账各写各的时间。
 *
 * ⛔ 最后一层必须落在**订单**上（`onOpenOrder`）；接口没有逐单明细的地方要如实写「接口没有给这个」，
 *    不许拿别的东西凑一个列表出来。
 */
internal fun LazyListScope.reportNodeItems(
    vm: ReportV2ViewModel,
    node: ReportNode,
    onOpen: (ReportNode) -> Unit,
    onOpenTab: (Int) -> Unit,
    onOpenOrder: (Long) -> Unit,
) {
    when {
        node.id == ReportNodes.profit.id -> item { ProfitNode(vm, onOpen, onOpenTab) }
        node.id == ReportNodes.revenue.id -> item { RevenueNode(vm, onOpen, onOpenTab) }
        node.id == ReportNodes.cost.id -> item { CostNode(vm, onOpen, onOpenTab) }
        node.id == ReportNodes.driverFee.id -> item { DriverFeeNode(vm, onOpen, onOpenTab) }
        node.id == ReportNodes.expense.id -> item { ExpenseNode(vm, onOpenOrder) }
        node.id == ReportNodes.depreciation.id -> item { DepreciationNode(vm) }
        node.id == ReportNodes.tax.id -> item { TaxNode(vm, onOpenTab) }
        node.id == ReportNodes.balance.id -> item { BalanceNode(vm, onOpen) }
        node.id == ReportNodes.receivable.id -> item { ReceivableNode(vm) }
        node.id == ReportNodes.stock.id -> item { StockNode(vm, onOpenTab) }
        node.id == ReportNodes.driverPayable.id -> item { DriverPayableNode(vm, onOpen, onOpenTab) }
        node.id == ReportNodes.supplierPayable.id -> item { SupplierPayableNode(vm, onOpenTab) }
        node.id == ReportNodes.cash.id -> item { CashNode(vm, onOpenTab) }
        node.id == ReportNodes.ops.id -> item { OpsNode(vm, onOpen) }
        node.id == ReportNodes.opsProducts.id -> item { ProductsNode(vm, onOpenTab) }
        node.id == ReportNodes.opsDrivers.id -> item { DriversNode(vm, onOpen, onOpenTab) }
        node.id == ReportNodes.opsVehicles.id -> item { VehiclesNode(vm, onOpenTab) }
        node.id == ReportNodes.opsExceptions.id -> item { ExceptionsNode(vm, onOpenOrder, onOpenTab) }
        node.id == ReportNodes.kpi.id -> item { KpiNode(vm) }
        node.id.startsWith("cust:") -> item { CustomerNode(vm, node, onOpenOrder) }
        else -> item { EmptyView("这一页还没接上") }
    }
}

/** 长清单只画前这么多条（手机上一屏滚到底没人看，末尾会写清楚一共多少条）。 */
private const val LIST_CAP = 40

private fun moneyOf(v: Double): String = money(String.format(Locale.US, "%.2f", v))

@Composable
private fun CapNote(total: Int) {
    if (total > LIST_CAP) NoteText("只画了前 " + LIST_CAP + " 条（一共 " + total + " 条）。")
}

/** 一个节点的头：这是什么、这一段是哪一段、大数是多少。 */
@Composable
private fun Head(title: String, sub: String?, amount: String?, tone: Tone, icon: ImageVector? = null, color: Color = Palette.gray, subHint: Boolean = false) {
    LineRow(icon, color, title, sub, amount, if (tone == Tone.PLAIN) Color.Unspecified else toneColor(tone), null, false, MaterialTheme.typography.titleLarge, subHint = subHint)
    HairLine()
}

// ------------------------------------------------------------------ 利润表
@Composable
private fun ProfitNode(vm: ReportV2ViewModel, onOpen: (ReportNode) -> Unit, onOpenTab: (Int) -> Unit) {
    val p = vm.profit
    SectionCard {
        SectionTitle("利润表")
        Spacer(Modifier.height(4.dp))
        if (p == null) { LoadingBox(); return@SectionCard }
        Head(
            "营业利润",
            null,
            money(p.operatingProfit),
            amountTone(vm.operatingProfit),
        )
        LineRow(ReportNodes.revenue.icon, ReportNodes.revenue.color, "营业收入", null, money(p.revenueTotal), Color.Unspecified, { onOpen(ReportNodes.revenue) }, true)
        HairLine()
        LineRow(ReportNodes.cost.icon, ReportNodes.cost.color, "− 商品成本", "按进货价算", "−" + money(p.costTotal), Color.Unspecified, { onOpen(ReportNodes.cost) }, true)
        HairLine()
        LineRow(null, Palette.gray, "＝ 商品毛利", "毛利率 " + percentText(ratioOf(p.grossProfit, p.revenueTotal)), money(p.grossProfit), toneColor(amountTone(vm.grossProfit)), null, false)
        HairLine()
        LineRow(ReportNodes.driverFee.icon, ReportNodes.driverFee.color, "− 司机运费", "按每单应付给司机的钱", "−" + money(p.deliveryCost), Color.Unspecified, { onOpen(ReportNodes.driverFee) }, true)
        HairLine()
        LineRow(ReportNodes.expense.icon, ReportNodes.expense.color, "− 期间费用", "油费、维修、过路费这些", "−" + money(p.operatingExpenseTotal), Color.Unspecified, { onOpen(ReportNodes.expense) }, true)
        HairLine()
        LineRow(ReportNodes.depreciation.icon, ReportNodes.depreciation.color, "− 车辆折旧", "车没填购置价就算不出来", "−" + money(p.depreciationTotal), Color.Unspecified, { onOpen(ReportNodes.depreciation) }, true)
        HairLine()
        LineRow(null, Palette.gray, "＝ 营业利润", null, money(p.operatingProfit), toneColor(amountTone(vm.operatingProfit)), null, false)
        Spacer(Modifier.height(6.dp))
        OldEntryRow("老页面：营业纵览", 0, onOpenTab)
    }
}

@Composable
private fun RevenueNode(vm: ReportV2ViewModel, onOpen: (ReportNode) -> Unit, onOpenTab: (Int) -> Unit) {
    val p = vm.profit
    val t = vm.turnover
    SectionCard {
        SectionTitle("营业收入")
        Spacer(Modifier.height(4.dp))
        if (p == null || t == null) { LoadingBox(); return@SectionCard }
        Head("该收多少", "已送达的单才算", money(p.revenueTotal), Tone.PLAIN, subHint = true)
        LineRow(null, Palette.gray, "有成本出处的收入", null, money(p.revenueCovered), Color.Unspecified, null, false)
        HairLine()
        LineRow(null, Palette.gray, "没成本出处的收入", "没有进货价，算不出成本", money(p.revenueUncovered), toneColor(Tone.WARN), { onOpen(ReportNodes.cost) }, true)
        HairLine()
        LineRow(null, Palette.gray, "单数与客单", (t.totalOrders).toString() + " 单已送达 · 客单 " + money(t.avgOrder), null, Color.Unspecified, null, false)
        Spacer(Modifier.height(6.dp))
        LineRow(ReportNodes.opsProducts.icon, ReportNodes.opsProducts.color, "按商品看", null, null, Color.Unspecified, { onOpen(ReportNodes.opsProducts) }, true)
        HairLine()
        LineRow(ReportNodes.receivable.icon, ReportNodes.receivable.color, "按客户看（谁还欠着）", null, null, Color.Unspecified, { onOpen(ReportNodes.receivable) }, true)
        OldEntryRow("老页面：营业纵览", 0, onOpenTab)
    }
}

@Composable
private fun CostNode(vm: ReportV2ViewModel, onOpen: (ReportNode) -> Unit, onOpenTab: (Int) -> Unit) {
    val c = vm.costCoverage
    val p = vm.profit
    SectionCard {
        SectionTitle("商品成本")
        Spacer(Modifier.height(4.dp))
        if (c == null || p == null) { LoadingBox(); return@SectionCard }
        Head("这一段卖出去的货，进价一共多少", "按入库流水的加权平均进货价算；这一段有 " + c.totalLines + " 行、其中 " + c.coveredLines + " 行算得出成本", money(p.costTotal), Tone.PLAIN)
        LineRow(null, Palette.gray, "有出处的收入", "算得出成本的收入", money(c.revenueCovered), Color.Unspecified, null, false)
        HairLine()
        LineRow(null, Palette.gray, "没出处的收入", "没有进货价，这部分毛利算不准", money(c.revenueUncovered), toneColor(Tone.WARN), null, false)
        HairLine()
        LineRow(null, Palette.gray, "靠平均价算的行", c.costAvgLines.toString() + " 行", c.costSnapshotLines.toString() + " 行有快照", Color.Unspecified, null, false)
        if (c.missingPurchasePriceCount > 0) {
            Spacer(Modifier.height(6.dp))
            NoteText("有 " + c.missingPurchasePriceCount + " 个商品没填进货价：")
            c.missingPurchasePrice.take(LIST_CAP).forEach { item ->
                LineRow(null, Palette.gray, item.name.orEmpty().ifBlank { "（没名字）" }, "库存 " + item.stock + " " + item.unit, "缺进货价", toneColor(Tone.WARN), null, false)
            }
            CapNote(c.missingPurchasePrice.size)
            LineRow(null, Palette.violet, "去哪儿补", "商品资料里填上进货价，这一段就会自动重算", null, Color.Unspecified, { onOpenTab(1) }, true)
        } else {
            NoteText("这一段没有算不出成本的商品。")
        }
    }
}

@Composable
private fun DriverFeeNode(vm: ReportV2ViewModel, onOpen: (ReportNode) -> Unit, onOpenTab: (Int) -> Unit) {
    val p = vm.profit
    SectionCard {
        SectionTitle("司机运费（按单应付）")
        Spacer(Modifier.height(4.dp))
        if (p == null) { LoadingBox(); return@SectionCard }
        Head("这一段该付给司机多少", "按每一单的规则算出来的应得，不是订单上那个运费字段", money(p.deliveryCost), Tone.PLAIN, subHint = true)
        val rows = owedRows(vm)
        if (rows.isEmpty()) {
            EmptyView("这一段没有司机的待结运费")
        } else {
            rows.take(LIST_CAP).forEach { d ->
                LineRow(null, Palette.gray, d.driverName.orEmpty().ifBlank { "（没名字）" }, "完成了 " + d.completedCount + " 单", money(d.freightOwed), toneColor(Tone.BAD), { onOpen(ReportNodes.driverPayable) }, true)
            }
            CapNote(rows.size)
        }
        Spacer(Modifier.height(6.dp))
        LineRow(ReportNodes.driverPayable.icon, ReportNodes.driverPayable.color, "谁还没结、欠了多少", null, null, Color.Unspecified, { onOpen(ReportNodes.driverPayable) }, true)
        OldEntryRow("老页面：司机绩效", 2, onOpenTab)
    }
}

@Composable
private fun ExpenseNode(vm: ReportV2ViewModel, onOpenOrder: (Long) -> Unit) {
    val p = vm.profit
    SectionCard {
        SectionTitle("期间费用")
        Spacer(Modifier.height(4.dp))
        if (p == null) { LoadingBox(); return@SectionCard }
        Head("这一段花掉多少", "油费、维修、过路费、罚款这些日常开销", money(p.operatingExpenseTotal), Tone.WARN, subHint = true)
        val byCat = p.operatingExpenses
        if (byCat.isEmpty()) {
            EmptyView("这一段没有分类明细")
        } else {
            byCat.forEach { e ->
                LineRow(null, Palette.gray, ReportFinance.expenseCategoryLabel(e.category), null, money(e.amount), Color.Unspecified, null, false)
            }
        }
        Spacer(Modifier.height(8.dp))
        SectionTitle("每一笔（能点开单子）")
        val all = vm.expenses
        if (all.isEmpty()) {
            EmptyView("这一段的费用单据列表是空的")
        } else {
            all.take(LIST_CAP).forEach { x ->
                val who = listOfNotNull(
                    x.vehicleName?.takeIf { it.isNotBlank() },
                    x.driverName?.takeIf { it.isNotBlank() },
                    x.orderNo?.takeIf { it.isNotBlank() },
                ).joinToString(" · ")
                LineRow(
                    null, Palette.gray,
                    ReportFinance.expenseCategoryLabel(x.category) + (if (x.note.orEmpty().isBlank()) "" else "（" + x.note.orEmpty() + "）"),
                    shortDate(x.expDate) + (if (who.isBlank()) "" else " · " + who),
                    money(x.amount),
                    Color.Unspecified,
                    if (x.orderId != null) ({ onOpenOrder(x.orderId!!) }) else null,
                    x.orderId != null,
                )
            }
            CapNote(all.size)
        }
    }
}

@Composable
private fun DepreciationNode(vm: ReportV2ViewModel) {
    val v = vm.vehicleCost
    SectionCard {
        SectionTitle("车辆折旧")
        Spacer(Modifier.height(4.dp))
        if (v == null) { LoadingBox(); return@SectionCard }
        Head(
            "这一段摊到的折旧",
            "按购置价、使用年限、残值率摊到这一段；" + v.vehicleCount.toString() + " 台车里 " + v.uncoveredCount.toString() + " 台算不出来",
            money(v.depreciationTotal),
            Tone.PLAIN,
        )
        NoteText("每月计提 " + money(v.depreciationMonthlyTotal))
        val cars = v.perVehicle.filter { num(it.depreciation) != 0.0 || !it.depreciationCovered }
        if (cars.isEmpty()) {
            EmptyView("这一段没有需要提折旧的车")
        } else {
            cars.take(LIST_CAP).forEach { c ->
                val why = c.depreciationUncoveredReasons.firstOrNull()
                val sub = if (c.depreciationCovered) {
                    "购置价 " + money(c.purchasePrice) + " · 用 " + (c.usefulLifeYears ?: 0) + " 年"
                } else {
                    "算不出来：" + (why ?: "台账缺一格")
                }
                LineRow(null, if (c.depreciationCovered) Palette.gray else Palette.warn, c.plateNo + " · " + c.driverName.orEmpty().ifBlank { "没挂司机" }, sub, if (c.depreciationCovered) money(c.depreciation) else "—", toneColor(if (c.depreciationCovered) Tone.PLAIN else Tone.WARN), null, false)
            }
            CapNote(cars.size)
        }
        Spacer(Modifier.height(6.dp))
    }
}

@Composable
private fun TaxNode(vm: ReportV2ViewModel, onOpenTab: (Int) -> Unit) {
    val t = vm.taxSummary
    SectionCard {
        SectionTitle("税账（增值税）")
        Spacer(Modifier.height(4.dp))
        if (t == null) { LoadingBox(); return@SectionCard }
        Head("这一段应纳增值税", "销项减进项；增值税是价外税，不从营业利润那条链里扣", money(t.vatPayable), Tone.INFO, subHint = true)
        LineRow(null, Palette.gray, "销项（开出去的票）", (t.output?.count ?: 0).toString() + " 张 · 不含税 " + money(t.output?.netAmount), money(t.output?.taxAmount), Color.Unspecified, null, false)
        HairLine()
        LineRow(null, Palette.gray, "进项（收进来的票）", (t.input?.count ?: 0).toString() + " 张 · 不含税 " + money(t.input?.netAmount), money(t.input?.taxAmount), Color.Unspecified, null, false)
        HairLine()
        LineRow(null, Palette.gray, "没标税率的张数", "销项 " + (t.output?.untaxedCount ?: 0) + " 张 · 进项 " + (t.input?.untaxedCount ?: 0) + " 张", null, Color.Unspecified, null, false)
        Spacer(Modifier.height(6.dp))
        OldEntryRow("老页面：税账", 9, onOpenTab)
    }
}

// ------------------------------------------------------------------ 资产负债表
@Composable
private fun BalanceNode(vm: ReportV2ViewModel, onOpen: (ReportNode) -> Unit) {
    val c = vm.customers
    SectionCard {
        SectionTitle("资产负债表（到 " + vm.asOfText + " 为止）")
        Spacer(Modifier.height(4.dp))
        if (c == null) { LoadingBox(); return@SectionCard }
        Head("别人欠我的 + 我手上的 − 我欠别人的", "这是时点账（某一天为止的结存），不是「这一段」发生了多少", money(c.totals?.balance), Tone.BAD, subHint = true)
        LineRow(ReportNodes.receivable.icon, ReportNodes.receivable.color, "别人欠我", (c.totals?.debtorCount ?: 0).toString() + " 个客户 · " + (c.totals?.orderCount ?: 0) + " 张单", money(c.totals?.balance), toneColor(Tone.BAD), { onOpen(ReportNodes.receivable) }, true)
        HairLine()
        LineRow(null, Palette.gray, "客户先给的钱（预收）", "钱到了、货还没发，这是欠别人的货", money(c.totals?.prepaid), Color.Unspecified, null, false)
        HairLine()
        LineRow(ReportNodes.stock.icon, ReportNodes.stock.color, "库存（按数量看）", "接口只给数量、没有金额；要有金额得先有进货价", vm.stockKinds.toString() + " 个品种有结存", Color.Unspecified, { onOpen(ReportNodes.stock) }, true)
        HairLine()
        LineRow(ReportNodes.driverPayable.icon, ReportNodes.driverPayable.color, "我欠司机（待结运费）", "接口按人给，这一行是页面相加的", moneyOf(vm.driverOwed), toneColor(Tone.BAD), { onOpen(ReportNodes.driverPayable) }, true)
        HairLine()
        LineRow(ReportNodes.supplierPayable.icon, ReportNodes.supplierPayable.color, "我欠供应商（应付货款）", "接口按单给，这一行是页面相加的", moneyOf(vm.supplierUnpaid), Color.Unspecified, { onOpen(ReportNodes.supplierPayable) }, true)
        HairLine()
        LineRow(ReportNodes.depreciation.icon, ReportNodes.depreciation.color, "固定资产（车）", "车没填购置价，账上算不出这一块", "缺台账", toneColor(Tone.WARN), { onOpen(ReportNodes.depreciation) }, true)
        Spacer(Modifier.height(6.dp))
    }
}

@Composable
private fun ReceivableNode(vm: ReportV2ViewModel) {
    val c = vm.customers
    SectionCard {
        SectionTitle("别人欠我（到 " + vm.asOfText + " 为止）")
        Spacer(Modifier.height(4.dp))
        if (c == null) { LoadingBox(); return@SectionCard }
        Head("一共 " + (c.totals?.debtorCount ?: 0) + " 个客户欠款", (c.totals?.orderCount ?: 0).toString() + " 张单挂账 · 超额度 " + (c.totals?.overLimitCount ?: 0) + " 家", money(c.totals?.balance), Tone.BAD)
        val buckets = c.totals?.buckets.orEmpty()
        if (buckets.isEmpty()) {
            NoteText("这个版本没有给账龄分档。")
        } else {
            buckets.forEach { (k, v) -> LineRow(null, Palette.gray, ReportFinance.bucketLabel(k), "压在这一档里的欠款", money(v), Color.Unspecified, null, false) }
        }
        Spacer(Modifier.height(8.dp))
        SectionTitle("欠得最多的（一个一个看）")
        val rows = c.rows.withIndex().sortedByDescending { num(it.value.balance) }
        if (rows.isEmpty()) {
            EmptyView("到这一天为止没有欠款")
        } else {
            rows.take(LIST_CAP).forEach { e ->
                val r = e.value
                val sub = listOfNotNull(
                    (r.orderCount).toString() + " 单",
                    if (r.oldestDays > 0) "最久 " + r.oldestDays + " 天" else null,
                    if (r.overLimit) "超额度" else null,
                ).joinToString(" · ")
                LineRow(null, if (r.overLimit) Palette.bad else Palette.gray, r.name.orEmpty().ifBlank { ReportFinance.debtorKindLabel(r.kind) }, sub, money(r.balance), toneColor(Tone.BAD), { vm.openCustomer(e.index) }, true)
            }
            CapNote(rows.size)
        }
    }
}

@Composable
private fun CustomerNode(vm: ReportV2ViewModel, node: ReportNode, onOpenOrder: (Long) -> Unit) {
    val row = vm.customers?.rows?.getOrNull(node.arg.toInt())
    SectionCard {
        SectionTitle(node.title)
        Spacer(Modifier.height(4.dp))
        if (row == null) {
            EmptyView("这个客户不在这份欠款清单里了 —— 换过时间档位之后清单会重排，回上一页重新点一次。")
            return@SectionCard
        }
        Head("欠款（到 " + vm.asOfText + " 为止）", (row.orderCount).toString() + " 张单" + (if (row.oldestDays > 0) " · 最久 " + row.oldestDays + " 天" else "") + (if (row.phone.orEmpty().isNotBlank()) " · " + row.phone.orEmpty() else ""), money(row.balance), Tone.BAD)
        if (!row.limit.isNullOrBlank()) {
            LineRow(null, Palette.gray, "信用额度", "已用 " + money(row.creditUsed), money(row.limit), Color.Unspecified, null, false)
            HairLine()
            LineRow(null, if (row.overLimit) Palette.bad else Palette.gray, "还能欠多少", if (row.overLimit) "已经超过额度了" else "剩下的额度", money(row.creditAvailable), toneColor(if (row.overLimit) Tone.BAD else Tone.GOOD), null, false)
        }
        Spacer(Modifier.height(8.dp))
        SectionTitle("每一张单")
        if (row.orders.isEmpty()) {
            EmptyView("接口没有给这个客户的逐单明细")
        } else {
            row.orders.forEach { o ->
                val sub = listOfNotNull(
                    shortDate(o.deliveredOn).takeIf { it.isNotBlank() }?.plus(" 送达"),
                    o.shipperName.orEmpty().takeIf { it.isNotBlank() },
                    if (o.days > 0) "账龄 " + o.days + " 天" else null,
                    ReportFinance.bucketLabel(o.bucket),
                ).joinToString(" · ")
                LineRow(null, Palette.gray, o.orderNo.orEmpty().ifBlank { "（没有单号）" }, sub, money(o.arrears), toneColor(if (num(o.arrears) > 0) Tone.BAD else Tone.PLAIN), { onOpenOrder(o.orderId) }, true)
            }
        }
    }
}

@Composable
private fun StockNode(vm: ReportV2ViewModel, onOpenTab: (Int) -> Unit) {
    SectionCard {
        SectionTitle("库存")
        Spacer(Modifier.height(4.dp))
        val list = vm.inventory
        if (list.isEmpty()) { LoadingBox(); return@SectionCard }
        Head("手上有 " + vm.stockKinds + " 个品种有结存", "接口只给数量、没有金额", null, Tone.PLAIN)
        list.sortedByDescending { it.stock }.take(LIST_CAP).forEach { i ->
            LineRow(null, Palette.gray, i.productName.orEmpty().ifBlank { "（没名字）" }, i.category.orEmpty().ifBlank { "没分类" } + (if (i.reserved > 0) " · 已留 " + i.reserved else ""), i.stock.toString() + " " + i.unit, Color.Unspecified, null, false)
        }
        CapNote(list.size)
        LineRow(null, Palette.violet, "看库存流水（每一笔进出）", "老页面里能看到每一笔入库出库", null, Color.Unspecified, { onOpenTab(1) }, true)
    }
}

@Composable
private fun DriverPayableNode(vm: ReportV2ViewModel, onOpen: (ReportNode) -> Unit, onOpenTab: (Int) -> Unit) {
    SectionCard {
        SectionTitle("我欠司机（待结运费）")
        Spacer(Modifier.height(4.dp))
        val rows = owedRows(vm)
        if (vm.drivers == null) { LoadingBox(); return@SectionCard }
        Head("一共欠 " + rows.size + " 个司机", "接口按人给、没有给合计 —— 这一行是页面把每个司机的数相加起来的", moneyOf(vm.driverOwed), Tone.BAD)
        if (rows.isEmpty()) {
            EmptyView("这一段没有待结运费")
        } else {
            rows.take(LIST_CAP).forEach { d ->
                LineRow(null, Palette.gray, d.driverName.orEmpty().ifBlank { "（没名字）" }, "完成 " + d.completedCount + " 单" + (d.billingMode?.takeIf { it.isNotBlank() }?.let { " · " + it } ?: ""), money(d.freightOwed), toneColor(Tone.BAD), null, false)
            }
            CapNote(rows.size)
        }
        Spacer(Modifier.height(6.dp))
        OldEntryRow("老页面：司机绩效", 2, onOpenTab)
        LineRow(ReportNodes.driverFee.icon, ReportNodes.driverFee.color, "这些钱是怎么算出来的", "按单应付的那份明细", null, Color.Unspecified, { onOpen(ReportNodes.driverFee) }, true)
    }
}

@Composable
private fun SupplierPayableNode(vm: ReportV2ViewModel, onOpenTab: (Int) -> Unit) {
    SectionCard {
        SectionTitle("我欠供应商（应付货款）")
        Spacer(Modifier.height(4.dp))
        val list = vm.payables
        Head("一共 " + list.size + " 张单", "接口按单给、没有给合计 —— 这一行是页面把它们相加起来的", moneyOf(vm.supplierUnpaid), Tone.BAD)
        if (list.isEmpty()) {
            EmptyView("这一段没有应付未付的货款")
        } else {
            list.sortedByDescending { num(it.unpaid) }.take(LIST_CAP).forEach { s ->
                val sub = listOfNotNull(
                    s.supplierName.orEmpty().takeIf { it.isNotBlank() },
                    shortDate(s.docDate).takeIf { it.isNotBlank() },
                    if (s.paid.orEmpty().isBlank()) null else "已付 " + money(s.paid),
                    if (s.paymentCount > 0) "付过 " + s.paymentCount + " 次" else null,
                ).joinToString(" · ")
                LineRow(null, Palette.gray, s.title.orEmpty().ifBlank { "（没有名目）" }, sub, money(s.unpaid), toneColor(if (num(s.unpaid) > 0) Tone.BAD else Tone.PLAIN), null, false)
            }
            CapNote(list.size)
        }
        Spacer(Modifier.height(6.dp))
        OldEntryRow("老页面：客户欠款", 10, onOpenTab)
    }
}

// ------------------------------------------------------------------ 现金流量表
@Composable
private fun CashNode(vm: ReportV2ViewModel, onOpenTab: (Int) -> Unit) {
    val s = vm.cashSummary
    SectionCard {
        SectionTitle("现金流量表")
        Spacer(Modifier.height(4.dp))
        if (s == null) { LoadingBox(); return@SectionCard }
        Head("这一段真进来多少、真出去多少", "看的是钱有没有动（收付款流水），与「该收多少」不是一回事", money(s.net), amountTone(num(s.net)))
        LineRow(null, Palette.good, "进来", "收到的货款（现金 / 转账）", money(s.income), toneColor(Tone.GOOD), null, false)
        HairLine()
        LineRow(null, Palette.warn, "出去", "付给司机、供应商、日常开销", money(s.expense), toneColor(Tone.WARN), null, false)
        HairLine()
        LineRow(null, Palette.gray, "一共几笔", null, s.count.toString() + " 笔", Color.Unspecified, null, false)
        val ins = vm.cashInRows
        val outs = vm.cashOutRows
        if (ins.isNotEmpty() || outs.isNotEmpty()) {
            Spacer(Modifier.height(8.dp))
            SectionTitle("钱从哪儿进来")
            if (ins.isEmpty()) {
                LineRow(null, Palette.gray, "这一段没有进账", null, "—", Color.Unspecified, null, false)
            } else {
                ins.forEach { b ->
                    LineRow(null, Palette.good, ReportFinance.bizLabel(b.bizType), b.count.toString() + " 笔", money(b.amount), Color.Unspecified, null, false)
                }
            }
            Spacer(Modifier.height(8.dp))
            SectionTitle("钱花到哪儿去了")
            if (outs.isEmpty()) {
                LineRow(null, Palette.gray, "这一段没有出账", null, "—", Color.Unspecified, null, false)
            } else {
                outs.forEach { b ->
                    LineRow(null, Palette.warn, ReportFinance.bizLabel(b.bizType), b.count.toString() + " 笔", money(b.amount), Color.Unspecified, null, false)
                }
            }
        }
        Spacer(Modifier.height(6.dp))
        OldEntryRow("老页面：资金收支", 4, onOpenTab)
    }
}

// ------------------------------------------------------------------ 运营分析表
@Composable
private fun OpsNode(vm: ReportV2ViewModel, onOpen: (ReportNode) -> Unit) {
    val t = vm.turnover
    val p = vm.profit
    SectionCard {
        SectionTitle("运营分析表")
        Spacer(Modifier.height(4.dp))
        if (t == null || p == null) { LoadingBox(); return@SectionCard }
        Head("这一段卖出多少、赚多少", t.totalOrders.toString() + " 单已送达 · 客单 " + money(t.avgOrder), money(t.totalAmount), Tone.PLAIN)
        LineRow(null, Palette.gray, "营业额", "已送达的单", money(t.totalAmount), Color.Unspecified, null, false)
        HairLine()
        LineRow(null, Palette.gray, "商品毛利", "毛利率 " + percentText(ratioOf(p.grossProfit, p.revenueTotal)), money(p.grossProfit), toneColor(amountTone(vm.grossProfit)), null, false)
        HairLine()
        LineRow(null, Palette.gray, "营业利润", "减掉运费、费用、折旧之后", money(p.operatingProfit), toneColor(amountTone(vm.operatingProfit)), null, false, subHint = true)
        Spacer(Modifier.height(8.dp))
        SectionTitle("往哪儿看")
        LineRow(ReportNodes.opsProducts.icon, ReportNodes.opsProducts.color, "商品", "哪个卖得多、哪个亏", null, Color.Unspecified, { onOpen(ReportNodes.opsProducts) }, true)
        HairLine()
        LineRow(ReportNodes.opsDrivers.icon, ReportNodes.opsDrivers.color, "司机", "跑了多少、还欠多少", null, Color.Unspecified, { onOpen(ReportNodes.opsDrivers) }, true)
        HairLine()
        LineRow(ReportNodes.opsVehicles.icon, ReportNodes.opsVehicles.color, "车辆", "哪台车在烧钱", null, Color.Unspecified, { onOpen(ReportNodes.opsVehicles) }, true)
        HairLine()
        LineRow(ReportNodes.opsExceptions.icon, ReportNodes.opsExceptions.color, "异常单", "卡住的和超时的（近 30 天）", null, Color.Unspecified, { onOpen(ReportNodes.opsExceptions) }, true)
    }
}

@Composable
private fun ProductsNode(vm: ReportV2ViewModel, onOpenTab: (Int) -> Unit) {
    val p = vm.products
    SectionCard {
        SectionTitle("商品经营")
        Spacer(Modifier.height(4.dp))
        if (p == null) { LoadingBox(); return@SectionCard }
        Head("这一段卖了多少", p.items.size.toString() + " 个商品 · 一共 " + p.totalQty + " 件", money(p.totalAmount), Tone.PLAIN)
        val items = p.items.sortedByDescending { num(it.amount) }
        items.take(LIST_CAP).forEach { i ->
            val cost = num(i.cost)
            val sub = i.qty.toString() + " 件" + (if (cost > 0) " · 成本 " + money(i.cost) + " · 毛利 " + moneyOf(num(i.amount) - cost) else " · 没进货价，算不出毛利")
            LineRow(null, if (cost > 0) Palette.gray else Palette.warn, i.productName.orEmpty().ifBlank { "（没名字）" }, sub, money(i.amount), Color.Unspecified, null, false)
        }
        CapNote(items.size)
        OldEntryRow("老页面：商品经营", 1, onOpenTab)
    }
}

@Composable
private fun DriversNode(vm: ReportV2ViewModel, onOpen: (ReportNode) -> Unit, onOpenTab: (Int) -> Unit) {
    val d = vm.drivers
    SectionCard {
        SectionTitle("司机绩效")
        Spacer(Modifier.height(4.dp))
        if (d == null) { LoadingBox(); return@SectionCard }
        Head("这一段有 " + d.drivers.size + " 个司机在跑", "完成单数按已送达算", null, Tone.PLAIN, subHint = true)
        val rows = d.drivers.sortedByDescending { it.completedCount }
        rows.take(LIST_CAP).forEach { r ->
            LineRow(null, Palette.gray, r.driverName.ifBlank { "（没名字）" }, "完成 " + r.completedCount + " 单", money(r.freightOwed), toneColor(if (num(r.freightOwed) > 0) Tone.BAD else Tone.PLAIN), { onOpen(ReportNodes.driverPayable) }, true)
        }
        CapNote(rows.size)
        OldEntryRow("老页面：司机绩效", 2, onOpenTab)
    }
}

@Composable
private fun VehiclesNode(vm: ReportV2ViewModel, onOpenTab: (Int) -> Unit) {
    val v = vm.vehicleCost
    SectionCard {
        SectionTitle("车辆成本")
        Spacer(Modifier.height(4.dp))
        if (v == null) { LoadingBox(); return@SectionCard }
        Head("这一段这些车一共花了多少", v.vehicleCount.toString() + " 台车 · 开销 " + money(v.expenseTotal) + " + 配送 " + money(v.deliveryCostTotal) + " + 折旧 " + money(v.depreciationTotal), money(v.totalCost), Tone.PLAIN)
        val cars = v.perVehicle.sortedByDescending { num(it.totalCost) }
        cars.take(LIST_CAP).forEach { c ->
            val sub = "开销 " + money(c.expenseTotal) + " · 配送 " + money(c.deliveryCost) + " · 折旧 " + (if (c.depreciationCovered) money(c.depreciation) else "缺台账")
            LineRow(null, if (c.depreciationCovered) Palette.gray else Palette.warn, c.plateNo + " · " + c.driverName.orEmpty().ifBlank { "没挂司机" }, sub, money(c.totalCost), Color.Unspecified, null, false)
        }
        CapNote(cars.size)
        OldEntryRow("老页面：车辆成本", 7, onOpenTab)
    }
}

@Composable
private fun ExceptionsNode(vm: ReportV2ViewModel, onOpenOrder: (Long) -> Unit, onOpenTab: (Int) -> Unit) {
    SectionCard {
        SectionTitle("异常单（近 30 天）")
        Spacer(Modifier.height(4.dp))
        val list = vm.exceptions
        Head("卡住的和超时的", "⚠️ 这一页固定看最近 30 天，与上面那颗时间药丸的档位无关", list.size.toString() + " 单", if (list.isEmpty()) Tone.PLAIN else Tone.WARN)
        if (list.isEmpty()) {
            EmptyView("近 30 天没有异常单")
        } else {
            list.take(LIST_CAP).forEach { e ->
                val sub = listOfNotNull(
                    shortDate(e.orderDate).takeIf { it.isNotBlank() }?.plus(" 下单"),
                    e.shipperName?.takeIf { it.isNotBlank() },
                    e.driverName?.takeIf { it.isNotBlank() },
                    e.exceptionReason.orEmpty().takeIf { it.isNotBlank() },
                ).joinToString(" · ")
                LineRow(null, Palette.warn, e.orderNo.orEmpty().ifBlank { "（没有单号）" }, sub, null, Color.Unspecified, { onOpenOrder(e.id) }, true)
            }
            CapNote(list.size)
        }
        OldEntryRow("老页面：异常与审计", 5, onOpenTab)
    }
}

// ------------------------------------------------------------------ 关键指标表
@Composable
private fun KpiNode(vm: ReportV2ViewModel) {
    val p = vm.profit
    val c = vm.costCoverage
    val rev = vm.revenueAmount
    val margin = ratioOf(p?.grossProfit, p?.revenueTotal)
    val be = breakevenValue(p)
    val safety = if (be != null && rev != 0.0) (rev - be) / rev else null
    SectionCard {
        SectionTitle("赚不赚钱（比率）")
        Spacer(Modifier.height(4.dp))
        if (p == null) { LoadingBox(); return@SectionCard }
        LineRow(null, Palette.gray, "毛利率", "商品毛利 ÷ 营业额", percentText(margin), toneColor(if ((margin ?: 0.0) >= 0.0) Tone.GOOD else Tone.WARN), null, false, subHint = true)
        HairLine()
        LineRow(null, Palette.gray, "营业利润率", "营业利润 ÷ 营业额", percentText(ratioOf(p.operatingProfit, p.revenueTotal)), toneColor(amountTone(vm.operatingProfit)), null, false, subHint = true)
        HairLine()
        LineRow(null, Palette.warn, "净利率", "净利 = 营业利润 − 所得税；接口没有所得税这一项", "缺所得税", toneColor(Tone.WARN), null, false, subHint = true)
        HairLine()
        LineRow(null, Palette.gray, "保本营业额（粗算）", "（期间费用 + 折旧）÷ 毛利率；这一段要卖到这么多才不亏", if (be == null) "—" else moneyOf(be), Color.Unspecified, null, false, subHint = true)
        HairLine()
        LineRow(null, Palette.gray, "安全边际率", "（实际营业额 − 保本营业额）÷ 实际营业额；负的=还没到保本点", percentText(safety), toneColor(if ((safety ?: 0.0) >= 0.0) Tone.GOOD else Tone.WARN), null, false, subHint = true)
        Spacer(Modifier.height(8.dp))
        SectionTitle("成本和费用")
        LineRow(null, Palette.gray, "司机运费率", "司机运费 ÷ 营业额", percentText(ratioOf(p.deliveryCost, p.revenueTotal)), Color.Unspecified, null, false, subHint = true)
        HairLine()
        LineRow(null, Palette.gray, "期间费用率", "期间费用 ÷ 营业额", percentText(ratioOf(p.operatingExpenseTotal, p.revenueTotal)), Color.Unspecified, null, false, subHint = true)
        HairLine()
        LineRow(null, Palette.gray, "折旧占收入", "折旧 ÷ 营业额；车没填购置价就是 0", percentText(ratioOf(p.depreciationTotal, p.revenueTotal)), Color.Unspecified, null, false, subHint = true)
        HairLine()
        LineRow(null, Palette.gray, "成本覆盖率", "有成本出处的收入 ÷ 全部收入；低 = 毛利算不准", percentText(ratioOf(c?.revenueCovered, c?.revenueTotal)), toneColor(if ((ratioOf(c?.revenueCovered, c?.revenueTotal) ?: 1.0) >= 0.9) Tone.GOOD else Tone.WARN), null, false, subHint = true)
        Spacer(Modifier.height(6.dp))
    }
}

// ------------------------------------------------------------------ 公共小零件
/** 司机的待结运费（0 的不画）。 */
private fun owedRows(vm: ReportV2ViewModel) =
    vm.drivers?.drivers.orEmpty().filter { num(it.freightOwed) != 0.0 }.sortedByDescending { num(it.freightOwed) }

/** 老页面入口那一行（老 11 页一个都没删，从这儿进还是老样子）。 */
@Composable
private fun OldEntryRow(label: String, tab: Int, onOpenTab: (Int) -> Unit) {
    Spacer(Modifier.height(4.dp))
    LineRow(null, Palette.violet, label, null, "老样子 →", toneColor(Tone.VIOLET), { onOpenTab(tab) }, true)
}
