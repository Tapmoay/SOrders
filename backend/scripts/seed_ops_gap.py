"""补齐经营数据：车台账 / 采购进货 / 上周送达成单 / 挂账单位 / 发票 / 收款（增量、幂等）。

## 为什么是另一个脚本（而不是重跑 seed_demo_data）

scripts/seed_demo_data.py 是给空库用的：--reset 会把业务数据整个清掉，而且它有一道守卫
（库里已经存在别的司机账号就直接拒绝执行，让用户先跑 --reset --yes）。
开发库现在有 124 个用户 / 551 张单 / 881 行账本 —— 为了补最后一周的数据把 6~9 月的历史全换掉，
显然不划算。所以这份脚本是增量的：只补缺口，且每个 section 都先查库再决定（跑第二遍是空转）。

## 补的是什么（2026-10-05 实测的缺口）

| 缺口 | 实测现状 | 哪个 section |
|---|---|---|
| 车辆折旧四格 | 15 台车 purchase_price/purchase_date/useful_life_years/residual_rate 全 NULL | vehicles |
| 采购单 | 0 张（supplier_payables 只有 1 行历史遗留） | purchase |
| 上周没有任何送达 | 最后一次送达 2026-09-26，10 月只有 1 张待派 + 2 张退货 | deliver |
| 10 月的开销 | 10 月 0 笔（9 月 9 笔） | expenses |
| 挂账单位额度 / 订单挂到单位 | credit_limit 全 NULL、orders.arrears_unit_id 全 NULL | charge |
| 发票 | 0 张 | invoice |
| 「从没记过进货价」的商品 | id=71 速冻水饺（在售、有库存、cost 0） | purchase（进一次货就修好） |

## 规矩（与 seed_demo_data 同一套，逐条都别破）

1. 走真实业务函数：update_vehicle / create_purchase_order / assign_driver + complete_delivery /
   charge_order / update_unit / create_invoice / create_receipt_endpoint / create_expense ——
   账本、司机账单、现金流水、库存流水、审计日志都由业务代码自己写，本脚本不直接 insert 这几张表。
   只有两处例外，都在代码里标了理由：customers.arrears_unit_id（服务端没有入口）与
   回放历史后的日期对齐 SQL（不补这一步，账本/账单/流水会全挤在今天）。
2. 日期取自业务时刻：库里时间列一律 UTC naive，写之前过 to_utc_naive()。
3. 该填的都填：联系人、地址、单位、成本、备注 —— 空字段在界面上就是一条横线。
4. 预览是默认：不带 --yes 只打印计划。

用法（在 backend/ 目录下跑，送达照片会写到 uploads/）：

    python -m scripts.seed_ops_gap                  # 预览
    python -m scripts.seed_ops_gap --yes            # 写库
    python -m scripts.seed_ops_gap --yes --only vehicles,purchase
"""

import argparse
import random
import sys
from datetime import date, datetime, time as dtime, timedelta
from decimal import ROUND_HALF_UP, Decimal

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from fastapi import BackgroundTasks  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402

from app.core.business_time import business_date, business_today, to_utc_naive  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import (ArrearsUnit, Customer, Expense, Order, OrderProduct,  # noqa: E402
                        Product, PurchaseOrder, ShipperReceipt, SupplierPayable,
                        User, Vehicle)
from app.models.enums import OrderStatus, UserRole  # noqa: E402
from app.models.product import PriceRule  # noqa: E402
from app.models.shipper import ShipperLocation  # noqa: E402
from scripts.seed_demo_data import (DRIVER_REMARKS, EXPENSE_NOTES, ROUTES,  # noqa: E402
                                    biz_day_sql, person, phone, wall_now,
                                    write_delivery_photo)

#: 写进采购单 remark 的标记（幂等靠它认人；也是事后把这一轮补的数据挑出来的把手）
MARK = "补录"
#: 本轮补的那一周：报表中心的「上周」= 2026-09-28 ~ 2026-10-04（今天 2026-10-05 是周一）
WEEK_START = date(2026, 9, 28)
WEEK_END = date(2026, 10, 4)

#: 补的送达成单：逐日写死（不用随机）。日均 ~6 单，与库里的真实节奏一致
#: （9 月 151 单约每周 35 单；含尖峰的上一周 50 单）。
#: 今天（10-05）故意不补 —— 现在是凌晨三点，"今天还没有发出去的货"本来就是对的。
DELIVER_PLAN = [
    (date(2026, 9, 27), 3),   # 周日：只有早班几单
    (date(2026, 9, 28), 9),   # 周一最忙
    (date(2026, 9, 29), 10),
    (date(2026, 9, 30), 8),
    (date(2026, 10, 1), 5),   # 国庆假期：走货明显少下来
    (date(2026, 10, 2), 4),
    (date(2026, 10, 3), 6),   # 假期里补货的小高峰
    (date(2026, 10, 4), 2),
]
#: 撤销单：掺在送达单里（营业额报表的「已撤销」那一档要有真实样本）
CANCEL_PLAN = {date(2026, 9, 28): 1, date(2026, 9, 30): 1, date(2026, 10, 2): 1}
#: 还在飞的单：10-04 晚上下的、到此刻还没送达（(日, 时, 分, 状态)）
IN_FLIGHT = [
    (date(2026, 10, 4), 18, 20, "pending"),
    (date(2026, 10, 4), 19, 5, "pending"),
    (date(2026, 10, 4), 20, 40, "pending"),
    (date(2026, 10, 4), 21, 15, "accepted"),
]

#: 车辆购置资料：逐台写死（跑第二遍必须一模一样）。
#: 格式 (购置价, 购置日期, 使用年限, 残值率)；None = 这一格留空。
#: 最后一台（粤B12345）故意四格全空、id=14 故意缺「使用年限」——
#: 报表中心的「折旧未覆盖（车没填购置价就算不出来）」需要真实样本，
#: 全填满的话那两条分支在真机上永远看不到（这正是这次补数据要能测的东西）。
VEHICLE_PLAN = {
    1: ("118000.00", "2023-04-12", "8", "0.05"),
    2: ("88000.00", "2024-03-06", "8", "0.05"),
    3: ("132000.00", "2022-11-19", "8", "0.06"),
    4: ("246000.00", "2023-07-01", "10", "0.08"),
    5: ("79000.00", "2024-09-23", "8", None),          # 残值率留空 = 0%（唯一留空有意义的一格）
    6: ("105000.00", "2023-01-15", "8", "0.05"),
    7: ("218000.00", "2022-05-28", "10", "0.10"),
    8: ("96000.00", "2024-06-11", "8", "0.05"),
    9: ("126000.00", "2023-09-04", "8", "0.05"),
    10: ("335000.00", "2021-08-16", "12", "0.10"),     # 挂车，最贵
    11: ("268000.00", "2024-02-20", "10", "0.08"),
    12: ("84000.00", "2022-12-03", "8", "0.04"),
    13: ("113000.00", "2025-01-09", "8", "0.05"),
    14: ("92000.00", "2024-08-27", None, "0.05"),      # 故意缺「使用年限」
    15: (None, None, None, None),                      # 故意四格全空
}

#: 采购单：doc_date 与行数（商品/数量/单价由固定种子的随机数池生成，跑两遍一样）
PURCHASE_DAYS = [date(2026, 9, 19), date(2026, 9, 20), date(2026, 9, 22), date(2026, 9, 24),
                 date(2026, 9, 26), date(2026, 9, 28), date(2026, 9, 29), date(2026, 10, 1),
                 date(2026, 10, 2), date(2026, 10, 3), date(2026, 10, 4), date(2026, 10, 4)]

#: 哪些客户是"账挂在哪个单位名下"的档口/门店（客户 id -> 单位 id）。
#: 挂账单位是"替这些客户结账的管理处/食堂"，所以报表把它们并成一行看额度。
UNIT_CUSTOMERS = {
    2: [26, 29, 28],   # 信立农批市场管理处 <- 顺鑫蔬菜批发 / 万家冻品 / 城东水产
    3: [12, 15],       # 惠阳人民医院饭堂 <- 东江快餐店 / 东江生鲜超市
    4: [9, 8],         # 德赛工业园食堂 <- 陈记中学食堂 / 聚福楼肠粉店
    5: [19, 22],       # 伯恩光学食堂 <- 顺发农副产品店 / 家家福川菜馆
    6: [25, 30],       # TCL 液晶产业园食堂 <- 兴发果业 / 新叶生鲜配送
}
#: 额度的给法：额度 = 真实挂账额 x 倍数（先算出真实挂账再乘）。
#: 0.6 与 0.55 = 故意给得不够 -> 报表里出现「超限」；其余给得宽 -> 正常状态。
#: 两边都有样本，超限那条分支才测得到。
CREDIT_FACTOR = {2: "0.60", 3: "1.60", 4: "0.55", 5: "2.00", 6: "1.15"}

#: 10 月的开销（(日期, 分类, 金额, 车序号)）。分类与名册一致，车相关的挂车。
EXPENSE_PLAN = [
    (date(2026, 9, 28), "加油", "620.00", 0),
    (date(2026, 9, 28), "过路", "185.00", 3),
    (date(2026, 9, 29), "维修", "1500.00", 8),
    (date(2026, 9, 30), "加油", "480.00", 5),
    (date(2026, 9, 30), "停车", "60.00", 10),
    (date(2026, 10, 1), "罚款", "200.00", 2),
    (date(2026, 10, 2), "过路", "260.00", 7),
    (date(2026, 10, 3), "加油", "900.00", 11),
    (date(2026, 10, 3), "保险", "3800.00", 4),
    (date(2026, 10, 4), "维修", "350.00", 12),
    (date(2026, 10, 4), "其他", "180.00", -1),          # 办公耗材：不挂车
]


def q2(value) -> Decimal:
    """金额一律两位、显式 ROUND_HALF_UP（全站口径；Decimal 默认是 HALF_EVEN，会差 1 分）。"""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def pick_time(day: date, rng: random.Random) -> datetime:
    """下单时刻：早班 6~9 点半 + 下午 14~17 点两个主峰（与 seed_demo_data 的性格一致）。"""
    hour = rng.choice([6, 6, 7, 7, 7, 8, 8, 9, 14, 14, 15, 15, 16, 16, 17])
    return datetime.combine(day, dtime(hour, rng.randint(0, 59)))


# ---------------------------------------------------------------- ① 车辆折旧四格
def sec_vehicles(db, dispatcher, yes: bool, rng: random.Random) -> None:
    from app.api.v1.vehicles import update_vehicle
    from app.schemas.accounting_v2 import VehicleUpdate

    todo = []
    for v in db.scalars(select(Vehicle).order_by(Vehicle.id)).all():
        spec = VEHICLE_PLAN.get(v.id)
        if spec is None or all(x is None for x in spec):
            continue                      # 计划里没有 / 故意留空的那台
        if v.purchase_price is not None and v.purchase_date is not None:
            continue                      # 已补过（幂等）
        fields = {}
        if spec[0] is not None:
            fields["purchase_price"] = Decimal(spec[0])
        if spec[1] is not None:
            fields["purchase_date"] = date.fromisoformat(spec[1])
        if spec[2] is not None:
            fields["useful_life_years"] = Decimal(spec[2])
        if spec[3] is not None:
            fields["residual_rate"] = Decimal(spec[3])
        todo.append((v, fields))

    print(f"[vehicles] 待补 {len(todo)} 台（计划里共 {len(VEHICLE_PLAN)} 台，"
          f"其中粤B12345 故意四格全空、粤SZM3825 故意缺使用年限）")
    for v, fields in todo:
        desc = " ".join(f"{k}={val}" for k, val in fields.items())
        print(f"    {v.plate_no}({v.vehicle_type}) {desc}")
    if not yes:
        return
    for v, fields in todo:
        update_vehicle(v.id, VehicleUpdate(**fields), dispatcher, db)
    print(f"[vehicles] 已写 {len(todo)} 台")


# ---------------------------------------------------------------- ② 采购进货
def sec_purchase(db, dispatcher, yes: bool, rng: random.Random) -> None:
    from app.api.v1.purchase_orders import create_purchase_order
    from app.schemas.purchase import PurchaseItemIn, PurchaseOrderCreate

    done = db.scalar(select(func.count()).select_from(PurchaseOrder)
                     .where(PurchaseOrder.remark.like(f"%{MARK}%")))
    if done:
        print(f"[purchase] 库里已有 {done} 张带「{MARK}」的采购单，跳过")
        return

    products = db.scalars(select(Product).where(Product.is_active.is_(True),
                                                Product.id <= 36).order_by(Product.id)).all()
    dumpling = db.get(Product, 71)          # 在售、有库存、从没记过进货价
    orders = []
    for idx, day in enumerate(PURCHASE_DAYS):
        lines = []
        if idx == 0 and dumpling is not None:
            # 给速冻水饺进一次货 —— 修掉报表里「从没记过进货价」那一名册（cost 0 -> 18.60）
            lines.append(PurchaseItemIn(product_id=dumpling.id, quantity=40,
                                        unit_cost=Decimal("18.60")))
        for p in rng.sample(products, rng.randint(3, 5)):
            if any(l.product_id == p.id for l in lines):
                continue
            qty = rng.randint(10, 45)
            unit_cost = q2(Decimal(p.cost_price) * Decimal(str(round(rng.uniform(0.95, 1.08), 4))))
            if unit_cost <= 0:
                continue
            lines.append(PurchaseItemIn(product_id=p.id, quantity=qty, unit_cost=unit_cost))
        if lines:
            orders.append((day, lines))

    total = sum((l.unit_cost * l.quantity for _, lines in orders for l in lines), Decimal("0"))
    print(f"[purchase] 待建 {len(orders)} 张采购单（{PURCHASE_DAYS[0]} ~ {PURCHASE_DAYS[-1]}），"
          f"合计约 ¥{q2(total)}（供应商：永盛食品有限公司）")
    for day, lines in orders:
        head = "、".join(f"{db.get(Product, l.product_id).name}×{l.quantity}@{l.unit_cost}"
                         for l in lines[:3])
        print(f"    {day} {len(lines)} 行：{head}{' 等' if len(lines) > 3 else ''}")
    if not yes:
        return
    for day, lines in orders:
        create_purchase_order(PurchaseOrderCreate(
            supplier_id=1, doc_date=day, remark=f"门店订货，{MARK}", items=lines,
        ), db, dispatcher)
    print(f"[purchase] 已建 {len(orders)} 张（库存 + 成本价历史 + 供应商应付 由服务层自己写）")


# ---------------------------------------------------------------- ③ 送达成单
def sec_deliver(db, dispatcher, yes: bool, rng: random.Random) -> None:
    """补 2026-09-27 ~ 2026-10-04 的单（含撤销单与 10-04 夜里还没送达的 4 张）。

    走的是与真机同一条路：建单 -> assign_driver -> complete_delivery（它自己写账本、
    司机账单、库存流水、货损开销与红冲）。回放历史的那三个时刻必须在 complete_delivery
    之后重设（它内部 lock_order_row + db.refresh 会丢掉未 flush 的内存改动）。
    """
    from app.schemas.order import DamageItem
    from app.services.order_flow import assign_driver, complete_delivery

    todo = []
    for day, n in DELIVER_PLAN:
        have = db.scalar(select(func.count()).select_from(Order).where(Order.order_date == day)) or 0
        if have < n:
            todo.append((day, n - have))
    cancelled = []
    for day, n in CANCEL_PLAN.items():
        c = db.scalar(select(func.count()).select_from(Order)
                      .where(Order.order_date == day, Order.status == OrderStatus.CANCELLED)) or 0
        if c < n:
            cancelled.append((day, n - c))

    if not todo and not cancelled:
        print("[deliver] 这一周的单已经在了，跳过")
        return

    shippers = db.scalars(select(User).where(User.role == UserRole.SHIPPER,
                                             User.id <= 35).order_by(User.id)).all()
    drivers = db.scalars(select(User).where(User.role == UserRole.DRIVER,
                                            User.id <= 58).order_by(User.id)).all()
    products = db.scalars(select(Product).where(Product.is_active.is_(True)).order_by(Product.id)).all()
    locs_by_shipper = {}
    for s in shippers:
        rows = db.scalars(select(ShipperLocation).where(ShipperLocation.shipper_id == s.id,
                                                       ShipperLocation.is_deleted.is_(False))).all()
        if rows:
            locs_by_shipper[s.id] = list(rows)
    fallback = list(db.scalars(select(ShipperLocation)
                               .where(ShipperLocation.shipper_id == dispatcher.id,
                                      ShipperLocation.is_deleted.is_(False))).all())
    if not fallback:
        fallback = list(db.scalars(select(ShipperLocation)
                                   .where(ShipperLocation.is_deleted.is_(False))).all())

    unit_shippers = [db.get(Customer, c).user_id for cs in UNIT_CUSTOMERS.values() for c in cs]
    unit_shippers = [u for u in unit_shippers if u]
    other_shippers = [s for s in shippers if s.id not in set(unit_shippers)]

    events = []
    for day, n in todo:
        for _ in range(n):
            events.append((pick_time(day, rng), "delivered"))
    for day, n in cancelled:
        for _ in range(n):
            events.append((pick_time(day, rng), "cancelled"))
    live = db.scalar(select(func.count()).select_from(Order)
                     .where(Order.order_date == date(2026, 10, 4),
                            Order.status.notin_([OrderStatus.DELIVERED,
                                                 OrderStatus.CANCELLED]))) or 0
    if live < len(IN_FLIGHT):
        for day, hh, mm, kind in IN_FLIGHT:
            events.append((datetime.combine(day, dtime(hh, mm)), kind))
    events.sort(key=lambda e: e[0])

    n_each = {k: sum(1 for _, x in events if x == k)
              for k in ("delivered", "cancelled", "pending", "accepted")}
    print(f"[deliver] 待建 {len(events)} 单：送达 {n_each['delivered']} / 撤销 {n_each['cancelled']} / "
          f"待派 {n_each['pending']} / 已接单 {n_each['accepted']}")
    print(f"    {DELIVER_PLAN[0][0]} ~ {DELIVER_PLAN[-1][0]}，逐日 "
          + "、".join(f"{d.strftime('%m-%d')}x{n}" for d, n in DELIVER_PLAN)
          + f"；今天（{business_today()}）故意不补（凌晨三点，今天的货还没出去）")
    if not yes:
        return

    for created, kind in events:
        day = created.date()
        # 六成的单落在"账挂在单位名下"的那几家客户，其余散给别的货主
        if rng.random() < 0.6:
            shipper = db.get(User, rng.choice(unit_shippers))
        else:
            shipper = rng.choice(other_shippers)
        lines = rng.sample(products, rng.choices([1, 2, 3, 4, 5], weights=[38, 28, 18, 10, 6], k=1)[0])
        own = locs_by_shipper.get(shipper.id)
        loc = rng.choice(own) if own and rng.random() < 0.7 else rng.choice(fallback)
        route = rng.choice(ROUTES)
        payment = rng.choices(["arrears", "cash"], weights=[78, 22], k=1)[0]
        o = Order(order_no=f"SO{created:%Y%m%d}{rng.randrange(10 ** 10):010d}",
                  status=OrderStatus.PENDING_DISPATCH,
                  shipper_id=shipper.id, order_date=created.date(),
                  created_at=to_utc_naive(created), updated_at=to_utc_naive(created),
                  delivery_description=rng.choice(["送到后门卸货", "走正门找收货员", "卸在一楼月台",
                                                   "提前 10 分钟打电话", "冷藏品请直接进冷库"]),
                  address_detail=loc.detail_address, address_lat=loc.address_lat,
                  address_lng=loc.address_lng, contact_dongjia_phone=phone(),
                  contact_dongjia_name=person(0.4),
                  contact_boss_name=shipper.full_name, contact_boss_phone=shipper.phone,
                  remark=rng.choice(["", "", "尽量上午送到", "货要新鲜的", "带票据过来"]),
                  freight_fee=Decimal(route[2]) + Decimal(rng.choice([0, 0, 5, 10, 15])),
                  payment_method=payment, collect_cash=(payment == "cash"),
                  paid=False, is_exception=False,
                  # delivery_photo_urls 是 JSON 列（给 list），image_urls 是 Text 列（给字符串）
                  image_urls="[]", delivery_photo_urls=[])
        db.add(o)
        db.flush()
        for p in lines:
            qty = rng.choices([1, 2, 3, 4, 5, 6, 8, 10, 12, 20],
                              weights=[22, 18, 14, 12, 10, 8, 6, 5, 3, 2], k=1)[0]
            price = p.default_unit_price
            if shipper.is_member:
                pr = db.query(PriceRule).filter(PriceRule.shipper_id == shipper.id,
                                               PriceRule.product_id == p.id).first()
                if pr is not None:
                    price = pr.special_unit_price
            db.add(OrderProduct(order_id=o.id, product_id=p.id, product_name_snapshot=p.name,
                                unit_snapshot=p.unit, quantity=qty, unit_price=price,
                                line_total=q2(price * qty), cost_price_snapshot=p.cost_price))

        if kind == "delivered":
            driver = rng.choice(drivers)
            assign_driver(db, o, driver, dispatcher,
                          internal_note=rng.choice(["", "", "客户催过", "顺路带过去", "熟客"]))
            o.dispatched_at = created + timedelta(minutes=rng.randint(5, 90))
            o.driver_acknowledged_at = o.dispatched_at + timedelta(minutes=rng.randint(2, 120))
            o.status = OrderStatus.ACCEPTED
            db.flush()
            cap = min(wall_now() - timedelta(hours=1), datetime.combine(day, dtime(21, 0)))
            dlv = min(o.driver_acknowledged_at + timedelta(hours=rng.uniform(0.7, 6)), cap)
            if dlv <= created:
                dlv = created + timedelta(minutes=rng.randint(5, 25))
            dsp, ack = o.dispatched_at, o.driver_acknowledged_at
            if dlv <= ack:
                room = max(0, int((dlv - created).total_seconds() // 60))
                ack = max(created, dlv - timedelta(minutes=min(room // 2, 60)))
                dsp = max(created, ack - timedelta(minutes=min(room // 3, 30)))
            dmg = None
            if rng.random() < 0.035:
                line = db.query(OrderProduct).filter(OrderProduct.order_id == o.id).first()
                if line and line.quantity > 1:
                    dmg = [DamageItem(order_product_id=line.id, quantity=1)]
            photo = write_delivery_photo(o.id, o.order_no, dlv, shipper.full_name)
            complete_delivery(db, o, driver, [photo],
                              driver_remark=rng.choice(DRIVER_REMARKS),
                              damage_items=dmg, damage_note="运输途中挤压" if dmg else "")
            # 三个时刻必须在 complete_delivery 之后写：它的第一件事是 lock_order_row +
            # db.refresh(order)，会把还没 flush 的内存改动整份丢掉。
            o.delivered_at = to_utc_naive(dlv)
            o.dispatched_at = to_utc_naive(dsp)
            o.driver_acknowledged_at = to_utc_naive(ack)
            o.updated_at = to_utc_naive(dlv)
            if rng.random() < 0.04:
                o.is_exception = True
                o.exception_reason = rng.choice(["客户说少送一箱", "迟到两小时", "包装破损"])
            db.commit()
        elif kind == "cancelled":
            o.status = OrderStatus.CANCELLED
            o.cancelled_at = to_utc_naive(created + timedelta(hours=rng.randint(1, 20)))
            db.commit()
        elif kind == "accepted":
            driver = rng.choice(drivers)
            assign_driver(db, o, driver, dispatcher, internal_note="夜里下单，明早出车")
            o.dispatched_at = to_utc_naive(created + timedelta(minutes=25))
            o.driver_acknowledged_at = to_utc_naive(created + timedelta(minutes=40))
            o.status = OrderStatus.ACCEPTED
            db.commit()
        else:
            db.commit()
    print(f"[deliver] 已建 {len(events)} 单（其中送达 {n_each['delivered']}）")


# ---------------------------------------------------------------- ④ 10 月的开销
def sec_expenses(db, dispatcher, yes: bool, rng: random.Random) -> None:
    from app.api.v1.expenses import create_expense
    from app.schemas.accounting_v2 import ExpenseCreate

    cars = db.scalars(select(Vehicle).where(Vehicle.is_active.is_(True)).order_by(Vehicle.id)).all()
    todo = []
    for day, cat, amount, car_idx in EXPENSE_PLAN:
        exists = db.scalar(select(func.count()).select_from(Expense)
                           .where(Expense.exp_date == day, Expense.category == cat,
                                  Expense.amount == Decimal(amount))) or 0
        if exists:
            continue
        car = cars[car_idx] if 0 <= car_idx < len(cars) else None
        note = (f"{car.plate_no} {EXPENSE_NOTES[cat][0]}" if car is not None else "办公室耗材")
        todo.append((day, cat, amount, car, note))

    print(f"[expenses] 待补 {len(todo)} 笔（{WEEK_START} ~ {WEEK_END}）")
    for day, cat, amount, car, note in todo:
        plate = car.plate_no if car is not None else "（不挂车）"
        print(f"    {day} {cat} ¥{amount} {plate}｜{note}")
    if not yes:
        return
    for day, cat, amount, car, note in todo:
        create_expense(ExpenseCreate(
            exp_date=day, category=cat, amount=Decimal(amount), note=note,
            vehicle_id=car.id if car is not None else None,
            driver_id=car.driver_id if car is not None else None,
        ), dispatcher, db)
    print(f"[expenses] 已写 {len(todo)} 笔（含现金流水，由服务层自己写）")


# ---------------------------------------------------------------- ⑤ 客户收款
def sec_receipt(db, dispatcher, yes: bool, rng: random.Random) -> None:
    """给几家"付得爽快"的客户造逐单核销收款 + 两笔滚动收款。

    金额必须精确等于所选订单的 arrears（ITEMIZED 的硬校验），所以先用
    order_money.money_map 算出来再传 —— 少一分多一分都会被拒。
    走的是端点 create_receipt_endpoint（不是 service）：只有端点会写 RECEIPT_CREATE 审计行。
    """
    from app.api.v1.ledger import create_receipt_endpoint
    from app.models.enums import ReceiptSettleMode
    from app.schemas.accounting_v2 import ShipperReceiptCreate
    from app.services.order_money import money_map

    mapped = [x for cs in UNIT_CUSTOMERS.values() for x in cs]
    pool = [c for c in (4, 5, 6, 10, 11, 13, 14, 16, 17, 18, 20, 21, 23, 24, 27, 31, 32)
            if c not in mapped]
    picked_cust = sorted(rng.sample(pool, 8))
    today = business_today()

    plan = []
    for cid in picked_cust:
        cust = db.get(Customer, cid)
        if cust is None or cust.user_id is None:
            continue
        orders = db.scalars(select(Order).where(Order.shipper_id == cust.user_id,
                                                Order.status == OrderStatus.DELIVERED,
                                                Order.paid.isnot(True))
                            .order_by(Order.delivered_at.desc())).all()
        if not orders:
            continue
        mm = money_map(db, orders)
        cand = [o for o in orders if mm[o.id].arrears > 0][: rng.randint(1, 3)]
        if not cand:
            continue
        amount = sum((mm[o.id].arrears for o in cand), Decimal("0"))
        # 收款日必须晚于这批单里**最晚**的那次送达（客户收到货才付钱）。
        # ⛔ 早先写成 cand[-1]（最老那单）→ 收款日会早于新单的送达日，
        #    于是「已收」记在订单窗口、现金流水的日期却落在窗口外，两页对不上。
        last = max((business_date(o.delivered_at) or o.order_date) for o in cand)
        received_at = min(last + timedelta(days=rng.randint(1, 2)), today)
        plan.append((cust, cand, q2(amount), received_at,
                     rng.choice(["cash", "transfer", "wechat"])))

    print(f"[receipt] 待造 {len(plan)} 张逐单核销收款 + 2 张滚动收款")
    for cust, cand, amount, received_at, method in plan:
        print(f"    {cust.name} ¥{amount} {method} {received_at} "
              f"（核销单号 {', '.join(str(o.id) for o in cand)}）")
    if not yes:
        return
    n = 0
    for cust, cand, amount, received_at, method in plan:
        create_receipt_endpoint(ShipperReceiptCreate(
            customer_id=cust.id, amount=amount, method=method, received_at=received_at,
            order_ids=[o.id for o in cand], settle_mode=ReceiptSettleMode.ITEMIZED,
            note=rng.choice(["现场结清", "微信转账", "月结第一笔", "老板亲自来结"]),
        ), BackgroundTasks(), dispatcher, db)
        n += 1
    # 滚动收款没有"逐单核销"那样的天然幂等（它不动订单），所以自己认一下备注。
    rolled = db.scalar(select(func.count()).select_from(ShipperReceipt)
                       .where(ShipperReceipt.note == "先付一笔，月底再对")) or 0
    for _ in range(0 if rolled else 2):
        cust = db.get(Customer, rng.choice(pool))
        create_receipt_endpoint(ShipperReceiptCreate(
            customer_id=cust.id, amount=Decimal(rng.choice(["800.00", "1500.00"])),
            method="transfer", received_at=today - timedelta(days=rng.randint(1, 4)),
            order_ids=[], settle_mode=ReceiptSettleMode.ROLLING, note="先付一笔，月底再对",
        ), BackgroundTasks(), dispatcher, db)
        n += 1
    print(f"[receipt] 已写 {n} 张（逐单核销会逐单生成现金流水；滚动收款不动订单）")


# ---------------------------------------------------------------- ⑥ 挂账单位与额度
def sec_charge(db, dispatcher, yes: bool, rng: random.Random) -> None:
    """把客户的未收订单挂到挂账单位名下，再按真实挂账额给单位设信用额度。

    两件事必须一起做：只设额度不挂订单的话，报表里根本没有 unit 分组
    （balance_query._debtor_of 先看 orders.arrears_unit_id），额度永远看不出效果。
    """
    from app.api.v1.arrears import update_unit
    from app.api.v1.orders_payment import charge_order
    from app.schemas.arrears import ArrearsUnitUpdate
    from app.schemas.order import OrderChargeBody
    from app.services.order_money import money_map

    cust_of_shipper = {}
    cust_ids = []
    for unit_id, cs in UNIT_CUSTOMERS.items():
        for cid in cs:
            cust = db.get(Customer, cid)
            cust_ids.append(cid)
            if cust is not None and cust.user_id:
                cust_of_shipper[cust.user_id] = unit_id

    orders = db.scalars(select(Order).where(Order.shipper_id.in_(list(cust_of_shipper)),
                                            Order.status == OrderStatus.DELIVERED,
                                            Order.paid.isnot(True),
                                            Order.payment_method == "arrears")
                        .order_by(Order.id)).all()
    todo = [o for o in orders if o.arrears_unit_id is None]
    mm = money_map(db, orders)
    total = sum((mm[o.id].arrears for o in orders), Decimal("0"))
    by_unit = {}
    for o in orders:
        unit_id = cust_of_shipper[o.shipper_id]
        by_unit[unit_id] = by_unit.get(unit_id, Decimal("0")) + mm[o.id].arrears

    print(f"[charge] {len(UNIT_CUSTOMERS)} 个挂账单位 / {len(cust_ids)} 家客户；"
          f"待挂订单 {len(todo)} 张（这些客户共有 {len(orders)} 张未收挂账单，合计 ¥{q2(total)}）")
    for unit_id, amount in sorted(by_unit.items()):
        unit = db.get(ArrearsUnit, unit_id)
        factor = Decimal(CREDIT_FACTOR[unit_id])
        print(f"    {unit.name}：挂账 ¥{q2(amount)} -> 额度 ¥{q2(amount * factor)}"
              f"（{'会超限' if factor < 1 else '额度宽松'}）")
    if not yes:
        return

    for o in todo:
        charge_order(o.id, OrderChargeBody(arrears_unit_id=cust_of_shipper[o.shipper_id]),
                     db, dispatcher)
    # 这一格没有 HTTP 入口：/customers 只有「建客户」与「合并」（create_customer 才收
    # arrears_unit_id），已有档案改挂账单位在服务端根本没有入口 —— 所以直接 UPDATE。
    # 它是本脚本唯一直接写业务表的例外（另一处是回放历史后的日期对齐 SQL）。
    for unit_id, cs in UNIT_CUSTOMERS.items():
        for cid in cs:
            db.execute(text("update customers set arrears_unit_id = :u where id = :c"),
                       {"u": unit_id, "c": cid})
    db.commit()
    for unit_id, amount in sorted(by_unit.items()):
        factor = Decimal(CREDIT_FACTOR[unit_id])
        update_unit(unit_id, ArrearsUnitUpdate(credit_limit=q2(amount * factor)), db, dispatcher)
    print(f"[charge] 已挂 {len(todo)} 张单、设 {len(by_unit)} 个单位额度、"
          f"{len(cust_ids)} 家客户档案改挂单位")


# ---------------------------------------------------------------- ⑦ 发票
def sec_invoice(db, dispatcher, yes: bool, rng: random.Random) -> None:
    """进项票挂采购单、销项票挂客户。

    销项票不挂账本行：正常销售（source=ORDER）的账本行 customer_id 恒为 NULL
    （ledger_sync.sync_ledger_from_delivered_order 一个字都没写），所以销项票根本没有
    账本行可挂 —— 能挂的只有退货/货损红冲那几行。这是产品级缺口，造数脚本不绕。
    """
    from app.api.v1.invoices import create_invoice
    from app.models import Invoice
    from app.schemas.invoice import InvoiceCreate
    from app.services.order_money import money_map

    # 只认本脚本开的号段（0441 进项 / 0442 销项）：票号同方向唯一、连回收站一起算，
    # 重跑撞号会 409。别的来源的票不管。
    have = db.scalar(select(func.count()).select_from(Invoice)
                     .where(Invoice.invoice_no.like("044%"))) or 0
    if have:
        print(f"[invoice] 库里已有 {have} 张本脚本开的票，跳过（票号唯一，重跑会 409）")
        return

    pos = db.scalars(select(PurchaseOrder).order_by(PurchaseOrder.doc_date, PurchaseOrder.id)).all()
    groups = [pos[i:i + 3] for i in range(0, len(pos), 3)][:4]
    rates = ["9.00", "9.00", "3.00", None]
    inputs = []
    for idx, group in enumerate(groups):
        amount = Decimal("0")
        for po in group:
            payable = db.get(SupplierPayable, po.payable_id) if po.payable_id else None
            amount += Decimal(payable.amount) if payable is not None else Decimal("0")
        if amount <= 0:
            continue
        last_day = max(po.doc_date for po in group)
        # 票期夹在测试窗口内：报表中心的「上周」= 09-28 ~ 10-04，票落在窗口外就测不到税汇。
        inputs.append((group, q2(amount), rates[idx % len(rates)],
                       min(last_day + timedelta(days=2), WEEK_END)))

    outputs = []
    for cid, rate in ((26, "3.00"), (9, "9.00"), (22, None)):
        cust = db.get(Customer, cid)
        if cust is None or cust.user_id is None:
            continue
        orders = db.scalars(select(Order).where(Order.shipper_id == cust.user_id,
                                                Order.status == OrderStatus.DELIVERED,
                                                Order.order_date >= WEEK_START,
                                                Order.order_date <= WEEK_END)).all()
        if not orders:
            continue
        mm = money_map(db, orders)
        amount = sum((mm[o.id].receivable for o in orders), Decimal("0"))
        if amount <= 0:
            continue
        outputs.append((cust, q2(amount), rate, WEEK_END))

    print(f"[invoice] 待开 {len(inputs)} 张进项票 + {len(outputs)} 张销项票")
    for group, amount, rate, when in inputs:
        print(f"    进项 ¥{amount} 税率 {rate or '未税'} {when} <- 采购单 "
              f"{', '.join(str(po.id) for po in group)}")
    for cust, amount, rate, when in outputs:
        print(f"    销项 ¥{amount} 税率 {rate or '未税'} {when} <- {cust.name}")
    if not yes:
        return
    for idx, (group, amount, rate, when) in enumerate(inputs):
        create_invoice(InvoiceCreate(
            direction="INPUT", invoice_no=f"0441{when:%m%d}{idx:02d}", invoice_date=when,
            amount=amount, tax_rate=Decimal(rate) if rate else None, tax_amount=None,
            supplier_id=1, purchase_order_ids=[po.id for po in group],
            note=f"进项票（挂采购单 {len(group)} 张）",
        ), db, dispatcher)
    for idx, (cust, amount, rate, when) in enumerate(outputs):
        create_invoice(InvoiceCreate(
            direction="OUTPUT", invoice_no=f"0442{when:%m%d}{idx:02d}", invoice_date=when,
            amount=amount, tax_rate=Decimal(rate) if rate else None, tax_amount=None,
            customer_id=cust.id, note=f"销项票（{cust.name}）",
        ), db, dispatcher)
    print(f"[invoice] 已开 {len(inputs) + len(outputs)} 张")


# ---------------------------------------------------------------- ⑧ 回放历史的日期对齐
def align_history(db) -> None:
    """把"按送达时刻派生"的行对齐回那一单的业务日（照抄 seed_demo_data 的那一段）。

    为什么必须做：complete_delivery 那一串业务函数写的都是"此刻"（线上就该这样），
    而我们是在一次性回放历史 —— 不对齐的话账本/司机账单/货损开销/库存流水会全挤在今天，
    报表与日期筛选直接测不了。
    一个字都不许用 date(时间戳)：库里存 UTC，北京 06:30 的单存进去是前一天 22:30 ——
    业务日 = UTC + 8 小时取日期（business_date 的定义），两种库写法走 biz_day_sql。
    每条都带一个"子查询确实算得出值"的门：order_id 可能指向一张已经不在了的订单，
    那时子查询回 NULL，往 NOT NULL 列写 NULL 就是 IntegrityError。
    """
    dialect = db.get_bind().dialect.name
    order_day = biz_day_sql("coalesce(o.delivered_at, o.order_date)", dialect)

    def alignable(table: str) -> str:
        return (f"order_id is not null and exists (select 1 from orders o "
                f"where o.id = {table}.order_id "
                f"and coalesce(o.delivered_at, o.order_date) is not null)")

    n_bills = db.execute(text(f"""
        update driver_bills set month = (
            select substr({order_day}, 1, 7) from orders o where o.id = driver_bills.order_id
        ) where {alignable('driver_bills')}
    """)).rowcount
    n_ledger = db.execute(text(f"""
        update ledgers set entry_date = (
            select {order_day} from orders o where o.id = ledgers.order_id
        ) where {alignable('ledgers')}
    """)).rowcount
    n_exp = db.execute(text(f"""
        update expenses set exp_date = (
            select {order_day} from orders o where o.id = expenses.order_id
        ) where {alignable('expenses')}
    """)).rowcount
    n_cash = db.execute(text(f"""
        update cash_flows set flow_date = (
            select {order_day} from orders o where o.id = cash_flows.order_id
        ) where biz_type = 'EXPENSE_LOSS' and {alignable('cash_flows')}
    """)).rowcount
    n_inv = db.execute(text("""
        update inventory_movements set created_at = (
            select coalesce(o.delivered_at, o.created_at) from orders o
            where o.id = inventory_movements.order_id
        ) where order_id is not null and exists (
            select 1 from orders o where o.id = inventory_movements.order_id
              and coalesce(o.delivered_at, o.created_at) is not null
        )
    """)).rowcount
    # 采购入库流水：采购流水**不挂订单**（order_id 为空），上面那条统一 UPDATE 碰不到它，
    # 而 purchase_service 写流水用的是"此刻" —— 补录历史采购时 12 张单的入库行全挤在今天凌晨，
    # 成本口径 cost_basis._weighted_avg 是按 inventory_movements.created_at 落窗口的
    # → 历史上任何一周都取不到「本期加权均价」，毛利会静默退回订单快照那一级
    # （第一轮实测：上周 cost_avg_lines = 0 / cost_snapshot_lines = 83）。
    n_buy = 0
    for mid, doc_date, created in db.execute(text("""
        select im.id, po.doc_date, im.created_at
        from inventory_movements im
        join purchase_order_items poi on poi.movement_id = im.id
        join purchase_orders po on po.id = poi.order_id
        where im.source = 'PURCHASE'
    """)).all():
        day = doc_date if isinstance(doc_date, date) else date.fromisoformat(str(doc_date))
        when = to_utc_naive(datetime.combine(day, dtime(10, 0)))
        # ⛔ 判"已经对齐过"必须比**业务日**，不能比时间戳的前 10 位：库里存 UTC，
        # 北京 10-05 凌晨 3 点写进去是 10-04 19:06 UTC，前 10 位跟 doc_date 撞上就被跳过，
        # 那两张 10-04 的采购单永远留在"此刻"（实测漏了 10 条，见探针「附」段）。
        seen = created if isinstance(created, datetime) else datetime.fromisoformat(str(created))
        if (seen + timedelta(hours=8)).date() == day:
            continue
        db.execute(text("update inventory_movements set created_at = :w where id = :i"),
                   {"w": when, "i": int(mid)})
        n_buy += 1
    db.commit()
    print(f"[align] 账单月份 {n_bills} / 账本日期 {n_ledger} / 开销日期 {n_exp} / "
          f"货损流水 {n_cash} / 库存流水时间 {n_inv} / 采购入库时间 {n_buy} 已对齐到各单的业务日")


def main() -> int:
    ap = argparse.ArgumentParser(description="补齐经营数据（增量、幂等）")
    ap.add_argument("--yes", action="store_true", help="确认写库（不带这个参数只预览）")
    ap.add_argument("--only", default="", help="只跑某几个 section，逗号分隔："
                                             "vehicles,purchase,deliver,expenses,receipt,charge,invoice")
    args = ap.parse_args()
    only = {s.strip() for s in args.only.split(",") if s.strip()}

    rng = random.Random(20261005)
    db = SessionLocal()
    try:
        dispatcher = db.get(User, 1)
        if dispatcher is None or dispatcher.role != UserRole.DISPATCHER:
            print("开发库里找不到派单员 users.id=1（13800000001），先跑 seed_dev_users。")
            return 1
        print(f"今天 = {business_today()}（业务日）；操作人 = {dispatcher.full_name}"
              f"（users.id={dispatcher.id}）")
        print(f"模式 = {'写库' if args.yes else '预览'}；section = {sorted(only) or '全部'}")
        print()

        sections = [
            ("vehicles", sec_vehicles),
            ("purchase", sec_purchase),
            ("deliver", sec_deliver),
            ("expenses", sec_expenses),
            ("receipt", sec_receipt),
            ("charge", sec_charge),
            ("invoice", sec_invoice),
        ]
        for name, fn in sections:
            if only and name not in only:
                continue
            print(f"—— {name} " + "-" * 56)
            fn(db, dispatcher, args.yes, rng)
            print()
        if args.yes:
            print("—— align " + "-" * 57)
            align_history(db)
    finally:
        db.close()
    print()
    print("完成。" + ("" if args.yes else "（预览模式：一个字都没写，加 --yes 才落库）"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
