# -*- coding: utf-8 -*-
"""阶梯价 —— 算价扩展的**第一个 v2 实现**（R4-07b，Compatibility 演练就是加这个文件）。

前 N 件按一个单价，超出部分按另一个单价。

## 它与前两个实现的两点不同（这正是 v2 要证的）

1. **它实现了 `breakdown()`** —— 给出**多行**原生明细（"前 10 件 × 8.00" + "超出 5 件 × 9.00"），
   而不是像 v1 实现那样由适配器合成一行。派单员因此能复核"这 125.00 是怎么来的"。
2. **它照样满足 v1** —— `isinstance(x, PricingContract)` 为真（v2 是 v1 的超集，
   不是另一个协议世界），所以**旧消费方一行代码都不用改**。

## 不变式：明细各行之和 **必须** 等于总额

契约里写死的一条（`_check_extension_contracts` 与契约用例都核）。
所以这里的 `price()` 不是"另算一遍"，而是**把 breakdown 加起来** ——
两处算同一个数迟早会走散，而这里结构上就没有两处。
"""
from __future__ import annotations

from decimal import Decimal

from app.core.contracts.money import Money
from app.core.contracts.pricing import NoPricingRule, PricingContext, PricingLine, PricingResult


class TieredPricing:
    """阶梯价（PricingContract **v2**）。"""

    name = "tiered"
    version = 1
    kind = "tiered"

    def applies_to(self, context: PricingContext) -> bool:
        """归我管 = 快照点名要阶梯价。缺料也仍然归我管（那是缺料）。"""
        return context.rule_snapshot.get("pricing_kind") == self.kind

    def _tier(self, context: PricingContext) -> tuple[Money, Decimal, Money]:
        snapshot = context.rule_snapshot
        base_price = snapshot.get("base_price")
        base_qty = snapshot.get("base_qty")
        over_price = snapshot.get("over_price")
        if base_price in (None, "") or base_qty in (None, ""):
            raise NoPricingRule(
                "这一单按「阶梯价」算，但规则快照里少了 base_price（首档单价）或 base_qty（首档数量）"
                " —— 请先把这两项配好再派单"
            )
        if over_price in (None, ""):
            raise NoPricingRule("这一单按「阶梯价」算，但规则快照里少了 over_price（超出部分的单价）")
        if context.quantity is None:
            raise NoPricingRule("这一单按「阶梯价」算，但单子上没有数量 —— 请先填数量")
        return Money.of(base_price), Decimal(str(base_qty)), Money.of(over_price)

    def breakdown(self, context: PricingContext) -> tuple[PricingLine, ...]:
        """阶梯明细：首档 + 超出部分（超出为 0 时只给一行 —— ⛔ 不摆一行"×0 件"充数）。"""
        base_price, base_qty, over_price = self._tier(context)
        quantity = Decimal(context.quantity.value) if context.quantity else Decimal("0")
        first = min(quantity, base_qty)
        rest = quantity - first
        lines = [PricingLine(label="前 " + format(base_qty, "f") + " 件内 " + base_price.as_text() + " 元/件",
                             money=base_price.times(first))]
        if rest > 0:
            lines.append(PricingLine(
                label="超出 " + format(rest, "f") + " 件 " + over_price.as_text() + " 元/件",
                money=over_price.times(rest),
            ))
        return tuple(lines)

    def price(self, context: PricingContext) -> PricingResult:
        """总额 = **明细相加**（⛔ 不另算一遍 —— 两处算同一个数迟早走散）。"""
        lines = self.breakdown(context)
        money = lines[0].money
        for line in lines[1:]:
            money = money + line.money
        return PricingResult(
            money=money,
            rule_name="阶梯价",
            detail=" + ".join(line.label + " = " + line.money.as_text() + " 元" for line in lines)
        )


PROVIDER = TieredPricing()