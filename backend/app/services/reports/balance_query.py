"""逐债务人应收余额与账龄（FEAT-0015 第五期）：**还欠多少、欠了多久、额度够不够**。


⛔ **只读**：本包下的模块只允许 SELECT / JOIN / GROUP BY —— 判据 _tools/qa/_check_report_boundary.py
在 AST 层面禁止落库写法与写服务依赖，而且它是**算出来的**（services/reports/** 由 glob 自动收）。
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.business_time import business_date
from app.models import ArrearsUnit, Customer, Ledger, Order, ShipperReceipt, User
from app.models.enums import LedgerSource, OrderStatus, ReceiptSettleMode
from app.services.money_contract import money_map
from app.services.receipt_credit import rolling_receipt_credit_map
from app.services.reports.loader import delivered_span_sql

ZERO = Decimal("0")

#: 账龄桶的键与顺序（页面、导出、判据三处都按这个顺序摆；客户端的中文名见 ReportFinance）。
BUCKET_KEYS = ("0_30", "31_60", "61_90", "over_90")

#: 账龄看的是「到今天还欠着的钱」：历史全在范围内，只有**上界**（as_of）在切。
#: ⚠️ 这里不用 2000-01-01：那是 DatePresets 的「全部」（展示用），账龄的时间下界要真的是"从头"。
EARLIEST = date(1970, 1, 1)

#: 三种凭证都认不出来时的那一行（历史数据里确实有没有货主也没有单位的单）
UNKNOWN_NAME = "未填货主"

_NOTES = [
    "欠款 = 应收 − 已收 + 已退（`order_money.arrears`，与营业纵览、客户经营页同一处实现）。"
    "负数 = 预收（收多了 / 退多了），单列在下面，不进账龄桶。",
    "账龄从这一单**最早的一笔记账日**算起（账本 entry_date）；没有账本行的单按送达日算。"
    "红冲只冲减金额，不改账龄起点 —— 一笔老账退了一部分，剩下的还是老账。",
    "这是**时点账**：看的是「截止报表日还欠着多少」，与窗口起点无关（窗口只决定报表日取哪一天）。",
    "额度只长在「挂账单位」这一种行上（挂账单位名册里设，没设 = 不限额）。超限只是提示，不挡下单、不挡发货。",
    "行是按**债务人**分的：挂了单位的认单位，没挂单位的认货主（系统账号的名字 / 手机号），"
    "再不然认临时货主名 —— 都在为「这一笔钱该向谁要」服务。",
    "⚠️ 把报表日往前调（选过去的窗口）读法是：「那些天**之前送达**的单，到今天还欠着多少」。"
    "收款流水没有历史快照（一笔单收了几次、什么时候收的，账上只留总额），所以这不是「当时那一刻的账」。"
    "要对那一天的账，只能看当天的营业纵览/账本 —— 这一页回答的是「现在该向谁要钱、这笔钱欠多久了」。",
    "**未指定订单的收款（滚动收款）会冲减这里的欠款**，冲掉的部分进「预收」那一列（2026-10-10，BUG-0036 / 台账 TB-14）：不冲的话，客户明明付过钱，催收名单上还是全款。⛔「挂账汇总」那一页仍是**按单**的（它回答「哪些单还没收」），不受此影响。",
]


def bucket_of(days: int) -> str:
    """账龄天数归桶（0-30 / 31-60 / 61-90 / >90）：30 与 31、90 与 91 分属两桶。"""
    if days <= 30:
        return "0_30"
    if days <= 60:
        return "31_60"
    if days <= 90:
        return "61_90"
    return "over_90"


def _anchor_map(db: Session, order_ids: list[int]) -> dict[int, date]:
    """每一单的账龄起点：**最早**的那条正向账本行（订单行 / 手工行）。

    ⛔ 只取 min(entry_date)，账本上那一列金额一个字都不碰 —— 钱那一侧的唯一口径是 order_money，
    判据 _tools/qa/_check_money_contract.py 明令禁止在别处再写一遍求和。
    """
    if not order_ids:
        return {}
    rows = db.execute(
        select(Ledger.order_id, func.min(Ledger.entry_date))
        .where(
            Ledger.order_id.in_(order_ids),
            Ledger.source.in_((LedgerSource.ORDER, LedgerSource.MANUAL)),
        )
        .group_by(Ledger.order_id)
    ).all()
    return {int(oid): d for oid, d in rows if oid is not None and d is not None}


def _debtor_of(o: Order) -> tuple[str, str]:
    """这笔欠款该记在谁头上：挂账单位 → 货主 → 临时货主 → 说不清。

    ⚠️ 为什么不是「客户档案」（customers）：订单上根本没有 customer_id，唯一的路是
    customers.arrears_unit_id 这条**可空、非唯一**的映射 —— 按它分组必然出现
    「同一个客户两个答案」。而上面这三种凭证是对订单集合的**划分**（互斥且不漏），
    加起来的总额与既有口径逐分对得上。
    """
    if o.arrears_unit_id is not None:
        return "unit", str(o.arrears_unit_id)
    name = (o.arrears_unit_name or "").strip()
    if name:
        return "unit_name", name
    if o.shipper_id is not None:
        return "shipper", str(o.shipper_id)
    temp = (o.temp_shipper_name or "").strip()
    if temp:
        return "temp", temp
    return "unknown", ""


def _user_label(u: User | None) -> tuple[str, str]:
    """货主的显示名与手机号：与 order_response 的货主名同一口径（名字 → 手机号 → 空）。"""
    if u is None:
        return "", ""
    return ((u.full_name or "").strip() or (u.phone or "").strip()), (u.phone or "").strip()


def _empty_buckets() -> dict[str, Decimal]:
    return {k: ZERO for k in BUCKET_KEYS}


def _q2(v: Decimal) -> Decimal:
    """出参的金额一律到分（含零）。

    ⚠️ 不是重新算钱：`money_map` 给的本来就是两位小数，这里只是把「没欠款的那个桶」这种
    零值也写成 `0.00` —— 不然同一张表里 `"0"` 与 `"6726.40"` 混排，导出到 Excel 是文本、
    客户端按字符串直显时又对不齐（`shipper_ledger` 那三个数同理）。
    """
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def build_customer_balances(db: Session, as_of: date, *, include_orders: bool = False) -> dict:
    """逐债务人的时点余额与账龄（截止 as_of），供报表页、导出与 AI 复用。

    as_of 的语义是**时点**：一张 3 月送达、至今还欠着的单，在 12 月的报表里仍然算欠款，
    账龄按它自己的记账日起算。窗口起点不参与余额（那是「这一段发生了多少」的报表的活）。
    """
    rows = list(
        db.scalars(
            select(Order).where(
                Order.status == OrderStatus.DELIVERED,
                Order.delivered_at.isnot(None),
                # 与 load_delivered / arrears_query 同一条：软删（隔离区）的单不算欠款。
                Order.deleted_at.is_(None),
                # 窗口预过滤只用来**减字节**（2026-09-23 容量实测：原来无条件全库读进内存）；
                # 下面那句 ds is None or ds > as_of 仍是权威判据。
                *delivered_span_sql(EARLIEST, as_of),
            )
        )
    )
    money = money_map(db, rows)
    use: list[tuple[Order, object, date]] = []
    for o in rows:
        ds = business_date(o.delivered_at)
        if ds is None or ds > as_of:
            continue
        mm = money[o.id]
        if mm.arrears == ZERO:
            # 一分钱都不欠的单不进这份报表（否则会多出一堆 0 元行，看的人只会以为系统坏了）。
            continue
        use.append((o, mm, ds))

    unit_ids = {o.arrears_unit_id for o, _mm, _ds in use if o.arrears_unit_id is not None}
    shipper_ids = {
        o.shipper_id
        for o, _mm, _ds in use
        if o.arrears_unit_id is None and not (o.arrears_unit_name or "").strip() and o.shipper_id is not None
    }
    units = {u.id: u for u in db.scalars(select(ArrearsUnit).where(ArrearsUnit.id.in_(unit_ids)))} if unit_ids else {}
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(shipper_ids)))} if shipper_ids else {}
    # 单位名下能解析到的客户档案（customers.arrears_unit_id 这条映射本身就是"能解析到"的意思）：
    # 催收时"这个单位是哪个客户"往往比名字更有用。
    unit_customers: dict[int, list[str]] = {}
    if unit_ids:
        for cid, uname, cname in db.execute(
            select(Customer.arrears_unit_id, User.full_name, User.phone)
            .join(User, User.id == Customer.user_id, isouter=True)
            .where(Customer.arrears_unit_id.in_(unit_ids))
        ).all():
            label = (uname or "").strip() or (cname or "").strip()
            if label:
                unit_customers.setdefault(int(cid), []).append(label)
    anchors = _anchor_map(db, [o.id for o, _mm, _ds in use])

    groups: dict[tuple[str, str], dict] = {}
    for o, mm, ds in use:
        kind, key = _debtor_of(o)
        g = groups.get((kind, key))
        if g is None:
            g = _new_group(kind, key, units, users, unit_customers)
            groups[(kind, key)] = g
        anchor = anchors.get(o.id) or ds
        days = max((as_of - anchor).days, 0)
        amount = mm.arrears
        g["balance"] += amount
        g["order_count"] += 1
        if amount > ZERO:
            g["buckets"][bucket_of(days)] += amount
            g["oldest_days"] = max(g["oldest_days"], days)
        else:
            # 预收（负数）：单列，不进账龄桶 —— 桶回答的是"欠久了多少"，负数没有"欠"。
            g["prepaid"] += -amount
        if include_orders:
            g["orders"].append(
                {
                    "order_id": o.id,
                    "order_no": o.order_no,
                    "delivered_on": ds.isoformat(),
                    "shipper_name": _order_shipper_label(o, users),
                    "receivable": mm.receivable,
                    "collected": mm.net_collected,   # ⚠️ 这是 @property，⛔ 不加括号
                    "arrears": amount,
                    "anchor": anchor.isoformat(),
                    "days": days,
                    "bucket": bucket_of(days) if amount > ZERO else "",
                }
            )

    # 未指定订单的收款（滚动收款）冲减这里欠款，冲掉的部分进「预收」列（BUG-0036 / TB-14）。
    # ⛔ 只冲**已经有欠款行**的债务人：已经收清的人不在这里凭空多一行出来（那笔钱在现金流水与
    #    收款记录里查得到）；恒等式 balance == Σ buckets − prepaid 保持不变。
    for key, credit in rolling_receipt_credit_map(db, as_of).items():
        g = groups.get(key)
        if g is None:
            continue
        g["prepaid"] += credit
        g["balance"] -= credit
    out_rows = [_finish_group(g) for g in groups.values()]
    # 欠得多的在前；一样多按名字排（两次跑出来的顺序必须一样，导出与页面才对得上）。
    out_rows.sort(key=lambda r: (-r["balance"], r["name"]))

    total_buckets = _empty_buckets()
    for r in out_rows:
        for k in BUCKET_KEYS:
            total_buckets[k] += r["buckets"][k]
    totals = {
        "balance": _q2(sum((r["balance"] for r in out_rows), ZERO)),
        "prepaid": _q2(sum((r["prepaid"] for r in out_rows), ZERO)),
        "buckets": total_buckets,
        "debtor_count": len(out_rows),
        "order_count": sum(r["order_count"] for r in out_rows),
        "over_limit_count": sum(1 for r in out_rows if r["over_limit"]),
        "no_unit_balance": _q2(sum((r["balance"] for r in out_rows if r["kind"] != "unit"), ZERO)),
        "no_unit_count": sum(1 for r in out_rows if r["kind"] != "unit"),
    }
    return {
        "as_of": as_of.isoformat(),
        "rows": out_rows,
        "bucket_keys": list(BUCKET_KEYS),
        "totals": totals,
        "notes": list(_NOTES),
    }


def _order_shipper_label(o: Order, users: dict[int, User]) -> str:
    """这一单的货主显示名（明细里用）：未挂单位的单要能看出是谁的单。"""
    name, _phone = _user_label(users.get(o.shipper_id) if o.shipper_id is not None else None)
    return name or (o.temp_shipper_name or "").strip()


def _new_group(
    kind: str,
    key: str,
    units: dict[int, ArrearsUnit],
    users: dict[int, User],
    unit_customers: dict[int, list[str]],
) -> dict:
    """开一行：把这一行是谁（名字 / 电话 / 额度）先定下来，钱在后面累加。"""
    g = {
        "kind": kind,
        "unit_id": None,
        "name": UNKNOWN_NAME,
        "phone": "",
        "customer_names": [],
        "balance": ZERO,
        "prepaid": ZERO,
        "buckets": _empty_buckets(),
        "oldest_days": 0,
        "order_count": 0,
        "limit": None,
        "orders": [],
    }
    if kind == "unit":
        unit = units.get(int(key))
        g["unit_id"] = int(key)
        g["name"] = (unit.name if unit is not None else "") or ("挂账单位#" + key)
        g["phone"] = (unit.phone or "").strip() if unit is not None else ""
        g["limit"] = unit.credit_limit if unit is not None else None
        g["customer_names"] = sorted(set(unit_customers.get(int(key), [])))
    elif kind == "unit_name":
        g["name"] = key
    elif kind == "shipper":
        name, phone = _user_label(users.get(int(key)))
        g["name"] = name or ("货主#" + key)
        g["phone"] = phone
    elif kind == "temp":
        g["name"] = key
    return g


def _finish_group(g: dict) -> dict:
    """收尾：算额度用量、明细按"欠得最久的在前"排。"""
    limit = g["limit"]
    g["balance"] = _q2(g["balance"])
    g["prepaid"] = _q2(g["prepaid"])
    g["buckets"] = {k: _q2(v) for k, v in g["buckets"].items()}
    used = g["balance"] if g["balance"] > ZERO else ZERO
    g["credit_used"] = _q2(used)
    g["credit_available"] = _q2(limit - used) if limit is not None else None
    g["over_limit"] = bool(limit is not None and used > limit)
    if g["orders"]:
        g["orders"].sort(key=lambda x: (-x["days"], x["order_id"]))
    return g
