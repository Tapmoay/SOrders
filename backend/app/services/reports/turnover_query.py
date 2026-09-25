"""营业额 / 毛利 / 货损那一份**只读**查询（指南 §九 点名的 turnover_query）。


⛔ **只读**：本包下的模块只允许 SELECT / JOIN / GROUP BY —— 判据 _tools/qa/_check_report_boundary.py
在 AST 层面禁止落库写法与写服务依赖，而且它是**算出来的**（services/reports/** 由 glob 自动收）。
"""
from __future__ import annotations

from app.services.reports._common import _label, _range_dates, _span_label, _window
from app.services.reports.loader import load_delivered
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.core.business_time import business_date, business_local, business_range_utc
from app.models import Order
from app.models.enums import OrderStatus
from app.schemas.reports import ReportArrearsUnitItem, ReportSeriesItem
from app.services.cost_basis import SNAPSHOT, CostBasis
from app.services.money_contract import has_per_order_pay, line_receivable, money_map, pay_for_order



def build_turnover(db: Session, mode: str, anchor: date, *, span: tuple[date, date] | None = None) -> dict:
    """营业纵览聚合（含成本/毛利/货损/资金/撤销/挂账单位），供接口与导出复用。

    [span] 非空 = 这一段明确区间（App 的档位药丸走这条）；空 = 老口径 `mode` + `anchor`。
    两种走法**共用下面这一整段聚合**（`start`/`end` 是唯一的差别）——
    分成两份实现的下场是"同一个窗口两条路两个数"，而页面上看不出来。
    """
    d = anchor
    start, end = span if span else _window(mode, anchor)
    days = _range_dates(start, end)
    orders = load_delivered(db, span=(start, end))
    # ⚠️ 一页/一期的**钱**先一次算完（`order_money`：4 条分组查询，与订单条数无关）：
    #    本期营业额要**减掉退货红冲**、已收要含现场收现金、挂账要减掉已收与退货 ——
    #    这三件事原来各自用 `paid` + `line_total` 现算，加了"部分核销"与"退货"之后
    #    必然与账本页、订单详情说不到一起（而两边都不报错）。
    money = money_map(db, orders)
    # 成本口径**只有一处**（`services/cost_basis.py`）：本期的入库加权平均进货价。
    basis = CostBasis(db, start, end)
    day_map: dict[str, ReportSeriesItem] = {}
    hour_amount: dict[int, Decimal] = {}
    hour_orders: dict[int, int] = {}
    total_amount = Decimal("0")
    total_freight = Decimal("0")
    total_orders = 0
    cost_total = Decimal("0")
    cost_covered_amount = Decimal("0")
    total_lines = 0
    cost_covered_lines = 0
    # 参与毛利的行里，有多少行真的用了"入库加权平均进货价"、有多少行退回了下单快照
    cost_avg_lines = 0
    cost_snapshot_lines = 0
    damage_qty = 0
    damage_amount = Decimal("0")
    collected = Decimal("0")
    arrears_total = Decimal("0")
    arrears_map: dict[str, Decimal] = {}
    for o in orders:
        # ⚠️ 按**业务当地日**分桶（2026-09-19 审计 R12-M11）：`delivered_at` 存的是 UTC，
        #    直接用 `.date()` 会让东八区当地 00:00~08:00 送达的单落进**前一天**
        #    ——"早上看今天的日报是 0"就是这么来的，而两个页面都不报错。
        ds = business_date(o.delivered_at)
        if ds is None or ds < start or ds > end:
            continue
        key = f"{ds.month}-{ds.day}"
        # 营业额 = **应收**（`order_money.receivable`）＝ 当时卖的 − 退掉的。
        # 退货是"这笔生意少了一部分"，营业额不减就成了"退了货还照记收入"。
        mm = money[o.id]
        amount = mm.receivable
        item = day_map.setdefault(key, ReportSeriesItem(label=key))
        item.amount += amount
        item.orders += 1
        # ⚠️ 「司机运费支出」= **司机应得的钱**，不是订单上那个运费（2026-09-19 审计 R12-M2）：
        #    v3.36 起"司机拿多少"由计费规则决定（每单固定／运费提成／商品金额提成／工资+提成），
        #    而 `orders.freight_fee` 只是**提成基数**。原来这里直接累加它，于是同一个词
        #    在「营业纵览」和「司机运费结算」页是两个数（同一天实测：47870.00 vs 24770.00，
        #    虚高 93%），而两个页面都不报错——老板照这一格判断车费成本会系统性高估。
        #    口径现在与账单/结算页/司机绩效导出**同源**：`pay_for_order` 一处实现。
        pay = pay_for_order(o).total if has_per_order_pay(o) else Decimal("0")
        item.freight += pay
        # ⚠️ 小时桶也按**业务当地时刻**（2026-09-19 审计 R13-R3）：`delivered_at` 是 UTC，
        #    直接取 `.hour` 会把当地凌晨 0~3 点送达的单标成「16~18时」——
        #    日报的时段分布整段错位，而数字看起来很正常。
        h = business_local(o.delivered_at).hour
        hour_amount[h] = hour_amount.get(h, Decimal("0")) + amount
        hour_orders[h] = hour_orders.get(h, 0) + 1
        total_amount += amount
        total_freight += pay
        total_orders += 1
        for lp in o.order_products:
            # 退货的货**回到库里了**（`order_return` 已回补库存）→ 这一行的成本不能照全额算，
            # 否则"退了货还照记成本"，毛利被两头挤（收入减了、成本没减）。
            net_qty = int(lp.quantity or 0) - int(lp.returned_quantity or 0)
            if net_qty <= 0 and (lp.damage_quantity or 0) <= 0:
                continue
            total_lines += 1
            # ⚠️ 成本 = **入库流水的加权平均进货价**（2026-09-19 用户要求，取代下单快照）。
            #    快照是"下单那一刻的最新进货价"，进货价一涨，从旧库存出的货就被按高价算成本
            #    → 毛利偏低。三级口径（期间均价 / 累计均价 / 下单快照兜底）与理由全写在
            #    `services/cost_basis.py`，这里**不许**再自己写一份取成本的逻辑。
            cost, basis_src = basis.of(lp.product_id, lp.cost_price_snapshot)
            if cost > 0:
                cost_covered_lines += 1
                cost_total += cost * Decimal(max(0, net_qty))
                # 收入侧**只收参与毛利的行**（见 schemas/reports.py 里 cost_covered_amount 的注释）：
                # 不这么写，没成本的行会以"0 成本"全额变成毛利。
                # 用 `line_receivable`（= 行金额 − 退掉那部分）与上面的成本同口径。
                cost_covered_amount += line_receivable(lp)
                if basis_src == SNAPSHOT:
                    cost_snapshot_lines += 1
                else:
                    cost_avg_lines += 1
            dq = lp.damage_quantity or 0
            if dq > 0:
                damage_qty += dq
                # ⛔ 货损**故意**还是快照口径：送达那一刻就按当时的快照把损失金额写进了
                #    开销账与现金流水（`accounting_service.apply_damage_accounting`），
                #    那是一笔已入账的历史金额 —— 追溯改成均价会让账本和报表各说一套。
                snap = lp.cost_price_snapshot or Decimal("0")
                damage_amount += snap * Decimal(dq) if snap > 0 else Decimal("0")
        # ⚠️ 这笔钱**只有两个去处**：已收 / 还没收（挂账）。必须写成完整划分。
        #
        # 原来是两条带条件的判据（`cash 且已收` / `arrears 且未收`），于是
        # **挂账结清**（收款方式 `arrears_settle`：payment_method 还是 arrears，但 paid=True）
        # 和 `cash 且未收` 这两种组合**两边都不算**——营业额 200、已收 100、挂账 0，
        # 差出来的 100 在报表上哪一列都不属于（v3.39 探针实测：挂账结清后
        # "已收 +0 / 挂账 -100"，钱凭空消失）。
        #
        # 2026-09-20 改成**按钱算**（`order_money` 一处）：`paid` 一个布尔只能表达
        # "全收/全没收"，而按商品核销之后"收了一半"是常态、退货又会让应收变小。
        # 恒等式仍然成立、而且现在是精确的：`营业额(应收) = 净已收 + 挂账`。
        collected += mm.settled - mm.refunded
        if mm.arrears != 0:
            arrears_total += mm.arrears
            uname = (o.arrears_unit_name or "").strip() or "未分配挂账单位"
            arrears_map[uname] = arrears_map.get(uname, Decimal("0")) + mm.arrears
    # 曲线的粒度：**单日按小时铺、跨天按天铺**。
    # ⚠️ 2026-09-22：这里原来只看 `mode`（`mode == "day"` → 每小时一个点）。
    #    而 App 现在发的是一段区间（`span`），`mode` 只剩"没给区间时"的老口径 ——
    #    于是"整月区间 + mode=day"会被画成**每小时一个点**：同一段时间，
    #    走 mode 是 30 个点、走区间是 24 个点，两边都"看着有理"（本文件的新测试当场抓到）。
    #    粒度必须由**窗口本身**决定，而不是由请求里那个已经不作数的参数决定。
    if start == end:
        series = [
            ReportSeriesItem(
                label=f"{h:02d}时",
                amount=hour_amount.get(h, Decimal("0")),
                orders=hour_orders.get(h, 0),
            )
            for h in sorted(hour_orders)
        ]
    else:
        series = [day_map.get(f"{x.month}-{x.day}", ReportSeriesItem(label=f"{x.month}-{x.day}")) for x in days]
    # ⚠️ 单均价先量化到两位（2026-09-19 审计 R13-R7）：`Decimal/Decimal` 会给出
    #    28 位商（实测导出的单元格是 `193.4895418326693227091633466`），
    #    Excel 里既难看又和界面上显示的"¥193.49"对不上。
    avg = (total_amount / total_orders).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if total_orders else Decimal("0")
    # ⚠️ 撤销数按**业务当地日**筛（2026-09-19 审计 R13-R3）：`func.date(cancelled_at)` 取的是
    #    UTC 日期，东八区当地 00:00~08:00 撤销的单会被算到前一天 ——
    #    实测「今天撤销 0 单」而当天其实有 125 张（该行只在 >0 时渲染，于是整行消失）。
    #    `business_range_utc` 把当地日区间换成库里的 UTC 时刻，SQL 侧直接比时间列。
    c_start, c_end = business_range_utc(start, end)
    cancelled_orders = db.scalar(
        select(func.count(Order.id)).where(
            Order.status == OrderStatus.CANCELLED,
            Order.cancelled_at.isnot(None),
            Order.cancelled_at >= c_start,
            Order.cancelled_at < c_end,
            # ⚠️ 必须排**隔离区（软删）**的单（2026-09-24 第 22 轮 F8-2）：这里是全后端唯一
            #    漏了这一条的 Order 聚合（同文件 `load_delivered` 有）。删除是"伪装删除"，
            #    行还在库里 —— 而派单员**任意状态都能删**（含已撤销），于是"删掉一张撤销单"
            #    之后这张 KPI 不跟着少：数与明细对不上，且越删差得越多。
            #    本机实测当时差 0（26 张软删单里 0 张 CANCELLED）→ 是**潜伏**缺陷，不是不存在。
            Order.deleted_at.is_(None),
        )
    ) or 0
    return {
        "period_label": _span_label(start, end) if span else _label(d, mode),
        "total_amount": total_amount,
        "total_orders": total_orders,
        "total_freight": total_freight,
        "avg_order": avg,
        "series": series,
        "cost_total": cost_total,
        "cost_covered_amount": cost_covered_amount,
        "total_lines": total_lines,
        "cost_covered_lines": cost_covered_lines,
        "cost_avg_lines": cost_avg_lines,
        "cost_snapshot_lines": cost_snapshot_lines,
        "damage_qty": damage_qty,
        "damage_amount": damage_amount,
        "collected": collected,
        "arrears_total": arrears_total,
        "cancelled_orders": cancelled_orders,
        "arrears_units": [
            ReportArrearsUnitItem(name=k, amount=v)
            for k, v in sorted(arrears_map.items(), key=lambda kv: -kv[1])[:5]
        ],
        "_window": (start, end),
    }
