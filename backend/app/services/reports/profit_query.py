"""经营利润表（只读）：把已经算得出来的四块钱按**同一个窗口**汇合。

老板五问的第 1 问是「这月赚了多少（营业额 − 成本 = 利润）」。
营业额、商品成本、司机应得、开销这四块钱**各自都已经有唯一实现**（`order_money` / `cost_basis` /
`driver_pay` / `expenses`，契约见 `services/money_contract.py`），可系统里**从来没有一处把它们相减** ——
这个文件就是那一处。

⛔ 它**只相减、不重新取数**：前四格直接取营业纵览 `build_turnover` 的同一批聚合数，于是

    revenue_total == turnover.total_amount
    delivery_cost == turnover.total_freight

是**构造上成立**的，而不是靠两处各算一遍再希望它们相等（毛利上已经栽过一次：同一个月
72,177.75 vs 正确 10,789.00 —— 差 6.7 倍，两边都不报错）。

每一格的来源（全部是既有唯一实现，本文件一个原始金额都不自己算）：

    营业收入(应收)   turnover.total_amount        ← order_money.receivable
    参与毛利收入     turnover.cost_covered_amount ← 与营业纵览/商品经营同一句口径
    商品成本         turnover.cost_total          ← cost_basis（入库加权平均进货价，三级兜底）
    配送成本         turnover.total_freight       ← driver_pay.pay_for_order（⛔ 不是 orders.freight_fee）
    期间费用         expenses 按 exp_date 落窗口、按分类聚合（**已含货损开销**，⛔ 不再扣 damage_amount）
    税金及附加       Σ 开销里**分类名带「税」**的那些笔（口径唯一判据 tax_query.is_tax_category）
    应交增值税       销项税额 - 进项税额，价外税、**不进营业利润**（唯一实现 tax_service.sum_taxes）
    车辆折旧         Σ 各车在窗口内按自然月摊到的折旧 ← `services/vehicle_depreciation.py`（唯一实现）

⛔ 没有成本数据的那部分收入**单列**（`revenue_uncovered`），既不按 0 成本、也不按平均成本替它猜。
⛔ 没有购置信息的车同样**单列**（`depreciation_uncovered`），它们的折旧是「算不出来」而不是 0。

本包只允许 SELECT / JOIN / GROUP BY —— 判据 `_tools/qa/_check_report_boundary.py` 在 AST 层面盯着。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.expense import Expense
from app.models.vehicle import Vehicle
from app.services import vehicle_depreciation as vdep
from app.services.reports.tax_query import is_tax_category, vat_of_span
from app.services.reports.turnover_query import build_turnover

_ZERO = Decimal("0")

#: 凡「今天是 0」或「今天算不进」的地方，一律进 `notes` —— 老板看到的每一格都要能解释：
#: 是「真的是 0」，还是「还没有这个数据源，所以先记 0」。
_NOTES: tuple[str, ...] = (
    "税金及附加 = 开销里分类名带「税」的那些笔（今天系统里没有这种分类，所以这一格是 0）。"
    "它不是「不用交税」，是「还没有记」—— 记一笔分类叫「税金」的开销，这一格就会动。",
    "应交增值税（销项税额 - 进项税额）单列一行，不进营业利润：它是价外税、代收代付，"
    "不是这一期赚的钱（来源是发票台账，看税账页）。",
    "车辆折旧已经算进来了（第二期落地）：月折旧额 = 购置价 ×（1 − 残值率）÷（使用年限 × 12），"
    "从购置日期起、按每个自然月的天数摊到这个窗口里（提足之后就是 0，不是没算）。"
    "没录购置价 / 购置日期 / 使用年限的车算不出折旧，它们的折旧没进这一格（营业利润偏高），"
    "单列在「折旧未覆盖」那一行里 —— 把缺的那一格补上，这一格就会跟着变。",
    "固定工资制司机的工资不在配送成本里：工资走月度工资单、不按单产生应付，"
    "而这里的配送成本 = Σ 司机应得的按单金额。所以营业利润偏高。",
    "没有成本数据的那部分收入不进商品毛利（单列在 revenue_uncovered）："
    "没有按 0 成本或平均成本替它猜 —— 毛利算得准不准，看 covered_lines / total_lines。",
    "货损开销已经包含在期间费用里（货损是一张开销单），这里不重复扣 damage_amount。",
)


def build_profit(db: Session, mode: str, anchor: date, *, span: tuple[date, date] | None = None) -> dict[str, Any]:
    """一个窗口的经营利润（只读）。

    `span` 的语义与 `/reports/turnover` 完全同源：接口层用 `_span(mode, anchor, date_from, date_to)`
    算好再传进来（⛔ 本文件不认识 date_from/date_to，也不自己解析窗口）。
    """
    turnover = build_turnover(db, mode, anchor, span=span)
    start, end = turnover["_window"]

    # 期间费用：按**业务发生日**落窗口、按分类聚合。
    # ⛔ 不用 `cash_flows.flow_date` —— 钱什么时候付、这笔费用算哪一期，是两件事
    #    （口径单一：经营报表按业务发生时间，资金与结算单按资金实际发生时间）。
    # ⛔ 不加 `is_deleted` 过滤：`expenses` 表**没有软删列**（开销删掉就是真删）。
    rows = db.execute(
        select(Expense.category, func.sum(Expense.amount))
        .where(Expense.exp_date >= start, Expense.exp_date <= end)
        .group_by(Expense.category)
    ).all()
    expenses = [
        {"category": (str(name or "").strip() or "未分类"), "amount": amount or _ZERO}
        for name, amount in rows
    ]
    # 服务端定序：金额大的在前，金额相同按分类名 —— 界面与导出不必各自再排一遍（排法只有一处）。
    expenses.sort(key=lambda r: (-r["amount"], r["category"]))
    expense_total = sum((r["amount"] for r in expenses), _ZERO)

    # 税金及附加（FEAT-0014 接线）：开销里**分类名带「税」**的那些笔 —— 判据只有一处
    # （`tax_query.is_tax_category`）。它们从期间费用里**挖出来单列**，否则营业利润会被扣两次。
    # ⛔ 仍然不许按一个税率编一个数出来：这一格只可能来自真实开销，没有就是 0。
    tax_total = _ZERO
    tax_expenses = [r for r in expenses if is_tax_category(r["category"])]
    if tax_expenses:
        tax_total = sum((r["amount"] for r in tax_expenses), _ZERO)
        expenses = [r for r in expenses if not is_tax_category(r["category"])]
        expense_total = expense_total - tax_total

    # 应交增值税（价外税）：销项税额 - 进项税额。⛔ 不进 operating_profit —— 代收代付的钱，
    # 摆在同一页上只是让老板看见「这个月要交多少」，不是让他以为赚少了。
    vat = vat_of_span(db, start, end)

    # 车辆折旧：窗口与上面四块**同一个**（起止就是 turnover 的窗口），唯一实现在
    # `services/vehicle_depreciation.py` —— 这里只做两件事：读一次车辆表、把合计搬进来。
    # ⛔ 缺购置信息的车**不进**这一格（它们的折旧是「算不出来」而不是 0），单列在下面。
    dep = vdep.summarize(db.scalars(select(Vehicle)).all(), start, end)
    depreciation_total = Decimal(str(dep["total"]))

    revenue_total = turnover["total_amount"]
    revenue_covered = turnover["cost_covered_amount"]
    cost_total = turnover["cost_total"]
    delivery_cost = turnover["total_freight"]
    gross_profit = revenue_covered - cost_total
    operating_profit = gross_profit - delivery_cost - expense_total - depreciation_total - tax_total

    return {
        "period_label": turnover["period_label"],
        "revenue_total": revenue_total,
        "revenue_covered": revenue_covered,
        "revenue_uncovered": revenue_total - revenue_covered,
        "cost_total": cost_total,
        "gross_profit": gross_profit,
        "total_lines": turnover["total_lines"],
        "covered_lines": turnover["cost_covered_lines"],
        "cost_avg_lines": turnover["cost_avg_lines"],
        "cost_snapshot_lines": turnover["cost_snapshot_lines"],
        "delivery_cost": delivery_cost,
        "operating_expense_total": expense_total,
        "operating_expenses": expenses,
        "tax_expenses": tax_expenses,
        "depreciation_total": depreciation_total,
        "depreciation_monthly_total": Decimal(str(dep["monthly_total"])),
        "depreciation_vehicle_count": int(dep["covered_count"]),
        "depreciation_uncovered_count": int(dep["uncovered_count"]),
        "depreciation_uncovered": list(dep["uncovered"]),
        "tax_total": tax_total,
        "vat_output": vat["vat_output"],
        "vat_input": vat["vat_input"],
        "vat_payable": vat["vat_payable"],
        "operating_profit": operating_profit,
        "collected": turnover["collected"],
        "arrears_total": turnover["arrears_total"],
        "cancelled_orders": turnover["cancelled_orders"],
        "damage_qty": turnover["damage_qty"],
        "damage_amount": turnover["damage_amount"],
        "notes": list(_NOTES),
    }
