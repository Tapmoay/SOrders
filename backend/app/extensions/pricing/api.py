# -*- coding: utf-8 -*-
"""算价试算的**只读**路由（由核心装配，见 manifest 的 routes / capability）。

与单位换算那条路由同形（指南 §27）：⛔ 一行鉴权都没有、一行数据库都没有，
`require_permission(ORDER_READ_ALL)` 由**核心**在装配时施加。

## 为什么参数是"平"的，而不是给一个 order_id

因为扩展**没有库访问权**（那是判据盯着的边界，不是偷懒）。
"订单 -> 计价上下文"这一步由核心的 `core/pricing_context.py::context_of` 负责，
这条路由只演示**契约本身**：给一份上下文，出一条 Money。
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.contracts.money import MoneyError
from app.core.contracts.pricing import (
    AmbiguousPricingRule,
    NoPricingRule,
    PricingContext,
    PricingError,
)
from app.core.contracts.quantity import Quantity, QuantityError
from app.extensions.pricing import resolve

router = APIRouter(tags=["pricing"])


class QuoteOut(BaseModel):
    """一条报价。⛔ money 是**核心的** Money 渲染出来的，不是这里自己算的。"""

    amount: str
    currency: str
    rule_name: str
    detail: str
    source: str
    candidates: tuple[str, ...] = ()


def _dec(raw: str | None, label: str) -> Decimal | None:
    if raw in (None, ""):
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=label + "请填一个正常的数字：" + str(raw)) from exc


@router.get("/pricing/quote", response_model=QuoteOut)
def quote(
    pricing_kind: str = Query(..., description="按哪一条规则算（派单时定格在规则快照里的那个值）"),
    amount: str | None = Query(None, description="统一价规则的金额"),
    unit_price: str | None = Query(None, description="按量计费规则的单价"),
    quantity_value: str | None = Query(None, description="数量"),
    quantity_unit: str | None = Query(None, description="数量单位"),
) -> QuoteOut:
    """试算一次报价（**只读**：不写任何表、不留任何状态）。

    三句中文错各有各的意思：
    * 「没有一条计费规则管这一单」= 快照里没写按哪条算，或写的那个值没有实现 —— 等派单员手动定价；
    * 「被 N 条规则同时认领」= 不猜，把候选交出去；
    * 「缺料」= 管是管，但快照里少了算它需要的东西。
    """
    snapshot: dict[str, object] = {"pricing_kind": pricing_kind}
    if amount not in (None, ""):
        snapshot["amount"] = amount
    qty = None
    if quantity_value not in (None, ""):
        try:
            qty = Quantity(_dec(quantity_value, "数量"), quantity_unit or "", "count")
        except QuantityError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    context = PricingContext(
        unit_price=_dec(unit_price, "单价"),
        quantity=qty,
        rule_snapshot=snapshot,
    )
    try:
        provider = resolve(context)
        result = provider.price(context)
    except (NoPricingRule, AmbiguousPricingRule) as exc:
        detail = str(exc)
        if isinstance(exc, AmbiguousPricingRule):
            detail += "（候选：" + "、".join(exc.candidates) + "）"
        raise HTTPException(status_code=400, detail=detail) from exc
    except (PricingError, MoneyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return QuoteOut(
        amount=result.money.as_text(),
        currency=result.money.currency,
        rule_name=result.rule_name,
        detail=result.detail,
        source=provider.name,
        candidates=result.candidates,
    )