# -*- coding: utf-8 -*-
"""按量计费 —— 算价扩展的**第二个实现**（R4-05b，Replace 演练就是加这个文件）。

单价 × 数量。它和「统一价」对同一张订单会给出**不同的**数 —— 这正是"可替换"的证明：
把订单规则快照里的 `pricing_kind` 从 `standard` 改成 `per_quantity`，算法就换了，
而核心与扩展的代码一个字节都没动。

## 它也顺手证明了一件事：扩展算钱不许自己造钱

金额全部经核心的 `Money`：`Money.of(单价).times(数量)`。
⛔ 它没有"直接用 Decimal 相乘"的那条路 —— `times` 会在因子是 `float` 或另一个 `Money` 时拒绝，
而 `Money` 的构造会把结果归一到两位小数 + ROUND_HALF_UP（与全项目同一条口径，
见 `_check_extension_contracts.py` 对全项目 14 处 quantize 的对账）。
"""
from __future__ import annotations

from decimal import Decimal

from app.core.contracts.money import Money
from app.core.contracts.pricing import NoPricingRule, PricingContext, PricingResult


class PerQuantityPricing:
    """按量计费（PricingContract v1）。"""

    name = "per_quantity"
    version = 1
    kind = "per_quantity"

    def applies_to(self, context: PricingContext) -> bool:
        """归我管 = 快照点名要按量计费。缺单价或数量也仍然归我管（那是缺料）。"""
        return context.rule_snapshot.get("pricing_kind") == self.kind

    def price(self, context: PricingContext) -> PricingResult:
        raw = context.rule_snapshot.get("unit_price")
        if raw in (None, ""):
            raw = context.unit_price
        if raw in (None, ""):
            raise NoPricingRule(
                "这一单按「按量计费」算，但没有单价（unit_price）—— 请先给它定个单价再派单"
            )
        if context.quantity is None:
            raise NoPricingRule(
                "这一单按「按量计费」算，但单子上没有数量 —— 请先填数量（或改用统一价）"
            )
        unit_price = Money.of(raw)
        quantity = Decimal(context.quantity.value)
        money = unit_price.times(quantity)
        return PricingResult(
            money=money,
            rule_name="按量计费",
            detail=(unit_price.as_text() + " 元 × " + format(quantity, "f") + " "
                    + context.quantity.unit + " = " + money.as_text() + " 元"),
        )


PROVIDER = PerQuantityPricing()