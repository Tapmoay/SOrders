# -*- coding: utf-8 -*-
"""统一价 —— 算价扩展的第一个实现（R4-05a）。

规则快照里给定一个金额，这一单就收这么多。它是最简单的一种，也是"计价规则可以换"的对照组：
下一个实现（按量计费）加进来时，核心、清单、路由、__init__.py **一个都不用动**。
"""
from __future__ import annotations

from app.core.contracts.money import Money
from app.core.contracts.pricing import NoPricingRule, PricingContext, PricingResult


class StandardPricing:
    """统一价（PricingContract v1）。"""

    name = "standard"
    version = 1

    #: 它认领哪一类单 —— 规则快照里的 pricing_kind 对上这个值才归它管。
    #: 这不是契约要求的字段，是**它自己的选择依据**；核心不认识这个值（§13 单向性）。
    kind = "standard"

    def applies_to(self, context: PricingContext) -> bool:
        """归我管 = 快照点名要统一价。缺金额也仍然归我管（那是缺料，不是别人的活）。"""
        return context.rule_snapshot.get("pricing_kind") == self.kind

    def price(self, context: PricingContext) -> PricingResult:
        raw = context.rule_snapshot.get("amount")
        if raw in (None, ""):
            raise NoPricingRule(
                "这一单按「统一价」算，但规则快照里没有 amount（金额）—— 请先给它定个价再派单"
            )
        money = Money.of(raw)
        return PricingResult(
            money=money,
            rule_name="统一价",
            detail="按派单时定格的统一价 " + money.as_text() + " 元",
        )


PROVIDER = StandardPricing()