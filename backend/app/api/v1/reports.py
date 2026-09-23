"""报表（派单员）：营业额/商品明细 按日/周/月聚合，供折线图与条形图使用。"""

from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload

from app.core.business_time import business_date, business_local, business_range_utc, local_stamp
from app.services.ledger_scope import visible_ledger_select
from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.models import Order, OrderProduct, User
from app.models.enums import OrderStatus
from app.schemas.reports import ProductReportItem, ProductReportOut, ReportArrearsUnitItem, ReportSeriesItem, TurnoverReportOut
from app.services.cost_basis import SNAPSHOT, CostBasis
from app.services.driver_pay import has_per_order_pay, pay_for_order
from app.services.order_money import line_receivable, money_map

router = APIRouter(prefix="/reports", tags=["reports"])


def _window(mode: str, anchor: date) -> tuple[date, date]:
    """[mode] 对应的时间窗口，**两端都是闭区间里的最后一天**。

    ⚠️ 月窗口的上界以前是"下月 1 日"（`day=1 + 32 天 → day=1`），而调用方用的是
    **闭区间** `ds <= end`（见 `build_turnover`），于是**下个月 1 号的单会被算进本月**。
    报表上的表现很隐蔽：本月最后一天的日报是对的，月报却多了一天的数据。
    现在统一返回"本月最后一天"，与周/日两种模式一致。
    """
    d = anchor
    if mode == "week":
        start = d - timedelta(days=d.weekday())
        return start, start + timedelta(days=6)
    if mode == "month":
        first = d.replace(day=1)
        return first, (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    return d, d


def _label(d: date, mode: str) -> str:
    if mode == "week":
        start = d - timedelta(days=d.weekday())
        return f"{start.month}-{start.day}~{start + timedelta(days=6):%m-%d}"
    if mode == "month":
        return f"{d.year}-{d.month:02d}月"
    return f"{d.month}-{d.day}"


def _span_label(start: date, end: date) -> str:
    """给了**明确区间**时那个标签（`9-1~9-20` / 整天 `9-18` / 整月 `2026-09月`）。

    与 `_label(d, mode)` 同一套写法：整月仍然写成 `2026-09月`（导出的表头读它），
    其余一律写成一段区间 —— 用户看到"这两个数"时必须能从标题上认出是哪一段。
    """
    if start == end:
        return f"{start.month}-{start.day}"
    if start.day == 1 and (start + timedelta(days=32)).replace(day=1) - timedelta(days=1) == end:
        return f"{start.year}-{start.month:02d}月"
    return f"{start.month}-{start.day}~{end.month}-{end.day}"


def _span(
    mode: str,
    anchor: date,
    date_from: date | None,
    date_to: date | None,
) -> tuple[date, date]:
    """这一次报表要看的窗口 —— **后端唯一的入口**（接口与导出都走它）。

    给了 `date_from` + `date_to` 就用它（App 的档位药丸走这条：今天/昨天/近 7 天/本月/上月/自定义
    都是**一段区间**，六个页签共用同一段）；没给就还是老的 `mode` + `anchor`
    （`day`/`week`/`month`，既有调用方与既有测试一行都不用改）。

    ⚠️ **只给一头 → 400**，不许"猜另一头"：半截窗口要么查全量要么查出空列表，
       两种都不是用户想要的（App 侧那条规矩同理：`DateRangeDialog` 只选一头时"应用"什么都不做）。
    """
    if (date_from is None) != (date_to is None):
        raise HTTPException(status_code=400, detail="date_from 与 date_to 必须同时给")
    if date_from is not None and date_to is not None:
        if date_to < date_from:
            raise HTTPException(status_code=400, detail="结束日期不能早于开始日期")
        return date_from, date_to
    return _window(mode, anchor)


def _range_dates(start: date, end: date) -> list[date]:
    out, cur = [], start
    while cur <= end:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def delivered_span_sql(start: date, end: date) -> tuple:
    """把「业务当地日闭区间」翻译成 `delivered_at`（UTC naive）的**半开区间**条件。

    ⚠️ 这不是第二套口径，而是 `business_date()` 那套判据在 SQL 侧的**等价前置过滤**：
    `core/business_time.business_range_utc(start, end)` 给出的 `[start 当地 00:00, end+1 当地 00:00)`
    与循环里那句 `ds < start or ds > end` 覆盖的是**同一批时刻**（半开 / 闭区间只是写法差别）。

    ### 为什么必须加它（2026-09-23 容量实测，见 `_tools/perf/`）
    `load_delivered` 原来是**无条件把全库已送达单连行一起读进内存**，再由函数体按窗口丢掉 ——
    也就是说**看一天的报表，也要把三年历史全查一遍**。实测（2 万单的副本库）：
    `mode=day` 与 `mode=month` 的耗时都是 **2.3 秒左右**（同一条 2.2~2.5s、看不出窗口差别），
    而数据保留策略是 **3 年** —— 这个代价随时间线性长，且页面与导出走的是同一段聚合。
    加了窗口过滤之后，读的行数只与窗口有关、与全库历史无关。
    """
    lo, hi = business_range_utc(start, end)
    return Order.delivered_at >= lo, Order.delivered_at < hi


def load_delivered(db: Session, *, span: tuple[date, date] | None = None) -> list[Order]:
    """全部已送达订单（按送达时间排序）；由各报表按窗口过滤，减少重复查询。

    [span] 非空 = 只读这一段业务日区间内的单（**调用方已经知道窗口时一定要传**，
    否则就是把全库历史读进内存再丢掉，见 [delivered_span_sql]）。
    循环里那句 `ds < start or ds > end` 仍然保留 —— 它才是权威判据，SQL 侧只是同口径的预过滤。

    ### 为什么必须排掉软删（隔离区）的单
    `DELETE /orders/{id}` 是**伪装删除**（进隔离区 30 天，可恢复），用户界面上已经看不到了。
    而报表这边以前**没有这个过滤**——只 grep 过 `deleted_at`：
    全后端只有 `orders.py` 与 `data_retention.py` 用到了它。
    后果是"删掉的那张单还在营业额、毛利、货损、司机应付里"：
    用户删掉一张错单，报表上的数字**一分都不减**，而他会以为删干净了。
    """
    q = (
        select(Order)
        .options(selectinload(Order.order_products))
        .where(
            Order.status == OrderStatus.DELIVERED,
            Order.delivered_at.isnot(None),
            # 隔离区里的单不算数（列可能不存在于极老的库里时由 schema_bootstrap 补齐）
            Order.deleted_at.is_(None),
        )
    )
    if span is not None:
        q = q.where(*delivered_span_sql(span[0], span[1]))
    return list(db.scalars(q.order_by(Order.delivered_at)))


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


def build_products(db: Session, mode: str, anchor: date, *, span: tuple[date, date] | None = None) -> dict:
    """商品经营聚合（含成本/货损），供接口与导出复用。

    [span] 的含义与 [build_turnover] 一致（两页必须**同一个窗口口径**）。
    """
    d = anchor
    start, end = span if span else _window(mode, anchor)
    # 成本口径与营业纵览**同一处**（`services/cost_basis.py`）：两页的毛利必须对得上
    basis = CostBasis(db, start, end)
    agg: dict[str, ProductReportItem] = {}
    total_qty = 0
    total_amount = Decimal("0")
    cost_total = Decimal("0")
    damage_qty = 0
    damage_amount = Decimal("0")
    total_lines = 0
    cost_covered_lines = 0
    cost_covered_amount = Decimal("0")
    cost_avg_lines = 0
    cost_snapshot_lines = 0
    for o in load_delivered(db, span=(start, end)):
        ds = business_date(o.delivered_at)
        if ds is None or ds < start or ds > end:
            continue
        for lp in o.order_products:
            name = lp.product_name_snapshot or "未命名商品"
            item = agg.setdefault(name, ProductReportItem(product_name=name))
            # ⛔ **数量与金额一律按净额**（2026-09-23 第 17 轮并行渗透抓到：这里原来是**毛额**，
            #    于是"商品毛利"这个词在同一份导出里有两个数 —— 营业纵览 sheet ¥4,896.60、
            #    商品经营 sheet ¥4,911.10，差额随退货量线性放大，老板按哪个都对不上）。
            #    两条口径必须与 `build_turnover` 的循环**逐行同源**：
            #    · 整行退完且无货损 → `continue`（那一行不进商品经营，也不进毛利）；
            #    · 数量取 `quantity − returned_quantity`、金额取 `line_receivable`（行金额 − 退掉那部分）、
            #      成本按净件数算 —— 与那边第 217/228/232 行一字不差。
            #    判据：`tests/test_report_gross_profit_one_source.py`（两个端点同窗口逐项相等）。
            net_qty = int(lp.quantity or 0) - int(lp.returned_quantity or 0)
            if net_qty <= 0 and (lp.damage_quantity or 0) <= 0:
                continue
            net_amount = line_receivable(lp)
            item.qty += max(0, net_qty)
            item.amount += net_amount
            item.order_count += 1
            total_qty += max(0, net_qty)
            total_amount += net_amount
            total_lines += 1
            cost, basis_src = basis.of(lp.product_id, lp.cost_price_snapshot)
            if cost > 0:
                cost_covered_lines += 1
                item.covered_lines += 1
                # ⚠️ 毛利的两侧必须是**同一批行**（2026-09-19 审计第十七轮）：
                #    只累计成本、收入侧却用全额，等于"没成本的行按 0 成本、100% 毛利进账"。
                #    本机实测：商品页/导出的表头毛利 11,071.00，而营业纵览（正确口径）是 10,789.00；
                #    唯一那个混合组 ttt 印出 327.50（正确 45.50，差 7.2 倍）。
                item.covered_amount += net_amount
                cost_covered_amount += net_amount
                cost_total += cost * Decimal(max(0, net_qty))
                item.cost += cost * Decimal(max(0, net_qty))
                if basis_src == SNAPSHOT:
                    cost_snapshot_lines += 1
                else:
                    cost_avg_lines += 1
            dq = lp.damage_quantity or 0
            if dq > 0:
                item.damage_qty += dq
                damage_qty += dq
                # 货损与营业纵览同口径（快照，理由见那边）
                snap = lp.cost_price_snapshot or Decimal("0")
                amt = snap * Decimal(dq) if snap > 0 else Decimal("0")
                damage_amount += amt
                item.damage_amount += amt
    items = sorted(agg.values(), key=lambda x: -x.amount)
    return {
        "period_label": _span_label(start, end) if span else _label(d, mode),
        "total_qty": total_qty,
        "total_amount": total_amount,
        "items": items,
        "cost_total": cost_total,
        "damage_qty": damage_qty,
        "damage_amount": damage_amount,
        "total_lines": total_lines,
        "cost_covered_lines": cost_covered_lines,
        "cost_covered_amount": cost_covered_amount,
        "cost_avg_lines": cost_avg_lines,
        "cost_snapshot_lines": cost_snapshot_lines,
        "_window": (start, end),
    }


def _cost_basis_note(data: dict) -> str:
    """导出里的"成本怎么算的"说明行。

    ⛔ 营业纵览与商品经营两个 sheet **必须用这同一份文字**：两边各写一句，
       改口径时漏改一处，导出里就出现两个互相矛盾的口径说明
       （而"两个表对不上"正是这份报表历史上最贵的一类缺陷）。
    """
    return (
        f"成本口径：入库流水的加权平均进货价（{data['cost_avg_lines']} 行）；"
        f"另有 {data['cost_snapshot_lines']} 行该商品没记过进货价、按下单时的成本快照算；"
        f"共 {data['cost_covered_lines']}/{data['total_lines']} 行算得出成本，其余行不进毛利；"
        f"参与毛利的收入 {data['cost_covered_amount']}／未参与 {data['total_amount'] - data['cost_covered_amount']}"
    )


@router.get("/turnover", response_model=TurnoverReportOut)
def turnover_report(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
    mode: str = Query("day", pattern="^(day|week|month)$"),
    anchor: date = Query(..., alias="date", description="YYYY-MM-DD 锚点日期"),
    date_from: date | None = Query(None, description="YYYY-MM-DD（与 date_to 成对给，优先于 mode+anchor）"),
    date_to: date | None = Query(None, description="YYYY-MM-DD"),
) -> TurnoverReportOut:
    span = _span(mode, anchor, date_from, date_to)
    data = build_turnover(db, mode, anchor, span=span)
    data.pop("_window", None)
    return TurnoverReportOut(**{**data, "period_label": data["period_label"]})


@router.get("/products", response_model=ProductReportOut)
def product_report(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
    mode: str = Query("day", pattern="^(day|week|month)$"),
    anchor: date = Query(..., alias="date", description="YYYY-MM-DD 锚点日期"),
    date_from: date | None = Query(None, description="YYYY-MM-DD（与 date_to 成对给，优先于 mode+anchor）"),
    date_to: date | None = Query(None, description="YYYY-MM-DD"),
) -> ProductReportOut:
    span = _span(mode, anchor, date_from, date_to)
    data = build_products(db, mode, anchor, span=span)
    data.pop("_window", None)
    return ProductReportOut(**data)


def build_arrears_summary(db: Session, start: date, end: date) -> list[dict]:
    """挂账单位欠款汇总（按未付挂账订单聚合），供客户经营页与导出复用。"""
    from app.models import CashFlow

    rows = list(
        db.scalars(
            select(Order)
            .options(selectinload(Order.order_products))
            .where(
                Order.status == OrderStatus.DELIVERED,
                Order.delivered_at.isnot(None),
                # ⚠️ 隔离区（软删）的单不算欠款（2026-09-19 审计）：这个查询与 `load_delivered`
                #    是同一批口径，但当初只给 `load_delivered` 加了这一条 → 删掉一张挂账单之后，
                #    「营业纵览·挂账未收」减了、而这一份（客户经营页 + kind=customers 导出）没减，
                #    同一个页面两个"挂账未收"。实测本机差 ¥500。
                Order.deleted_at.is_(None),
                # ⚠️ **只按 `paid=False` 划"还没收"**，不再加 `payment_method == "arrears"`
                #    （2026-09-19 审计 R13-R4）：营业纵览那一份用的是 `paid=False` 一条判据，
                #    这里多一条 `payment_method == "arrears"` → 只要库里有一张
                #    `cash + paid=0 + collect_cash=0` 的已送达单（老数据/导库/直接改库都可能），
                #    两个"挂账未收"就永久分叉（实测 63,006.00 vs 62,920.50，差 ¥85.50 / 7 张单）。
                #    schema 里 `arrears_total` 的注释写的就是"挂账未收（paid=False）"——
                #    判据只有一处实现，才不会再走散。
                Order.paid.is_(False),
                # ⚠️ 与 `load_delivered` 同一个窗口预过滤（2026-09-23 容量实测）：
                #    这一段原来也是全库读进内存再按窗口丢。挂账页与营业纵览共用同一批单，
                #    两边的窗口口径必须一模一样（下面循环里那句 `ds < start or ds > end` 仍是权威判据）。
                *delivered_span_sql(start, end),
            )
        )
    )
    unit_map: dict[str, dict] = {}
    # 金额改成**这一单还欠多少**（`order_money.arrears`），不是"当时卖了多少"：
    # 收了一半的单、退了一部分的单，欠款都不等于 `line_total` 之和。
    money = money_map(db, rows)
    for o in rows:
        ds = business_date(o.delivered_at)
        if ds is None or ds < start or ds > end:
            continue
        mm = money[o.id]
        if mm.arrears == 0:
            # `paid=False` 但一分钱都不欠了（比如整单被收干净了、或货全退了）→ 不算挂账。
            # 把它算进去会得到一条"0 元欠款"的挂账单位行，看的人只会以为系统坏了。
            continue
        name = (o.arrears_unit_name or "").strip() or "未分配挂账单位"
        g = unit_map.setdefault(name, {"name": name, "count": 0, "amount": Decimal("0")})
        g["count"] += 1
        g["amount"] += mm.arrears
    return sorted(unit_map.values(), key=lambda x: -x["amount"])


@router.get("/arrears-summary")
def arrears_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
    date_from: date = Query(..., description="YYYY-MM-DD"),
    date_to: date = Query(..., description="YYYY-MM-DD"),
) -> list[dict]:
    start = date_from
    end = date_to
    return build_arrears_summary(db, start, end)


def _money(v) -> float:
    """导出里的金额写成**数字**（不是文本），保留两位小数。

    2026-09-19 审计 R13-R7：原来一律 `str(decimal)` 写进单元格，openpyxl 存成**文本**
    （实测 `B2='97131.7500' type=s`）——用户在 Excel 里 `SUM` 选一列金额，
    得到的是 0（或只把"单数/件数"这种真数字加起来），账要自己拿计算器重算。
    金额是给人算的，必须能被 Excel 当数用。

    ⚠️ 进位方式必须显式写 `ROUND_HALF_UP`（2026-09-19 审计 F7）：`.quantize()` 的默认是
    **ROUND_HALF_EVEN**（银行家舍入），而全项目的 `driver_pay.money()` 是 ROUND_HALF_UP ——
    金额正好落在半分位上时（如 0.125）两处差 1 分，而"导出与页面差 1 分"是对账时最难查的那种。
    同族的货损两处已在第十五轮改过，这里是最后一处。
    """
    if v is None or v == "":
        return ""
    return float(Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


@router.get("/export")
def export_report(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
    kind: str = Query(..., pattern="^(turnover|products|drivers|customers|finance|audit)$"),
    mode: str = Query("day", pattern="^(day|week|month)$"),
    anchor: date = Query(..., alias="date", description="YYYY-MM-DD 锚点日期"),
    date_from: date | None = Query(None, description="YYYY-MM-DD（finance/customers 可用，优先于 mode+anchor）"),
    date_to: date | None = Query(None, description="YYYY-MM-DD"),
) -> StreamingResponse:
    """报表 Excel 导出（内存流 xlsx）。"""
    from io import BytesIO
    from openpyxl import Workbook

    from app.models import CashFlow, DriverSettlement, Expense, Ledger
    from app.models.enums import SettlementStatus

    d = anchor
    # 文件名的日期段 = **这一份报表真实取数的区间**（不是锚点日）。
    # ⛔ 原来只有 drivers/customers/finance/audit 四个 kind 按真实区间命名，
    #    `turnover`/`products` 一律写锚点日 —— 而它们的内容是 `_window(mode, anchor)`
    #    （mode=month 时是整月）：`kind=turnover&mode=month&date=2026-09-18` 导出的文件叫
    #    `turnover-report-2026-09-18.xlsx`、内容却是 09-01~09-30。对账/存档时按文件名找回来
    #    会拿到一份"名字与内容不符"的凭证（2026-09-19 第二轮外部检查 R2-4；
    #    第十一轮报过一次，第十五轮只修了另外四个 kind，这两个漏了）。
    # ⚠️ 2026-09-22（报表时间控件换成档位药丸那一轮）：**六个 kind 现在都认 `date_from/date_to`**
    #    （`turnover`/`products` 也收下了），所以这一段的判据收成**一个** `_span(...)` ——
    #    与页面上、与下面 `build_*` 用的是**同一个窗口**。原来那段"turnover/products 一律按 mode"
    #    的分支留着就又会分叉（App 现在发的就是区间）。
    s, e = _span(mode, d, date_from, date_to)
    range_label = f"{s}_{e}" if s != e else str(s)
    wb = Workbook()

    def next_sheet(title: str):
        if wb.active.title == "Sheet" and wb.active.max_row == 1 and wb.active.max_column == 1:
            ws = wb.active
            ws.title = title
            return ws
        return wb.create_sheet(title)

    if kind == "turnover":
        data = build_turnover(db, mode, d, span=(s, e))
        ws = next_sheet("营业纵览")
        ws.append(["营业纵览", _span_label(s, e), "金额口径：已送达未撤销"])
        ws.append(["营业金额", _money(data["total_amount"]), "订单数", data["total_orders"], "单均价", _money(data["avg_order"])])
        ws.append([
            # 口径同「司机运费结算」页：按计费规则应付（不是订单上的运费）——审计 R12-M2
            "司机运费支出(按计费规则应付)", _money(data["total_freight"]),
            "商品毛利(仅算得出成本的行)",
            # 毛利 = 参与计算的收入 − 那些行的成本。**两侧必须是同一批行**（见 schemas/reports.py 的注释）
            _money(data["cost_covered_amount"] - data["cost_total"]),
            _cost_basis_note(data),
        ])
        ws.append(["货损件数", data["damage_qty"], "货损金额", _money(data["damage_amount"]), "已收", _money(data["collected"])])
        ws.append(["挂账未收", _money(data["arrears_total"]), "已撤销订单", data["cancelled_orders"]])
        ws.append([])
        ws.append(["时间", "单数", "金额", "运费"])
        for pt in data["series"]:
            # ⚠️ 循环变量刻意不叫 `s`：`s`/`e` 是上面算好的**导出区间**（文件名与内容同源），
            #    拿 `s` 当循环变量会把它盖掉 —— 而这里恰好是"营业纵览"分支，改名零风险。
            ws.append([pt.label, pt.orders, _money(pt.amount), _money(pt.freight)])
        ws.append([])
        ws.append(["挂账未收单位TOP"])
        for u in data["arrears_units"]:
            ws.append([u.name, _money(u.amount)])
    elif kind == "products":
        data = build_products(db, mode, d, span=(s, e))
        ws = next_sheet("商品经营")
        ws.append(["商品经营", _span_label(s, e)])
        # ⚠️ 毛利的两侧必须**同一批行**（2026-09-19 审计第十七轮）：这里原来用
        #    "Σ 有成本行的**全额**金额 − cost_total" 当表头毛利 → 与营业纵览
        #    （cost_covered_amount − cost_total）差 ¥282（本机 11,071.00 vs 10,789.00），
        #    而逐行列更离谱：用的是 `amount − cost` 老公式，合计回到修复前那个错数 72,177.75。
        ws.append(["销售总额", _money(data["total_amount"]), "总件数", data["total_qty"],
                   "商品毛利(仅算得出成本的行)",
                   _money((data["cost_covered_amount"] or Decimal("0")) - (data["cost_total"] or Decimal("0")))])
        ws.append(["货损件数", data["damage_qty"], "货损金额", _money(data["damage_amount"]), _cost_basis_note(data)])
        ws.append([])
        ws.append(["商品", "件数", "单数", "金额", "参与毛利的金额", "毛利", "货损件数", "货损金额"])
        for it in data["items"]:
            cov = it.covered_amount or Decimal("0")
            # 算不出成本的行**不进毛利**（写"—"，不是写一个看起来像毛利的大数）
            gross = _money(cov - it.cost) if (it.covered_lines or 0) > 0 else "—"
            ws.append([it.product_name, it.qty, it.order_count, _money(it.amount), _money(cov), gross, it.damage_qty, _money(it.damage_amount)])
    elif kind in ("drivers", "customers", "finance", "audit"):
        # `s`/`e` 与文件名已经按同一套规则算好（见函数开头）——这里不许再算一遍
        if kind == "drivers":
            from app.services.stats_service import driver_performance

            ws = next_sheet("司机绩效")
            ws.append(["司机绩效", f"{s} ~ {e}"])
            ws.append(["司机", "完成单量", "准时率", "拍照率", "平均送达分钟", "计费方式", "待结运费"])
            # ⚠️ 这一块原来自己又写了一遍算法，于是三处与页面不是同一件事（2026-09-19 审计 R13-R5）：
            #    ① 「平均送达分钟」写死 `""` → 所有行、所有月份恒空；
            #    ② 准时率分母只算**有 `expected_deliver_before`** 的单，而页面按 models 的口径
            #       **空则按订单日末**（本库 637 张已送达单里 419 张没有 SLA → 导出恒空、页面有值）；
            #    ③ 工资制司机这里印 0，页面印"工资制"。
            #    现在**直接复用页面那一个服务**（`stats_service.driver_performance`）：
            #    一个指标只有一处实现，导出与页面不可能再走散。
            for row in driver_performance(db, s, e):
                rate = row["on_time_rate"]
                avg_sec = row["avg_delivery_seconds"]
                owed = row["freight_owed"]
                ws.append(
                    [
                        row["driver_name"],
                        row["completed_count"],
                        "" if rate is None else round(rate, 4),
                        round(row["photo_upload_rate"] or 0.0, 4),
                        "" if avg_sec is None else round(avg_sec / 60, 1),
                        row["billing_mode"] or "",
                        # ⚠️ 待结运费必须是**数字**（2026-09-19 第二轮外部检查 R2-3(exp)）：
                        #    `stats_service.driver_performance` 这一格给的是**字符串**
                        #    （`str(Decimal)` —— 页面按 JSON 收它没问题），原样写进 xlsx
                        #    会让整列变成文本，用户在 Excel 里选这一列 `SUM` 得 **0**，
                        #    账得自己拿计算器重算（与 R13-R7 修金额列是同一个毛病，两处都走 `_money`）。
                        #    两位小数口径与页面一致（页面 `formatMoney`，`_money` 也是 ROUND_HALF_UP）。
                        # ⚠️ 工资制司机这一格仍是**文字"工资制"**（页面同款，刻意）：印 0 会被读成
                        #    "这个月一分钱都不用付给他"。
                        # ⚠️ 没有待结值（既不是工资制、服务层也没算出应付）时写真数值 0，
                        #    不再写文本 "0" —— 那一格同样是文本列里的坑。
                        "工资制" if row["billing_mode"] == "SALARY" else (_money(owed) if owed else 0),
                    ]
                )
        elif kind == "customers":
            from app.models import User

            ws = next_sheet("客户经营")
            ws.append(["客户账汇总", f"{s} ~ {e}"])
            # 货主账/批发商账（复用 ledger accounts 逻辑的简化：按流水聚合）
            # ⚠️ 隔离区（软删）订单的那份账不算（R13-R6）：与营业纵览同一句，否则
            #    "客户经营"的订货总额会比"营业额"多出一张已删单的钱（本机差 ¥4,600）。
            # ⚠️ 日期条件**下推到 SQL**（2026-09-19 第二轮外部检查 R2-7(exp)）：原来是
            #    `list(db.scalars(visible_ledger_select()))` —— 把**整张 ledgers 表**读进内存，
            #    再在 Python 里 `if r.entry_date < s or r.entry_date > e: continue` 丢掉区间外的行。
            #    导一份"9 月客户经营"要先把三年的账全部拉进进程（还得逐行过一遍
            #    `visible_ledger_clause` 的 exists 判据），库越大越慢、内存越高。
            #    口径**一处没变**：可见性仍只由 `visible_ledger_select()` 决定，区间交给数据库。
            #    ⚠️ 原来那两行 Python 过滤是**删掉**、不是留成双保险：同一件事两个判据，
            #    下次改口径时必然只改一处（本仓库已经在"两处口径"上栽过好几次）。
            #    ⚠️ `s`/`e` 是 `date` 对象（`_window` 返回的就是 date，`date_from`/`date_to`
            #    也是），与 `Ledger.entry_date`（Date 列）同类型比较，不存在"字符串比大小"。
            rows = list(
                db.scalars(
                    visible_ledger_select()
                    .where(Ledger.entry_date >= s)
                    .where(Ledger.entry_date <= e)
                )
            )
            users: dict[int, User | None] = {}
            shipper_buckets: dict[int, dict] = {}
            member_buckets: dict[int, dict] = {}
            temp_bucket: dict[str, dict] = {}
            for r in rows:
                if r.shipper_id is not None:
                    if r.shipper_id not in users:
                        u = db.get(User, r.shipper_id)
                        users[r.shipper_id] = u
                    u = users[r.shipper_id]
                    b = (member_buckets if (u is not None and getattr(u, "is_member", False)) else shipper_buckets).setdefault(
                        r.shipper_id, {"name": (u.full_name or u.phone or f"货主#{r.shipper_id}") if u else f"货主#{r.shipper_id}", "count": 0, "total": Decimal("0")}
                    )
                else:
                    name = (r.temp_shipper_name or "").strip() or "临时货主"
                    b = temp_bucket.setdefault(name, {"name": name, "count": 0, "total": Decimal("0")})
                b["count"] += 1
                b["total"] += r.total or Decimal("0")
            ws.append(["类别", "客户", "笔数", "总额"])
            for b in sorted(shipper_buckets.values(), key=lambda x: -x["total"]):
                ws.append(["货主", b["name"], b["count"], _money(b["total"])])
            for b in sorted(temp_bucket.values(), key=lambda x: -x["total"]):
                ws.append(["临时货主", b["name"], b["count"], _money(b["total"])])
            for b in sorted(member_buckets.values(), key=lambda x: -x["total"]):
                ws.append(["批发商", b["name"], b["count"], _money(b["total"])])
            ws.append([])
            ws.append(["挂账未收 TOP"])
            ws.append(["单位", "笔数", "金额"])
            for g in build_arrears_summary(db, s, e):
                ws.append([g["name"], g["count"], _money(g["amount"])])
        elif kind == "finance":
            ws = next_sheet("资金收支")
            flows = list(
                db.scalars(
                    select(CashFlow)
                    # ⛔ 导出的数与页面上的数必须是同一批行：已撤销的流水两边都不算
                    #    （2026-09-22 起 `cash_flows` 有软删，见 `models/cash_flow.py` 文件头）。
                    .where(
                        CashFlow.flow_date >= s,
                        CashFlow.flow_date <= e,
                        CashFlow.is_deleted.is_(False),
                    )
                    .order_by(CashFlow.flow_date.desc())
                )
            )
            income = sum((f.amount for f in flows if str(f.direction).lower() == "in"), Decimal("0"))
            expense = sum((f.amount for f in flows if str(f.direction).lower() == "out"), Decimal("0"))
            ws.append(["资金收支", f"{s} ~ {e}"])
            ws.append(["流入", _money(income), "流出", _money(expense), "净额", _money(income - expense)])
            ws.append([])
            ws.append(["日期", "方向", "金额", "对象", "渠道", "类型", "备注"])
            for f in flows:
                ws.append([f.flow_date.isoformat(),
                           "收入" if str(f.direction).lower() == "in" else "支出",
                           _money(f.amount), f.party_name or "", f.channel, f.biz_type, f.note])
            ws.append([])
            ws.append(["开销分类"])
            ws.append(["分类", "金额"])
            exp_rows = list(db.scalars(select(Expense).where(Expense.exp_date >= s, Expense.exp_date <= e)))
            cat_map: dict[str, Decimal] = {}
            for x in exp_rows:
                cat_map[x.category] = cat_map.get(x.category, Decimal("0")) + x.amount
            for cat, amt in sorted(cat_map.items(), key=lambda kv: -kv[1]):
                ws.append([cat, _money(amt)])
        elif kind == "audit":
            from app.models import OperationLog

            ws = next_sheet("异常与审计")
            from app.services import stats_service
            ex = stats_service.exception_orders(db, s, e)
            ws.append(["异常订单", f"{s} ~ {e}"])
            ws.append(["订单号", "货主", "司机", "异常原因", "处理结果", "解决时间"])
            for o in ex:
                ws.append([
                    o["order_no"], o["shipper_name"] or "", o["driver_name"] or "",
                    o["exception_reason"], o["exception_resolution"],
                    o["exception_resolved_at"].isoformat() if o["exception_resolved_at"] else "",
                ])
            ws.append([])
            # ⛔ 「敏感操作日志」原来**完全不看区间**（就是 `order_by(id.desc()).limit(200)`）：
            #    导出一份"09-01 的审计报告"，里面躺着的却是**库里最新**的 200 条日志（可能是 09-18 的）。
            #    审计凭证"名字写着 A、内容是 B"比"少给几条"严重得多——看的人会以为那就是当天的全部动作。
            #    现在按**业务当地日区间**过滤（与保留任务同一个 UTC 换算），并且如实说清有没有被截断。
            lo, hi = business_range_utc(s, e)
            in_range = (OperationLog.created_at >= lo, OperationLog.created_at < hi)
            total = db.scalar(
                select(func.count()).select_from(OperationLog).where(*in_range)
            ) or 0
            logs = list(
                db.scalars(
                    select(OperationLog).where(*in_range).order_by(OperationLog.id.desc()).limit(200)
                )
            )
            note = f"{s} ~ {e}"
            if total > len(logs):
                note += f"（区间内共 {total} 条，这里只列了最近 {len(logs)} 条）"
            else:
                note += f"（共 {total} 条）"
            ws.append(["敏感操作日志", note])
            ws.append(["时间", "操作", "内容"])
            for log in logs:
                # ⚠️ 印**当地时刻**（2026-09-24 第 19 轮）：这一列原来直接 `created_at.isoformat()`，
                #    而 `created_at` 存的是 **UTC naive** —— 东八区当地 00:00~08:00 的动作会被印成
                #    **前一天**的时间（导出的窗口却是"业务当地日"）：一份"09-24 的审计报告"里
                #    躺着一行 `2026-09-23T16:29`，看的人会以为这条动作不属于这一天、
                #    或者怀疑导出窗口没生效。口径只有一处：`business_time.local_stamp`
                #    （第 18 轮为"印给人看的时间戳"建的那个入口）；这里要带年份，所以显式给 fmt。
                ws.append([
                    local_stamp(log.created_at, fmt="%Y-%m-%d %H:%M") if log.created_at else "",
                    log.action,
                    log.change_content or "",
                ])

    buf = BytesIO()
    wb.save(buf)
    fn = f"{kind}-report-{range_label}.xlsx"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fn}"'},
    )