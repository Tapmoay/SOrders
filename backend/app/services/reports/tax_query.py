"""税账报表（FEAT-0014）：一段窗口里开了多少票、该交多少增值税。

老板五问的这一问是「这个月要交多少税」。系统里**唯一**的税事实是发票台账（`invoices` 表，
读写在 `services/tax_service.py`），本文件只做两件事：

  ① 按窗口把票分方向汇总（销项 / 进项），把 `应交增值税 = 销项税额 − 进项税额` 算出来；
  ② 把窗口里的票逐张列出来（含作废票、未税票 —— 这两类都**不算**进 ①，只在明细里看得见）。

⛔ 三条不许动的口径：

  * 增值税是**价外税**（代收代付）：它**不进** `operating_profit`。利润表把「应交增值税」
    与「税金及附加」分成两行摆着 —— 一行是「这个月要交多少」，一行是「已经花掉的税」。
  * 窗口按**发票业务日期** `invoices.invoice_date`，⛔ 不按 `created_at`：老板补录一张
    上个月开的票，它要落回上个月那一格。
  * 汇总口径的唯一实现是 `tax_service.sum_taxes`（本文件不重算第二遍），
    单张票的「算不算数」判据是 `tax_service.counts_in_tax`。

本包只允许 SELECT / JOIN / GROUP BY —— 判据 `_tools/qa/_check_report_boundary.py` 在 AST 层面盯着。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.services import tax_service
from app.services.reports.turnover_query import build_turnover

#: 开销分类名里出现这个字，就算「税金及附加」。
#. 今天系统里没有任何一笔这种开销，所以利润表那一格是 0 ——
#. 老板记一笔分类叫「税金」「附加税」的开销，它就会动。
#: ⛔ 判据只有这一处：利润表 `reports/profit_query.py` import 它，不许各写一遍。
TAX_CATEGORY_KEYWORD = "税"

#: 凡「今天是 0」或「今天不适用」的地方都要能解释 —— 税账页脚下的口径说明。
_NOTES: tuple[str, ...] = (
    "应交增值税 = 销项税额 − 进项税额。增值税是价外税（代收代付），不进营业利润 —— "
    "经营利润表把它单列一行，和「税金及附加」分开摆。",
    "作废的票不算数（明细里灰着摆出来），没填税率的票（未税）也不算数：它们缺的正是「税额」这一格。",
    "进项税按「已登记」就算数：今天系统里没有「认证 / 勾选」这个事实可记，所以不假装有这一步。",
    "窗口按开票日期（业务日期）落，不按录入时间 —— 补录上个月开的票，它落回上个月。",
)


def is_tax_category(name: str | None) -> bool:
    """这个开销分类算不算「税金及附加」（口径唯一判据，利润表也 import 它）。"""
    return TAX_CATEGORY_KEYWORD in str(name or "")


def vat_of_span(db: Session, start: date, end: date) -> dict[str, Any]:
    """利润表要的三个数：这一段的销项税额 / 进项税额 / 应交增值税。

    ⛔ 只搬 `tax_service.sum_taxes` 的结果，本函数一个字都不重算。
    """
    totals = tax_service.sum_taxes(db, start, end)
    return {
        "vat_output": totals["output"]["tax_amount"],
        "vat_input": totals["input"]["tax_amount"],
        "vat_payable": totals["vat_payable"],
        "voided_count": totals["voided_count"],
    }


def build_tax_summary(
    db: Session, mode: str, anchor: date, *, span: tuple[date, date] | None = None
) -> dict[str, Any]:
    """一个窗口的税账（只读）。

    `span` 的语义与 `/reports/turnover` 完全同源：接口层用 `_span(mode, anchor, date_from, date_to)`
    算好再传进来（⛔ 本文件不认识 date_from/date_to）。
    """
    turnover = build_turnover(db, mode, anchor, span=span)
    start, end = turnover["_window"]
    totals = tax_service.sum_taxes(db, start, end)
    invoices = tax_service.list_invoices(db, date_from=start, date_to=end)
    sups, cus = tax_service.party_names(db, invoices)

    rows: list[dict[str, Any]] = []
    for inv in invoices:
        row = tax_service.brief(inv, sups=sups, cus=cus)
        is_input = row["direction"] == tax_service.INPUT
        rows.append(
            {
                "id": row["id"],
                "direction": row["direction"],
                "invoice_no": row["invoice_no"],
                "invoice_date": row["invoice_date"],
                "amount": row["amount"],
                "tax_rate": row["tax_rate"],
                "tax_amount": row["tax_amount"],
                "net_amount": tax_service.net_of(row["amount"], row["tax_amount"]),
                "status": row["status"],
                # 票上的对方：进项票是供应商、销项票是客户（两边都为空时留空串）
                "party_name": (row["supplier_name"] if is_input else row["customer_name"]) or "",
                "counts_in_tax": row["counts_in_tax"],
            }
        )

    return {
        "mode": mode,
        "anchor": anchor,
        "date_from": start,
        "date_to": end,
        "label": turnover["period_label"],
        "output": totals["output"],
        "input": totals["input"],
        "vat_payable": totals["vat_payable"],
        "voided_count": totals["voided_count"],
        "by_rate": totals["by_rate"],
        "default_tax_rate": tax_service.DEFAULT_TAX_RATE,
        "invoices": rows,
        "notes": list(_NOTES),
    }
