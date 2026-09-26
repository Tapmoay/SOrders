# -*- coding: utf-8 -*-
"""把**订单**映射成 `PricingContext`（R4-05）。

## 这是谁的活（指南 §20）

    Order -> PricingContext -> PricingContract -> Money -> Core Settlement / Ledger

箭头左边两格是**核心**的：订单是核心的事实，`PricingContext` 是核心定义的类型。
所以"把订单读成一份计价上下文"这件事只能由核心做 —— 扩展根本没有库访问权
（判据 `_check_extension_dependencies.py` 第 2 组：扩展不许 import `app.models` / `app.database`）。

## 一件刻意不做的事：核心**不替**调用方挑规则

`context_of` 只把订单**自己的事实**搬进上下文，⛔ **不往 `rule_snapshot` 里塞
`pricing_kind`**。理由是指南 §13 的单向性：核心一旦写出某个实现的名字，
它就开始认识具体实现了 —— 而"这一单该按哪条规则算"是**配置**（派单时定格的那份快照），
不是核心该猜的东西。

快照为空时，所有实现的 `applies_to` 都会返回 False，于是调用方拿到 `NoPricingRule` ——
这正好接上本项目既有的口径：**「没匹配到就没有定价，由派单员手动定价」**（用户 2026-09-21 原话）。
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from app.core.contracts.pricing import PricingContext
from app.models.order import Order


def _json_or_none(raw: str | None) -> Mapping[str, Any]:
    """订单上的 JSON 快照列是 Text（历史原因），坏了就当没有 —— ⛔ 不抛：
    一张脏快照只是一条参考信息，不该让整条计价链路 500。"""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def context_of(order: Order, *, rule_snapshot: Mapping[str, Any] | None = None) -> PricingContext:
    """订单 -> 计价上下文。**只读**：不查库、不写任何东西。

    `rule_snapshot` 由调用方给（派单时定格的那一份）；不给就是空快照 ——
    那时没有任何实现会认领这一单，结果是 `NoPricingRule`，也就是"等派单员手动定价"。
    """
    return PricingContext(
        order_id=getattr(order, "id", None),
        order_no=order.order_no or "",
        category=order.freight_category or "",
        from_place="",
        to_place=order.address_detail or "",
        quantity=None,          # 数量在订单商品行上，要另一条读路径；本轮不猜、也不顺手查库
        unit_price=None,
        driver_id=order.driver_id,
        vehicle_type=None,      # 车型挂在司机身上，不在订单上
        rule_snapshot=dict(rule_snapshot or {}),
    )


def driver_rule_of(order: Order) -> Mapping[str, Any]:
    """订单上那份**司机计费规则**快照（派单时定格的，与 `driver_pay` 同源）。

    它**不是**运费规则：一个是"司机这趟拿多少"，一个是"这一单收多少"。
    放在这里是因为两者都住在 `orders` 那张表的快照列上，读法一样。
    """
    return _json_or_none(order.driver_rule_snapshot)