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
    税金及附加       **今天恒为 0**（系统还没有税账）—— 如实报 0，原因写进 notes

⛔ 没有成本数据的那部分收入**单列**（`revenue_uncovered`），既不按 0 成本、也不按平均成本替它猜。

本包只允许 SELECT / JOIN / GROUP BY —— 判据 `_tools/qa/_check_report_boundary.py` 在 AST 层面盯着。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.expense import Expense
from app.services.reports.turnover_query import build_turnover

_ZERO = Decimal("0")

#: 凡「今天是 0」或「今天算不进」的地方，一律进 `notes` —— 老板看到的每一格都要能解释：
#: 是「真的是 0」，还是「还没有这个数据源，所以先记 0」。
_NOTES: tuple[str, ...] = (
    "税金及附加记 0：系统还没有税账（没有发票登记表，也没有任何一处写过税费流水）。"
    "这不是「不用交税」，是「还没有记」—— 记了之后这一格才会动。",
    "折旧没有算进去：车辆台账里没有购置价与折旧字段，也没有月度计提。"
    "所以这张表的营业利润偏高（少了折旧那一块），第二期补车辆台账时接进来。",
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

    revenue_total = turnover["total_amount"]
    revenue_covered = turnover["cost_covered_amount"]
    cost_total = turnover["cost_total"]
    delivery_cost = turnover["total_freight"]
    gross_profit = revenue_covered - cost_total
    tax_total = _ZERO
    operating_profit = gross_profit - delivery_cost - expense_total - tax_total

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
        "tax_total": tax_total,
        "operating_profit": operating_profit,
        "collected": turnover["collected"],
        "arrears_total": turnover["arrears_total"],
        "cancelled_orders": turnover["cancelled_orders"],
        "damage_qty": turnover["damage_qty"],
        "damage_amount": turnover["damage_amount"],
        "notes": list(_NOTES),
    }
