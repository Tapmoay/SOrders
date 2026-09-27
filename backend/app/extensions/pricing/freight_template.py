# -*- coding: utf-8 -*-
"""承运运费 —— 从**定格的那份价目表**里挑一条（PricingContract v2）。

## 它是什么，为什么现在才写

R4 的算价扩展已经有三个实现（统一价 / 按量计费 / 阶梯价），但它们都是**演练用**的
—— 生产上真正在跑的是核心的**价目匹配**（`services/freight_pricing.quote_for`）。
用户 2026-09-27 §12：

> 「不要再把生产接线设计成 Order → 具体 PricingImplementation，应该是
>  Order → PricingContext → PricingContract → implementation → Money。」

这个实现就是那一步的**候选**：它把核心的价目匹配**原样搬进契约**，
⛔ 一行业务规则都不改（同一个匹配顺序、同一条「同一档多条 = 不猜」）。

## 它为什么能算（⛔ 它读不到库）

`PricingContext.rule_snapshot` 是**派单那一刻定格的那一份**；核心负责把两样东西读进去：

    {
      "pricing_kind": "freight_template",
      "category_id": 3,                 ← 这一单属于哪一类货（可空 = 没分类）
      "route_ids": [7, 9],              ← 这个送货地址属于哪几条线路（核心按地址查出来的）
      "templates": [                    ← 候选价目 = **这个司机的规则勾了的那些**（核心读的）
        {"id": 12, "name": "仓前线蔬菜价", "price_name": "小车价", "fee": "120.00",
         "to_place": "…", "route_id": 7, "category_ids": [3]}
      ]
    }

⭐ 「哪个司机 → 他的规则勾了哪些价目」是**核心的事实**，不是计价方式的一部分，
所以它由核心读好、放进快照；这一层只做**纯挑选**。
⛔ 这也正是它能在 Shadow 里被安全对照的原因：给它同一份快照，它必须给出同一个结论。

## 与核心那版的逐条对应（Golden Set 就是拿这个逐一比对的）

| 核心 `quote_for` | 这里 |
| --- | --- |
| 没有送货地址 → 认不出路线 | `_pick` 第一句 |
| 候选为空（没挂规则 / 规则没勾价目） | 第二句 |
| 路线：`to_place` 相等 或 `route_id` 命中该地址的线路 | `by_route` |
| 分类优先级 0 命中 / 1 通用 / 2 不是这一类 | `rank` |
| 2 的一条都不剩 → 不可用 | `usable` |
| 同一档多条 → **不猜**，带候选清单 | `AmbiguousPricingRule` |
"""
from __future__ import annotations

from app.core.contracts.money import Money
from app.core.contracts.pricing import (
    AmbiguousPricingRule,
    NoPricingRule,
    PricingContext,
    PricingLine,
    PricingResult,
)


def _label(t: dict) -> str:
    """价目的显示名 —— **带上编号**：同名价目是真实存在的，没有编号就说不清是哪一条。"""
    return (str(t.get("name") or "价目")) + "（#" + str(t.get("id")) + "）"


class FreightTemplatePricing:
    """承运运费（PricingContract **v2**）：按价目表收。"""

    name = "freight_template"
    version = 1
    #: 它认领哪一类单 —— 规则快照里的 pricing_kind 对上这个值才归它管。
    kind = "freight_template"

    def applies_to(self, context: PricingContext) -> bool:
        """归我管 = 快照点名要「按价目表」。缺料也仍然归我管（那是缺料，不是别人的活）。"""
        return context.rule_snapshot.get("pricing_kind") == self.kind

    # ------------------------------------------------------------------ 挑选
    def _pick(self, context: PricingContext) -> dict:
        """挑出这一单该用哪一条价目 —— ⛔ 与核心 `quote_for` 的优先级逐条一致。"""
        snapshot = context.rule_snapshot
        to_place = (context.to_place or "").strip()
        if not to_place:
            raise NoPricingRule("这一单没有送货地址，认不出路线 —— 先在订单里补地址")

        raw_templates = snapshot.get("templates")
        templates = [t for t in (raw_templates or []) if isinstance(t, dict)]
        if not templates:
            raise NoPricingRule(
                "这个司机的规则一条价目都没勾（或者他还没挂规则）—— "
                "运费是从「他的规则勾了哪几条价目」来的，先去把这一步配好"
            )

        route_ids = {int(x) for x in (snapshot.get("route_ids") or [])}
        by_route = [
            t for t in templates
            if (str(t.get("to_place") or "").strip() == to_place)
            or (t.get("route_id") is not None and int(t["route_id"]) in route_ids)
        ]
        if not by_route:
            raise NoPricingRule("这条路线还没有价目 —— 到「运费模板」里给这条线路加一条价，或在这里手动定价")

        cat_id = snapshot.get("category_id")

        def rank(t: dict) -> int:
            cats = [int(c) for c in (t.get("category_ids") or [])]
            if cat_id is None:
                # ⚠️ "不知道这一单是哪一类"时这一维**不参与筛选** —— 否则待定价那一页
                #    （还没定分类）会把带分类的价目全判成不可用，明明有价也报"没有价目"。
                return 1
            if int(cat_id) in cats:
                return 0
            return 1 if not cats else 2

        ranked = sorted(by_route, key=lambda t: (rank(t), -int(t.get("id") or 0)))
        usable = [t for t in ranked if rank(t) != 2]
        if not usable:
            raise NoPricingRule("这条路线上的价目都不是这一类的 —— 在这里手动定价，或去「运费模板」补一条")

        best = rank(usable[0])
        same = [t for t in usable if rank(t) == best]
        if len(same) > 1:
            # ⛔ 不猜：默默取到另一条，正是本项目最恨的那类静默错误。
            raise AmbiguousPricingRule(
                "这条路线 + 这类货下有多条同样优先的价目 —— 请自己挑一条，系统不替你猜",
                tuple(_label(t) for t in same),
            )
        return same[0]

    # ------------------------------------------------------------------ 出价
    def breakdown(self, context: PricingContext) -> tuple[PricingLine, ...]:
        """价目表计价只有一行（就是那条价目的金额）。"""
        t = self._pick(context)
        return (PricingLine(label="价目 " + _label(t) + " 的金额", money=Money.of(t.get("fee") or 0)),)

    def price(self, context: PricingContext) -> PricingResult:
        """总额 = **明细相加**（⛔ 不另算一遍 —— 两处算同一个数迟早走散）。"""
        lines = self.breakdown(context)
        money = lines[0].money
        for line in lines[1:]:
            money = money + line.money
        t = self._pick(context)
        return PricingResult(
            money=money,
            rule_name="价目：" + _label(t),
            detail="按价目 " + _label(t) + " 收 " + money.as_text() + " 元",
        )


PROVIDER = FreightTemplatePricing()
