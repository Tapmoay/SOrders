"""车辆成本表（只读）：一台车在这段时间里**花了多少钱**。

第二期（FEAT-0012）把车辆折旧接进利润表之后，老板的追问会从「这月赚了多少」变成
「哪台车在烧钱」—— 这个文件就是回答第二问的那一处：把**按车算得出来的三笔成本**
摆在一起，每一笔都来自既有的唯一实现，本文件一个原始金额都不自己算。

    车辆折旧      services/vehicle_depreciation.py（月额 = 购置价 ×(1−残值率)÷(年限×12)，按自然月天数摊进窗口）
    这台车的开销   expenses.vehicle_id 指到这台车的那些（按 exp_date 落窗口、按分类聚合）
    配送成本      挂在这台车上的司机（vehicles.driver_id）在这个窗口里的**按单应付**合计
                  （money_contract.pay_for_order，与运费结算页、利润表同一个函数）

⛔ **收入不按车拆**：`orders` 上只有司机、没有「这一单是哪台车拉的」这个事实，
   硬把收入按台数或按比例摊到车上就是编一个数 —— 而编出来的数会被拿去决定
   「这车还要不要留」。所以这张表只算成本、一分钱收入都不写。

恒等式（两条，可当场复算）：

    total_cost == depreciation + expense_total + delivery_cost        （逐车）
    totals.total_cost == Σ per_vehicle[*].total_cost                  （合计 == 逐车相加）

⛔ 挂不上车的开销（没挂车 / vehicle_id 查不到车）**不进任何一台车的成本**，但它们会在
   `unlinked_expense_*` / `orphan_expense_*` 上单列，并在 `expense_window_total` 里与各车相加 ——
   同一窗口里利润表认、这张表不认的那笔钱必须看得见（BUG-0023 / 台账 TB-07）。

⛔ **只读**：本包下的模块只允许 SELECT / JOIN / GROUP BY —— 判据 _tools/qa/_check_report_boundary.py
在 AST 层面禁止落库写法与写服务依赖，而且它是**算出来的**（services/reports/** 由 glob 自动收）。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import User, Vehicle
from app.models.expense import Expense
from app.services import vehicle_depreciation as vdep
from app.services.money_contract import has_per_order_pay, pay_for_order
from app.services.money_text import money_text
from app.services.reports._common import _span_label, _window
from app.services.reports.loader import load_delivered

_ZERO = Decimal("0.00")

# 开销单的分类写空时的兜底名（既有的开销页也是这么显示的）
_UNCATEGORISED = "未分类"

# 口径说明（用户可见：页面上逐条常显、导出也写进去）。⛔ 不许出现 markdown 星号 ——
# 手机上会原样显示成两个星号。
_NOTES: tuple[str, ...] = (
    "这张表只算成本、不算收入：订单上只有司机、没有「哪台车拉的」这个事实，按比例摊出来的收入会被拿去决定这车留不留（摊错了比不摊更糟）。",
    "「这台车的开销」= 开销单里挂到这台车的那些（燃油 / 维修 / 过路 / 停车 / 保险这类按车记的）；没挂车的开销进不了本表 —— 它们仍然在利润表的「期间费用」里（一个是全店、一个是按车，两处口径不冲突）。",
    "「配送成本」= 现在挂在这台车上的那位司机，在这一段时间里按单应付的合计（与运费结算页、利润表同源）。换过司机的话，历史单算在当时那位司机头上、不会跟着车走。"
    "没挂车的司机，他们这段时间的配送成本一分钱都不在「成本合计」里 —— 那些钱在利润表的「司机运费」那一格（那张表不按车分组）。",
    "车辆折旧只算购置信息齐全的车；缺购置价 / 购置日期 / 使用年限的车算不出折旧（不是 0），它们在下面「折旧未覆盖」的名单里。",
    "折旧是按月直线法摊出来的，不等于这段时间真的掏了这些现金 —— 买车的钱在购置那天就付出去了。",
)


def _driver_names(db: Session, vehicles: list[Vehicle]) -> dict[int, str]:
    """司机名：与车辆台账页同一套取法（`full_name` → `phone`）。"""
    ids = sorted({int(v.driver_id) for v in vehicles if v.driver_id})
    if not ids:
        return {}
    rows = db.execute(select(User.id, User.full_name, User.phone).where(User.id.in_(ids))).all()
    return {int(uid): (full_name or phone or "") for uid, full_name, phone in rows}


def _expense_buckets(
    db: Session, start: date, end: date, vehicle_ids: set[int]
) -> dict[str, Any]:
    """窗口内的开销按「挂到哪儿」分三块：挂到真实车辆的 / 没挂车的 / 挂到查无此车的。

    改前这里只返回第一块，而且 SQL 里带 `vehicle_id IS NOT NULL`：于是 `vehicle_id` 指到
    一台库里没有的车（开销单改前对关联一个都不校验，id=999999 照样落库）的那几笔，
    进了字典却**没有任何一行消费它** —— 同一个窗口里利润表认（期间费用），车辆成本表不认，
    两张表对不上、两边都不报错（BUG-0023 / 台账 TB-07）。

    ⛔ 这里仍然只读、只聚合；三块的分法就是「这一笔能不能算到某台车上」。
    """
    rows = db.execute(
        select(
            Expense.vehicle_id,
            Expense.category,
            func.count(Expense.id),
            func.sum(Expense.amount),
        )
        .where(Expense.exp_date >= start, Expense.exp_date <= end)
        .group_by(Expense.vehicle_id, Expense.category)
    ).all()
    linked: dict[int, list[dict[str, Any]]] = {}
    unlinked = {"total": _ZERO, "count": 0}
    orphan = {"total": _ZERO, "count": 0}
    window_count = 0
    for vehicle_id, category, count, amount in rows:
        name = str(category or "").strip() or _UNCATEGORISED
        money = amount or _ZERO
        window_count += int(count or 0)
        if vehicle_id is None:
            unlinked["total"] += money
            unlinked["count"] += int(count or 0)
            continue
        if int(vehicle_id) not in vehicle_ids:
            orphan["total"] += money
            orphan["count"] += int(count or 0)
            continue
        linked.setdefault(int(vehicle_id), []).append({"category": name, "amount": money})
    for items in linked.values():
        items.sort(key=lambda r: (-r["amount"], r["category"]))
    return {"linked": linked, "unlinked": unlinked, "orphan": orphan, "window_count": window_count}


def _driver_pay(db: Session, start: date, end: date) -> dict[int, Decimal]:
    """这个窗口里**每位司机**的按单应付合计。

    ⛔ 不写第二份算法：`has_per_order_pay` / `pay_for_order` 就是运费结算页与利润表用的那两个函数
    （工资制司机不按单拿钱，所以这里没有他们的数 —— 与「司机运费结算」页一致）。
    """
    out: dict[int, Decimal] = {}
    for order in load_delivered(db, span=(start, end)):
        if order.driver_id is None or not has_per_order_pay(order):
            continue
        key = int(order.driver_id)
        out[key] = out.get(key, _ZERO) + pay_for_order(order).total
    return out


def build_vehicle_cost(
    db: Session,
    mode: str,
    anchor: date,
    *,
    span: tuple[date, date] | None = None,
) -> dict[str, Any]:
    """一段时间里**每一台车**花掉的钱（折旧 ＋ 这台车的开销 ＋ 挂靠司机的配送成本）。

    窗口的算法与其它报表完全一致：给了 `span` 就用它（App 的档位药丸），否则 `mode` + `anchor`。
    """
    start, end = span if span else _window(mode, anchor)

    vehicles = list(db.scalars(select(Vehicle).order_by(Vehicle.id)))
    # 折旧：逐车的「算不算得出来 / 每月多少 / 这一段摊到多少」全部由折旧服务一处给，
    # ⛔ 本文件不重算一遍（两处算法迟早不一样，而这里差一分就是一条对不上的账）。
    dep = vdep.summarize(vehicles, start, end)
    dep_rows = {int(r["vehicle_id"]): r for r in dep["per_vehicle"]}

    # 窗口内的开销分三块取（挂到真实车的 / 没挂车的 / 挂到查无此车的）——
    # 后两块不进任何一台车的成本，但必须**报出来**（BUG-0023）。
    expenses = _expense_buckets(db, start, end, {int(v.id) for v in vehicles})
    linked = expenses["linked"]
    pay = _driver_pay(db, start, end)
    names = _driver_names(db, vehicles)

    per_vehicle: list[dict[str, Any]] = []
    for v in vehicles:
        row = dep_rows.get(int(v.id), {})
        items = linked.get(int(v.id), [])
        expense_total = sum((r["amount"] for r in items), _ZERO)
        delivery_cost = pay.get(int(v.driver_id), _ZERO) if v.driver_id else _ZERO
        depreciation = Decimal(str(row.get("window_depreciation") or _ZERO))
        per_vehicle.append(
            {
                "vehicle_id": int(v.id),
                "plate_no": v.plate_no or "",
                "is_active": bool(v.is_active),
                "driver_id": v.driver_id,
                "driver_name": names.get(int(v.driver_id), "") if v.driver_id else "",
                # ↓ 本段是折旧服务 `as_dict()` 的原样搬运（含「算不出来时月额是 null」这个语义）
                "depreciation_covered": bool(row.get("covered")),
                "depreciation_uncovered_reasons": list(row.get("uncovered_reasons") or []),
                "purchase_price": row.get("purchase_price"),
                "purchase_date": row.get("purchase_date"),
                "useful_life_years": row.get("useful_life_years"),
                "residual_rate": row.get("residual_rate"),
                "residual_rate_effective": row.get("residual_rate_effective"),
                "monthly_depreciation": row.get("monthly_depreciation"),
                "depreciation": depreciation,
                "expenses": items,
                "expense_total": expense_total,
                "delivery_cost": delivery_cost,
                "total_cost": depreciation + expense_total + delivery_cost,
            }
        )

    depreciation_total = Decimal(str(dep["total"]))
    expense_total_all = sum((r["expense_total"] for r in per_vehicle), _ZERO)
    delivery_total = sum((r["delivery_cost"] for r in per_vehicle), _ZERO)
    unlinked = expenses["unlinked"]
    orphan = expenses["orphan"]
    off_vehicle_total = unlinked["total"] + orphan["total"]
    expense_window_total = expense_total_all + off_vehicle_total
    notes = list(_NOTES)
    if unlinked["count"] or orphan["count"]:
        # 动态那一行只在**真有挂不上的钱**时出现：没有就一个字都不多说。
        # ⛔ 金额一律过 money_text（用户可见的说明文字只许用这一份显示口径）；
        #    行里不许出现 markdown 星号（手机上会原样显示成两个星号）。
        notes.append(
            f"本窗口还有 {unlinked['count'] + orphan['count']} 笔没挂到任何一台车上的开销："
            f"未挂车的 {unlinked['count']} 笔共 {money_text(unlinked['total'])} 元、"
            f"挂到查不到车辆的 {orphan['count']} 笔共 {money_text(orphan['total'])} 元。"
            f"窗口内全部开销 {money_text(expense_window_total)} 元 ＝ 上面各车开销合计 "
            f"{money_text(expense_total_all)} 元 ＋ 这 {money_text(off_vehicle_total)} 元；"
            "未挂车的那些仍然在利润表的「期间费用」里 —— 拿本表这一行与利润表的"
            "「期间费用」＋「税金及附加」两格对同一段时间，钱就对得上。"
        )
    return {
        "period_label": _span_label(start, end),
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "vehicle_count": len(per_vehicle),
        "covered_count": int(dep["covered_count"]),
        "uncovered_count": int(dep["uncovered_count"]),
        "depreciation_total": depreciation_total,
        # 月额合计与窗口无关（页面上的「每月固定」那一格读它）
        "depreciation_monthly_total": Decimal(str(dep["monthly_total"])),
        "expense_total": expense_total_all,
        # ↓ 挂不上车的开销（BUG-0023）：expense_total 的语义一个字都没变（只有挂到真实车辆的），
        #   这两块是**另外报出来**的 —— 一个用户拿同一窗口能把两张表对上，或至少看到「另有 N 笔 X 元」。
        "unlinked_expense_total": unlinked["total"],
        "unlinked_expense_count": int(unlinked["count"]),
        "orphan_expense_total": orphan["total"],
        "orphan_expense_count": int(orphan["count"]),
        # = expense_total + 上面两块（窗口内全部开销；与利润表「期间费用 + 税金及附加」对齐）
        "expense_window_total": expense_window_total,
        "expense_window_count": int(expenses["window_count"]),
        "delivery_cost_total": delivery_total,
        "total_cost": depreciation_total + expense_total_all + delivery_total,
        "per_vehicle": per_vehicle,
        "notes": notes,
    }
