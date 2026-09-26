# -*- coding: utf-8 -*-
"""算价扩展的清单。字段含义见 docs/R4_EXTENSIONS.md 第 1 节。

* kind="policy" —— 指南 §9 的第二类扩展：定价 / 折扣 / 运费 / 税费 / 佣金这一族；
* provides=("pricing.calculate",) —— 与边界图里 pricing.freight 那一条对应；
* requires=("money.core",) —— 它算出来的必须是核心的 Money；
* compatibility="PricingContract v1"；
* owns_tables=() —— 它**不拥有任何表**：算价不落库，事实交给核心事务；
* routes="api" + capability="ORDER_READ_ALL" —— 试算报价是派单员看的（下单页 / 派单页）。
"""
from __future__ import annotations

from app.core.extension_registry import ExtensionManifest

MANIFEST = ExtensionManifest(
    id="pricing",
    version=1,
    kind="policy",
    provides=("pricing.calculate",),
    requires=("money.core",),
    consumes=(),
    emits=(),
    config=(),
    compatibility="PricingContract v1",
    owns_tables=(),
    routes="api",
    capability="ORDER_READ_ALL",
    why="把「这一单该收多少」收成一条只产出核心 Money 的纯计算契约：换一种计价方式只加一个文件，钱的事实仍归核心事务",
)